---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when standard
  queries fail, by parsing raw SQLite page structures, varints, serial types,
  and cell records — with corruption-aware fallback strategies for zeroed
  regions, bit-flips, damaged headers, and fragmented records. Outputs
  recoverable records as JSON matching the task-specific schema.
---

# SQLite Database Recovery Skill

## Overview

This skill recovers rows from corrupted SQLite database files by directly
parsing the binary format at the byte level. It is needed when `sqlite3`
reports "database disk image is malformed" or similar errors due to corruption
mechanisms such as truncation, zeroed regions, random byte flips, damaged page
structures, or split fragments.

## SQLite Binary Format Reference

### File Header (first 100 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0x00   | 16   | Magic string "SQLite format 3\000" |
| 0x10   | 2    | Page size in bytes (big-endian). 0x1000 = 4096 |
| 0x12   | 1    | File format write version |
| 0x13   | 1    | File format read version |
| 0x1C   | 4    | Size of database in pages |
| 0x28   | 4    | Schema cookie |
| 0x2C   | 4    | Schema format number |
| 0x38   | 4    | Text encoding (1=UTF-8, 2=UTF-16le, 3=UTF-16be) |

### Page Types

Each page starts with a B-tree page header (except page 1, which starts at
offset 100 after the file header):

- **0x0D**: Leaf table B-tree page (contains actual row data)
- **0x05**: Interior table B-tree page (contains child page pointers)
- **0x0A**: Leaf index B-tree page
- **0x02**: Interior index B-tree page

### Leaf Table B-tree Page Header (8 bytes)

| Offset | Size | Field |
|--------|------|-------|
| +0     | 1    | Page type (0x0D) |
| +1     | 2    | First freeblock offset (0 = none) |
| +3     | 2    | Number of cells on this page |
| +5     | 2    | Offset to start of cell content area |
| +7     | 1    | Number of fragmented free bytes |

### Cell Pointer Array

Immediately follows the 8-byte B-tree header. Contains `num_cells` entries,
each a 2-byte big-endian offset (relative to page start) pointing to a cell.

### Leaf Table Cell Format

Each cell in a leaf table B-tree page contains:

1. **Payload length** (varint): total bytes of the record payload
2. **Rowid** (varint): the row's INTEGER PRIMARY KEY value
3. **Payload** (record): the actual column data

### SQLite Record Format

A record payload consists of:

1. **Header size** (varint): total bytes of the record header (including this varint)
2. **Serial types** (varints): one per column, indicating the data type and size
3. **Data values**: packed sequentially after the header

### Varint Encoding

SQLite varints are 1–9 bytes. Each byte contributes 7 bits to the value
(high bit = continuation flag), except the 9th byte which uses all 8 bits.

```
def read_varint(data, offset):
    result = 0
    for i in range(9):
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | byte
            return result, 9
```

### Serial Type Reference

| Serial Type | Meaning | Data Size |
|-------------|---------|-----------|
| 0           | NULL    | 0 bytes |
| 1           | 8-bit signed integer | 1 byte |
| 2           | 16-bit signed integer (big-endian) | 2 bytes |
| 3           | 24-bit signed integer (big-endian) | 3 bytes |
| 4           | 32-bit signed integer (big-endian) | 4 bytes |
| 5           | 48-bit signed integer (big-endian) | 6 bytes |
| 6           | 64-bit signed integer (big-endian) | 8 bytes |
| 7           | IEEE 754 64-bit float (big-endian) | 8 bytes |
| 8           | Integer constant 0 | 0 bytes |
| 9           | Integer constant 1 | 0 bytes |
| 10, 11      | Reserved | 0 bytes |
| N ≥ 12, even | BLOB of length (N-12)/2 | (N-12)/2 bytes |
| N ≥ 13, odd  | TEXT of length (N-13)/2 | (N-13)/2 bytes |

## Recovery Methodology

### Phase 1: Standard SQLite Attempt

Always try standard tools first. They may work if corruption is minor:

```bash
sqlite3 damaged.db ".tables"
sqlite3 damaged.db ".schema"
sqlite3 damaged.db "SELECT * FROM tablename;"
```

If these fail with "database disk image is malformed", proceed to raw recovery.

### Phase 2: Extract File Structure

Read the file header to determine page size and page count:

```python
page_size = struct.unpack('>H', data[16:18])[0]
num_pages = len(data) // page_size
```

### Phase 2.5: Auto-Detect Schema from sqlite_master

Before attempting data recovery, try to extract the schema from the sqlite_master table on page 0. This table contains CREATE TABLE SQL statements that reveal column names and types.

**Key insight**: Even if the SQL text is corrupted (e.g., serial type bit-flips causing truncation), enable corruption recovery when parsing sqlite_master records. The "too small" serial type fix will recover the full SQL text.

```python
# Parse sqlite_master record with corrupt_recovery=True
record = parse_record(data, payload_start, payload_len, corrupt_recovery=True)
# Extract: type, name, tbl_name, rootpage, sql
# Parse column names from SQL: CREATE TABLE name (col1 TYPE1, col2 TYPE2, ...)
```

If schema extraction succeeds, use the detected column names for output. If it fails (e.g., schema page completely zeroed), fall back to generic column names (col0, col1, ...) or use schema hints if provided.

### Phase 3: Parse Pages and Cells

For each page:

1. Determine B-tree header offset (100 for page 0, 0 for others)
2. Read page type byte
3. For leaf table pages (0x0D):
   - Extract cell count from B-tree header
   - Read cell pointer array
   - For each cell pointer, parse the cell

### Phase 4: Decode Cell Records

For each cell:

1. Read payload length varint
2. Read rowid varint
3. Parse record header:
   - Read header size varint
   - Read serial type varints until header is consumed
4. For each serial type, extract the corresponding value from the data section

### Phase 5: Corruption Recovery

When standard parsing fails, apply these strategies in order:

#### Strategy A: Validate and Correct Serial Types

Check if a serial type is valid (matches one of the defined types). If invalid:

- Try single-bit-flip corrections (flip each of the 8 bits and re-check)
- Validate the corrected type against remaining payload bounds
- Use schema knowledge to constrain expected types

**Two corruption directions:**

1. **Too large (exceeds bounds)**: Serial type claims more data than remains. Example: 0x61 (97) claims TEXT(42) but only 10 bytes remain. Flip bit 6 → 0x21 (33) = TEXT(10) ✓

2. **Too small (leftover bytes)**: Serial type is structurally valid and fits, but `data_pos < payload_end` after consuming all values. Example: 0x5B (91) claims TEXT(39) but actual text is 41 chars. Flip bit 2 → 0x5F (95) = TEXT(41) ✓

**Critical Implementation Pattern**: Check BOTH conditions in the same branch. Serial type 0x61 is structurally valid (odd ≥ 13 → TEXT of 42) but contextually invalid when only 11 bytes remain. Checking `size < 0` alone misses this:

```python
size = serial_type_size(st)
remaining = payload_end - data_pos

# CRITICAL: Combined check catches both invalid types AND valid-but-too-large types
if size < 0 or size > remaining:
    # Try single-bit-flip corrections
    for bit in range(8):
        candidate = st ^ (1 << bit)
        candidate_size = serial_type_size(candidate)
        if 0 <= candidate_size <= remaining:
            st = candidate
            size = candidate_size
            break
    else:
        return None
```

**Detection**: After parsing all columns, check if `data_pos == payload_end`. If `data_pos < payload_end`, the last serial type was likely corrupted downward. Try bit-flips that increase its data size to consume exactly the remaining bytes.

Example: serial type 0x61 (97) is invalid. Flipping bit 6 gives 0x21 (33),
which is valid TEXT of length 10. If the next 10 bytes are printable text,
accept the correction.

#### Strategy B: Brute-Force Text Scanning

When page headers or cell pointers are damaged:

1. Search the entire file for known text patterns (e.g., "testword", column
   names, or any recognizable strings from the schema)
2. For each hit, scan backward for a valid record header
3. Scan forward to extract the complete record
4. Validate the extracted values against the expected schema

#### Strategy C: Fragment Reassembly

For records split across page boundaries or scattered in zeroed regions:

1. Identify fragments by their content (text patterns, partial serial types)
2. Check if fragments from different offsets can be concatenated
3. Validate the reassembled record structure

#### Strategy D: Schema Inference

When the schema table is damaged but data records survive:

1. Look for patterns in surviving records (consistent column count, type
   sequences)
2. Use the task description or output format hints to infer column names
   and types
3. Validate inferred schema against all recovered records

### Phase 6: Output Serialization

Convert recovered records to the task-specific JSON schema. Common patterns:

- Integer values that are whole numbers: output as JSON integers
- Float values: output as JSON floats
- Text values: output as JSON strings
- NULL values: output as JSON null or omit per schema requirements

## Generalized Recovery Script

The script `scripts/recover.py` implements this methodology with:

- **Input parameters**: database path, output JSON path, optional schema hints
- **Header-guided parsing**: reads page headers and cell pointer arrays
- **Brute-force fallback**: scans for text patterns when headers are damaged
- **Corruption-aware validation**: detects and corrects single-bit errors in
  serial types
- **Flexible output**: adapts to different column schemas and value types

## Family Variation Handling

This skill addresses the spec-defined axes:

- **corruption_mechanism**: Handles truncation (partial file), zeroed regions
  (brute-force scanning), bit-flips (serial type correction), damaged headers
  (skip to next cell), and fragments (pattern-based reassembly)
- **schema_and_value_encoding**: Parses any combination of NULL, integer,
  float, text, and blob columns; handles varying column counts and orders
- **record_identification**: Works with text keys (pattern scanning), numeric
  keys (rowid extraction), interleaved tables (page-level filtering), and
  damaged headers (fallback strategies)
- **recovery_scale**: Processes files from small (2 rows) to large (hundreds
  of rows, multiple pages) by iterating over all pages

## Common Pitfalls

1. **Assuming sqlite3 will work**: Always try it first, but be prepared for
   raw byte-level recovery
2. **Ignoring the file header**: Page size is critical; don't assume 4096
3. **Forgetting page 1 offset**: Page 1's B-tree header starts at offset 100,
   not 0
4. **Mishandling varints**: The 9th byte uses all 8 bits, not 7
5. **Overlooking serial type 8 and 9**: These are constants 0 and 1, not
   data types with payload
6. **Assuming all integers are stored as int64**: SQLite uses the smallest
   serial type that fits the value
7. **Ignoring REAL column schema**: Even if schema says REAL, SQLite may
   store small integers as int8/int16 for efficiency; output format should
   match the task's expectations (int vs float)
8. **Only checking "too large" serial types**: A corrupted serial type may be
   structurally valid and fit within bounds, but be too small (leaving
   unconsumed bytes). Always check `data_pos == payload_end` after parsing.
9. **Not enabling corruption recovery for sqlite_master**: The schema table
   itself can be corrupted. Parse it with `corrupt_recovery=True` to recover
   full SQL text from bit-flipped serial types.
10. **Hardcoding column names**: Extract schema from sqlite_master when
    possible, but be prepared for cases where the schema page is completely
    destroyed. Fall back to generic names or task-provided hints.

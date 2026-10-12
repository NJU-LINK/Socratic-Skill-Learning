---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when ordinary queries fail.
  Implements multi-level recovery: structure-based B-tree parsing with serial type fixup,
  brute-force record scanning with type validation, and auto-discovering pattern-based
  reconstruction. Handles corruption from truncation, zeroed regions, random bit flips,
  damaged page structures, corrupted serial types, multi-table databases, and diverse
  schema encodings.
---

# SQLite Corrupted Database Recovery

## Overview

When `sqlite3` reports "database disk image is malformed", the database file has suffered corruption
that prevents normal query execution. This skill recovers as many rows as possible by parsing the
raw binary format directly, bypassing SQLite's integrity checks.

The recovery is **schema-adaptive**: it detects table definitions from sqlite_master, auto-discovers
text patterns from the data, and validates recovered records against detected column types.

## SQLite Binary Format Reference

### File Layout

```
┌─────────────────────────────────────────┐
│ Page 1: File Header (100 B) + B-tree    │
├─────────────────────────────────────────┤
│ Page 2: B-tree page                     │
├─────────────────────────────────────────┤
│ ... more pages ...                      │
└─────────────────────────────────────────┘
```

### File Header (first 100 bytes, big-endian)

| Offset | Size | Meaning |
|--------|------|---------|
| 0      | 16   | Magic `"SQLite format 3\0"` |
| 16     | 2    | Page size (1=65536, else raw value) |
| 28     | 4    | File size in pages |
| 40     | 4    | Schema cookie |
| 44     | 4    | Schema format number |

### B-tree Page Types

Each page starts with a 1-byte type flag:

| Flag | Meaning |
|------|---------|
| 0x02 | Interior index b-tree page |
| 0x05 | Leaf index b-tree page |
| 0x0A | Interior table b-tree page |
| 0x0D | **Leaf table b-tree page** (contains row data) |

**Critical**: Only leaf table pages (0x0D) contain actual row data with rowids.

### B-tree Page Header

For page 1, the B-tree header starts at offset 100 (after the file header).
For all other pages, it starts at offset 0 within the page.

```
Offset 0:  page_flag              (1 byte)
Offset 1:  first_freeblock        (2 bytes, big-endian)
Offset 3:  cell_count             (2 bytes, big-endian)
Offset 5:  cell_content_offset    (2 bytes, big-endian)
Offset 7:  fragmented_free_bytes  (1 byte)

Cell pointer array: cell_count × 2 bytes (big-endian offsets from page start)
```

### Cell Format (Leaf Table B-tree, flag 0x0D)

Each cell contains:
```
payload_size  (varint)   — total record bytes
rowid         (varint)   — the row identifier
record_data   (payload_size bytes)
```

### Record Format

```
header_size    (varint)  — total header bytes including this varint
serial_type_1  (varint)
serial_type_2  (varint)
...
[body bytes for all columns, concatenated]
```

### Serial Type Codes

| Code | Meaning | Body bytes |
|------|---------|------------|
| 0    | NULL | 0 |
| 1    | 8-bit signed int | 1 |
| 2    | 16-bit signed int | 2 |
| 3    | 24-bit signed int | 3 |
| 4    | 32-bit signed int | 4 |
| 5    | 48-bit signed int | 6 |
| 6    | 64-bit signed int | 8 |
| 7    | IEEE-754 float (double) | 8 |
| 8    | Constant 0 | 0 |
| 9    | Constant 1 | 0 |
| N ≥ 12, even | BLOB | (N-12)/2 bytes |
| N ≥ 13, odd | TEXT (UTF-8) | (N-13)/2 bytes |

### Varint Encoding

Big-endian, up to 9 bytes:
- Bytes 1–8: high bit = continuation flag, low 7 bits = data
- Byte 9: all 8 bits are data
- Value = concatenate the data bits

```python
def read_varint(data, offset):
    result = 0
    for i in range(8):
        if offset + i >= len(data):
            return result, offset + i
        b = data[offset + i]
        result = (result << 7) | (b & 0x7F)
        if b < 0x80:
            return result, offset + i + 1
    if offset + 8 < len(data):
        result = (result << 8) | data[offset + 8]
    return result, offset + 9
```

## Recovery Strategy — Three Levels

### Level 1: Structure-based Recovery (Preferred)

Parse each page's B-tree header and cell pointers to extract records directly.

**When it works**: Page headers and cell pointers are intact, even if some record data is corrupted.

**Key steps**:
1. Parse file header to get page size
2. For each page, check if B-tree header flag is 0x0D (leaf table)
3. Read cell pointer array
4. For each cell: parse payload_size, rowid, then the record
5. Handle corrupted serial types via fixup (see below)

**Serial type fixup**: When a serial type claims more bytes than available in the payload,
the byte was likely bit-flipped. Try to find the correct serial type by computing what
length would make the record fit exactly within the known payload boundary.

Example: serial_type 0x61 (97) claims text of 42 bytes, but only 11 bytes remain.
The correct type is likely 0x21 (33) = text of 10 bytes, which fits perfectly.

### Level 2: Record Scanning (Fallback)

When page headers are corrupted, slide through each page byte-by-byte looking for
valid record structures.

**When it works**: Individual records are intact even though the page structure is damaged.

**Key steps**:
1. For each page, try parsing a record at every offset
2. Validate: serial types must be valid, body must fit within remaining page data
3. Filter: require at least one text value (>3 chars, mostly printable) AND one numeric value
4. Reject records with mostly null bytes or control characters

### Level 3: Auto-discovering Pattern-based Recovery (Last Resort)

Automatically discover text patterns from the data and reconstruct records around them.

**When it works**: Text content survives even when record structure is heavily damaged.

**Key steps**:
1. Scan the file for all printable ASCII sequences ≥6 bytes
2. Find common prefixes that appear multiple times (auto-discovered patterns)
3. For each pattern match, look backward up to 30 bytes for a valid record header
4. If found, parse the full record
5. For bit-flipped text, use fuzzy regex matching with character-class substitution

**Auto-discovery**: The pattern discovery is fully generic — it works with any text content
by finding repeated substrings in the raw data. No hardcoded patterns are needed.

## Overflow Page Handling

When a cell's payload is too large to fit on a single B-tree leaf page, SQLite stores it across multiple pages using an overflow chain.

### Overflow Threshold Formulas

For leaf table B-tree pages (flag 0x0D):
```
U = page_size - reserved_space   (typically reserved_space=0, so U=page_size)
M = ((U - 12) * 32 // 255) - 23   (minimum local payload)
X_max = U - 35                      (maximum local payload)

If payload_size <= X_max:  all bytes are local (no overflow)
If payload_size > X_max:   local_bytes = M + ((payload_size - M) % (U - 4))
                           but if local_bytes > X_max: local_bytes = M
                           overflow_bytes = payload_size - local_bytes
```

**Examples:**
- page_size=4096: M=487, X_max=4061
- page_size=1024: M=103, X_max=989
- page_size=512: M=39, X_max=477

### Overflow Page Structure

```
┌─────────────────────────────────┐
│ Cell on leaf page:              │
│   payload_size (varint)         │
│   rowid (varint)                │
│   local_payload (X bytes)       │
│   overflow_page_ptr (4 bytes BE)│ ← 1-indexed page number
└─────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│ Overflow page N:                │
│   next_page_ptr (4 bytes BE)    │ ← 0 = last page in chain
│   data (page_size - 4 bytes)    │
└─────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│ Overflow page M:                │
│   next_page_ptr = 0x00000000    │ ← end of chain
│   remaining_data                │
└─────────────────────────────────┘
```

### Implementation

The `read_overflow_payload()` function follows the overflow chain:
1. Start with the first overflow page number (from the cell)
2. Read 4-byte next_page pointer (0 = end of chain)
3. Read page_size-4 bytes of payload data
4. Follow next_page pointer to continue the chain
5. Use a visited set to prevent infinite loops from corrupted pointers

The `parse_leaf_table_cell()` function integrates overflow handling:
1. Calculate local vs overflow split using M/X formulas
2. Read local payload bytes
3. If overflow_page > 0, call `read_overflow_payload()` to assemble overflow bytes
4. Concatenate local + overflow bytes
5. Trim to exact payload_size (overflow pages may have padding)
6. Parse the complete record

### Corruption Considerations

- **Corrupted overflow pointers**: If the 4-byte pointer is bit-flipped, the chain breaks. The script gracefully degrades by using whatever local bytes are available.
- **Zeroed overflow pages**: Returns zeros, record parsing may fail but local portion is preserved.
- **Truncated files**: Overflow pages beyond file end are unavailable. The `offset + page_size > len(data)` check handles this.
- **Circular overflow chains**: Corrupted pointers could create cycles. The `visited` set prevents infinite loops.

## Multi-table Support

The script detects **all** table schemas from sqlite_master with robust handling of corruption:

1. Parse page 1's B-tree cells looking for sqlite_master entries
2. Extract CREATE TABLE statements for each table
3. Map root page numbers to table names
4. When formatting output, use the correct schema for each record based on its page

### Robust Schema Detection

Schema detection handles multiple levels of corruption:

1. **Exact match**: Parse the SQL from sqlite_master cells using standard regex
2. **Partial corruption**: If SQL has bit flips or missing characters, use fuzzy matching with permissive patterns (e.g., `CR.ATE\s+TAB.E\s+(\w+)`)
3. **Data-driven inference**: When SQL is completely unreadable, infer schema from data patterns and record structure
4. **Column parsing**: Handles complex column definitions with constraints (NOT NULL, PRIMARY KEY, etc.)

The fuzzy detection uses character-class patterns that allow single-character substitutions, making it resilient to bit flips in SQL keywords like CREATE, TABLE, and column type names.

If sqlite_master is completely corrupted, falls back to searching for CREATE TABLE patterns in raw bytes with fuzzy matching.

## Type Validation

When a schema is detected, recovered records are validated against column types:
- TEXT columns must have text serial types
- REAL/FLOAT columns must have float or int serial types
- INTEGER columns must have int serial types

This prevents false positives from Level 2 scanning where random byte sequences
happen to form valid-looking records with wrong type assignments.

## Corruption Types and Handling

| Corruption Type | Symptom | Recovery Method |
|----------------|---------|-----------------|
| Bit flips in serial types | Record won't parse, claims impossible sizes | Level 1 with fixup |
| Zeroed page regions | Pages are all zeros | Skip, use other pages |
| Corrupted page headers | Invalid page_flag or cell_count | Level 2 scanning |
| Bit flips in text data | Garbled text strings | Level 3 fuzzy matching |
| Truncated file | File shorter than expected | Parse what's available |
| Corrupted cell pointers | Wrong offsets, out of bounds | Level 2 scanning |
| Multiple tables | Different schemas per table | Multi-table detection |
| Unknown text patterns | No hardcoded patterns match | Auto-discovery |
| Overflow page chains | Records spanning multiple pages | Overflow assembly with chain following |
| Corrupted overflow pointers | Broken chain, partial data | Graceful degradation to local bytes |

## Usage

```bash
python3 scripts/recover.py <db_path> <output_json_path>
```

The script:
1. Detects all table schemas from sqlite_master
2. Runs all three recovery levels
3. Auto-discovers text patterns for Level 3
4. Deduplicates results (Level 1 takes priority)
5. Validates records against detected column types
6. Outputs JSON array of recovered rows

## Output Format

The output is a JSON array of objects with column names from the detected schema:

```json
[
  {"word": "testword02", "value": 10},
  {"word": "testword03", "value": 25},
  ...
]
```

Column names come from the CREATE TABLE statement. If no schema is detected,
the script falls back to generic `{"word": ..., "value": ...}` format.

## Implementation Notes

- The recovery script is self-contained in `scripts/recover.py`
- It handles both page-1 (with 100-byte file header offset) and other pages
- Serial type fixup is critical for recovering records with bit-flipped headers
- Auto-discovered patterns adapt to any text content — no hardcoded strings
- Type validation prevents false positives from random byte sequences
- Multi-table support maps records to correct schemas via root page numbers
- Text validation filters out false positives from zero-filled regions
- The script prioritizes Level 1 results over Level 2/3 to avoid garbage data

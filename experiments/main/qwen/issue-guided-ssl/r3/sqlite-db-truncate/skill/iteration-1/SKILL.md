---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when ordinary queries fail.
  Implements multi-level recovery: structure-based B-tree parsing, brute-force record scanning,
  and pattern-based reconstruction. Handles corruption from truncation, zeroed regions,
  random bit flips, damaged page structures, corrupted serial types, and split fragments.
---

# SQLite Corrupted Database Recovery

## Overview

When `sqlite3` reports "database disk image is malformed", the database file has suffered corruption
that prevents normal query execution. This skill recovers as many rows as possible by parsing the
raw binary format directly, bypassing SQLite's integrity checks.

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

### Level 3: Pattern-based Recovery (Last Resort)

Search for known text patterns anywhere in the file and reconstruct records around them.

**When it works**: Text content survives even when record structure is heavily damaged.

**Key steps**:
1. Search for known text patterns (e.g., "testword") in raw bytes
2. For each match, look backward up to 30 bytes for a valid record header
3. If found, parse the full record
4. For bit-flipped text, use fuzzy regex matching

## Corruption Types and Handling

| Corruption Type | Symptom | Recovery Method |
|----------------|---------|-----------------|
| Bit flips in serial types | Record won't parse, claims impossible sizes | Level 1 with fixup |
| Zeroed page regions | Pages are all zeros | Skip, use other pages |
| Corrupted page headers | Invalid page_flag or cell_count | Level 2 scanning |
| Bit flips in text data | Garbled text strings | Level 3 fuzzy matching |
| Truncated file | File shorter than expected | Parse what's available |
| Corrupted cell pointers | Wrong offsets, out of bounds | Level 2 scanning |

## Usage

```bash
python3 scripts/recover.py <db_path> <output_json_path>
```

The script:
1. Detects the schema from sqlite_master (page 1)
2. Runs all three recovery levels
3. Deduplicates results (Level 1 takes priority)
4. Outputs JSON array of recovered rows

## Output Format

The output is a JSON array of objects with column names as keys:

```json
[
  {"word": "testword02", "value": 10},
  {"word": "testword03", "value": 25},
  ...
]
```

For generic recovery without a known schema, the script attempts to produce
`{"word": ..., "value": ...}` format based on the first two columns.

## Implementation Notes

- The recovery script is self-contained in `scripts/recover.py`
- It handles both page-1 (with 100-byte file header offset) and other pages
- Serial type fixup is critical for recovering records with bit-flipped headers
- Text validation filters out false positives from zero-filled regions
- The script prioritizes Level 1 results over Level 2/3 to avoid garbage data

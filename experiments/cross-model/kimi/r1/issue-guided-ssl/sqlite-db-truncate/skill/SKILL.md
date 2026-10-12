---
name: sqlite-db-truncate
description: Recover records from corrupted SQLite databases using low-level format parsing and corruption-tolerant carving
---

# SQLite Database Truncate Recovery

## Overview

This skill provides tools and knowledge for recovering records from SQLite databases that have been corrupted through truncation, bit flips, or other damage that prevents standard SQLite tools from reading them.

## Core Capabilities

1. **Direct File Parsing**: Reads SQLite database files without relying on the SQLite library
2. **Varint Decoding**: Implements SQLite's variable-length integer encoding
3. **Serial Type Interpretation**: Handles SQLite's type system (NULL, integers, floats, text, blobs)
4. **Payload Validation**: Verifies record structure using payload-length consistency checks
5. **Corruption Recovery**: Attempts single-bit-flip correction for damaged serial type bytes

## Usage

```bash
python3 scripts/sqlite_carve.py <input.db> <output.json>
```

## Recovery Principles

### Structural Evidence is Ground Truth

The carver uses only structural evidence from the database file:
- Page header cell counts
- Cell pointer arrays
- Payload length validation
- Serial type width consistency

**No aesthetic filtering** is applied. Records are included if they pass structural validation, regardless of whether they form a "nice" sequence or have unexpected values.

### Bit-Flip Recovery

When payload length validation fails, the carver attempts single-bit-flip recovery on serial type bytes. This handles cases like:
- Serial type 0x61 (corrupted) → 0x21 (TEXT with 10 bytes)
- Any single-bit flip that makes the record structurally consistent

## SQLite File Format Reference

### Database Header (first 100 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0-15 | 16 | Header string "SQLite format 3\0" |
| 16-17 | 2 | Page size (big-endian) |
| 28-31 | 4 | Database size in pages |
| 56-59 | 4 | Text encoding (1=UTF-8) |

### B-Tree Page Header (Leaf Table: type 0x0d)

- Byte 0: Page type (0x0d = leaf table)
- Bytes 1-2: First freeblock offset
- Bytes 3-4: Number of cells (big-endian)
- Bytes 5-6: Start of cell content area
- Byte 7: Number of fragmented free bytes
- Byte 8+: Cell pointer array (2 bytes per cell, big-endian)

### Table Leaf Cell Format

```
payload_len[varint] | rowid[varint] | record
```

### Record Format

```
header_len[varint] | serial_types... | values...
```

**Important**: `header_len` includes the varint itself. After parsing the header_len varint, continue parsing serial types from that position, not from `offset + 1`.

### Serial Type Codes

| Code | Type | Size |
|------|------|------|
| 0 | NULL | 0 bytes |
| 1-6 | Integer | 1, 2, 3, 4, 6, 8 bytes |
| 7 | IEEE 754 float | 8 bytes |
| 8 | Constant 0 | 0 bytes |
| 9 | Constant 1 | 0 bytes |
| 12+N×2 | BLOB | N bytes |
| 13+N×2 | TEXT | N bytes |

### Varint Encoding

- 1-9 bytes, big-endian
- First 8 bytes: 7 data bits + 1 continuation bit
- 9th byte: 8 data bits (no continuation)

## Validation Check

For a valid record:
```
header_len + Σ(serial_type_width(serial_type[i])) == payload_len
```

If this check fails, try bit-flip recovery on each serial type byte.

## v01 Evidence

From `/app/trunc.db` bytes 0x1f77-0x1f88:
```
7465 7374 776f 7264 3039 3fe0 0000 0000 0000
```
- `74...39`: "testword09" (10 bytes of TEXT)
- `3f e0 00 00 00 00 00 00`: IEEE 754 double = 0.5

This is rowid 8, cell pointer 0x0f72, structurally valid with payload length 21 (matches header_len 3 + TEXT 10 + FLOAT 8 = 21).

Page 2 header declares 8 cells at pointers: 0xff0, 0xfe0, 0xfd0, 0xfc0, 0xfb0, 0xfa0, 0xf89, 0xf72. All 8 cells are structurally valid and recovered.

## Limitations

- Assumes single-table databases with data on page 2
- Cell pointers must be readable (b-tree page headers not corrupted)
- Does not handle overflow pages (records spanning multiple pages)
- Limited to UTF-8 text encoding
- Reserved serial types (10, 11) not supported

## Future Enhancements

- Multi-table support via sqlite_master parsing
- Overflow page handling
- Index page traversal
- Schema discovery and validation

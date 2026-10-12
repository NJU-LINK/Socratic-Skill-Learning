# SQLite On-Disk Format Reference (Recovery-Critical Subset)

## File Header (first 100 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0      | 16   | Magic: "SQLite format 3\000" |
| 16     | 2    | Page size (big-endian) |
| 18     | 1    | Write format (1=UTF-8, 2=UTF-16) |
| 19     | 1    | Read format |
| 20     | 1    | Reserved space per page |
| 21     | 1    | Max embedded payload fraction (must be 64) |
| 22     | 1    | Min embedded payload fraction (must be 32) |
| 23     | 1    | Leaf payload fraction (must be 32) |
| 24     | 4    | File change counter |
| 28     | 4    | Database size in pages |

## B-Tree Page Header

For page 1, the b-tree header starts at offset 100 (after the file header).
For all other pages, it starts at offset 0 within the page.

| Offset | Size | Field |
|--------|------|-------|
| 0      | 1    | Page type: 2=int interior, 5=int node, 10=leaf interior, 13=leaf table |
| 1      | 2    | First freeblock offset (0 = none) |
| 3      | 2    | Number of cells |
| 5      | 2    | Cell content area start offset |
| 7      | 1    | Fragmented free bytes |

For interior pages (types 2, 10), there's an additional 4-byte field at offset 8:
the right-most child pointer.

## Cell Pointer Array

Immediately after the page header (offset 8 for leaf pages, offset 12 for interior pages),
there are N 2-byte big-endian cell pointer offsets.

## Leaf Table B-Tree Cell Format

Each cell contains:
1. **Payload size** (varint): total bytes of the record payload
2. **Row ID** (varint): the INTEGER PRIMARY KEY value
3. **Record payload**: the actual row data

For payloads that exceed usable page size minus 12, overflow pages are used.
The first (usable_size - 12) bytes are stored locally, followed by a 4-byte
overflow page number.

## Record Format

A record consists of:
1. **Header size** (varint): total size of the header including this varint
2. **Serial types** (varints): one per column, describing the type and size
3. **Values**: concatenated column data in column order

## Varint Encoding

- Bytes 1-8: high 7 bits are data; low bit = continuation (1 = more bytes follow)
- Byte 9: all 8 bits are data (no continuation bit)
- Maximum 9 bytes, representing a 64-bit signed integer

## Serial Types

| Type | Meaning | Size (bytes) |
|------|---------|--------------|
| 0    | NULL    | 0 |
| 1    | 8-bit signed integer | 1 |
| 2    | 16-bit signed integer (big-endian) | 2 |
| 3    | 24-bit signed integer (big-endian) | 3 |
| 4    | 32-bit signed integer (big-endian) | 4 |
| 5    | 48-bit signed integer (big-endian) | 6 |
| 6    | 64-bit signed integer (big-endian) | 8 |
| 7    | IEEE 754 64-bit float (big-endian) | 8 |
| 8    | Constant 0 (schema format >= 4) | 0 |
| 9    | Constant 1 (schema format >= 4) | 0 |
| N>=12, even | BLOB of length (N-12)/2 | (N-12)/2 |
| N>=13, odd  | Text of length (N-13)/2 in DB encoding | (N-13)/2 |

## Key Integrity Constraint: Payload Size as Checksum

Given a cell's declared payload_size and the parsed record header:
```
expected_payload_size = header_size + sum(serial_type_size(st) for st in serial_types)
```
If `expected_payload_size != payload_size`, the record is corrupted.
This is the primary integrity check for recovery.

## sqlite_master Table

Page 1 always contains the sqlite_master table (rowid=1 for the first entry).
The record has 5 columns: type, name, tbl_name, rootpage, sql.
The `rootpage` field gives the page number of the table's root b-tree page.
The `sql` field contains the CREATE TABLE statement, which tells us column names
and types.

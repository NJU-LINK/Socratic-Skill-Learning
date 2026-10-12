# SQLite File Format Reference

## Overview

SQLite database files have a well-defined binary format. Understanding this format enables recovery of data even when standard tools fail due to corruption.

## File Structure

### Header (bytes 0-99)

```
Offset  Size  Description
------  ----  -----------
0       16    Header string: "SQLite format 3\0"
16      2     Page size (big-endian, 512-65536, or 1 for 65536)
18      1     File format write version
19      1     File format read version
20      1     Bytes of unused "reserved" space at end of each page
21      1     Maximum embedded payload fraction (64)
22      1     Minimum embedded payload fraction (32)
23      1     Leaf payload fraction (32)
24      4     File change counter
28      4     Size of database in pages
32      4     Page number of first freelist trunk page
36      4     Total number of freelist pages
40      4     Schema cookie
44      4     Schema format number
48      4     Default page cache size
52      4     Page number of largest root b-tree page
56      4     Text encoding (1=UTF-8, 2=UTF-16le, 3=UTF-16be)
60      4     User version
64      4     Incremental vacuum mode
68      4     Application ID
72      20    Reserved for expansion
92      4     Version-valid-for
96      4     SQLite version number
```

## Page Types

### B-Tree Page Types

| Value | Type | Description |
|-------|------|-------------|
| 0x02 | Interior index | Index tree internal node |
| 0x05 | Interior table | Table tree internal node |
| 0x0a | Leaf index | Index tree leaf node |
| 0x0d | Leaf table | Table tree leaf node |

## B-Tree Page Layout

### Header (8 bytes for leaf, 12 for interior)

```
Byte  Description
----  -----------
0     Page type
1-2   First freeblock offset (0 if none)
3-4   Number of cells
5-6   Offset to start of cell content area
7     Number of fragmented free bytes
8-11  Right-most child page number (interior only)
```

### Cell Pointer Array

After the header, a sorted array of 2-byte offsets (big-endian) pointing to cell content.

### Cell Content Area

Cells are stored from the end of the page toward the beginning.

## Cell Formats

### Table Leaf Cell

```
Bytes  Field
-----  -----
varint  Payload length (P)
varint  Rowid
P bytes Record payload
```

### Index Leaf Cell

```
Bytes  Field
-----  -----
varint  Payload length (P)
P bytes Record payload
```

## Record Format

Records are used for table rows and index entries.

### Header

```
Bytes  Field
-----  -----
varint  Header length (H)
varint  Serial type for column 0
varint  Serial type for column 1
...     More serial types...
```

The header length includes the length byte itself.

### Serial Types

Serial types are stored as varints in the header and determine both the column type and the number of bytes used for the value in the body.

| Serial Type | Meaning | Bytes of Data |
|-------------|---------|---------------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit signed int | 2 |
| 3 | 24-bit signed int | 3 |
| 4 | 32-bit signed int | 4 |
| 5 | 48-bit signed int | 6 |
| 6 | 64-bit signed int | 8 |
| 7 | IEEE 754-2008 float | 8 |
| 8 | Integer constant 0 | 0 |
| 9 | Integer constant 1 | 0 |
| 10,11 | (Reserved) | - |
| N≥12, even | BLOB | (N-12)/2 |
| N≥13, odd | TEXT | (N-13)/2 |

### Body

The body follows immediately after the header and contains the actual values encoded according to their serial types.

## Integer Encoding

Integers are stored big-endian (most significant byte first) with two's complement for signed values.

## Floating Point Encoding

IEEE 754-2008 64-bit floating point values, big-endian.

## Text Encoding

Text is stored as UTF-8 by default (determined by header bytes 56-59).

## Varint Encoding

Varints encode integers using 1-9 bytes:

- Each byte contributes 7 bits to the value
- The high bit (0x80) is set on all bytes except the last
- For the 9th byte, all 8 bits are used (no continuation bit)

### Encoding Algorithm

```python
def encode_varint(value):
    result = []
    while value >= 0x80:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)
```

### Decoding Algorithm

```python
def decode_varint(data, offset):
    result = 0
    for i in range(9):
        byte = data[offset + i]
        if i == 8:
            result = (result << 8) | byte
            return result, offset + 9
        else:
            result = (result << 7) | (byte & 0x7f)
            if not (byte & 0x80):
                return result, offset + i + 1
```

## Corruption Patterns

### Bit Flips

Single bit flips can corrupt:
- Serial type bytes (changing column types)
- Varint continuation bits (changing value sizes)
- Page type bytes (misinterpreting page structure)

### Truncation

File truncation may:
- Remove cells from the end of the database
- Leave partial records
- Corrupt b-tree structures

### Zeroed Regions

Zeroed bytes can cause:
- NULL values where data existed
- Lost cell pointers
- Empty pages

## Recovery Strategies

### Payload Validation

Verify that: `header_len + Σ(column_widths) == payload_len`

If this fails, try bit-flip recovery on serial type bytes.

### Pattern Matching

When cell pointers are corrupted:
- Scan for known text signatures
- Try parsing at each potential offset
- Validate extracted records

### Schema Recovery

The `sqlite_master` table (page 1) contains:
- Table names and definitions
- Column names and types
- Index information

This can be parsed even if data pages are corrupted.

## References

- SQLite File Format: https://www.sqlite.org/fileformat.html
- Database File Format: https://www.sqlite.org/fileformat2.html

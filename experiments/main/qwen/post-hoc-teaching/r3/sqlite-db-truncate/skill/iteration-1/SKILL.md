---
name: sqlite-db-truncate
description: >-
  Recover logically valid rows from damaged SQLite database files when ordinary
  queries fail due to corruption (bit flips, zeroed regions, truncation, damaged
  page structures). Parses the SQLite file format at the byte level, extracts
  cell data from b-tree leaf pages, repairs corrupted record headers using
  schema-guided disambiguation, handles overflow pages for large records,
  traverses multi-table b-trees, and serializes recovered rows to JSON.
---

# SQLite Database Recovery Skill

## Purpose

Recover rows from corrupted SQLite database files by parsing the binary format
directly, bypassing the SQLite library which rejects damaged files. Output
recovered records as JSON.

## Quick Start

```bash
# Run the recovery script
python3 recover_sqlite.py <input.db> <output.json> [col1,col2,...]

# Or use inline Python for one-off recovery
python3 -c "
import struct, json
# ... (see Detailed Procedure below)
"
```

## SQLite File Format Reference

### Database Header (first 100 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0-15   | 16   | Magic: "SQLite format 3\000" |
| 16-17  | 2    | Page size (big-endian; 1 means 65536) |
| 18     | 1    | File format write version |
| 19     | 1    | File format read version |
| 20     | 1    | Reserved space per page |
| 28-31  | 4    | Database size in pages |
| 44-47  | 4    | Application ID |
| 56-59  | 4    | SQLite version number |

### Page Types

- **0x02**: Interior index b-tree page
- **0x05**: Interior table b-tree page
- **0x0a**: Leaf index b-tree page
- **0x0d**: Leaf table b-tree page (contains actual row data)

### Leaf Table B-tree Page Header

| Offset | Size | Field |
|--------|------|-------|
| 0      | 1    | Flag (0x0d for leaf table) |
| 1-2    | 2    | First freeblock offset (0 = none) |
| 3-4    | 2    | Number of cells |
| 5-6    | 2    | First byte of cell content area |
| 7      | 1    | Fragmented free bytes |

For page 1 only, the b-tree header starts at offset 100 (after the file header).

### Interior Table B-tree Page Header

| Offset | Size | Field |
|--------|------|-------|
| 0      | 1    | Flag (0x05 for interior table) |
| 1-2    | 2    | First freeblock offset |
| 3-4    | 2    | Number of cells |
| 5-6    | 2    | First byte of cell content area |
| 7      | 1    | Fragmented free bytes |
| 8-11   | 4    | Rightmost child page number |

Interior page cell format:
- 4 bytes: left child page number (big-endian uint32)
- varint: rowid (maximum rowid in left child's subtree)

### Cell Format (Leaf Table)

1. **Payload length** (varint)
2. **Row ID** (varint)
3. **Payload** (SQLite record, possibly with overflow)

### SQLite Record Format

1. **Header size** (varint, includes itself)
2. **Serial types** (one varint per column)
3. **Data values** (encoded per serial type)

### Serial Types

| Code | Meaning | Size |
|------|---------|------|
| 0    | NULL | 0 |
| 1    | 8-bit signed int | 1 |
| 2    | 16-bit signed big-endian int | 2 |
| 3    | 24-bit signed big-endian int | 3 |
| 4    | 32-bit signed big-endian int | 4 |
| 5    | 48-bit signed big-endian int | 6 |
| 6    | 64-bit signed big-endian int | 8 |
| 7    | 64-bit IEEE 754 float | 8 |
| 8    | Constant 0 | 0 |
| 9    | Constant 1 | 0 |
| N≥12, even | BLOB of (N-12)/2 bytes | (N-12)/2 |
| N≥13, odd  | TEXT of (N-13)/2 bytes | (N-13)/2 |

### Varint Encoding

- Bytes with high bit set continue to next byte
- Up to 9 bytes; first 8 contribute 7 bits each, 9th contributes 8 bits
- All big-endian

### Overflow Pages

When a record's payload exceeds the local limit X, SQLite stores it across
multiple pages:

**Local payload limit calculation**:
```
U = page_size - reserved_space
X = min(U - 35, (U - 12) * 64/255 - 23)
```

If `payload_len > X`:
- First X bytes stored locally in the cell
- Last 4 bytes of local area contain first overflow page number (big-endian uint32)
- Each overflow page: 4 bytes next page number (0=end), then data filling rest of page
- Follow chain to reassemble full payload

## Detailed Recovery Procedure

### Step 1: Read and Validate File

```python
data = open(db_path, 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0]
if page_size == 1: page_size = 65536
reserved_space = data[20]
num_pages = len(data) // page_size
```

### Step 2: Recover Schema

**Primary**: Parse page 1 (sqlite_master table) at b-tree offset 100.
Each cell has 5 columns: type, name, tbl_name, rootpage, sql.

Extract ALL table schemas (not just the first), storing table_name → schema
and table_name → rootpage mappings.

**Fallback**: Scan raw file bytes for `CREATE TABLE` patterns.

### Step 3: Traverse B-trees

For each table in sqlite_master:
1. Start from its rootpage
2. If leaf page (0x0d), parse cells directly
3. If interior page (0x05), extract child page numbers and recurse
4. Associate each recovered row with its table's schema

### Step 4: Parse and Repair Records

For each cell:
1. Read payload length and row ID (varints)
2. **Check overflow**: if payload_len > X, read overflow chain
3. Parse record header (header size + serial types)
4. **Validate**: sum of serial type sizes + header size must equal payload length
5. **Repair if needed**: try single-bit flips on serial type bytes
   - **Schema-guided**: score by compatibility with expected column affinity
   - **Fallback**: prefer TEXT types when no schema available
6. Decode values according to (possibly repaired) serial types

### Step 5: Output JSON

Map column values to the schema's column names. Write as JSON array of objects.

## Corruption Handling Strategies

### Bit-Flip Corruption
- Detect via payload-length mismatch
- Repair by trying single-bit flips on serial type bytes
- **Schema-guided disambiguation**: use column type affinities to score candidates
  - INTEGER columns: serial types 1-6
  - REAL/FLOAT columns: serial types 1-7
  - TEXT columns: serial types ≥13, odd
  - BLOB columns: serial types ≥12, even
  - NULL (type 0) always valid
- Fallback to TEXT-preference heuristic when no schema available
- Also try 2-bit flips if single-bit doesn't resolve

### Overflow Page Corruption
- Calculate local payload limit X from page_size and reserved_space
- If payload_len > X, extract overflow page number from last 4 bytes of local area
- Follow overflow page chain: each page has 4-byte next pointer + data
- Reassemble full payload from local + overflow data
- Handle truncated chains gracefully (skip incomplete records)

### Zeroed Regions
- Skip cells where payload is all zeros
- Skip pages where b-tree header is zeroed

### Truncated Files
- Process only available pages
- Handle partial pages at end of file
- Skip records that extend beyond file boundary

### Damaged Page Structures
- Scan all page offsets for valid flag bytes (0x0d or 0x05)
- Validate cell pointer arrays:
  - Pointers must be past the header + pointer array area
  - Pointers must be within page bounds
  - Reject unreasonable cell counts (>10000)
- Skip pages with invalid structures

## Key Implementation Notes

1. **Varint decoding** must handle the 9-byte edge case correctly
2. **All integers** in SQLite are big-endian
3. **Page 1** has a 100-byte file header prefix before the b-tree header
4. **Cell pointers** are relative to the start of their page
5. **Deduplication** may be needed if corruption creates phantom duplicate cells
6. **Schema inference** from sqlite_master is more reliable than raw SQL scanning
7. **Integer values** stored in REAL columns are valid (SQLite type affinity)
8. **Overflow pages** are 1-indexed (page 1 = offset 0, page 2 = offset page_size)
9. **Interior pages** have 12-byte headers (8 standard + 4 for rightmost child)
10. **Multi-table recovery** requires traversing each table's b-tree separately

## Assets

- `recover_sqlite.py`: Complete recovery script handling all corruption types

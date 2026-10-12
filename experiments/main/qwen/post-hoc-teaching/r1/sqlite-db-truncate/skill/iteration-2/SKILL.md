---
name: sqlite-db-truncate
description: >
  Recover rows from corrupted SQLite database files when standard queries fail.
  Parses SQLite binary format including B-tree traversal (interior + leaf pages),
  overflow page chains, record headers, varints, and serial types. Handles
  corruption mechanisms including truncation, zeroed regions, random byte flips,
  damaged page structures, and fragmented records. Supports multi-table databases.
  Outputs recovered rows as JSON.
---

# SQLite Database Recovery Skill

## Overview

Recover data from corrupted SQLite database files by parsing the binary format
directly, bypassing the standard library's integrity checks. Handles bit flips,
zeroed regions, truncation, and damaged structures. Supports multi-table
databases via B-tree traversal.

## Quick Start

The skill includes a complete recovery script at:
```
/skill/sqlite-db-truncate/recover.py
```

**Run it from the task container:**
```bash
python3 /skill/sqlite-db-truncate/recover.py <db_path> <output.json> [--columns col1,col2,...]
```

The `--columns` flag overrides column names when the schema can't be recovered
from the database itself. Column names should match the JSON keys specified in
the task instruction.

If the script doesn't fully solve the task (e.g., unusual corruption patterns),
use the strategy below to implement custom recovery inline.

## Recovery Strategy

### Phase 1: Try Standard Access

Always try `sqlite3` first. If it works, serialize directly and skip binary parsing.

```python
import sqlite3
try:
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for (tname,) in tables:
        rows = conn.execute(f"SELECT * FROM [{tname}]").fetchall()
        # serialize...
except:
    pass  # Fall through to binary recovery
```

### Phase 2: Schema Extraction from sqlite_master

Page 1 (offset 0) has a 100-byte file header, then a b-tree page header.
The sqlite_master record has 5 columns:

| Column | Type | Content |
|--------|------|---------|
| 0 | TEXT | type: "table" |
| 1 | TEXT | table name |
| 2 | TEXT | table name (same) |
| 3 | INT | **rootpage** — root page number of the table's B-tree |
| 4 | TEXT | CREATE TABLE SQL statement |

**Critical**: The `rootpage` (column 3) tells you where the table's B-tree starts.
You must traverse from this root to find all leaf pages belonging to that table.

**Handle truncated SQL**: corruption may truncate the CREATE statement. Parse
what's available — column definitions before the truncation point are still valid.
The regex `CREATE\s+TABLE\s+\w+\s*\((.+)` (without requiring closing paren) works.

**When schema is unrecoverable**: If the schema page is too corrupted, you must
infer column count and types from the data itself:
- Scan leaf pages for valid records
- Count consistent serial types per record to determine column count
- Use the task instruction's JSON format to determine column names
- Use `--columns` flag or inline override

### Phase 3: B-tree Traversal

SQLite organizes table data in a B-tree. The root page number comes from
sqlite_master. You must walk the tree to find all leaf pages.

#### Page Types

| Type | Name | Content |
|------|------|---------|
| 0x02 | Interior index B-tree | Not relevant for table data |
| 0x05 | Interior table B-tree | Child pointers + separator rowids |
| 0x0A | Leaf index B-tree | Not relevant for table data |
| 0x0D | Leaf table B-tree | Actual row data |

#### Interior Table Page (0x05) Header

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Type: 0x05 |
| 1-2 | 2 | First freeblock offset |
| 3-4 | 2 | Number of cells |
| 5-6 | 2 | Content area start |
| 7 | 1 | Fragmented free bytes |
| 8-11 | 4 | **Right-most child page number** (uint32 big-endian) |
| 12+ | 2*n | Cell pointer array |

**Note**: Interior pages have a 4-byte right-most pointer that leaf pages don't have.
Cell pointer array starts at offset 12 (not 8).

#### Interior Cell Format

Each cell in an interior table page contains:
1. **Child page number** — 4 bytes, big-endian uint32
2. **Row ID** — varint (separator key, not a stored record)

Interior cells have **NO record payload**. They only route to child pages.

#### Leaf Table Page (0x0D) Header

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Type: 0x0D |
| 1-2 | 2 | First freeblock offset |
| 3-4 | 2 | Number of cells |
| 5-6 | 2 | Content area start |
| 7 | 1 | Fragmented free bytes |
| 8+ | 2*n | Cell pointer array |

#### Leaf Cell Format

Each cell contains:
1. **Payload length** (varint)
2. **Row ID** (varint)
3. **Payload** (SQLite record, possibly partial if overflowed)
4. **Overflow page number** (4 bytes, only if payload overflows)

#### B-tree Traversal Algorithm

```python
def collect_leaf_pages(data, page_size, root_page):
    """Walk B-tree from root_page, collecting all leaf page numbers."""
    leaf_pages = []
    visited = set()
    num_pages = len(data) // page_size

    def walk(page_num):
        # SQLite page numbers are 1-indexed: page 1 = offset 0
        if page_num < 1 or page_num > num_pages:
            return
        if page_num in visited:
            return
        visited.add(page_num)

        start = (page_num - 1) * page_size
        page = data[start:start + page_size]
        hdr = 100 if page_num == 1 else 0
        ptype = page[hdr]

        if ptype == 0x0D:  # Leaf table
            leaf_pages.append(page_num)
        elif ptype == 0x05:  # Interior table
            n_cells = struct.unpack('>H', page[hdr+3:hdr+5])[0]
            rightmost = struct.unpack('>I', page[hdr+8:hdr+12])[0]

            ptr_base = hdr + 12  # After rightmost pointer
            for i in range(n_cells):
                cp = ptr_base + 2 * i
                cell_off = struct.unpack('>H', page[cp:cp+2])[0]
                child = struct.unpack('>I', page[cell_off:cell_off+4])[0]
                walk(child)

            walk(rightmost)  # Don't forget rightmost!

    walk(root_page)
    return leaf_pages
```

**Important**: SQLite page numbers are **1-indexed**. Page 1 = offset 0 in the file,
page 2 = offset page_size, etc. Page 1 has a 100-byte file header, so its b-tree
header is at offset 100. All other pages have b-tree header at offset 0.

### Phase 4: Record Parsing

#### SQLite Record Format

A record payload consists of:
1. **Header size** (varint) — total header bytes including this varint
2. **Serial types** (varints) — one per column
3. **Column data** — concatenated in column order

#### Serial Type Table

| Code | Type | Size |
|------|------|------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit signed int (big-endian) | 2 |
| 3 | 24-bit signed int | 3 |
| 4 | 32-bit signed int | 4 |
| 5 | 48-bit signed int | 6 |
| 6 | 64-bit signed int | 8 |
| 7 | IEEE 754 float64 (big-endian) | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12, even | BLOB | (N-12)/2 bytes |
| N≥13, odd | TEXT (UTF-8) | (N-13)/2 bytes |

#### Varint Format

1-9 bytes. Each byte uses 7 data bits (low 7), high bit = continuation.
Exception: 9th byte uses all 8 bits (supports full 64-bit range).

```python
def read_varint(data, offset):
    """Returns (value, bytes_consumed). NOT absolute offset."""
    result = 0
    for i in range(9):
        if offset + i >= len(data):
            return result, i
        b = data[offset + i]
        if i < 8:
            result = (result << 7) | (b & 0x7f)
            if b < 0x80:
                return result, i + 1
        else:
            result = (result << 8) | b
            return result, i + 1
    return result, 9
```

### Phase 5: Overflow Page Handling

When a record's payload exceeds the page's usable space, SQLite stores the
excess on overflow pages.

**Detection**: If `rec_offset + payload_len > page_size`, the cell overflows.

**Overflow structure**:
1. The leaf cell stores a partial (local) payload + 4-byte first overflow page#
2. Each overflow page: first 4 bytes = next overflow page# (0 = end), rest = payload
3. Full record = local_payload + concat(overflow_page[4:] for each page in chain)

**Threshold**: Overflow occurs when payload > usable_space - 35 (approximately).
For 4KB pages, that's roughly payload > ~4050 bytes.

### Phase 6: Corruption Detection and Repair

#### Detection

A record is corrupted when:
- **Over-declared**: Serial types imply more data than the payload contains
  - `header_size + sum(serial_type_sizes) > payload_len`
- **Under-declared**: Serial types imply less data than the payload contains
  - `header_size + sum(serial_type_sizes) < payload_len`
- Cell pointers are out of bounds or overlapping
- Page type byte is invalid

Both cases indicate corruption and require repair.

#### Repair Strategy for Corrupted Serial Types

When a serial type byte has been corrupted (bit-flipped or otherwise damaged):

1. **Enumerate candidates**: For the corrupted column, compute how many bytes are available
2. **Generate all valid serial types** that match the available byte count:
   - Integer types: st=1 (1 byte), st=2 (2 bytes), st=3 (3 bytes), st=4 (4 bytes), st=5 (6 bytes), st=6 (8 bytes)
   - Float: st=7 (8 bytes)
   - Text: st=13+2*n for n bytes
   - Blob: st=12+2*n for n bytes
   - NULL/Constants: st=0,8,9 (0 bytes)
3. **Schema-guided selection**: Use column type hints from the schema to pick the best match:
   - INTEGER columns → prefer integer serial types (1-6)
   - REAL columns → prefer float serial type (7)
   - TEXT columns → prefer text serial types (odd ≥ 13)
   - BLOB columns → prefer blob serial types (even ≥ 12)
4. **Validation scoring**: When multiple fixes are possible, score each candidate:
   - Text values: +2 for valid UTF-8, +1 for printable ASCII, +5 for "table" in schema records, +3 for SQL keywords
   - Integer values: +2 if type matches, +1 if in reasonable range (0-1000)
   - Float values: +2 if type matches
5. **Re-decode** with the corrected serial type

**Example 1 (Over-declared)**: Serial type 0x21 (33, text 10 bytes) corrupted to 0x61 (97, text 42 bytes).
The payload was only 14 bytes, so 0x61 was impossible. Correcting to 0x21 recovered the original text.

**Example 2 (Under-declared)**: Serial type 0x01 (int8, 1 byte) corrupted to 0x00 (NULL, 0 bytes).
The payload had 1 extra byte. Correcting to 0x01 recovered the integer value.

**Example 3 (Wrong type)**: Serial type 0x04 (int32, 4 bytes) corrupted to 0x44 (blob 28 bytes).
The schema indicated INTEGER column. Enumerating candidates for 4 bytes: [1,2,3,4,7-text,6-blob]. Schema guidance selected st=4 (int32), recovering the correct integer value.

#### Corruption in Interior Pages

- **Corrupted child pointer**: Points to invalid page → skip that subtree,
  continue traversing other children
- **Unreadable interior page**: Fall back to scanning all leaf pages and
  assign by matching column count
- **Missing rootpage**: If only one table, all leaf pages likely belong to it

### Phase 7: Raw Scanning (Fallback)

When page structures are too damaged:
1. Scan entire file byte-by-byte for valid record patterns
2. At each offset, try parsing a record header (first byte = header size)
3. Validate: header size matches serial type count, data sizes are consistent
4. Use known text patterns to filter false positives
5. This works even when ALL page headers are destroyed

### Phase 8: Output

**Read the task instruction carefully** for the exact JSON format. Map recovered
column values to the specified keys:

```python
import json
output = []
for row in recovered_rows:
    obj = {col_name: value for col_name, value in zip(column_names, row)}
    output.append(obj)
with open(output_path, 'w') as f:
    json.dump(output, f)
```

**Type handling**: SQLite may store integers in REAL columns. Output values as-is
(int or float). The test framework typically accepts both `10` and `10.0` for a
REAL column, but match the instruction's examples when possible.

## Key Implementation Notes

1. **read_varint returns (value, bytes_consumed)** — not absolute offset. Callers
   must track position by adding bytes_consumed.

2. **Page numbers are 1-indexed** — Page 1 = offset 0, Page 2 = offset page_size, etc.
   Page 1 has a 100-byte file header, so its b-tree header is at offset 100.
   All other pages have b-tree header at offset 0.

3. **Interior pages (0x05)** have a 4-byte rightmost pointer at offset 8, pushing
   the cell pointer array to offset 12.

4. **Interior cells** contain only [child_page:4][rowid:varint] — no record payload.

5. **Schema SQL may be truncated** — parse_column_info should handle missing
   closing parenthesis.

6. **rootpage from sqlite_master** is essential for multi-table databases.
   Each table has its own B-tree rooted at its rootpage.

7. **Integer values in REAL columns** — SQLite may store integers even in REAL
   columns. Output the value as-is (int or float).

8. **Overflow pages** — for large records, follow the 4-byte page number chain.

9. **recover.py is at `/skill/sqlite-db-truncate/recover.py`** inside the task
   container. It can be run directly or used as a reference for inline recovery.

## Assets

- `recover.py` — Standalone recovery script at `/skill/sqlite-db-truncate/recover.py`
  implementing the full pipeline (B-tree traversal, overflow handling, corruption
  repair, multi-table support, raw scan fallback)

---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite database files when
  standard tools (sqlite3) report corruption. Combines SQLite binary format
  knowledge (page headers, B-tree cells, cell pointer arrays, record headers,
  varints, serial types) with raw byte scanning and bit-flip correction to
  extract records from corrupted pages. Serializes recovered records to the
  case-specific JSON schema.
---

# SQLite Database Corruption Recovery

## Overview

When a SQLite database file has corrupted bytes (bit flips, zeroed regions,
truncated areas, damaged page structures), `sqlite3` will typically report
"database disk image is malformed". The recovery strategy is to bypass the
standard query path and parse the raw binary data directly, using knowledge
of the SQLite on-disk format to identify and extract valid records.

## Recovery Algorithm (General)

### Step 1: Determine the Output Schema
The task instruction specifies the JSON output format. Parse it carefully to
identify column names and expected types. Common patterns:
- `[{"word": "...", "value": N}, ...]` — text key + numeric value
- `[{"key": "...", "data": "..."}, ...]` — two text columns
- Multi-table cases may require identifying table boundaries

### Step 2: Try sqlite3 First
```bash
sqlite3 /app/trunc.db ".tables" 2>&1
sqlite3 /app/trunc.db "SELECT * FROM tablename;" 2>&1
```
If sqlite3 works, use SQL directly. Only proceed to raw recovery if it fails.

### Step 3: Read File Header and Page Structure
```python
data = open('trunc.db', 'rb').read()
page_size = int.from_bytes(data[16:18], 'big')  # offset 16-17
total_pages = len(data) // page_size
```
Verify magic: `data[0:16] == b'SQLite format 3\x00'`

### Step 4: Extract Schema from sqlite_master (Page 1)
Page 1 (offset 0) contains the schema. Its B-tree header starts at offset 100
(after the 100-byte file header). Parse its cell pointer array and cells to
find `CREATE TABLE` statements. This tells you:
- **Table names**: The name of each table
- **Root page numbers**: Which page is the root of each table's B-tree
- **Column names**: Parsed from the SQL (even if truncated)
- **Column types**: Inferred from SQL type declarations

For multi-table databases, this step is critical for associating records with
the correct table and using the right column names.

### Step 5: For Each Data Page, Use the Cell Pointer Array
This is the **primary recovery mechanism**. For each table discovered in Step 4:

1. **Traverse the B-tree** from the table's root page to find all leaf pages:
   - **Leaf table pages** (type 0x0D): contain actual records
   - **Interior table pages** (type 0x0A): contain pointers to child pages
   - Interior page header: 12 bytes (8-byte base + 4-byte rightmost child pointer)
   - Interior cells: 4-byte left child page number + varint rowid
   - Traverse all children recursively to find all leaf pages

2. **For each leaf page**, read the B-tree page header:
   - Byte 0: page type (0x0D = leaf table b-tree)
   - Bytes 1-2: first freeblock offset
   - Bytes 3-4: cell count (uint16 BE) — **tells you how many records exist**
   - Bytes 5-6: cell content area start offset
   - Byte 7: fragmented free bytes

3. **Read the cell pointer array** (immediately after the 8-byte header):
   - `cell_count` entries, each a uint16 BE offset within the page
   - Each pointer gives the exact start of one cell

4. **Parse each cell** using the pointer:
   - Payload size (varint)
   - Rowid (varint)
   - Record payload (SQLite record format)

5. **Handle overflow pages** if payload_size exceeds the local limit (see below).
6. **If the page header is corrupted**, fall back to raw scanning (Step 6).

### Overflow Pages (Large Records)

When a record's payload is too large to fit on a single page, SQLite splits it
across multiple pages. The local payload occupies all remaining space on the
current page from the payload start position to the page boundary.

**Key insight**: The local payload is NOT computed by a formula — it's simply
whatever space remains on the page:
```python
page_end = page_num * page_size
local_payload = data[payload_start:page_end]
```

If `payload_size > len(local_payload)`, overflow pages are used:
- **Last 4 bytes of local payload**: overflow page number (uint32 BE)
- **Local data** (excluding the 4-byte pointer): `local_payload[:-4]`
- Remaining payload bytes are on overflow pages

Each overflow page has:
- Bytes 0-3: next overflow page number (uint32 BE, 0 = last page)
- Bytes 4 to page_size-1: continuation payload data (page_size - 4 bytes per page)

**Reconstruction algorithm:**
```python
def read_payload_with_overflow(data, payload_start, payload_size, page_size, page_num):
    page_end = page_num * page_size
    local_payload = data[payload_start:page_end]
    
    # No overflow needed
    if payload_size <= len(local_payload):
        return data[payload_start:payload_start + payload_size]
    
    # Overflow: last 4 bytes are the page pointer
    overflow_page_num = int.from_bytes(local_payload[-4:], 'big')
    local_data = local_payload[:-4]
    
    full_payload = local_data
    bytes_remaining = payload_size - len(local_data)
    current_page = overflow_page_num
    
    while bytes_remaining > 0 and current_page > 0:
        page_offset = (current_page - 1) * page_size
        next_page = int.from_bytes(data[page_offset:page_offset+4], 'big')
        page_data = data[page_offset+4:page_offset+page_size]
        bytes_available = min(len(page_data), bytes_remaining)
        full_payload += page_data[:bytes_available]
        bytes_remaining -= bytes_available
        current_page = next_page
    
    return full_payload if bytes_remaining == 0 else None
```

**Important**: The last 4 bytes of the local payload are the overflow page pointer,
NOT record data. Always use `local_payload[:-4]` when reconstructing.

### Step 6: Fallback — Raw Scanning
If the page header is unreadable:
- Scan from the bottom of the page upward
- At each offset, try to parse a valid cell (payload_size + rowid + valid record)
- Use record structure validation (valid header size, valid serial types, body
  size matches payload) to identify cell boundaries
- Search for recognizable text patterns as anchors

### Step 7: Handle Corruption in Record Parsing
When a record fails to parse:

**Corrupted serial types (bit flips):**
- If a serial type implies a body size larger than the payload, it's corrupted
- Try flipping individual bits (especially bit 6, which is commonly flipped)
- Verify the corrected serial type produces a consistent parse
- **Exact-fit heuristic**: Prefer serial types where `header_size + total_body_size == payload_size` (no wasted bytes)
- **Text-over-blob preference**: When multiple serial types give exact fit, prefer text (odd serial types ≥13) over blob (even serial types ≥12)

**Zeroed regions:**
- Records entirely in zeroed areas are unrecoverable
- Partially zeroed records may be salvageable if key fields survive

**Cross-page overflow:**
- If payload_size exceeds space remaining on the page, the record uses overflow pages
- Local payload: all bytes from payload_start to page end (last 4 = overflow page pointer, NOT data)
- Follow overflow chain: each page has 4-byte next pointer + (page_size-4) data bytes
- Reconstruct: `full_payload = local[:-4] + overflow_chain_data`
- If overflow chain is broken (corrupted page number), use partial data
- If a payload_size varint decodes to > file_size, it's likely a corrupted varint, not overflow

### Step 8: Serialize Output
Convert recovered records to the specified JSON format. Pay attention to:
- Integer values → JSON numbers (no decimal)
- Float values → JSON numbers (preserve decimal if non-integer)
- Text values → JSON strings
- NULL → JSON null

## SQLite On-Disk Format Reference

### File Header (first 100 bytes)
| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 | Magic: "SQLite format 3\000" |
| 16 | 2 | Page size (big-endian uint16) |
| 18 | 1 | File format write version |
| 19 | 1 | File format read version |
| 28 | 4 | File change counter |
| 32 | 4 | Database size in pages |
| 56 | 4 | Schema cookie |

### B-Tree Page Header (8 bytes for leaf, 12 bytes for interior)
For non-root pages: at page start. For page 1: at offset 100.

**Leaf table page (type 0x0D):**
| Byte | Field |
|------|-------|
| 0 | Page type: 0x0D |
| 1-2 | First freeblock offset (0 if none) |
| 3-4 | Number of cells |
| 5-6 | Cell content area start offset (within page) |
| 7 | Fragmented free bytes count |

**Interior table page (type 0x0A):**
| Byte | Field |
|------|-------|
| 0 | Page type: 0x0A |
| 1-2 | First freeblock offset (0 if none) |
| 3-4 | Number of cells |
| 5-6 | Cell content area start offset (within page) |
| 7 | Fragmented free bytes count |
| 8-11 | Rightmost child page number (uint32 BE) |

Note: Interior pages have an extra 4-byte field for the rightmost child pointer.

### Cell Pointer Array
Immediately after the 8-byte B-tree header: `cell_count × 2` bytes of uint16 BE
offsets, each pointing to a cell within the page.

### Table Leaf Cell Format
1. **Payload size** (varint): Total bytes of the record payload
2. **Rowid** (varint): The row's rowid
3. **Payload**: The SQLite record

### Interior Table Cell Format
1. **Left child page number** (uint32 BE): Page number of the left child
2. **Rowid** (varint): The divider key (not a full record)

Interior cells don't contain full records; they only store divider keys to guide B-tree traversal. The actual records are on leaf pages.

### SQLite Record Format
1. **Header size** (varint): Size of the header including this varint
2. **Serial types** (varints): One per column
3. **Body**: Values packed sequentially

### Varint Encoding
1-9 bytes. Bytes 1-8: high 7 bits = data, low bit = continuation (1=more, 0=last).
Byte 9: all 8 bits are data.

### Serial Types
| Type | Meaning | Body Size |
|------|---------|-----------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit signed big-endian int | 2 |
| 3 | 24-bit signed big-endian int | 3 |
| 4 | 32-bit signed big-endian int | 4 |
| 5 | 48-bit signed big-endian int | 6 |
| 6 | 64-bit signed big-endian int | 8 |
| 7 | IEEE 754 64-bit big-endian float | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12, even | BLOB of length (N-12)/2 | (N-12)/2 |
| N≥13, odd | Text UTF-8 of length (N-13)/2 | (N-13)/2 |

## Reference Implementation

The complete recovery implementation is in `recover_sqlite.py`, which includes:

- **Multi-table support**: Parses sqlite_master to extract table definitions with root page numbers and column names
- **B-tree traversal**: Recursively traverses from root pages through interior pages to find all leaf pages for each table
- **Overflow page handling**: Correctly reconstructs payloads that span multiple pages
- **Cell pointer array parsing**: Primary recovery mechanism using the authoritative cell index
- **Raw scanning fallback**: Bottom-up scanning when page headers are corrupted
- **Bit-flip correction**: Attempts to fix corrupted serial types by flipping individual bits, with exact-fit heuristic and text-over-blob preference
- **Schema extraction**: Reads CREATE TABLE statements from sqlite_master on page 1
- **Type preservation**: Maintains float vs integer distinction based on serial type
- **All-NULL filtering**: Rejects false positives from scanning fallback

See the script for the full implementation. Key functions:
- `extract_schema()`: Parses sqlite_master to get table definitions
- `find_leaf_pages()`: Traverses B-tree to find all leaf pages for a table
- `parse_column_names()`: Extracts column names from CREATE TABLE SQL
- `read_payload_with_overflow()`: Handles overflow page chains
- `recover_from_page_via_pointers()`: Uses cell pointer array
- `recover_from_page_via_scanning()`: Fallback scanner
- `try_fix_serial_types()`: Bit-flip correction
- `parse_record()`: SQLite record parser

## Corruption Patterns and Mitigations

| Corruption Type | Symptom | Mitigation |
|----------------|---------|------------|
| Bit flip in serial type | Body size > payload; parse fails | Flip individual bits; verify consistency; use exact-fit heuristic; prefer text over blob |
| Zeroed page header | Cell pointers unreadable | Fall back to raw bottom-up scanning |
| Zeroed records | All-zero payload | Skip; unrecoverable |
| Truncated file | Missing pages | Recover from available pages only |
| Overflow chain broken | Payload incomplete | Use partial data if usable |
| Corrupted rowid | Wrong rowid value | Use record position as proxy |

## Key Diagnostic Checks

1. **File header intact?** Check magic at offset 0.
2. **Page size?** Read uint16 at offset 16-17.
3. **Page headers readable?** Check type byte for 0x0D.
4. **Can sqlite3 open it?** If yes, use SQL. If no, raw recovery.
5. **Cell pointer array valid?** Check cell_count and content_start are reasonable.
6. **Records parse consistently?** Verify body sizes match payload.
7. **Values in expected ranges?** Sanity-check integers and floats.

## Important Notes

- The cell pointer array is the most reliable recovery mechanism — it tells you
  exactly where every cell starts, independent of any content patterns.
- When the page header survives but individual records have bit flips, the
  pointer array still works; you just need to handle per-record corruption.
- Always cross-validate: if cell_count says 8, you should find exactly 8 records.
- For multi-table databases, parse sqlite_master to get table definitions with
  root page numbers, then traverse each table's B-tree separately.
- B-tree traversal handles both leaf (0x0D) and interior (0x0A) pages:
  - Interior pages have 12-byte headers (extra 4 bytes for rightmost child)
  - Interior cells contain left child page numbers + rowid dividers
  - Recursively visit all children to find all leaf pages for a table
- Each table may have its own schema; use the correct column names per table.

---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when standard
  tools report "database disk image is malformed". Parses raw SQLite page
  structures, record headers, varints, serial types, and handles corruption
  including bit flips, zeroed regions, and damaged headers. Outputs JSON
  matching the schema-specific format.
---

# SQLite Database Recovery from Corrupted Storage

## When to use

When `sqlite3 <file>` reports "database disk image is malformed" but the file
has the correct size and starts with the `SQLite format 3\0` magic header.
The file contains valid data pages but has suffered byte-level corruption
(bit flips, zeroed regions, damaged headers) that prevents standard queries.

## Recovery pipeline

Run the bundled `recover.py` first:

```bash
python3 recover.py /path/to/corrupted.db /path/to/output.json
```

If the script fails or recovers too few rows, follow the manual procedure below.

### Step 1: Parse the 100-byte database header

Extract from the file header:
- **Page size**: bytes 16-17 (big-endian uint16). Value `1` means 65536.
- **Total pages**: bytes 28-31 (big-endian uint32).
- **Text encoding**: bytes 56-59 (1=UTF-8, 2=UTF-16le, 3=UTF-16be).

### Step 2: Extract schema from page 1 (sqlite_master)

Page 1 contains the `sqlite_master` table as a B-tree. Its header starts at
**byte offset 100** (not 0 — the first 100 bytes are the database header).

Parse the B-tree leaf header (8 bytes at offset 100):
| Offset | Size | Field |
|--------|------|-------|
| +0 | 1 | Page type (must be `0x0D` for table leaf) |
| +1 | 2 | First freeblock offset (0 = none) |
| +3 | 2 | Number of cells |
| +5 | 2 | Cell content area start (page-relative) |
| +7 | 1 | Fragmented free bytes |

Then read the **cell pointer array**: `num_cells` × 2-byte big-endian values
starting at offset 108. Each is a **page-relative** offset to a cell.

For each cell, parse:
1. `payload_size` (varint)
2. `rowid` (varint)
3. Record payload (payload_size bytes)

Parse the record: `hdr_size` (varint, **includes itself**), then serial types
(varints from byte 1 to byte hdr_size-1), then column data.

Decode each cell's sqlite_master record (5 columns):
`type, name, tbl_name, rootpage, sql`

Extract `CREATE TABLE` statements to learn column names, types, and which
root page each table starts on.

### Step 3: Find and parse all table B-tree leaf pages

Scan every page in the file. For page N (N ≥ 2), the B-tree header is at
offset 0 within the page. Look for page type byte `0x0D` (table leaf).

For each leaf page:
1. Parse the 8-byte B-tree header (same format as Step 2, but at offset 0).
2. Read cell pointer array.
3. For each cell pointer (page-relative offset):
   a. Read `payload_size` varint, `rowid` varint.
   b. Read `payload_size` bytes of record payload.
   c. Parse record header and serial types.
   d. Validate: sum of `serial_type_size()` for all columns must equal
      `payload_size - hdr_size`.
   e. If invalid, attempt correction (see below).
   f. Decode column values by dispatching on actual serial type.

### Step 4: Corruption correction

**Serial type bit flip** (most common corruption):
When the total data size from serial types doesn't match the payload:
1. For EACH column, compute the size used by all other columns.
2. Calculate `remaining = payload_size - hdr_size - other_columns_size`.
3. Find all serial types whose `serial_type_size()` equals `remaining`.
4. Compute Hamming distance from the observed (corrupted) serial type.
5. **Collect ALL valid single-column corrections across ALL columns.**
6. Pick the correction with the **globally minimum Hamming distance**.
   Do NOT just take the first column that works — compare all candidates.
7. **Tiebreaker via semantic validation**: When multiple corrections have the same Hamming distance:
   - Decode the record with each candidate correction
   - Score each decoded result based on recognizable content:
     * sqlite_master SQL column: +10 if contains "CREATE TABLE"
     * sqlite_master type column: +5 if is "table"/"index"/"view"/"trigger"
     * Data page text: +3 if contains expected patterns (e.g., "testword")
     * Any text: +1 if valid UTF-8 and printable
   - Pick the correction with the highest semantic score
   - This is data-driven rather than heuristic — the actual content guides the correction
8. Accept corrections with Hamming distance ≤ 3 bits.
9. If no single-column correction works, try pairs of columns (but require
   total Hamming ≤ 3 across both corrections).

**sqlite_master corruption**: The sqlite_master record itself can have
corrupted serial types (e.g., the SQL text column). When extracting schema:
- If the decoded values look garbled (e.g., "tablete" instead of "table",
  or "127979077530725" instead of "test"), the correction picked the wrong
  column or there are multiple corruptions. Try these strategies:
  1. Re-run correction with tiebreaker heuristics (prefer text→text, later columns)
  2. Try all valid corrections and pick the one producing the most recognizable output
  3. Use regex to find "CREATE TABLE" fragments in the decoded SQL
  4. Fall back to the task instruction's output format hint
- The schema SQL often contains recognizable fragments even when corrupted
  (e.g., "EATE TABLE test" → "CREATE TABLE test"). Use regex to extract
  table and column names from partial SQL.
- **Critical**: Even if sqlite_master is garbled, the data pages may still
  be recoverable. Extract column names from the task instruction format
  (e.g., `[{"word": "...", "value": ...}]` reveals columns "word" and "value").

**Page header damage**: If byte 0 is corrupted away from `0x0D`, scan the
last ~25% of the page for record-like structures anchored by recognizable
text patterns.

**Random bit flips in free space**: Non-zero bytes between the cell pointer
array end and cell content start are noise in freed space — ignore them.

**Cross-page (overflow) records**: If `payload_size` exceeds available space
in the page, the overflow page number is stored as a 4-byte big-endian
integer immediately after the local payload portion. Follow the overflow
page chain (each overflow page starts with a 4-byte next-page pointer).

### Step 5: Decode values and serialize output

Dispatch on the **actual serial type** of each column — never assume a fixed
encoding for a column:

| Serial type | Meaning | Size |
|-------------|---------|------|
| 0 | NULL | 0 |
| 1 | int8 (signed) | 1 |
| 2 | int16 (signed, big-endian) | 2 |
| 3 | int24 (signed, big-endian) | 3 |
| 4 | int32 (signed, big-endian) | 4 |
| 5 | int48 (signed, big-endian) | 6 |
| 6 | int64 (signed, big-endian) | 8 |
| 7 | IEEE-754 float64 (big-endian) | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| ≥12, even | Blob of length (st-12)/2 | (st-12)/2 |
| ≥13, odd | Text of length (st-13)/2 | (st-13)/2 |

SQLite REAL-affinity columns may store values as integers (types 1-6) or
floats (type 7). Always dispatch on the actual serial type in each record.

## Critical details

- **`hdr_size` includes itself**: Serial types occupy bytes 1 through
  `hdr_size - 1` of the record payload, NOT bytes 0 through `hdr_size - 1`.
- **Page 1 B-tree header at offset 100**: All other pages start at offset 0.
- **Cell pointers are page-relative**: Not file-relative offsets.
- **Varints**: SQLite uses a custom variable-length integer encoding. Each
  byte contributes 7 bits; the high bit means "more bytes follow". Maximum
  9 bytes. The 9th byte contributes all 8 bits (no continuation bit).
- **Output format**: Match the schema-specific JSON format given in the task
  instruction. Use column names from the recovered `CREATE TABLE` statement.

## Adapting to different family members

The spec declares these variation axes — all are handled by the pipeline:

- **corruption_mechanism**: The correction strategy (Step 4) handles bit
  flips via Hamming-distance matching. For zeroed regions, look for intact
  record fragments and reassemble. For truncated files, recover what's
  available from intact pages. For severely damaged B-tree headers, scan
  raw page data for record-like structures.
- **schema_and_value_encoding**: Schema extraction (Step 2) handles any
  number of tables and columns. Value decoding (Step 5) dispatches on
  actual serial types, handling NULLs, all integer widths, floats, text,
  and blobs. When sqlite_master is corrupted, use the task instruction's
  output format as a schema hint.
- **record_identification**: Cell pointers from B-tree headers identify
  records. When headers are damaged, fall back to text-pattern scanning
  in raw page data. For interior B-tree pages (type 0x05), follow child
  page pointers to find leaf pages.
- **recovery_scale**: The pipeline handles any number of pages, cells per
  page, and tables. Process pages sequentially. For hundreds of records
  spanning many pages, iterate through all pages and collect cells from
  each leaf page.

## Quick-start recovery script

When `recover.py` is not accessible in the task container, use this inline
pattern (adapt column names from task instruction):

```python
import struct, json

with open('/path/to/corrupted.db', 'rb') as f:
    data = f.read()

page_size = struct.unpack('>H', data[16:18])[0]
if page_size == 1: page_size = 65536

# Parse B-tree leaf page, extract cells, correct serial types, decode values
# See Steps 1-5 above for the full procedure
```

The key insight: SQLite stores data in fixed-size pages with B-tree structures.
Even when corruption makes `sqlite3` fail, the page structure often remains
intact enough to parse cell pointers and extract records. The main challenge
is correcting corrupted serial types in record headers — use Hamming distance
minimization to find the most likely correction.

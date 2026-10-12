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

## Solver Workflow (Optimized for Speed)

**Always deploy and run the full recovery script first.** It handles all corruption
types (bit flips, zeroed regions, overflow pages, multi-table) and schema recovery
automatically. The script runs in <1 second even for large databases.

**Do NOT manually parse hex dumps before running the script.** This wastes 5-10 turns
on analysis that the script handles automatically. Only analyze specific cells with
`xxd` if the script produces wrong results or crashes.

### Step-by-Step Workflow

1. **Deploy the recovery script** (see "Deploying the Recovery Script" below)

2. **Run the script**:
   ```bash
   python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json
   ```
   The script will auto-detect schema from sqlite_master or raw SQL scan.

3. **Check the output**:
   ```bash
   cat /app/recover.json
   ```
   Verify it matches the expected format from the task instruction.

4. **If schema not auto-detected**, pass column names from the instruction:
   ```bash
   python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json word,value
   ```

5. **If the script fails or produces wrong results**, THEN analyze:
   - Read error messages carefully
   - Use `xxd` to examine specific cells if needed
   - Consider using inline recovery approach (see "Detailed Recovery Procedure")

**Typical execution**: Deploy → Run → Check = 3 tool calls. Done.

**Only if something is wrong**: Deploy → Run → Check → Analyze → Fix = 5+ tool calls.

### Deploying the Recovery Script

The `recover_sqlite.py` file is a skill asset (package-relative path).
To use it in a task environment:

1. **Read the script**: use the `read` tool with the skill-relative path
   ```
   read(skill/sqlite-db-truncate/recover_sqlite.py)
   ```

2. **Write it to the execution environment**: use the `write` tool
   ```
   write(/app/recover_sqlite.py, <content from step 1>)
   ```
   Or use `task_shell` with a heredoc (but this is error-prone for large scripts).

3. **Run the script**:
   ```bash
   python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json
   ```

**Do NOT attempt to copy from host filesystem paths** — skill assets are
accessed through the skill tool interface, not filesystem mounts. The path
`/skill/sqlite-db-truncate/recover_sqlite.py` does not exist inside the
task container.

**Do NOT rewrite the script from memory** — this introduces bugs (e.g.,
incorrect serial type sizes). Always read the canonical version from the
skill package.

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

**Priority 1 - Task Instruction**: Parse the task instruction for schema hints.
Look for patterns like:
- "format: [{\"col1\": ..., \"col2\": ...}]"
- "columns: col1, col2"
- "table with columns X and Y"
Extract column names and infer types from column name patterns:
- Names containing 'id', 'count', 'num', 'age', 'year', 'index' → INTEGER
- Names containing 'value', 'price', 'amount', 'score', 'reading' → REAL
- Names containing 'name', 'word', 'text', 'title', 'label' → TEXT
- Names containing 'data', 'blob', 'image', 'raw' → BLOB
- Default → TEXT

**Priority 2 - sqlite_master**: Parse page 1 (sqlite_master table) at b-tree offset 100.
Each cell has 5 columns: type, name, tbl_name, rootpage, sql.
Extract ALL table schemas, storing table_name → schema and table_name → rootpage.
If sqlite_master is corrupted, try to repair using bit-flip correction on the SQL text.

**Priority 3 - Raw SQL Scan**: Scan file bytes for `CREATE TABLE` patterns.
Use regex to find and parse CREATE TABLE statements.

**Priority 4 - Data Inference**: When no schema is available, use a two-pass approach:
1. **Pass 1**: Scan all leaf pages with name-inferred types (from Priority 1) or TEXT defaults.
   Collect successfully decoded records.
2. **Refine**: Run `infer_schema_from_records` on the clean records to get better type estimates
   by analyzing serial type patterns across multiple records.
3. **Pass 2**: Re-scan pages that had unrepairable records using the refined types.
   This handles cases where column names are ambiguous or misleading.

**Critical**: Type hints must be available BEFORE the decoding pass. The instruction columns
are converted to type hints via `infer_types_from_column_names()` and passed as `expected_types`
to `parse_btree_leaf_page()`. This enables schema-guided repair even when sqlite_master is
destroyed, as long as the instruction provides column names.

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
- **Instruction-guided**: If task specifies column names/types, use those as schema
- Fallback to TEXT-preference heuristic when no schema available
- Also try 2-bit flips if single-bit doesn't resolve
- **Cross-record validation**: When repairing, check if the repaired value is consistent
  with patterns in other records (e.g., sequential IDs, similar text formats)

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
11. **Schema recovery chain**: instruction → sqlite_master → raw SQL scan → data inference
12. **Cross-record validation**: When repairing serial types, check consistency across
    multiple records (e.g., sequential IDs, similar text patterns)
13. **Data inference**: When no schema is available, analyze serial type patterns across
    records to infer column types (TEXT if most records have odd serial ≥13, etc.)

## Assets

- `recover_sqlite.py`: Complete recovery script handling all corruption types

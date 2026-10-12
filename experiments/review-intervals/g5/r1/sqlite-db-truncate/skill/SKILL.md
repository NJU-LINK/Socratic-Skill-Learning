---
name: sqlite-db-truncate
description: Recover records from corrupted SQLite databases when standard queries fail, using binary forensic analysis of pages, cells, and record structures.
---

# SQLite Database Forensic Recovery

## When to Use This Skill

Apply this skill when:
- SQLite database file exists but `sqlite3` reports "database disk image is malformed"
- Standard queries fail with corruption errors
- You need to recover data from damaged/truncated/corrupted SQLite files
- The file has correct size but contains bit-flips, zeroed regions, or damaged structures

## Quick Start

**Option 1: Use the provided recovery script**
```bash
python3 /skill/scripts/recover_sqlite.py <input.db> <output.json>
```

**Option 2: Implement recovery from scratch using this guide**
Follow the methodology below to write custom recovery code.

## Recovery Methodology

### Phase 1: Initial Assessment

1. **Check file basics:**
   ```bash
   file database.db
   ls -la database.db
   ```

2. **Try standard sqlite3 access:**
   ```bash
   sqlite3 database.db "SELECT * FROM sqlite_master;"
   ```
   If this works, you're done. If it fails, proceed to forensic recovery.

3. **Read file header to determine structure:**
   - Bytes 0-15: Must be `"SQLite format 3\000"` (fix if corrupted)
   - Bytes 16-17: Page size (big-endian uint16)
   - Bytes 28-31: Total page count

### Phase 2: Schema Recovery

**Try to extract schema from page 1:**

Page 1 contains the `sqlite_master` table with schema information. Parse the b-tree leaf page (type 0x0D at offset 100) to find cells. Each cell contains a record with columns:
- `type` (TEXT): "table", "index", etc.
- `name` (TEXT): table/index name
- `tbl_name` (TEXT): associated table name
- `rootpage` (INTEGER): root page number for the table
- `sql` (TEXT): CREATE TABLE/INDEX statement

The `sql` column gives you the exact schema: column names, types, and order.

**Handling corrupted schema records:**

When serial types in the schema record are corrupted (common with bit-flip corruption):
1. Decode the first 4 columns (type, name, tbl_name, rootpage) using their serial types
2. Calculate the byte offset where the SQL column should start
3. Extract SQL directly from the raw body bytes (look for printable ASCII starting with "CREATE TABLE")
4. Parse the extracted SQL to get column definitions

**If page 1 is too corrupted:**
- Search for `CREATE TABLE` strings in raw bytes
- Look for column names in the data
- Infer schema from record patterns

### Phase 3: Data Recovery

**Strategy A: Parse b-tree pages (preferred)**

1. **Identify leaf table b-tree pages:**
   - Scan each page for type byte 0x0D (leaf table b-tree)
   - Read b-tree header: type (1), first_freeblock (2), num_cells (2), cell_content_start (2), fragmented_bytes (1)
   - Read cell pointer array: num_cells × 2 bytes (big-endian offsets)

2. **Parse each cell:**
   - Payload length (varint)
   - Row ID (varint)
   - Record payload:
     - Header size (varint, includes itself)
     - Serial types (one varint per column)
     - Body values (sizes determined by serial types)

3. **Decode values based on serial types:**
   - 0: NULL
   - 1-6: Integers (1, 2, 3, 4, 6, 8 bytes, big-endian, signed)
   - 7: IEEE-754 float (8 bytes, big-endian)
   - 8: Integer 0 (constant)
   - 9: Integer 1 (constant)
   - ≥12 even: Blob of length (N-12)/2
   - ≥13 odd: Text of length (N-13)/2

4. **Validate record integrity:**
   - Sum of column sizes (from serial types) must equal body length
   - If validation fails, serial types are corrupted → use Strategy B

**Strategy B: Repair corrupted serial types**

When serial types are corrupted but data is intact, use **scored backtracking search**:

**Critical insight: SQLite uses dynamic typing.** A column declared as REAL may store values as compact 1-byte integers. However, **only REAL columns should try 8-byte float interpretation** — INTEGER columns should only try integer sizes to avoid "stealing" float bytes from adjacent REAL columns.

1. **For each column, enumerate possible (value, size, score) options:**
   - TEXT: Try all lengths 1..remaining. Decode as UTF-8, validate printable. Score: prefer longer pure-ASCII text (+100 bonus).
   - INTEGER: Try sizes 1, 2, 3, 4, 6, 8 bytes as integers only. Score: prefer small positive integers.
   - REAL: Try all integer sizes (1,2,3,4,6,8) AND 8-byte IEEE-754 float. Score: reasonable floats get **+150 bonus** (strong signal that bytes form valid float).
   - NULL: 0 bytes, score 0 (valid fallback for any column type)
   - BLOB: Try all lengths

2. **Use backtracking to find the highest-scoring valid assignment:**
   - Columns must be assigned contiguously in order (col 0 bytes before col 1 bytes)
   - Total bytes consumed must equal body length
   - Each column gets exactly one (value, size) option
   - Prune branches that can't beat the current best score

3. **Scoring heuristics:**
   - Pure ASCII text: +100 bonus, +1 per character
   - Small positive integer (<10000): +50 bonus, prefer smaller sizes
   - Reasonable float (not NaN/Inf, |val| < 1e9): **+150 bonus** (high because random bytes rarely form valid floats)
   - Extreme float (>1e9 or <1e-9): -100 penalty
   - NULL: 0 (neutral score, allows recovery of NULL values)

**Why this works:** In the v01 case, body = `testword02\x0a` (11 bytes). The backtracking considers:
- TEXT(10)="testword02" + INT(1)=10 → score ≈ 110+59 = 169 ✓
- TEXT(3)="tes" + FLOAT(8)=garbage → score ≈ 103-100 = 3 ✗

The scoring correctly prefers the meaningful interpretation.

**Strategy C: Text-pattern scanning (fallback)**

When cell parsing fails entirely:
- Search for recognizable text patterns in raw bytes
- For each match, look backward for record header
- Extract values from bytes following the text
- Use schema knowledge to determine value types and sizes

### Phase 4: Handle Multi-Page and Multi-Table Scenarios

**Multiple tables:**
- Each table has a root page (from sqlite_master)
- Parse each root page as a b-tree
- Internal b-tree pages (type 0x05) have child pointers; traverse recursively

**Large records (overflow pages):**
When a record is too large to fit on one page:
1. Calculate max_local = page_size - 35 (for leaf table pages)
2. If payload_len > max_local:
   - Local payload = first max_local bytes
   - Last 4 bytes of local payload = first overflow page number
   - Overflow pages chain together:
     - First 4 bytes = next overflow page number (0 = end)
     - Remaining bytes = record data
3. Concatenate local payload + overflow page data to get full record

**Truncated files:**
- Only parse pages that exist (min of header page count and actual file size / page size)
- If a page is partially present, parse what's available

**Zeroed regions:**
- Skip pages that are all zeros
- Recover from non-zero pages only

**Cross-page records:**
- Records cannot cross page boundaries except via overflow pages
- If a cell pointer points near the end of a page, check for overflow

### Phase 5: Output

Serialize recovered records as JSON array:
```json
[
  {"column1": value1, "column2": value2, ...},
  ...
]
```

Sort by a natural key (rowid, primary key, or first column) for consistency.

**Important:** Strip internal metadata fields (like `_rowid`) from the final output unless explicitly required.

## Implementation Checklist

When implementing recovery:

- [ ] Read and validate file header (fix magic string if needed)
- [ ] Determine page size and page count
- [ ] Parse page 1 to extract schema from sqlite_master
- [ ] Handle corrupted schema records (extract SQL from raw body)
- [ ] For each table, identify root page
- [ ] Parse b-tree leaf pages to find cells
- [ ] For each cell, parse payload and decode record
- [ ] Validate record integrity (serial types vs body length)
- [ ] Repair corrupted serial types using backtracking
- [ ] Handle overflow pages for large records
- [ ] Handle internal b-tree pages for large tables
- [ ] Output JSON with recovered records (strip internal fields)

## Common Pitfalls

1. **Varint parsing:** Remember varints can be 1-9 bytes. The 9th byte uses all 8 bits (not 7).

2. **Signed integers:** SQLite stores signed integers in big-endian format.

3. **Serial type validation:** Always check that total body size matches sum of column sizes. If not, serial types are corrupted.

4. **Page boundaries:** Cell content area grows from end of page backward; don't read past page boundary.

5. **Corruption patterns:** Bit flips often affect header bytes more than data; use data as anchor when headers are damaged.

6. **Schema extraction:** When serial types are corrupted in sqlite_master, the SQL text may be truncated. Extract it from raw body bytes by finding "CREATE TABLE" and reading until non-printable character.

7. **Text repair:** When repairing TEXT columns, try shortest matches first. Long text matches can consume bytes needed for other columns.

8. **REAL columns:** Despite the column type being REAL, SQLite may store values as compact integers (1-8 bytes) using dynamic typing. When repairing corrupted records, always try integer sizes for REAL columns, not just 8-byte floats.

9. **Column order:** Values in the body appear in the same order as columns in the CREATE TABLE statement.

10. **Scoring over greedy:** When repairing corrupted serial types, don't use greedy shortest-match for text. Use scored backtracking that prefers meaningful text + reasonable numeric values over short text + garbage floats.

11. **NULL handling:** Always include NULL (0 bytes, score 0) as an option for every column during repair. This allows recovery of NULL values when serial types are corrupted.

12. **INTEGER vs REAL float interpretation:** INTEGER columns should only try integer sizes (1,2,3,4,6,8 bytes). Only REAL columns should try 8-byte float interpretation. This prevents INTEGER columns from "stealing" float bytes from adjacent REAL columns during backtracking.

## Reference: SQLite Binary Format

**Database Header (100 bytes):**
- 0-15: Magic string `"SQLite format 3\000"`
- 16-17: Page size (big-endian uint16, 1 means 65536)
- 18: File format write version
- 19: File format read version
- 20: Reserved space per page
- 21: Max embedded payload fraction (must be 64)
- 22: Min embedded payload fraction (must be 32)
- 23: Leaf payload fraction (must be 32)
- 24-27: File change counter
- 28-31: Database size in pages

**B-tree Page Header (8 bytes for leaf table pages):**
- 0: Page type (0x0D = leaf table, 0x05 = internal table, 0x0A = leaf index, 0x02 = internal index)
- 1-2: First freeblock offset (0 = none)
- 3-4: Number of cells
- 5-6: Cell content area start offset
- 7: Fragmented free bytes

**Varint Encoding:**
- Each byte contributes 7 data bits (bits 0-6)
- High bit (bit 7) = continuation flag
- Maximum 9 bytes (9th byte uses all 8 bits)

**Serial Types:**
- 0: NULL (0 bytes)
- 1: 8-bit signed integer (1 byte)
- 2: 16-bit signed integer (2 bytes)
- 3: 24-bit signed integer (3 bytes)
- 4: 32-bit signed integer (4 bytes)
- 5: 48-bit signed integer (6 bytes)
- 6: 64-bit signed integer (8 bytes)
- 7: IEEE-754 64-bit float (8 bytes)
- 8: Integer 0 (0 bytes, constant)
- 9: Integer 1 (0 bytes, constant)
- N≥12, even: Blob of length (N-12)/2
- N≥13, odd: Text of length (N-13)/2 in UTF-8

**Text serial type formula:** For text of length L, serial type = 13 + 2×L

---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite storage when ordinary
  queries fail. Handles bit-flip corruption in serial types, page metadata,
  and unused areas, as well as truncation, zeroed regions, and damaged page
  structures. Parses the raw SQLite file format and uses schema-guided
  heuristics to reconstruct records.
---

# SQLite Database Recovery

## When to Use This Skill

Use this skill when:
- `sqlite3` reports "database disk image is malformed"
- A `.db` file exists but standard queries fail
- You need to recover data from a corrupted SQLite database
- The task mentions truncation, bit flips, zeroed regions, or corruption

## Quick-Start Checklist

1. **Try sqlite3 first** — `sqlite3 -json <db> 'SELECT * FROM <table>'`
2. **If that fails**, inspect raw bytes: `xxd <db> | head -20` to confirm SQLite magic
3. **Extract the schema** by searching page 1 for `CREATE TABLE` text (it usually survives bit flips)
4. **Run the recovery script**: `python3 scripts/recover_sqlite.py <db> /app/recover.json`
5. **Validate output** — check row count, spot-check values, ensure JSON format matches spec

## Recovery Script

The bundled `scripts/recover_sqlite.py` handles the full pipeline:

```bash
# Basic usage (auto-detects schema from raw bytes)
python3 scripts/recover_sqlite.py /app/trunc.db /app/recover.json

# With explicit schema (when auto-detect fails)
echo '{"mytable": [["col1","TEXT"],["col2","REAL"]]}' > schema.json
python3 scripts/recover_sqlite.py /app/trunc.db /app/recover.json schema.json
```

**What it does:**
- Tries `sqlite3 -json` first (fast path for uncorrupted files)
- Falls back to raw page-by-page parsing
- Finds `CREATE TABLE` text in page 1 to learn the schema
- Scans all pages for leaf table b-tree pages (type `0x0d`)
- For each record, parses payload length, rowid, and serial types
- When serial types are corrupted, uses **schema-guided scoring** to find the best column-size assignment
- Outputs a JSON array of objects

## SQLite File Format Reference

### Database Header (bytes 0–99 of page 1)

| Offset | Size | Field | Expected |
|--------|------|-------|----------|
| 0 | 16 | Magic string | `SQLite format 3\0` |
| 16 | 2 | Page size (bytes) | Power of 2, commonly 4096 |
| 18 | 1 | Write version | 1 |
| 19 | 1 | Read version | 1 |
| 28 | 4 | Database size (pages) | |
| 40 | 4 | Schema cookie | |
| 44 | 4 | Schema format | 4 |
| 56 | 4 | Text encoding | 1=UTF-8 |

### B-Tree Page Header

Starts at byte 100 for page 1, byte 0 for other pages.

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Page type: `0x0d`=leaf table, `0x05`=interior table |
| 1 | 2 | First freeblock offset |
| 3 | 2 | Number of cells |
| 5 | 2 | Cell content area start offset |
| 7 | 1 | Fragmented free bytes |

Cell pointer array follows immediately (2 bytes per cell, offset relative to page start).

### Record (Cell) Format

Each cell in a leaf table page:
1. **Payload length** — varint
2. **Row ID** — varint
3. **Record payload**:
   - Header size (varint, includes itself)
   - Serial types (one varint per column)
   - Column data (packed, no padding)

### Serial Types

| Code | Kind | Byte Size |
|------|------|-----------|
| 0 | NULL | 0 |
| 1–6 | Integer | 1, 2, 3, 4, 6, 8 |
| 7 | Float64 (IEEE 754) | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| ≥12 even | Text | (N−12)/2 |
| ≥13 odd | Blob | (N−13)/2 |

### Varint Encoding

Each byte: bit 7 = continuation flag, bits 0–6 = data. Up to 9 bytes. Big-endian, MSB first.

## Corruption Patterns and Fixes

### 1. Noise Bytes in Unused Areas

**Symptom**: sqlite3 fails but raw data looks intact.
**Cause**: Random bits flipped from 0→nonzero in unused page regions.
**Fix**: Zero all bytes between cell pointer array end and cell content start.

### 2. Corrupted Serial Types (Most Common)

**Symptom**: Record data looks valid but serial types don't match payload size.
**Common bit flips**:
- `0x20` (text 10) → `0x21` (blob 10): bit 0 flip. Same data size, just wrong kind.
- `0x16` (text 5) → `0x17` (blob 5): bit 0 flip.
- `0x07` (float64) → `0x01` (int8): multiple bits. Payload size mismatch.
- `0x61` (blob 42) → `0x21` (blob 10): bit 6 flip. Wildly wrong size.

**Fix strategy** (implemented in recovery script):
1. Compute expected data size from declared serial types
2. If it doesn't match actual payload size, use schema to enumerate valid column-size combinations
3. Score each candidate: prefer longer text, standard numeric sizes, penalize nulls
4. Pick highest-scoring parse

### 3. Corrupted Page Header

**Symptom**: Cell content area start doesn't match minimum cell pointer.
**Fix**: Set cell content area to the minimum valid cell pointer value.

### 4. Truncated File

**Symptom**: File is smaller than expected page count.
**Fix**: Parse only complete pages; skip partial pages at the end.

### 5. Zeroed Regions

**Symptom**: Large runs of zeros where data should be.
**Fix**: Recover records from non-zeroed pages; report partial results.

## Manual Recovery Procedure

When the script doesn't work or you need to debug:

### Step 1: Confirm SQLite Format
```bash
xxd -l 16 <db>
# Should show: 5351 4c69 7465 2066 6f72 6d61 7420 3300  SQLite format 3.
```

### Step 2: Get Page Size
```python
import struct
data = open('<db>', 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0]
print(f"Page size: {page_size}")
```

### Step 3: Find Schema
```python
import re
for m in re.finditer(rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', data[:page_size], re.I):
    print(f"Table: {m.group(1).decode()}")
    print(f"Columns: {m.group(2).decode()}")
```

### Step 4: Find Data Pages
```python
for pn in range(len(data) // page_size):
    offset = pn * page_size
    if data[offset] == 0x0d:
        print(f"Page {pn} at 0x{offset:04x}: leaf table b-tree")
```

### Step 5: Parse Records
For each leaf page, read cell pointers (offset 8, 2 bytes each), then for each cell:
1. Read payload length (varint) and rowid (varint)
2. Read record header to get serial types
3. If serial types don't match payload size, use schema-guided recovery
4. Extract text/numeric values

## Output Format

The task typically requires a JSON array:
```json
[
  {"word": "testword02", "value": 10},
  {"word": "testword03", "value": 25}
]
```

Key decisions:
- **Integers vs floats**: If schema says REAL but value was stored as a small integer (serial type 1-6), output the integer. JSON doesn't distinguish 10 from 10.0 at the number level.
- **Row ordering**: Sort by rowid (ascending) unless the task specifies otherwise.
- **NULL handling**: Include null values as JSON `null` unless told to skip incomplete rows.

## Verification

After recovery, verify:
1. ✅ Row count seems reasonable (check cell count in data pages)
2. ✅ Text columns contain readable strings
3. ✅ Numeric columns have plausible values (not garbage floats like 1e+253)
4. ✅ JSON is valid and matches expected schema
5. ✅ Output file is at the correct path

## Edge Cases

| Scenario | Approach |
|----------|----------|
| Multiple tables | Parse each table's root page from schema entries |
| Records spanning pages (overflow) | Follow overflow page chain (4-byte page number at end of local payload) |
| No CREATE TABLE found | Scan all pages for data patterns; try blind text extraction |
| Interior b-tree pages | Follow child page pointers to reach leaf pages |
| Very large databases | Process pages sequentially; memory-map the file |
| Non-standard page sizes | Read page size from header; handle 512 to 65536 |

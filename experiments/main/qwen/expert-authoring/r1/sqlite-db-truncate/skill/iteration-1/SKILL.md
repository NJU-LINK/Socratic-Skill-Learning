---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from a damaged SQLite database file when
  ordinary SQL queries fail. Parses raw binary page structures, decodes
  B-tree leaf cells and record formats, and handles corruption patterns
  including bit flips, zeroed regions, truncation, and damaged headers.
  Outputs recovered records as JSON in the case-specified schema.
---

# SQLite Raw Record Recovery

## When to Apply This Skill

Use this skill when:
- A `.db` / `.sqlite` file is present but `sqlite3` queries fail with
  "database disk image is malformed" or similar errors.
- The file is the correct size but contains corrupted bytes (bit flips,
  zeroed regions, random byte corruption, or truncation).
- The task requires recovering row data and writing it to JSON.

## High-Level Strategy

1. **Confirm corruption** — try `sqlite3 <db> "SELECT * FROM sqlite_master;"`
   and `sqlite3 <db> "PRAGMA integrity_check;"`. If these fail, proceed
   with raw recovery.
2. **Determine the expected output schema** — read the task instruction
   carefully for the exact JSON format and column names.
3. **Run the automated recovery script** (preferred first step):
   ```bash
   python3 /skill/scripts/recover_sqlite.py <db_file> /app/recover.json --schema-hint "col1,col2,..."
   ```
   If the script succeeds, verify the output and skip to step 6.
4. **If the script fails or results look incomplete**, perform manual
   binary analysis (see "Manual Binary Recovery" below).
5. **Cross-validate** — compare script output with manual pattern
   extraction to catch records the automated parser may have missed.
6. **Write `/app/recover.json`** in the exact format specified by the
   task instruction.

## SQLite Binary Format Quick Reference

### File Header (bytes 0–99)
| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 | Magic: `SQLite format 3\0` |
| 16 | 2 | Page size (1 means 65536) |
| 18 | 1 | File format write version |
| 19 | 1 | File format read version |
| 28 | 4 | Size of database in pages |
| 56 | 4 | Text encoding (1=UTF-8) |

### Page Types (first byte of each page)
| Value | Type |
|-------|------|
| 13 | Leaf table b-tree (data rows live here) |
| 10 | Leaf index b-tree |
| 5 | Interior table b-tree |
| 2 | Interior index b-tree |

**Only leaf table pages (type 13) contain actual row data.**

### Leaf Table Page Layout
```
Offset 0:  Page type byte (0x0D = 13)
Offset 1:  First freeblock (2 bytes, 0 = none)
Offset 3:  Number of cells (2 bytes)
Offset 5:  Cell content area start (2 bytes, 0 means 65536)
Offset 7:  Fragmented free bytes (1 byte)
Offset 8:  Cell pointer array (2 bytes × num_cells)
```

Cell pointers are offsets **relative to the start of the page**.
For page N (1-indexed), absolute file offset = `(N-1) × page_size + pointer`.

### Cell Structure (Leaf Table Page)
```
[payload_size varint] [rowid varint] [record]
```

### Record Format
```
[header_size varint] [serial_type_1 varint] [serial_type_2 varint] ... [payload bytes]
```

### Serial Types
| Value | Meaning | Bytes |
|-------|---------|-------|
| 0 | NULL | 0 |
| 1 | 8-bit int | 1 |
| 2 | 16-bit BE int | 2 |
| 3 | 24-bit BE int | 2* |
| 4 | 32-bit BE int | 4 |
| 5 | 48-bit BE int | 6 |
| 6 | 64-bit BE int | 8 |
| 7 | IEEE-754 float64 | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12 even | Blob | (N-12)/2 |
| N≥13 odd | Text (UTF-8) | (N-13)/2 |

*Serial type 3 reads 2 bytes in some implementations; the canonical
size is 3 bytes but corruption often makes this ambiguous.

### Varint Encoding
Each byte: bit 7 = continuation flag, bits 0–6 = data.
Up to 9 bytes; the 9th byte contributes all 8 bits.

### Cell Extent Calculation
Cells grow right-to-left within a page. The cell pointer array is in
**descending** order. Cell at `ptrs[i]` extends from `ptrs[i]` to
`ptrs[i-1]` (or end-of-page for `i=0`). The last cell (highest index)
extends to the cell content area start offset.

## Corruption Patterns and Mitigations

### 1. Bit Flips (Random)
**Symptoms**: Single bytes changed by 1–2 bits. Serial types, size
varints, or header bytes are slightly wrong. Page type byte may flip
(e.g., 0x0D → 0x0C or 0x0F).

**Mitigation**:
- If the page type byte doesn't match 0x0D but nearby bytes suggest a
  valid page structure, try parsing anyway.
- If a serial type produces an impossibly large content size (exceeding
  cell boundaries), try common alternatives:
  - 0x61 (97, 42-byte text) → likely should be 0x21 (33, 10-byte text)
    or 0x19 (25, 10-byte text). Check: `(0x61 ^ 0x21) = 0x40` (single bit).
  - 0x07 in header-size position → likely should be 0x03.
- Cross-validate: the number of bytes actually available in the cell
  should match header_size + sum(serial_type_sizes).

### 2. Zeroed Regions
**Symptoms**: Large sections of the file are 0x00. Cell pointer array
or cell content may be partially zeroed.

**Mitigation**:
- Scan the entire file for non-zero regions containing recognizable
  text patterns (e.g., column key prefixes).
- Reconstruct records from surviving fragments.
- Use the schema from page 1 (if readable) to determine column count
  and types.

### 3. Truncation
**Symptoms**: File is shorter than expected. Later pages are missing.

**Mitigation**:
- Parse only the pages that exist.
- Check the file header's page count vs actual file size.
- Records on truncated pages are lost; recover what remains.

### 4. Damaged Page Structures
**Symptoms**: Cell pointer array is corrupted. Pointers reference
overlapping or out-of-bounds regions.

**Mitigation**:
- Validate each pointer: must be within `[page_header_end, page_size)`.
- Sort valid pointers and use the cell-extent calculation.
- For invalid pointers, scan the page content area right-to-left
  looking for valid cell prefixes (size varint + rowid varint + valid
  record header).

## Manual Binary Recovery

Use this procedure when the automated script fails.

### Step 1: Inspect the file
```bash
xxd <db_file> | head -7          # Check SQLite magic and page size
xxd -s 0x1000 <db_file> | head -3 # Check page 2 header
file <db_file>                    # Verify SQLite identification
```

### Step 2: Extract page structure with Python
```python
import struct
data = open('<db_file>', 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0]

for pg in range(len(data) // page_size):
    p = pg * page_size
    ptype = data[p]
    if ptype == 0x0D:  # leaf table page
        num_cells = struct.unpack('>H', data[p+3:p+5])[0]
        ptrs = [struct.unpack('>H', data[p+8+2*i:p+10+2*i])[0]
                for i in range(num_cells)]
        print(f"Page {pg+1}: {num_cells} cells, ptrs={ptrs}")
```

### Step 3: Parse cells and decode records
```python
# For each cell pointer, read the cell bytes:
#   - Parse payload_size varint
#   - Parse rowid varint
#   - Parse record header_size varint
#   - Parse serial type varints
#   - Decode payload using serial types
# See /skill/scripts/recover_sqlite.py for full implementation.
```

### Step 4: Pattern-based fallback
When cell parsing fails, scan for text key patterns:
```python
import re
for m in re.finditer(b'<known_prefix>', data):
    start = m.start()
    # Read N bytes of text, then try int8 or float64 for the value
```

### Step 5: Read the schema (if possible)
```bash
# Try to extract CREATE TABLE from page 1:
strings <db_file> | grep -i "CREATE TABLE"
```
This gives column names and types for accurate decoding.

## Verification Checklist

- [ ] Output file exists at `/app/recover.json`
- [ ] Output is valid JSON (parseable by `json.loads()`)
- [ ] Each record has the exact keys specified in the task instruction
- [ ] Values have correct types (strings are strings, numbers are numbers)
- [ ] No duplicate records
- [ ] Records sorted in a reasonable order (by key or rowid)
- [ ] Cross-check: number of recovered records ≤ expected total
- [ ] Float values are finite (not NaN or Inf)
- [ ] Integer values are within expected range

## Key Pitfalls

1. **Do not rely on `sqlite3` CLI** — it will fail on corrupted databases.
   Always use raw binary parsing.
2. **Serial type byte corruption** is common. If a serial type implies
   more content bytes than the cell can hold, try XOR-ing with small
   values (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40) to find the
   correct single-bit-flip correction.
3. **Cell boundary calculation is critical.** Always use the pointer
   array to determine where each cell starts and ends; do not rely
   on the payload_size varint alone (it may be corrupted).
4. **Page 1 is the schema page** — it rarely contains user data.
   Page 2+ contains data in leaf table pages.
5. **Records may span pages** in databases with large rows or overflow
   pages. Check for overflow page pointers in cells when the payload
   size exceeds the usable page area.
6. **The output format is task-specific.** Always read the instruction
   to determine exact column names and JSON structure. Never assume
   column names from the schema alone — the task may require different
   names.

## Automated Recovery Script

The script at `/skill/scripts/recover_sqlite.py` implements the full
pipeline:
- Parses the SQLite file header and all pages
- Identifies leaf table pages and reads cell pointer arrays
- Decodes records using serial types (Strategy 1)
- Falls back to text-pattern extraction (Strategy 2)
- Infers column names from the schema page
- Outputs JSON

```bash
# With known column names:
python3 /skill/scripts/recover_sqlite.py /app/trunc.db /app/recover.json \
    --schema-hint "word,value"

# Without column names (auto-infer from schema):
python3 /skill/scripts/recover_sqlite.py /app/trunc.db /app/recover.json
```

If the script recovers fewer records than expected, supplement with
manual binary analysis to find records in corrupted regions the
automated parser skipped.

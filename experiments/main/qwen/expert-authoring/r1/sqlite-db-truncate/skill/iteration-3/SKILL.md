---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from a damaged SQLite database file when
  ordinary SQL queries fail. Parses raw binary page structures, decodes
  B-tree leaf cells and record formats, and handles corruption patterns
  including bit flips, zeroed regions, truncation, and damaged headers.
  Outputs recovered records as JSON in the case-specific schema.
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

1. **Read the task instruction** — determine the exact output JSON format,
   column names, and file paths. The instruction is the authority on what
   to produce.
2. **Confirm corruption** — try `sqlite3 <db> ".tables"` or
   `sqlite3 <db> "PRAGMA integrity_check;"`. If these fail, proceed
   with raw recovery.
3. **Run the automated recovery script** (preferred first step):
   ```bash
   python3 /skill/scripts/recover_sqlite.py <db_file> /app/recover.json \
       --schema-hint "col1,col2,..."
   ```
   Omit `--schema-hint` if column names are not obvious from the
   instruction; the script will infer them from the schema page.
4. **Verify the output** — `cat /app/recover.json` and check:
   - Correct number of records
   - Column names match the task instruction
   - Values have correct types (strings, integers, floats)
   - No garbage characters in string values
5. **If the script fails or results look incomplete**, perform manual
   binary analysis (see "Manual Binary Recovery" below).
6. **Cross-validate** (only if the script reports fewer records than
   expected) — scan the raw binary for text patterns to confirm
   completeness. Use Python since `strings` and `grep` may not be
   available:
   ```bash
   python3 -c "
   import re; data = open('<db_file>','rb').read()
   for m in re.finditer(b'[A-Za-z]{4,}', data):
       print(f'Offset {m.start()}: {m.group().decode()}')"
   ```

## Extracting the Output Schema from the Task Instruction

The task instruction specifies the exact output format. Parse it carefully:

```
The output should have the format [{"word": "testwordXY", "value": M}, ...]
```

From this, extract:
- **Column names**: `word`, `value`
- **Value types**: `word` is text (string), `value` is numeric (int or float)
- **Record key pattern**: words look like `testword` + digits

Pass column names to the script via `--schema-hint "word,value"`.

If the instruction specifies a different format (e.g., different column
names, more columns, or different types), adjust the schema-hint accordingly.

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

### Page Types (first byte of each page's B-tree header)
| Value | Type |
|-------|------|
| 13 (0x0D) | Leaf table b-tree — **data rows live here** |
| 10 (0x0A) | Leaf index b-tree |
| 5 (0x05) | Interior table b-tree |
| 2 (0x02) | Interior index b-tree |

**Page 1 is special**: the first 100 bytes are the file header. The
B-tree page header for the `sqlite_master` schema table starts at
byte offset 100 within the page.

### Leaf Table Page Layout (type 0x0D)
```
Offset 0:  Page type byte (0x0D)
Offset 1:  First freeblock offset (2 bytes, 0 = none)
Offset 3:  Number of cells (2 bytes)
Offset 5:  Cell content area start offset (2 bytes, 0 → 65536)
Offset 7:  Fragmented free bytes (1 byte)
Offset 8:  Cell pointer array (2 bytes × num_cells)
```

Cell pointers are **16-bit offsets relative to the start of the page**.
Absolute file offset = `(page_number - 1) × page_size + pointer`.

### Cell Structure (Leaf Table Page)
```
[payload_size varint] [rowid varint] [record]
```

### Record Format
```
[header_size varint] [serial_type_1 varint] [serial_type_2 varint] ... [body bytes]
```

`header_size` = total size of the record header in bytes (including the
header_size varint itself and all serial type varints).

### Serial Types
| Value | Meaning | Bytes |
|-------|---------|-------|
| 0 | NULL | 0 |
| 1 | 8-bit signed int | 1 |
| 2 | 16-bit BE signed int | 2 |
| 3 | **24-bit BE signed int** | **3** |
| 4 | 32-bit BE signed int | 4 |
| 5 | 48-bit BE signed int | 6 |
| 6 | 64-bit BE signed int | 8 |
| 7 | IEEE-754 float64 | 8 |
| 8 | Constant 0 | 0 |
| 9 | Constant 1 | 0 |
| N≥12 even | Blob | (N-12)/2 |
| N≥13 odd | Text (UTF-8) | (N-13)/2 |

### Varint Encoding
Each byte: bit 7 = continuation flag, bits 0–6 = data.
Up to 9 bytes; the 9th byte contributes all 8 bits.
Single-byte varints have values 0–127.

### Cell Extent Calculation (CRITICAL)

Cells grow **right-to-left** within a page. The cell pointer array is in
**descending** order. To determine each cell's byte range:

```
sorted_ptrs = sorted(ptrs)  # ascending order

For ptr at sorted index i:
  cell_start = ptr
  cell_end   = sorted_ptrs[i+1]  if i < len-1, else page_size
```

Equivalently, using the array's native descending order:
```
For array index i:
  cell_start = ptrs[i]
  cell_end   = ptrs[i-1]  if i > 0, else page_size
```

**Common pitfall**: confusing array order with sorted order. Always
verify that cell_start < cell_end and that cells don't overlap.

## Corruption Patterns and Mitigations

### 1. Bit Flips (Random)
**Symptoms**: Single bytes changed by 1–2 bits. Common targets:
- Serial type bytes (e.g., 0x21 → 0x61, changing text length from 10 to 42)
- Header size varint (e.g., 0x03 → 0x07)
- Page type byte (e.g., 0x0D → 0x0C)
- Payload size varint

**Detection**: After parsing serial types, compute the expected body size
(sum of all serial type sizes). Compare against the actual body size
(cell_extent - prefix_len - header_size). If they don't match, at least
one byte is corrupted.

**Repair strategy**:
1. Try single-bit flips on each serial type byte
2. For each candidate, check if the resulting total body size matches
3. Accept the fix that produces a consistent parse
4. The script implements this automatically in `try_fix_record()`

### 2. Zeroed Regions
**Symptoms**: Large sections of 0x00. Cell pointer array or content
partially zeroed.

**Mitigation**:
- Scan the file for non-zero regions with text patterns
- Reconstruct from surviving fragments
- Use Python `re.finditer(b'[A-Za-z]{4,}', data)` to find readable
  text in the binary (since `strings` may not be installed)

### 3. Truncation
**Symptoms**: File shorter than expected; later pages missing.

**Mitigation**: Parse only existing pages. Compare file header's page
count against actual file size.

### 4. Damaged Page Structures
**Symptoms**: Cell pointer array corrupted; pointers overlap or go
out of bounds.

**Mitigation**:
- Validate each pointer: must be in `[header_end, page_size)`
- Sort valid pointers and compute extents
- Scan content area right-to-left for valid cell prefixes

## Manual Binary Recovery

### Step 1: Inspect the file
```bash
file <db_file>                     # Verify SQLite identification
ls -la <db_file>                   # Check file size
sqlite3 <db_file> ".tables" 2>&1   # Confirm corruption
```

To inspect page headers:
```python
import struct
data = open('<db_file>', 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0]
print(f'Page size: {page_size}, Pages: {len(data)//page_size}')
print(f'Magic: {data[:16]}')
```

### Step 2: Extract schema
```python
import re
data = open('<db_file>', 'rb').read()
for m in re.finditer(b'CREATE\s+TABLE\s+\w+\s*\([^)]+\)', data):
    print(m.group().decode('ascii', errors='replace'))
```

### Step 3: Find data pages
```python
import struct
data = open('<db_file>', 'rb').read()
page_size = struct.unpack('>H', data[16:18])[0]
for pg in range(len(data) // page_size):
    p = pg * page_size
    btree_off = 100 if pg == 0 else 0  # page 1 has file header
    ptype = data[p + btree_off]
    if ptype == 0x0D:
        nc = struct.unpack('>H', data[p+btree_off+3:p+btree_off+5])[0]
        print(f"Page {pg+1}: leaf table, {nc} cells")
```

### Step 4: Parse cells with correct extent calculation
```python
# Read cell pointers
ptrs = []
for i in range(num_cells):
    off = p + btree_off + 8 + 2*i
    ptrs.append(struct.unpack('>H', data[off:off+2])[0])

# CRITICAL: compute extents from descending pointer order
for i in range(len(ptrs)):
    cell_start = ptrs[i]
    cell_end = ptrs[i-1] if i > 0 else page_size
    cell_bytes = page[cell_start:cell_end]
    
    # Parse: payload_size varint, rowid varint, record header, body
    pos = 0
    payload_size, pos = read_varint(cell_bytes, pos)
    rowid, pos = read_varint(cell_bytes, pos)
    record_start = pos
    header_size, pos = read_varint(cell_bytes, pos)
    
    # Parse serial types
    serial_types = []
    while pos < record_start + header_size:
        st, pos = read_varint(cell_bytes, pos)
        serial_types.append(st)
    
    # VALIDATE: sum of serial type sizes == body bytes available
    body_size = cell_end - cell_start - pos_prefix - header_size
    expected = sum(serial_type_size(st) for st in serial_types)
    if expected != body_size:
        # Try single-bit flip corrections on serial types
        ...
```

### Step 5: Pattern-based fallback
When cell parsing fails, scan for text patterns:
```python
import re, struct
for m in re.finditer(b'[A-Za-z]{4,}', data):
    text = m.group().decode('ascii')
    after = m.end()
    # Try float64
    if after + 8 <= len(data):
        fval = struct.unpack('>d', data[after:after+8])[0]
        print(f'{text} -> {fval}')
    # Try single-byte int
    elif after < len(data):
        print(f'{text} -> {data[after]} (int8)')
```

## Verification Checklist

- [ ] Output file exists at the path specified in the task instruction
- [ ] Output is valid JSON (parseable by `json.loads()`)
- [ ] Each record has the exact keys specified in the task instruction
- [ ] Values have correct types (strings, ints, floats as specified)
- [ ] No duplicate records
- [ ] String values are clean (no null bytes, no control characters)
- [ ] Float values are finite (not NaN or Inf)
- [ ] Cross-check (if uncertain): scan binary for text patterns using
      Python `re.finditer` to confirm completeness

## Key Pitfalls

1. **Do not rely on `sqlite3` CLI** — it will fail on corrupted databases.
2. **Serial type 3 is 3 bytes, not 2.** Serial type 3 = 24-bit int = 3 bytes.
3. **Cell extent calculation is the #1 source of bugs.** Always use the
   pointer array in its native descending order: cell at `ptrs[i]` extends
   to `ptrs[i-1]` (or page_size for i=0). Never sort and then index.
4. **Always validate serial types against cell extent.** The sum of serial
   type sizes must exactly equal the available body bytes. A mismatch
   means corruption — do NOT blindly decode.
5. **Page 1 has a 100-byte file header** before its B-tree page header.
   It contains the sqlite_master schema, not user data.
6. **Payload size varint can be corrupted.** Use cell extent (from pointer
   array) as ground truth for how many bytes the cell occupies.
7. **The output format is task-specific.** Always parse the task
   instruction to determine exact column names and JSON structure.
8. **Records may span pages** via overflow pages in large databases.
   Check if payload_size exceeds the usable page area.

## Automated Recovery Script

The script at `/skill/scripts/recover_sqlite.py` implements:
- File header parsing and page enumeration
- Leaf table page identification (with bit-flip correction on page type)
- Correct cell extent calculation from descending pointer arrays
- Serial type validation against cell extents
- Automatic bit-flip correction on corrupted serial types and headers
- Pattern-based fallback for cells that can't be structurally parsed
- Schema inference from page 1's CREATE TABLE statements
- Deduplication and sorting by rowid

```bash
# With known column names (preferred):
python3 /skill/scripts/recover_sqlite.py /app/trunc.db /app/recover.json \
    --schema-hint "word,value"

# Without column names (auto-infer from schema):
python3 /skill/scripts/recover_sqlite.py /app/trunc.db /app/recover.json
```

If the script recovers fewer records than expected, supplement with
manual binary analysis to find records in corrupted regions.

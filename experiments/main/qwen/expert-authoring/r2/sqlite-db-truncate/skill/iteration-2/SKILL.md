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

## CRITICAL: Deploying the Script into the Task Container

Skill scripts live in the **host workspace** and are **NOT directly executable**
from the isolated `/app` task container. You must deploy the script first:

```
# Step 1: Read the script content using the read tool
read  skill/sqlite-db-truncate/scripts/recover_sqlite.py

# Step 2: Write it into the container using task_shell with a heredoc
task_shell: cat > /app/recover_sqlite.py << 'PYEOF'
  <paste the full script content here>
PYEOF

# Step 3: Run it
task_shell: python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json
```

**Do NOT try** `python3 skill/sqlite-db-truncate/scripts/recover_sqlite.py` or
any host workspace path from inside `task_shell` — it will fail with "No such file".

## Quick-Start Checklist

1. **Deploy the script** into the container (see above)
2. **Try sqlite3 first** — `sqlite3 -json <db> 'SELECT * FROM <table>'`
3. **If that fails**, the deployed script handles everything automatically
4. **Run**: `python3 /app/recover_sqlite.py <db_path> /app/recover.json`
5. **Validate output** — check row count, spot-check values, verify JSON format

## Recovery Script

`scripts/recover_sqlite.py` — a self-contained Python script (no external deps
beyond stdlib) that handles the full pipeline:

```bash
# Auto-detect schema from raw bytes
python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json

# With explicit schema override (when auto-detect fails)
echo '{"mytable": [["col1","TEXT"],["col2","REAL"]]}' > /app/schema.json
python3 /app/recover_sqlite.py /app/trunc.db /app/recover.json /app/schema.json
```

**What it does:**
- Tries `sqlite3 -json` first (fast path for uncorrupted files)
- Falls back to raw page-by-page parsing
- Extracts `CREATE TABLE` text from page 1 to learn the schema
- Scans all pages for leaf table b-tree pages (type `0x0d`)
- Parses each cell: payload length (varint), rowid (varint), serial types
- When serial types are corrupted, uses **schema-guided scoring** to find
  the best column-size assignment
- Outputs a JSON array of objects sorted by rowid

## Inline Fallback (No Script Deployment)

If deploying the script is difficult, use this compact inline approach directly
in a single `task_shell` call. Adapt the `schema_types` and output column names
to match the actual database schema:

```python
python3 << 'PYEOF'
import struct, json, re

def parse_varint(data, offset):
    if offset >= len(data): return 0, offset + 1
    result = 0
    for i in range(9):
        if offset + i >= len(data): return result, offset + i + 1
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7f)
            if byte < 0x80: return result, offset + i + 1
        else:
            result = (result << 8) | byte
            return result, offset + i + 1
    return result, offset + 9

def decode_serial_type(st):
    if st == 0: return ('null', 0)
    elif 1 <= st <= 6: return ('int', [0,1,2,3,4,6,8][st])
    elif st == 7: return ('float', 8)
    elif st >= 12:
        if st % 2 == 0: return ('text', (st-12)//2)
        else: return ('blob', (st-13)//2)
    return ('other', 0)

def _is_print(b): return 0x20<=b<=0x7e or b in (9,10,13)

# ── READ FILE AND FIND SCHEMA ──
DB_PATH = '/app/trunc.db'
OUT_PATH = '/app/recover.json'

with open(DB_PATH, 'rb') as f: data = f.read()
ps = struct.unpack('>H', data[16:18])[0]
if ps == 1: ps = 65536

# Auto-detect schema from CREATE TABLE text
schema_match = re.search(
    rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', data[:ps], re.I)
if not schema_match:
    # Fallback: manually specify table name and column schema
    table_name = "test"
    schema_types = ['TEXT', 'REAL']
    col_names = ['word', 'value']
else:
    table_name = schema_match.group(1).decode()
    cols_raw = schema_match.group(2).decode()
    col_names = []
    schema_types = []
    for cd in cols_raw.split(','):
        parts = cd.strip().split()
        col_names.append(parts[0])
        schema_types.append(parts[1].upper() if len(parts) >= 2 else 'BLOB')

# ── RECOVER RECORDS ──
def recover_payload(payload, schema_types):
    """Parse a record, handling corrupted serial types via scoring."""
    if len(payload) < 2: return None
    hs, _ = parse_varint(payload, 0)
    if hs < 2 or hs > min(len(payload), 50): return None
    sts, pos = [], 1
    while pos < hs:
        st, pos = parse_varint(payload, pos); sts.append(st)
    nc = len(sts); ds = hs; ad = len(payload) - ds
    if ad < 0: return None

    # Check if declared types match payload size
    declared = sum(decode_serial_type(s)[1] for s in sts)
    if declared == ad:
        return extract_vals(payload, ds, sts, schema_types)

    # Schema-guided recovery with scoring
    if len(schema_types) != nc: return None
    cands = []
    for j in range(nc):
        t = schema_types[j]
        if t in ('TEXT','BLOB'):
            cands.append(list(range(min(ad+1, 2000))))
        elif t in ('REAL','INTEGER'):
            cands.append([0,1,2,3,4,6,8])
        else:
            cands.append(list(range(ad+1)))

    best = [None]; best_sc = [-1e9]
    def dfs(idx, cur, rs):
        if idx == nc:
            if rs == ad:
                sc = 0.0; off = ds
                for k in range(nc):
                    sz = cur[k]; st = schema_types[k]
                    if st=='TEXT' and sz>0:
                        sc += sz*10
                        tb = payload[off:off+sz]
                        try:
                            s = tb.decode('utf-8')
                            if s.isalnum() or s.replace('_','').isalnum():
                                sc += 15
                            if len(s)>=3: sc += 5
                        except: pass
                    elif st in ('REAL','INTEGER'):
                        sc += {8:6,4:4,6:2,3:2,2:2,1:1}.get(sz,0) if st=='REAL' \
                              else {1:4,2:4,3:3,4:3,6:2,8:2}.get(sz,0)
                    if sz==0 and st!='BLOB': sc -= 8
                    off += sz
                if sc > best_sc[0]: best_sc[0]=sc; best[0]=list(cur)
            return
        rmax = sum(max(cands[k]) for k in range(idx+1,nc)) if idx+1<nc else 0
        for sz in cands[idx]:
            ns = rs + sz
            if ns > ad: break
            if ns + rmax < ad: continue
            if schema_types[idx]=='TEXT' and sz>0:
                off = ds + rs; ok = True
                for kk in range(sz):
                    if off+kk>=len(payload) or not _is_print(payload[off+kk]):
                        ok=False; break
                if not ok: continue
            cur.append(sz); dfs(idx+1, cur, ns); cur.pop()

    dfs(0, [], 0)
    if best[0]:
        return extract_by_sizes(payload, ds, best[0], schema_types)
    return None

def extract_vals(payload, ds, sts, schema):
    vals, d = [], ds
    for j, st in enumerate(sts):
        kind, sz = decode_serial_type(st)
        exp = schema[j] if j < len(schema) else None
        if kind == 'null': vals.append(None)
        elif kind == 'int':
            if d+sz<=len(payload):
                vals.append(int.from_bytes(payload[d:d+sz],'big',signed=True)); d+=sz
            else: vals.append(None)
        elif kind == 'float':
            if d+8<=len(payload):
                vals.append(struct.unpack('>d',payload[d:d+8])[0]); d+=8
            else: vals.append(None)
        elif kind in ('text','blob'):
            if d+sz<=len(payload):
                raw = payload[d:d+sz]
                if kind=='text' or exp=='TEXT':
                    try: vals.append(raw.decode('utf-8'))
                    except: vals.append(raw.decode('latin-1'))
                else: vals.append(raw)
                d+=sz
            else: vals.append(None)
        else: vals.append(None)
    return vals

def extract_by_sizes(payload, ds, sizes, schema):
    vals, d = [], ds
    for sz, st in zip(sizes, schema):
        if sz == 0: vals.append(None)
        elif st == 'TEXT':
            try: vals.append(payload[d:d+sz].decode('utf-8'))
            except: vals.append(payload[d:d+sz].decode('latin-1'))
            d+=sz
        elif st == 'REAL':
            if sz==8: vals.append(struct.unpack('>d',payload[d:d+8])[0])
            elif sz==4: vals.append(struct.unpack('>f',payload[d:d+4])[0])
            elif 1<=sz<=6: vals.append(int.from_bytes(payload[d:d+sz],'big',signed=True))
            else: vals.append(None)
            d+=sz
        elif st == 'INTEGER':
            if d+sz<=len(payload):
                vals.append(int.from_bytes(payload[d:d+sz],'big',signed=True))
            else: vals.append(None)
            d+=sz
        else:
            if d+sz<=len(payload): vals.append(payload[d:d+sz])
            else: vals.append(None)
            d+=sz
    return vals

# ── SCAN ALL PAGES ──
all_rows = []
for pn in range(len(data) // ps):
    pstart = pn * ps
    if pstart + 1 > len(data): break
    if data[pstart] != 0x0d: continue
    page = data[pstart:pstart+ps]
    cc = struct.unpack('>H', page[3:5])[0]
    ptrs = []
    for i in range(cc):
        o = 8+i*2
        if o+2>len(page): break
        ptrs.append(struct.unpack('>H',page[o:o+2])[0])
    for ptr in sorted(p for p in ptrs if p < ps):
        ao = pstart+ptr; off = ao
        pl, off = parse_varint(data, off)
        rid, off = parse_varint(data, off)
        if pl<=0 or pl>ps: continue
        pay = data[off:off+pl]
        if len(pay)<3: continue
        v = recover_payload(pay, schema_types)
        if v and len(v)>0:
            row = {}
            for j, cn in enumerate(col_names):
                row[cn] = v[j] if j < len(v) else None
            all_rows.append((rid, row))

all_rows.sort(key=lambda x: x[0])
output = [r for _, r in all_rows]
with open(OUT_PATH, 'w') as f: json.dump(output, f, indent=2)
print(f"Recovered {len(output)} rows")
print(json.dumps(output[:3], indent=2))
PYEOF
```

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

## Adapting to Different Schemas

The family varies in table count, column types, and column order. To adapt:

1. **Extract schema**: Search for `CREATE TABLE` in page 1 — the regex
   `CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)` works even with bit-flip corruption
   because the SQL text is usually in the data area (not the corrupted header).

2. **Column type mapping**: The recovery script maps SQL types to recovery logic:
   - `TEXT` → validate bytes as printable UTF-8, score longer runs higher
   - `REAL` → prefer 8-byte float, accept smaller int storage
   - `INTEGER` → accept any valid integer size (1–8 bytes)
   - `BLOB` → accept raw bytes

3. **Multiple tables**: Scan all pages; each leaf page (type `0x0d`) belongs to
   some table. The script currently tries all known schemas against each page.
   If tables have different schemas, match records to the schema that produces
   valid parses.

4. **Column order matters**: The schema's column order matches the serial type
   order in the record. Do NOT reorder columns.

## Output Format

The task typically requires a JSON array:
```json
[
  {"word": "testword02", "value": 10},
  {"word": "testword03", "value": 25}
]
```

Key decisions:
- **Integers vs floats**: If schema says REAL but value was stored as a small
  integer (serial type 1–6), output the integer. JSON numbers are untyped.
- **Row ordering**: Sort by rowid (ascending) unless the task specifies otherwise.
- **NULL handling**: Include null values as JSON `null`.

## Verification

After recovery, verify:
1. ✅ Row count matches cell count in data pages
2. ✅ Text columns contain readable strings (not garbage)
3. ✅ Numeric columns have plausible values (not 1e+253)
4. ✅ JSON is valid and matches the expected schema format from the task
5. ✅ Output file is at the correct path (`/app/recover.json`)

## Edge Cases

| Scenario | Approach |
|----------|----------|
| Multiple tables | Parse each table's root page from schema entries |
| Records spanning pages (overflow) | Follow overflow page chain (4-byte page number at end of local payload) |
| No CREATE TABLE found | Scan all pages for data patterns; try blind text extraction |
| Interior b-tree pages | Follow child page pointers (right-most pointer at offset 8) to reach leaf pages |
| Very large databases | Process pages sequentially; the script is already O(pages × cells) |
| Non-standard page sizes | Read page size from header byte 16–17; handle 512 to 65536 |
| Schema itself corrupted | Try `sqlite3 .recover` or manually inspect hex for SQL text fragments |

---
name: sqlite-db-truncate
description: >
  Recover logically valid rows from damaged SQLite databases when standard
  queries fail due to corruption (truncation, bit flips, zeroed regions,
  damaged page structures, or split fragments). Parse the raw SQLite file
  format — headers, B-tree pages, record headers, varints, serial types —
  to extract and serialize recoverable records into JSON.
---

# Corrupted SQLite Row Recovery

## When to Use This Skill

The database file exists but `sqlite3` returns `database disk image is
malformed`. You must recover rows by parsing the raw binary format and
write them to a JSON file.

## Procedure

### Step 1 — Confirm Corruption

```bash
sqlite3 /app/trunc.db ".schema" 2>&1
```

If it returns `malformed`, proceed to Step 2.

### Step 2 — Run Recovery (copy-paste this entire block)

```bash
cd /app && python3 << 'PYEOF'
import struct, json, re, sys
from pathlib import Path

DB_PATH  = "/app/trunc.db"
OUT_PATH = "/app/recover.json"

# If auto-detection fails, set SCHEMA_SQL manually, e.g.:
#   SCHEMA_SQL = "CREATE TABLE test (word TEXT, value REAL)"
SCHEMA_SQL = None

data = Path(DB_PATH).read_bytes()
ps = int.from_bytes(data[16:18], "big")
page_size = 65536 if ps == 1 else ps
n_pages = len(data) // page_size

def read_varint(buf, pos):
    r = 0
    for i in range(9):
        if pos >= len(buf): return r, pos
        b = buf[pos]; pos += 1
        if i < 8:
            r = (r << 7) | (b & 0x7F)
            if b < 0x80: return r, pos
        else:
            r = (r << 8) | b
    return r, pos

def st_size(st):
    if st in (0, 8, 9): return 0
    if 1 <= st <= 6: return (0,1,2,3,4,6,8)[st]
    if st == 7: return 8
    if st >= 12 and st % 2 == 0: return (st - 12) // 2
    if st >= 13 and st % 2 == 1: return (st - 13) // 2
    return -1

def parse_record(rec):
    if not rec or rec[0] < 2: return None
    hs = rec[0]
    if hs > len(rec): return None
    pos = 1; types = []
    while pos < hs:
        st, pos = read_varint(rec, pos); types.append(st)
    dpos = hs; vals = []
    for st in types:
        sz = st_size(st)
        if sz < 0 or dpos + sz > len(rec): return None
        if st == 0: vals.append(None)
        elif st == 8: vals.append(0)
        elif st == 9: vals.append(1)
        elif 1 <= st <= 6:
            vals.append(int.from_bytes(rec[dpos:dpos+sz], "big", signed=True))
        elif st == 7:
            vals.append(struct.unpack(">d", rec[dpos:dpos+8])[0])
        elif st >= 13 and st % 2 == 1:
            vals.append(rec[dpos:dpos+sz].decode("utf-8", errors="replace"))
        else:
            vals.append(rec[dpos:dpos+sz])
        dpos += sz
    return vals

def fix_types(raw, expected_body):
    total = sum(st_size(s) for s in raw)
    if all(st_size(s) >= 0 for s in raw) and total == expected_body:
        return list(raw)
    for idx in range(len(raw)):
        for bit in range(8):
            c = raw[idx] ^ (1 << bit)
            trial = list(raw); trial[idx] = c
            if all(st_size(s) >= 0 for s in trial) and \
               sum(st_size(s) for s in trial) == expected_body:
                return trial
    for idx in range(len(raw)):
        for b1 in range(8):
            for b2 in range(b1+1, 8):
                c = raw[idx] ^ (1 << b1) ^ (1 << b2)
                trial = list(raw); trial[idx] = c
                if all(st_size(s) >= 0 for s in trial) and \
                   sum(st_size(s) for s in trial) == expected_body:
                    return trial
    return None

def recover_cell(page, ptr, ncols):
    if ptr >= len(page): return None
    psz, p = read_varint(page, ptr)
    rid, p = read_varint(page, p)
    rec = page[p:p+psz]
    if len(rec) < psz: rec += b"\x00" * (psz - len(rec))
    if not rec or rec[0] < 2: return None
    hs = rec[0]
    if hs > len(rec): return None
    pos = 1; types = []
    while pos < hs:
        st, pos = read_varint(rec, pos); types.append(st)
    if not types: return None
    fixed = fix_types(types, psz - hs)
    if fixed is None: return None
    new_hdr = bytes([hs] + [t if t < 0x80 else t for t in fixed])
    vals = parse_record(new_hdr + rec[hs:])
    if vals is None or len(vals) != ncols: return None
    return rid, vals

def parse_cols(sql):
    m = re.match(r"CREATE\s+TABLE\s+\S+\s*\((.*)\)", sql, re.I|re.S)
    if not m: return []
    cols = []
    for part in re.split(",", m.group(1)):
        toks = part.strip().split()
        if not toks: continue
        name = toks[0].strip("\"'` ")
        aff = toks[1].upper() if len(toks) > 1 else "BLOB"
        if "INT" in aff: aff = "INTEGER"
        elif any(x in aff for x in ("REAL","FLOA","DOUB")): aff = "REAL"
        elif any(x in aff for x in ("TEXT","CHAR","CLOB")): aff = "TEXT"
        else: aff = "BLOB"
        cols.append((name, aff))
    return cols

# --- Schema detection: regex scan is most robust for corrupted DBs ---
schemas = []
if SCHEMA_SQL:
    schemas = [("manual", parse_cols(SCHEMA_SQL), SCHEMA_SQL)]
else:
    for m_found in re.finditer(rb"CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)", data):
        sql = m_found.group(0).decode("utf-8", errors="replace")
        tbl = m_found.group(1).decode()
        schemas.append((tbl, parse_cols(sql), sql))

if not schemas:
    # Last resort: infer from task instruction JSON hint
    # e.g. [{"word": "testwordXY", "value": M}] → word TEXT, value REAL
    print("ERROR: no schema found. Set SCHEMA_SQL manually.", file=sys.stderr)
    sys.exit(1)

tbl_name, columns, sql = schemas[0]
ncols = len(columns)
print(f"Schema: {sql}", file=sys.stderr)

# --- Recover data from all pages ---
seen = set(); rows = []
for pgnum in range(1, n_pages + 1):
    pg = data[(pgnum-1)*page_size : pgnum*page_size]
    hoff = 100 if pgnum == 1 else 0
    if hoff + 8 > len(pg): continue
    if pg[hoff] != 0x0d: continue   # skip non-leaf-table pages
    nc = int.from_bytes(pg[hoff+3:hoff+5], "big")
    if nc > 10000: continue          # sanity check
    hdr_sz = 12 if pg[hoff] in (0x02, 0x05) else 8
    base = hoff + hdr_sz
    for i in range(nc):
        if base + 2 + i*2 > len(pg): break
        cptr = int.from_bytes(pg[base+i*2:base+2+i*2], "big")
        r = recover_cell(pg, cptr, ncols)
        if r and r[0] not in seen:
            seen.add(r[0]); rows.append(r)

rows.sort(key=lambda x: x[0])
result = []
for rid, vals in rows:
    row = {}
    for i, (cn, _) in enumerate(columns):
        row[cn] = vals[i] if i < len(vals) else None
    result.append(row)

print(f"Recovered {len(result)} rows", file=sys.stderr)
with open(OUT_PATH, "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
PYEOF
```

### Step 3 — If Auto-Detection Fails

If the script prints `ERROR: no schema found`, extract the schema from the
task instruction. The JSON format hint contains column names and types:

| Example value | Inferred type |
|---------------|---------------|
| `"testwordXY"` (quoted) | TEXT |
| `M` (bare integer) | INTEGER or REAL |
| `3.14` (bare float) | REAL |

Set `SCHEMA_SQL` at the top of the script:
```python
SCHEMA_SQL = "CREATE TABLE test (word TEXT, value REAL)"
```

## How It Works

The script:
1. Reads the SQLite file header to get page size and page count.
2. Scans raw bytes for `CREATE TABLE` to find the schema (regex is more
   robust than parsing sqlite_master, which may itself be corrupted).
3. Walks every leaf-table page, reading the B-tree header and cell
   pointer array.
4. For each cell: parses payload-size varint, rowid varint, then the
   record header. Validates each serial type by checking that the total
   body size equals `payload_size − header_size`. If invalid, tries
   single-bit then two-bit XOR correction.
5. Decodes column values using the corrected serial types.
6. Deduplicates by rowid, sorts, and writes JSON.

## Corruption Correction

**Random bit flips** are the dominant corruption mode. The algorithm:
1. `expected_body = payload_size − header_size`
2. `actual_body = sum(st_size(t) for t in serial_types)`
3. If mismatch: try XOR-ing each serial type byte with each single-bit
   mask (8 candidates per byte). Accept the first fix where the total
   body size matches.
4. If no single-bit fix: try two-bit XOR (28 candidates per byte).

**Zeroed regions**: intact cells before the zero boundary are recovered;
cells spanning the boundary may be partially recovered.

**Damaged B-tree headers**: pages where `flags != 0x0d` are skipped.

## Output Format

Match the JSON schema from the task instruction exactly:
- Integer serial types (1–6) → JSON integer
- Float serial type (7) → JSON float
- NULL → `null`
- Write to the path in the task instruction (usually `/app/recover.json`)

## Serial Type Reference

| Type | Meaning | Body bytes |
|------|---------|------------|
| 0 | NULL | 0 |
| 1–6 | Signed int | 1, 2, 3, 4, 6, 8 |
| 7 | IEEE-754 float64 | 8 |
| 8, 9 | Constants 0, 1 | 0 |
| ≥12 even | BLOB | (N−12)/2 |
| ≥13 odd | TEXT | (N−13)/2 |

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

The database file exists at the expected path and `file` recognises it as
SQLite, but `sqlite3 <db> ".schema"` or `SELECT` statements return
`database disk image is malformed`. The task requires recovering as many
rows as possible and writing them to a JSON file.

## Step-by-Step Procedure

### Step 1 — Try Standard Tooling (30 seconds)

```bash
sqlite3 /app/trunc.db ".schema" 2>/dev/null
sqlite3 /app/trunc.db "SELECT * FROM <table>;" 2>/dev/null
```

If this succeeds, dump to JSON and stop. If `database disk image is
malformed`, proceed to Step 2.

### Step 2 — Run the Recovery Script (primary path)

The skill ships a ready-to-use Python script at `scripts/recover_sqlite.py`
(relative to this SKILL.md file). Run it first **without** `--schema-hint`
so it auto-detects the schema from sqlite_master:

```bash
python3 scripts/recover_sqlite.py /app/trunc.db /app/recover.json
```

If the script reports `Could not determine schema`, extract the schema from
the task instruction. The task instruction usually contains a JSON format
hint like `[{"word": "testwordXY", "value": M}, ...]` — the key names are
the column names. Infer types from the example values: quoted strings →
TEXT, bare numbers → INTEGER or REAL. Then re-run with `--schema-hint`:

```bash
python3 scripts/recover_sqlite.py /app/trunc.db /app/recover.json \
  --schema-hint 'CREATE TABLE test (word TEXT, value REAL)'
```

**What the script handles:**
- Reads the file header to determine page size and page count.
- Parses sqlite_master (page 1) with the same bit-flip correction used
  for data cells, so corrupted schema rows are recovered too.
- Falls back to regex-scanning raw bytes for `CREATE TABLE` if page 1
  B-tree structures are too damaged.
- Walks every cell-pointer on every data page, validates each serial
  type, and corrects single- or two-bit flips by checking that the total
  body size matches `payload_size − header_size`.
- Also scans each page byte-by-byte for records that exist outside the
  cell-pointer array (handles corrupted pointer arrays).
- Deduplicates by rowid and sorts output by rowid.

### Step 3 — Inline Fallback (if the script is unavailable or fails)

If `scripts/recover_sqlite.py` cannot be found or produces wrong output,
copy the following inline recipe into a `task_shell` heredoc. It
implements the full recovery pipeline in one self-contained script:

```python
python3 << 'PYEOF'
import struct, json, re, sys
from pathlib import Path

DB_PATH   = "/app/trunc.db"
OUT_PATH  = "/app/recover.json"
# Set SCHEMA_SQL to None to auto-detect from sqlite_master,
# or provide a CREATE TABLE string if auto-detection fails.
SCHEMA_SQL = None  # e.g. "CREATE TABLE test (word TEXT, value REAL)"

data = Path(DB_PATH).read_bytes()
ps = int.from_bytes(data[16:18], "big")
page_size = 65536 if ps == 1 else ps
n_pages = len(data) // page_size

# --- Varint & serial-type helpers ---
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
    # single-bit flip
    for idx in range(len(raw)):
        for bit in range(8):
            c = raw[idx] ^ (1 << bit)
            trial = list(raw); trial[idx] = c
            if all(st_size(s) >= 0 for s in trial) and \
               sum(st_size(s) for s in trial) == expected_body:
                return trial
    # two-bit flip
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

# --- Schema detection ---
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

schemas = []
if SCHEMA_SQL:
    schemas = [("manual", parse_cols(SCHEMA_SQL), SCHEMA_SQL)]
else:
    # Try sqlite_master on page 1
    pg1 = data[:page_size]
    off1 = 100
    if off1 + 8 <= len(pg1) and pg1[off1] == 0x0d:
        nc1 = int.from_bytes(pg1[off1+3:off1+5], "big")
        for i in range(nc1):
            cptr = int.from_bytes(pg1[off1+8+i*2:off1+10+i*2], "big")
            r = recover_cell(pg1, cptr, 5)
            if r and isinstance(r[1][4], str) and "CREATE" in r[1][4].upper():
                tbl = r[1][1]; sql = r[1][4]
                cols = parse_cols(sql)
                rp = r[1][3] if isinstance(r[1][3], int) else 2
                schemas.append((tbl, cols, sql))
                break
    if not schemas:
        for m in re.finditer(rb"CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)", data):
            sql = m.group(0).decode("utf-8", errors="replace")
            tbl = m.group(1).decode()
            schemas.append((tbl, parse_cols(sql), sql))

if not schemas:
    print("ERROR: no schema found", file=sys.stderr); sys.exit(1)

tbl_name, columns, sql = schemas[0]
ncols = len(columns)
col_names = [c[0] for c in columns]
print(f"Table: {tbl_name}, columns: {col_names}", file=sys.stderr)

# --- Determine data pages ---
root_pages = list(range(2, n_pages + 1))

seen = set(); rows = []
for pgnum in root_pages:
    pg = data[(pgnum-1)*page_size : pgnum*page_size]
    # structured parse
    hoff = 100 if pgnum == 1 else 0
    if hoff + 8 <= len(pg) and pg[hoff] == 0x0d:
        nc = int.from_bytes(pg[hoff+3:hoff+5], "big")
        hdr_sz = 12 if pg[hoff] in (0x02, 0x05) else 8
        base = hoff + hdr_sz
        for i in range(nc):
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

### Step 4 — Extract Schema from Task Instruction

If the schema cannot be parsed from sqlite_master *and* the script/reports
no schema, look at the task instruction's JSON format example:

```
[{"word": "testwordXY", "value": M}, ...]
```

From this, derive:
- Column names: `word`, `value`
- Column types: `word` has a string example → TEXT; `value` has a bare
  number → REAL or INTEGER (use REAL to be safe — SQLite stores integers
  in REAL columns as integer serial types anyway).

Construct: `CREATE TABLE <name> (word TEXT, value REAL)`

The table name is usually visible in the task instruction or can be guessed.
If unsure, try `test`, `data`, or the filename stem.

## Output Serialization

- Match the JSON schema from the task instruction exactly.
- Integer serial types (1–6) → JSON integer.
- Float serial type (7) → JSON float.
- NULL → `null`.
- Write to the path in the task instruction (typically `/app/recover.json`).

## SQLite Format Reference

Use these tables when debugging script output or writing custom recovery
logic for unusual corruption patterns.

### File Header

| Offset | Size | Meaning |
|--------|------|---------|
| 0      | 16   | `SQLite format 3\0` |
| 16     | 2    | Page size (big-endian; raw value 1 → 65536) |
| 28     | 4    | File change counter |
| 32     | 4    | Database size in pages |
| 100    | …    | Page-1 B-tree content starts here |

### B-Tree Page Header

| Offset | Size | Meaning |
|--------|------|---------|
| 0      | 1    | Flags: `0x0d`=leaf table, `0x05`=interior table, `0x0a`=leaf index, `0x02`=interior index |
| 1      | 2    | First freeblock offset (0 = none) |
| 3      | 2    | Number of cells |
| 5      | 2    | Cell content area start offset |
| 7      | 1    | Fragmented free bytes |

Cell pointer array follows the header: `num_cells × 2` bytes.

### Cell Layout (leaf table)

`payload_size_varint | rowid_varint | record_bytes`

### Record Format

`header_size_byte | serial_type_varints… | column_values…`

| Serial Type | Meaning |
|-------------|---------|
| 0           | NULL (0 bytes) |
| 1–6         | Signed integer, 1/2/3/4/6/8 bytes |
| 7           | IEEE-754 float64, 8 bytes big-endian |
| 8, 9        | Constants 0, 1 (0 bytes) |
| ≥12, even   | BLOB of `(N-12)/2` bytes |
| ≥13, odd    | TEXT of `(N-13)/2` bytes |

### Varint Encoding

Up to 9 bytes. Each byte: bit 7 = continuation flag, bits 0–6 = data.
The 9th byte contributes all 8 bits.

## Corruption Correction Strategy

The dominant corruption mode in this family is **random bit flips** —
isolated bytes have one or two bits flipped. The correction algorithm:

1. Compute `expected_body = payload_size − header_size`.
2. Compute `actual_body = sum(st_size(t) for t in serial_types)`.
3. If `actual_body == expected_body`, no correction needed.
4. Otherwise, for each serial-type position, try XOR with each single-bit
   mask (8 candidates). Accept the first candidate where the corrected
   total body size equals `expected_body`.
5. If no single-bit fix works, try two-bit XOR (28 candidates per
   position). This handles rarer double-flip corruption.
6. If still no fix, skip that cell (it is too damaged).

For **zeroed regions**: cell pointers may survive while cell content is
partly zeroed. Extract intact cells; for partially zeroed cells, recover
columns before the zero boundary.

For **damaged B-tree headers**: scan each page byte-by-byte looking for
valid cell starts (small varint for payload, small varint for rowid,
plausible record header byte).

## Validation Checklist

Before writing JSON output:

- [ ] Every serial type is legal (0–9, or ≥12 with correct parity).
- [ ] Body bytes sum to `payload_size − header_size` exactly.
- [ ] Text columns decode as valid UTF-8.
- [ ] Float values are not NaN or Infinity (unless expected).
- [ ] Rowids are positive.
- [ ] Column count matches the schema.

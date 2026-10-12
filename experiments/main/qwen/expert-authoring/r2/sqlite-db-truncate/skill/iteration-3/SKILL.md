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

## Optimal Workflow (4 steps)

Follow these steps in order. **Do NOT do manual hex exploration** — the recovery
script handles all byte-level analysis automatically. Do NOT call `xxd`,
`hexdump`, or inspect raw bytes before running the script.

### Step 1: Read the task and this SKILL.md

Read `task.yaml` (in the host workspace, not `/app`) to understand the required
output path and JSON format.

### Step 2: Deploy the recovery script into the container

The script lives in the **host workspace** at
`skill/sqlite-db-truncate/scripts/recover_sqlite.py`. It is **NOT directly
executable** from the isolated `/app` task container.

To deploy it:
1. Use the `read` tool to read the script file from the skill package
2. Use `task_shell` with a heredoc to write it into the container:
   ```bash
   cat > /app/recover_sqlite.py << 'PYEOF'
   <paste the full script content here>
   PYEOF
   ```

**Do NOT** try `python3 skill/.../recover_sqlite.py` from `task_shell` — it will
fail with "No such file or directory".

### Step 3: Run the recovery script

```bash
python3 /app/recover_sqlite.py <db_path> /app/recover.json
```

The script automatically:
- Tries `sqlite3` first (fast path for uncorrupted files)
- Falls back to raw page-by-page parsing if sqlite3 fails
- Extracts `CREATE TABLE` text from page 1 to learn the schema
- Scans all pages for leaf table b-tree pages (type `0x0d`)
- Parses each cell: payload length (varint), rowid (varint), serial types
- When serial types are corrupted, uses **schema-guided scoring** to find
  the best column-size assignment
- Outputs a JSON array of objects sorted by rowid

### Step 4: Verify the output

```bash
cat /app/recover.json
```

Check that:
- Text columns contain readable strings (not garbage)
- Numeric columns have plausible values (not 1e+253)
- Row count seems reasonable
- JSON format matches the task specification

## Inline Fallback (No Script Deployment)

If deploying the script fails or you need a single-call approach, use this
compact inline Python in a single `task_shell` call. It auto-detects the
schema from `CREATE TABLE` text in page 1:

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

DB_PATH = '/app/trunc.db'
OUT_PATH = '/app/recover.json'

with open(DB_PATH, 'rb') as f: data = f.read()
ps = struct.unpack('>H', data[16:18])[0]
if ps == 1: ps = 65536

# Auto-detect schema from CREATE TABLE text in page 1
schema_match = re.search(
    rb'CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)', data[:ps], re.I)
if not schema_match:
    print("ERROR: No CREATE TABLE found. Inspect hex manually."); exit(1)
table_name = schema_match.group(1).decode()
cols_raw = schema_match.group(2).decode()
col_names, schema_types = [], []
for cd in cols_raw.split(','):
    parts = cd.strip().split()
    col_names.append(parts[0])
    schema_types.append(parts[1].upper() if len(parts) >= 2 else 'BLOB')

def recover_payload(payload, schema_types):
    if len(payload) < 2: return None
    hs, _ = parse_varint(payload, 0)
    if hs < 2 or hs > min(len(payload), 50): return None
    sts, pos = [], 1
    while pos < hs:
        st, pos = parse_varint(payload, pos); sts.append(st)
    nc = len(sts); ds = hs; ad = len(payload) - ds
    if ad < 0: return None
    declared = sum(decode_serial_type(s)[1] for s in sts)
    if declared == ad:
        return extract_vals(payload, ds, sts, schema_types)
    if len(schema_types) != nc: return None
    cands = []
    for j in range(nc):
        t = schema_types[j]
        if t in ('TEXT','BLOB'): cands.append(list(range(min(ad+1, 2000))))
        elif t in ('REAL','INTEGER'): cands.append([0,1,2,3,4,6,8])
        else: cands.append(list(range(ad+1)))
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
                            if s.isalnum() or s.replace('_','').isalnum(): sc += 15
                            if len(s)>=3: sc += 5
                        except: pass
                    elif st in ('REAL','INTEGER'):
                        sc += ({8:6,4:4,6:2,3:2,2:2,1:1}.get(sz,0) if st=='REAL'
                               else {1:4,2:4,3:3,4:3,6:2,8:2}.get(sz,0))
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
    if best[0]: return extract_by_sizes(payload, ds, best[0], schema_types)
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
print(f"Recovered {len(output)} rows -> {OUT_PATH}")
for r in output[:3]: print(r)
PYEOF
```

## SQLite File Format Reference

For manual debugging when the script fails or produces wrong results.

### Database Header (bytes 0–99 of page 1)

| Offset | Size | Field | Expected |
|--------|------|-------|----------|
| 0 | 16 | Magic string | `SQLite format 3\0` |
| 16 | 2 | Page size (bytes) | Power of 2, commonly 4096 |
| 28 | 4 | Database size (pages) | |
| 44 | 4 | Schema format | 4 |
| 56 | 4 | Text encoding | 1=UTF-8 |

### B-Tree Page Header

Starts at byte 100 for page 1, byte 0 for other pages.

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | Page type: `0x0d`=leaf table, `0x05`=interior table |
| 3 | 2 | Number of cells |
| 5 | 2 | Cell content area start offset |

Cell pointer array follows immediately at offset 8 (2 bytes per cell).

### Record (Cell) Format

Each cell in a leaf table page:
1. **Payload length** — varint
2. **Row ID** — varint
3. **Record payload**: header size (varint), serial types (varints), column data (packed)

### Serial Types

| Code | Kind | Byte Size |
|------|------|-----------|
| 0 | NULL | 0 |
| 1–6 | Integer | 1, 2, 3, 4, 6, 8 |
| 7 | Float64 (IEEE 754) | 8 |
| ≥12 even | Text | (N−12)/2 |
| ≥13 odd | Blob | (N−13)/2 |

## Corruption Patterns

### Corrupted Serial Types (Most Common)

Serial type bytes get bit flips, making declared sizes mismatch payload.
Example: `0x20` (text 10 bytes) → `0x21` (blob 10 bytes, same size) or
`0x61` (blob 42 bytes, wrong size entirely).

**Fix**: Schema-guided scoring enumerates valid column-size combinations
and picks the parse that produces the most plausible data.

### Mixed Integer/Float in REAL Columns

SQLite stores small REAL values as compact integers (serial types 1-6).
The recovery script handles this: when schema says REAL and serial type
is an integer type, it reads the integer value directly.

### Noise Bytes in Unused Page Areas

Random bits flipped in unused regions between cell pointers and cell content.
Doesn't affect record parsing (records are at cell pointer offsets).

### Corrupted Page Headers

Cell content area start pointer doesn't match minimum cell pointer.
The recovery script ignores the cell content area field and uses cell
pointers directly to locate records.

## Adapting to Different Schemas

The family varies in table count, column types, and column order.

1. **Schema extraction**: `CREATE TABLE` text in page 1 usually survives
   corruption. The regex `CREATE\s+TABLE\s+(\w+)\s*\(([^)]+)\)` works
   even when serial types in the schema record are corrupted.

2. **Column type mapping**:
   - `TEXT` → validate as printable UTF-8, score longer runs higher
   - `REAL` → prefer 8-byte float, accept smaller integer storage
   - `INTEGER` → accept any valid integer size (1–8 bytes)
   - `BLOB` → accept raw bytes

3. **Multiple tables**: Each leaf page belongs to some table. Match records
   to the schema that produces valid parses.

4. **Column order matters**: Schema column order matches serial type order
   in records. Do NOT reorder.

## Output Format Decisions

- **Integers vs floats**: Output integers for REAL columns stored as small
  ints. JSON numbers are untyped.
- **Row ordering**: Sort by rowid ascending unless the task says otherwise.
- **NULL handling**: Include nulls as JSON `null`.

## Verification Checklist

After recovery:
1. ✅ Row count matches cell count in data pages
2. ✅ Text columns contain readable strings
3. ✅ Numeric columns have plausible values (not garbage like 1e+253)
4. ✅ JSON matches expected format from task.yaml
5. ✅ Output file at correct path (typically `/app/recover.json`)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Script not found in container | Deploy via heredoc (Step 2 above) |
| No CREATE TABLE found | Schema itself corrupted; inspect hex at page 1 data area |
| Wrong values in output | Check serial type scoring; may need manual parse of specific cells |
| Missing rows | Check if records span overflow pages (follow 4-byte page pointers) |
| Page 1 also has data | Skip page 1's schema cell (it's sqlite_master, not user data) |

## Edge Cases

| Scenario | Approach |
|----------|----------|
| Interior b-tree pages | Follow child page pointers to reach leaf pages |
| Records spanning pages (overflow) | Follow overflow chain (4-byte page number at end of local payload) |
| Very large databases | Script is already O(pages × cells), no changes needed |
| Non-standard page sizes | Read from header byte 16–17; handle 512 to 65536 |
| Schema itself corrupted | Try `sqlite3 .recover` or inspect hex for SQL text fragments |

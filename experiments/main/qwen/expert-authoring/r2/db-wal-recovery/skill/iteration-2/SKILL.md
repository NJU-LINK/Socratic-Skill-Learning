---
name: db-wal-recovery
description: >
  Diagnose, decode, and recover data from a corrupted or obfuscated SQLite
  Write-Ahead Log (WAL) file paired with a base database. Covers single-byte
  XOR, base64, bitwise inversion, byte-swapping, damaged headers, partial
  frames, and full WAL reconstruction. Produces a complete JSON export of all
  recovered records.
---

# SQLite WAL Recovery

## Overview

A SQLite WAL-mode database consists of three files:
- `*.db` — the base database (always usable alone, shows pre-WAL state)
- `*.db-wal` — the write-ahead log (frames of updated pages)
- `*.db-shm` — shared-memory index (optional, can be regenerated)

The task: the WAL file is encoded or corrupted, so SQLite only sees the base
data. You must decode/repair the WAL, apply it, and export **all** records as
JSON.

---

## TWO CRITICAL RULES

### RULE 1: Operation ordering — read raw bytes before sqlite3

**Never open the database with `sqlite3.connect()` before reading and decoding
the WAL file.** Opening the DB causes SQLite to inspect the WAL, and if the
WAL is corrupted/encoded, SQLite may silently delete it or overwrite it.

Correct order:
1. Read raw DB header bytes (with `open()`, not `sqlite3`)
2. Read raw WAL bytes (with `open()`)
3. Decode/repair the WAL **in memory**
4. Write the decoded WAL back
5. Remove `-shm` file
6. **Only then** open with `sqlite3.connect()`

### RULE 2: Do NOT recompute checksums — the decoded WAL's checksums are valid

Byte-level encodings (XOR, base64, bitwise NOT, byte-swap) preserve every
byte of the WAL including its checksums. The decoded WAL is identical to the
original WAL that SQLite created — its checksums are correct by construction.

**Even if a verification script reports "checksum mismatch," this is almost
certainly because your verification code uses the wrong byte order, NOT
because the WAL's checksums are wrong.** The SQLite WAL checksum byte order
depends on the host architecture in subtle ways that are easy to get wrong.

**What to do instead:** Write the decoded WAL directly (preserving all original
bytes including checksums) and let SQLite validate it. If SQLite still rejects
the WAL, use the manual page-application fallback (Phase 4.3) which bypasses
checksum validation entirely.

---

## Phase 1 — Reconnaissance

### 1.1 Inventory the artifacts

```bash
ls -la /app/*.db /app/*.db-wal /app/*.db-shm 2>/dev/null
```

### 1.2 Save a backup immediately

```bash
cp /app/main.db-wal /app/main.db-wal.original
cp /app/main.db /app/main.db.backup
```

**This is non-negotiable.** If anything goes wrong during decoding or WAL
application, you need to be able to restore the original files.

### 1.3 Read the database header (raw bytes, NOT sqlite3)

```python
import struct
data = open('/app/main.db', 'rb').read()
# Database header: 2-byte page size at offset 16-17 (big-endian)
page_size = struct.unpack('>H', data[16:18])[0]
if page_size == 1:
    page_size = 65536
print(f"Page size: {page_size}")
```

**Note:** The **database** header uses **2 bytes** for page size (offset 16–17),
but the **WAL** header uses **4 bytes** at offset 8–11.

### 1.4 Read the WAL header (raw bytes)

The first 32 bytes of a valid WAL file:

| Offset | Size | Field                 |
|--------|------|-----------------------|
| 0      | 4    | Magic: `37 7f 06 82` (BE cksums) or `37 7f 06 83` (LE cksums) |
| 4      | 4    | Version (3007000)     |
| 8      | 4    | Page size             |
| 12     | 4    | Checkpoint sequence   |
| 16     | 4    | Salt-1                |
| 20     | 4    | Salt-2                |
| 24     | 8    | Header checksum       |

---

## Phase 2 — Diagnose the Encoding

### 2.1 Check for a valid WAL magic

```python
wal = open('/app/main.db-wal', 'rb').read()
magic = wal[:4]
VALID_MAGICS = [b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83']
if magic in VALID_MAGICS:
    print("WAL magic is valid — no encoding, just apply directly")
else:
    print(f"WAL magic is {magic.hex()} — encoding detected")
```

### 2.2 Common encodings to test

Apply each candidate transform to the first 32 bytes and check for valid magic:

| Encoding | Transform | Detection hint |
|----------|-----------|----------------|
| Single-byte XOR | `b ^ key` for key in 1..255 | Most frequent byte is likely the XOR key |
| Base64 | `base64.b64decode(wal)` | File is ASCII, chars in [A-Za-z0-9+/=] |
| Bitwise NOT | `b ^ 0xFF` | Magic becomes `C8 80 F9 7D` or `C8 80 F9 7C` |
| 2-byte swap | swap adjacent bytes | Bytes 0,1 and 2,3 are swapped pairs of magic |

**Quick XOR key finder:**

```python
from collections import Counter
freq = Counter(wal)
most_common_byte = freq.most_common(1)[0][0]
# The most common byte likely maps to 0x00 (zero padding in WAL pages)
key = most_common_byte

# Verify: decode first 32 bytes and check
decoded_hdr = bytes([b ^ key for b in wal[:32]])
print(f"Candidate key: 0x{key:02x}")
print(f"Decoded magic: {decoded_hdr[:4].hex()}")

# Brute-force if frequency heuristic fails
for k in range(256):
    d = bytes([b ^ k for b in wal[:4]])
    if d in VALID_MAGICS:
        print(f"XOR key: 0x{k:02x}")
```

### 2.3 Validate the decoded WAL structure

After decoding, verify:
1. Magic is valid
2. Version field is `3007000` (bytes 4–7, big-endian u32)
3. Page size matches the database header
4. File size = `32 + N*(24 + page_size)` for some integer N ≥ 1
5. Salt values in frame headers match the WAL header salt

```python
import struct

decoded = bytes([b ^ key for b in wal])
magic = decoded[:4]
version = struct.unpack('>I', decoded[4:8])[0]
wal_page_size = struct.unpack('>I', decoded[8:12])[0]
salt1 = struct.unpack('>I', decoded[16:20])[0]
salt2 = struct.unpack('>I', decoded[20:24])[0]

assert magic in VALID_MAGICS, f"Bad magic: {magic.hex()}"
assert version == 3007000, f"Bad version: {version}"
assert wal_page_size == db_page_size, f"Page size mismatch: {wal_page_size} vs {db_page_size}"

remainder = len(decoded) - 32
assert remainder > 0 and remainder % (24 + wal_page_size) == 0, "Bad file size"
n_frames = remainder // (24 + wal_page_size)
print(f"Valid WAL: {n_frames} frames, page size {wal_page_size}")

# Verify frame salts
offset = 32
for i in range(n_frames):
    fs1 = struct.unpack('>I', decoded[offset+8:offset+12])[0]
    fs2 = struct.unpack('>I', decoded[offset+12:offset+16])[0]
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    commit = struct.unpack('>I', decoded[offset+4:offset+8])[0]
    salt_ok = (fs1 == salt1 and fs2 == salt2)
    print(f"  Frame {i+1}: page={pgno}, commit={commit}, salt_match={salt_ok}")
    offset += 24 + wal_page_size
```

**If frame salts don't match:** This may indicate the WAL has frames from
different sessions. The simplest fix is to override all frame salts to match
the header salt before writing (see Phase 3.2).

---

## Phase 3 — Write the Decoded WAL

### 3.1 Write directly — do NOT modify checksums

```python
# Write the decoded WAL (preserving all original bytes including checksums)
open('/app/main.db-wal', 'wb').write(decoded)
```

**Do NOT recompute or modify checksums.** The decoded WAL's checksums are
already valid. Recomputing them risks introducing errors due to byte-order
confusion, which will cause SQLite to reject and delete the WAL.

### 3.2 Fix frame salts only if needed

If frames had salt mismatches (from Phase 2.3), fix the salt fields only:

```python
repaired = bytearray(decoded)
salt1_bytes = repaired[16:20]
salt2_bytes = repaired[20:24]
offset = 32
while offset + 24 + page_size <= len(repaired):
    repaired[offset+8:offset+12] = salt1_bytes
    repaired[offset+12:offset+16] = salt2_bytes
    offset += 24 + page_size
open('/app/main.db-wal', 'wb').write(repaired)
```

### 3.3 Remove stale shared-memory file and open

```bash
rm -f /app/main.db-shm
```

Then open with SQLite:

```python
import sqlite3
conn = sqlite3.connect('/app/main.db')
conn.row_factory = sqlite3.Row
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()
total = 0
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t['name']}").fetchone()[0]
    print(f"  {t['name']}: {count} rows")
    total += count
print(f"Total rows: {total}")
```

### 3.4 Checkpoint to merge WAL into database

```python
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.commit()
conn.close()
```

---

## Phase 4 — Fallbacks (if SQLite rejects the WAL)

### 4.1 Detect WAL rejection

If SQLite shows only the base record count (not the expected total), the WAL
was rejected. Common symptoms:
- SQLite deleted `main.db-wal` after opening
- Row count equals only the base DB records
- No error message (SQLite silently ignores invalid WALs)

### 4.2 Restore from backup and try again

```bash
cp /app/main.db-wal.original /app/main.db-wal
cp /app/main.db.backup /app/main.db
rm -f /app/main.db-shm
```

### 4.3 Manual page application (bypasses all checksum validation)

This is the **reliable fallback** when SQLite won't accept the WAL. It
directly overlays WAL page data onto the database file:

```python
import struct

# Read the decoded WAL from backup
decoded = bytes([b ^ key for b in open('/app/main.db-wal.original', 'rb').read()])
# Or if you already decoded it: decoded = <your decoded WAL bytes>

db = bytearray(open('/app/main.db.backup', 'rb').read())
page_size = struct.unpack('>H', db[16:18])[0]
if page_size == 1:
    page_size = 65536

# Parse and apply each frame
offset = 32
applied = 0
while offset + 24 + page_size <= len(decoded):
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    if pgno == 0:
        break
    page_data = decoded[offset+24:offset+24+page_size]
    # Page 1 starts at byte 0; page N starts at byte (N-1)*page_size
    start = (pgno - 1) * page_size
    if start + page_size <= len(db):
        db[start:start+page_size] = page_data
    applied += 1
    offset += 24 + page_size

print(f"Applied {applied} pages manually")

# Write the patched database
open('/app/main.db', 'wb').write(db)

# Remove WAL and SHM so SQLite opens the DB directly
import os
for suffix in ['-wal', '-shm', '-journal']:
    p = '/app/main.db' + suffix
    if os.path.exists(p):
        os.remove(p)
```

Then open the database:

```python
conn = sqlite3.connect('/app/main.db')
# Switch to DELETE journal mode to avoid WAL issues
conn.execute("PRAGMA journal_mode=DELETE")
conn.commit()
```

### 4.4 Full reconstruction (last resort)

If the database itself is also corrupted, extract pages from both the base
database and the WAL, pick the latest version of each page (WAL version wins
for frames with higher sequence), and assemble a new database file.

---

## Phase 5 — Extract and Export

### 5.1 Discover schema dynamically

```python
conn = sqlite3.connect('/app/main.db')
conn.row_factory = sqlite3.Row
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()
```

### 5.2 Export all tables as JSON

For each table, fetch all rows ordered by primary key:

```python
import json

results = []
for table_name in [t['name'] for t in tables]:
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    col_names = [c['name'] for c in cols]
    rows = conn.execute(
        f"SELECT * FROM {table_name} ORDER BY {col_names[0]}"
    ).fetchall()
    for row in rows:
        results.append(dict(row))

with open('/app/recovered.json', 'w') as f:
    json.dump(results, f, indent=2)

conn.close()
```

### 5.3 Verify output

```python
import json
with open('/app/recovered.json') as f:
    data = json.load(f)
print(f"Records: {len(data)}")
print(f"First: {data[0]}")
print(f"Last: {data[-1]}")
ids = [r['id'] for r in data]
assert ids == sorted(ids), "Not sorted by id"
assert len(ids) == len(set(ids)), "Duplicate ids"
print("All checks passed!")
```

---

## Decision Tree

```
Start
├── Backup all files (cp main.db-wal main.db-wal.original)
├── Read DB page size (raw bytes, NOT sqlite3)
├── Read WAL (raw bytes)
│
├── WAL magic valid?
│   ├── YES → Write WAL, remove -shm, open with sqlite3
│   │   ├── All expected rows → Export JSON ✓
│   │   └── Missing rows → WAL was invalid, go to fallback
│   └── NO → Diagnose encoding (XOR, base64, NOT, swap)
│       ├── Transform found → Decode full WAL in memory
│       └── None work → Check for multi-layer encoding
│
├── Validate decoded WAL structure
│   ├── Magic, version, page_size OK
│   ├── Frame count matches file size
│   └── Frame salts match header salt
│       └── If not → Override frame salts
│
├── Write decoded WAL (DO NOT recompute checksums!)
├── Remove -shm file
├── Open with sqlite3.connect()
│   ├── All expected rows → Export JSON ✓
│   └── Only base rows (WAL rejected) → Manual page application
│
└── Manual page application fallback
    ├── Parse frames from decoded WAL
    ├── Overlay each frame's page data onto DB
    ├── Remove WAL/SHM files
    ├── Open with sqlite3 → Export JSON ✓
    └── Still wrong count → Full reconstruction (rare)
```

---

## Self-Verification Checklist

Before declaring success, verify:

- [ ] Record count matches the expected total (not just base DB count)
- [ ] All primary keys are present and unique
- [ ] JSON is valid and parseable
- [ ] Records are sorted by the required column (usually `id`)
- [ ] Output file is at the expected path (`/app/recovered.json`)
- [ ] WAL-updated records have updated values (not base values)

---

## Common Pitfalls

1. **Opening the DB with sqlite3 before decoding the WAL** (CRITICAL):
   `sqlite3.connect('/app/main.db')` causes SQLite to inspect the WAL file.
   If the WAL is encoded, SQLite may silently delete it. Always read the WAL
   as raw bytes **first**, decode, write back, and **only then** use sqlite3.

2. **Recomputing checksums** (CRITICAL):
   The decoded WAL's checksums are already valid. Recomputing them risks
   corruption due to byte-order confusion. SQLite will delete a WAL with
   bad checksums, and the original data is lost permanently if no backup
   exists. **Never recompute checksums.** If checksums appear wrong, it's
   your verification code that's wrong, not the WAL.

3. **Not saving a backup**: Always `cp main.db-wal main.db-wal.original`
   before modifying anything. If SQLite rejects and deletes the WAL, you
   need the original to try again or use manual page application.

4. **Reading DB page size as 4 bytes**: The database header stores page size
   as a **2-byte** big-endian integer at offset 16–17. The WAL header stores
   it as a 4-byte integer at offset 8–11.

5. **Forgetting to delete the `-shm` file**: SQLite may use a stale shared
   memory index and ignore the repaired WAL.

6. **Applying XOR to the wrong file**: Only transform the WAL, not the
   base database.

7. **Assuming single-table output**: Always check `sqlite_master` for all
   tables unless the task explicitly names one.

8. **Off-by-one in manual page application**: SQLite page numbers are
   1-indexed; page 1 starts at byte 0 in the database file.

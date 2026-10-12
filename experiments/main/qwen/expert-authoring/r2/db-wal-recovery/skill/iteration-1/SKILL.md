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

### CRITICAL: Operation ordering

**Never open the database with `sqlite3.connect()` before reading and decoding
the WAL file.** Opening the DB causes SQLite to inspect the WAL, and if the
WAL is corrupted/encoded, SQLite may silently delete it or overwrite it. The
correct order is:

1. Read the raw DB header bytes (with `open()`, not `sqlite3`)
2. Read the raw WAL bytes (with `open()`)
3. Decode/repair the WAL
4. Write the decoded WAL back
5. **Only then** open the database with `sqlite3.connect()`

---

## Phase 1 — Reconnaissance

### 1.1 Inventory the artifacts

```bash
ls -la /app/*.db /app/*.db-wal /app/*.db-shm 2>/dev/null
```

Note file sizes. A valid WAL has size `32 + N*(24 + page_size)` where
`page_size` comes from the database header.

### 1.2 Read the database header (raw bytes, NOT sqlite3)

```python
import struct
data = open('/app/main.db', 'rb').read()
# Database header: 2-byte page size at offset 16-17 (big-endian)
page_size = struct.unpack('>H', data[16:18])[0]
if page_size == 1:
    page_size = 65536
print(f"Page size: {page_size}")
```

Note: The **database** header uses 2 bytes for page size, but the **WAL**
header uses 4 bytes at offset 8–11.

### 1.3 Read the WAL header (raw bytes)

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

Read the first 32 bytes of the WAL and compare to expected values.

---

## Phase 2 — Diagnose the Encoding

### 2.1 Check for a valid WAL magic

```python
wal = open('/app/main.db-wal', 'rb').read()
magic = wal[:4]
VALID_MAGICS = [b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83']
if magic in VALID_MAGICS:
    print("WAL magic is valid — may just need header repair")
else:
    print(f"WAL magic is {magic.hex()} — encoding detected")
```

### 2.2 Common encodings to test

Apply each candidate transform to the first 32 bytes and check if the result
starts with a valid magic:

| Encoding | Transform | Detection hint |
|----------|-----------|----------------|
| Single-byte XOR | `b ^ key` for key in 1..255 | Dominant byte value in file is likely `0x00` mapped to key |
| Base64 | `base64.b64decode(wal)` | File is ASCII, chars in [A-Za-z0-9+/=] |
| Bitwise NOT | `b ^ 0xFF` | Magic would appear as `C8 80 F9 7D` or `C8 80 F9 7C` |
| 2-byte swap | swap adjacent bytes | Bytes 0,1 and 2,3 are swapped pairs of the magic |
| 4-byte swap | reverse each 4-byte group | Magic bytes appear reversed within each word |

**Quick XOR key finder:**

```python
import struct

target = b'\x37\x7f\x06\x82'
for key in range(256):
    decoded = bytes([b ^ key for b in wal[:4]])
    if decoded[:4] in VALID_MAGICS:
        print(f"XOR key candidate: 0x{key:02x} ({key})")
        # Verify against all 4 magic bytes
        # Also check the second valid magic
```

**Frequency analysis for XOR key:**
If the WAL has large runs of what should be zero padding, the most frequent
byte in the file is likely the XOR key.

```python
from collections import Counter
freq = Counter(wal)
most_common_byte, count = freq.most_common(1)[0]
print(f"Most common byte: 0x{most_common_byte:02x} ({count}/{len(wal)})")
# This byte is likely the XOR key (since 0x00 XOR key = key)
```

### 2.3 Validate the decoded WAL

After decoding, verify:
1. Magic is `37 7f 06 82` or `37 7f 06 83`
2. Version field is `3007000` (bytes 4–7 as big-endian u32)
3. Page size matches the database header
4. File size = `32 + N*(24 + page_size)` for some integer N ≥ 1
5. Salt values in frame headers match the WAL header salt

```python
import struct

decoded = bytes([b ^ key for b in wal])  # or other transform
magic = decoded[:4]
version = struct.unpack('>I', decoded[4:8])[0]
wal_page_size = struct.unpack('>I', decoded[8:12])[0]
salt1 = struct.unpack('>I', decoded[16:20])[0]
salt2 = struct.unpack('>I', decoded[20:24])[0]

assert magic in VALID_MAGICS
assert version == 3007000
assert wal_page_size == db_page_size
expected_len = len(decoded) - 32
assert expected_len % (24 + wal_page_size) == 0
n_frames = expected_len // (24 + wal_page_size)
print(f"Valid WAL: {n_frames} frames, page size {wal_page_size}")
```

---

## Phase 3 — Decode and Repair

### 3.1 Apply the transformation to the full WAL

```python
decoded = bytes([b ^ key for b in wal])
open('/app/main.db-wal.decoded', 'wb').write(decoded)
```

### 3.2 Verify frame headers

Each frame has a 24-byte header followed by `page_size` bytes of page data:

| Offset | Size | Field          |
|--------|------|----------------|
| 0      | 4    | Page number (1-indexed, big-endian) |
| 4      | 4    | Commit size (0 = not last, N = truncate to N pages) |
| 8      | 4    | Salt-1 (must match WAL header) |
| 12     | 4    | Salt-2 (must match WAL header) |
| 16     | 8    | Cumulative checksum |

```python
offset = 32
for i in range(n_frames):
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    commit = struct.unpack('>I', decoded[offset+4:offset+8])[0]
    fs1 = struct.unpack('>I', decoded[offset+8:offset+12])[0]
    fs2 = struct.unpack('>I', decoded[offset+12:offset+16])[0]
    if fs1 != salt1 or fs2 != salt2:
        print(f"Frame {i+1}: SALT MISMATCH — frame may be corrupted")
    else:
        print(f"Frame {i+1}: page={pgno}, commit={commit}")
    offset += 24 + wal_page_size
```

### 3.3 Repair damaged fields if needed

If the magic/version/page-size are correct but salts or checksums are wrong,
the header fields may have been individually damaged. Strategies:

- **Salt mismatch**: The WAL header salt or frame header salts may have been
  selectively corrupted. If most frames agree on a salt, trust the majority.
- **Checksum mismatch**: Recompute checksums using the algorithm below and
  overwrite the stored values.

### 3.4 WAL checksum algorithm

The checksum uses two running 32-bit accumulators over 8-byte groups.
Byte order of word reads is determined by the magic number:
- Magic `377f0682` → big-endian word reads
- Magic `377f0683` → little-endian word reads

```python
def wal_checksum(data, s1=0, s2=0, big_endian=True):
    fmt = '>II' if big_endian else '<II'
    i = 0
    while i + 7 < len(data):
        x, y = struct.unpack(fmt, data[i:i+8])
        s1 = (s1 + x + s2) & 0xFFFFFFFF
        s2 = (s2 + y + s1) & 0xFFFFFFFF
        i += 8
    return s1, s2
```

Checksums are **cumulative**:
- Header checksum covers bytes 0–23 (first 24 bytes of WAL header)
- Frame 1 header checksum = wal_checksum(frame_header_8_bytes, *header_cksum)
- Frame 1 page checksum = wal_checksum(page_data, *frame1_header_cksum)
- Frame 2 header checksum continues from frame 1 page checksum, etc.

If checksums are damaged, recompute and overwrite:

```python
big_endian = (decoded[:4] == b'\x37\x7f\x06\x82')
# Recompute header checksum
s1, s2 = wal_checksum(decoded[:24], big_endian=big_endian)
header_cksum = struct.pack('>II' if big_endian else '<II', s1, s2)
repaired = bytearray(decoded)
repaired[24:32] = header_cksum
# Continue for each frame...
```

---

## Phase 4 — Apply the WAL

### 4.1 Direct SQLite consumption (preferred)

If the decoded WAL has valid structure, just replace the WAL file and let
SQLite handle it:

```bash
cp /app/main.db-wal.decoded /app/main.db-wal
rm -f /app/main.db-shm  # Force SQLite to rebuild the shared-memory index
```

Then open the database normally:

```python
conn = sqlite3.connect('/app/main.db')
rows = conn.execute("SELECT * FROM <table> ORDER BY id").fetchall()
```

**Important**: Delete the `-shm` file so SQLite rebuilds the WAL index from
the repaired WAL.

### 4.2 Checkpoint to merge WAL into database

To make the changes permanent (WAL data merged into .db):

```python
conn = sqlite3.connect('/app/main.db')
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.commit()
conn.close()
```

### 4.3 Manual page application (fallback)

If SQLite refuses the WAL (e.g., due to irreparable checksum damage or
incompatible salt values), manually overlay pages onto the database:

```python
db = bytearray(open('/app/main.db', 'rb').read())
offset = 32
for i in range(n_frames):
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    if pgno == 1:
        # Page 1 starts at offset 0 in the db file
        db[0:page_size] = page_data
    elif pgno > 1:
        start = (pgno - 1) * page_size
        db[start:start+page_size] = page_data
    offset += 24 + page_size
open('/app/main.db', 'wb').write(db)
```

Then open the database (possibly in DELETE journal mode to avoid WAL issues):

```python
conn = sqlite3.connect('/app/main.db')
conn.execute("PRAGMA journal_mode=DELETE")
```

### 4.4 Full reconstruction (last resort)

If the database itself is also corrupted, extract pages from both the base
database and the WAL, pick the latest version of each page (WAL version wins),
and assemble a new database file. You may also need to:
- Re-read the schema from page 1
- Walk B-tree pages manually using `sqlite3` internals or a hex parser
- Extract row data from leaf pages

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

### 5.2 Export all tables

For each table, fetch all rows ordered by primary key (or the task's required
sort column):

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
```

### 5.3 Adapt to task requirements

- If the task specifies a particular table or sort order, use that.
- If there are multiple tables, check whether the task wants all rows from
  all tables or just one.
- Verify the record count matches expectations before writing.

---

## Decision Tree

```
Start
├── WAL magic valid?
│   ├── YES → Try opening with SQLite directly
│   │   ├── All expected rows present → Export JSON (done)
│   │   └── Missing rows → Check for frame corruption, repair checksums
│   └── NO → Is file ASCII/Base64?
│       ├── YES → base64 decode → go to "WAL magic valid?"
│       └── NO → XOR key search (most-frequent-byte & brute-force 0–255)
│           ├── Key found → Decode → go to "WAL magic valid?"
│           └── No key → Try bitwise NOT, byte-swap, or other transforms
│               ├── Transform found → Decode → go to "WAL magic valid?"
│               └── None work → Check for partial WAL, header-only damage,
│                   or multi-layer encoding
├── Decoded WAL valid but SQLite refuses?
│   ├── Salt mismatch → Override frame salts to match header
│   ├── Checksum mismatch → Recompute and patch checksums
│   └── Page count mismatch → Manual page application
└── Nothing works?
    ├── Extract raw page data from WAL frames anyway
    ├── Apply pages manually to database file
    └── Parse B-tree leaf pages for row data
```

---

## Self-Verification Checklist

Before writing the final JSON, verify:

- [ ] Record count matches the expected total (not just the base DB count)
- [ ] All primary keys are present and unique
- [ ] No NULL values in non-nullable columns
- [ ] JSON is valid and parseable
- [ ] Records are sorted by the required column (usually `id`)
- [ ] Output file is at the expected path (`/app/recovered.json`)

After writing:

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
```

---

## Common Pitfalls

1. **Opening the DB with sqlite3 before decoding the WAL** (CRITICAL):
   `sqlite3.connect('/app/main.db')` causes SQLite to inspect the WAL file.
   If the WAL is corrupted/encoded, SQLite may silently delete it or replace
   it with an empty WAL. Always read the WAL as raw bytes **first**, decode
   it, write it back, and **only then** open the database with sqlite3.
2. **Forgetting to delete the `-shm` file**: SQLite may use a stale shared
   memory index and ignore the repaired WAL. Remove it before opening.
3. **Reading DB page size as 4 bytes**: The database header stores page size
   as a 2-byte big-endian integer at offset 16–17. The WAL header stores it
   as a 4-byte integer at offset 8–11. Confusing these leads to wrong page
   sizes.
4. **Applying XOR to the wrong file**: Only transform the WAL, not the base
   database.
5. **Page size mismatch after decoding**: The WAL's page size field must match
   the database's page size. If they differ after decoding, the transform is
   wrong or you read the page size incorrectly.
6. **Not checking frame salts**: Frames from a different WAL session have
   different salts and should be discarded or re-salted.
7. **Recomputing checksums with wrong byte order**: The WAL checksum byte
   order depends on the host machine and WAL magic. If recomputing checksums,
   verify against the original stored values. When in doubt, preserve the
   original checksums from the decoded WAL (they were valid before encoding).
8. **Assuming single-table output**: Always check `sqlite_master` for all
   tables unless the task explicitly names one.
9. **Off-by-one in manual page application**: SQLite page numbers are
   1-indexed; page 1 starts at byte 0 in the database file.

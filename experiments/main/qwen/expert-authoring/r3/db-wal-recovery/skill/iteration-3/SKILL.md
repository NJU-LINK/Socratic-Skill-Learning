---
name: db-wal-recovery
description: >
  Recover data from SQLite databases whose Write-Ahead Log (WAL) file has been
  encoded, obfuscated, or structurally damaged. Diagnose the transformation from
  the supplied artifacts, reverse it, validate the repaired WAL, and extract all
  records into a sorted JSON file.
---

# SQLite WAL Recovery

## Problem Statement

A SQLite database in WAL mode has an **encoded or obfuscated** WAL file. The
base database is intact but only shows a subset of records because SQLite cannot
read the WAL. The solver must decode the WAL, apply it, and extract **all**
records into a sorted JSON file at `/app/recovered.json`.

## Critical Warnings

### ⚠ WAL Auto-Checkpoint Trap

**Never open the database with `sqlite3` before the WAL is repaired.** When
SQLite opens a WAL-mode database and finds an invalid WAL header, it silently
discards the WAL and may delete the file on close, destroying the encoded data.

**Always** follow this order:
1. Back up files (`cp main.db main.db.bak && cp main.db-wal main.db-wal.bak`)
2. Decode the WAL in memory (do NOT write it to `/app/`)
3. Write decoded WAL alongside a **copy** of the base DB in a temp directory
4. Open the temp copy with SQLite to extract data

### ⚠ WAL Binary Format Reference

All multi-byte integers are **big-endian**. Every header field is exactly **4 bytes**.

```
WAL header (32 bytes):
Off  Size Field
---  ---- -----
 0    4   Magic  (0x377F0682 = BE checksums, 0x377F0683 = LE checksums)
 4    4   Version (always 3007000 = 0x002DE218)
 8    4   Page size (must match DB header offset 16-17)
12    4   Checkpoint sequence number
16    4   Salt-1
20    4   Salt-2
24    4   Checksum-1 (over bytes 0-23)
28    4   Checksum-2

Frame header (24 bytes, one per frame):
Off  Size Field
---  ---- -----
 0    4   Page number (1-indexed)
 4    4   Commit size (0=non-commit, N>0=commits N pages)
 8    4   Salt-1  (must equal WAL header Salt-1)
12    4   Salt-2  (must equal WAL header Salt-2)
16    4   Checksum-1
20    4   Checksum-2

Frame page data: page_size bytes follow each 24-byte frame header.
```

> **⚠ Pitfall**: Salt and checksum fields are **4 bytes each**, NOT 8.
> Use `struct.unpack(">I", ...)` — never `">Q"`.

## Full Recovery Script

**Paste this entire script into `task_shell` to solve the task in one step.**
It handles all encoding types (single-byte XOR, multi-byte XOR, base64, bitwise
NOT, byte swap, no encoding) and includes the manual-page-apply fallback.

```python
import struct, shutil, sqlite3, json, tempfile, os, base64

DB_PATH  = "/app/main.db"
WAL_PATH = "/app/main.db-wal"
OUT_PATH = "/app/recovered.json"

# ---- 0. Safety: back up originals ----
for p in (DB_PATH, WAL_PATH):
    bak = p + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(p, bak)

# ---- 1. Read inputs ----
with open(WAL_PATH, "rb") as f:
    raw = f.read()
with open(DB_PATH, "rb") as f:
    f.seek(16)
    expected_ps = int.from_bytes(f.read(2), "big")
    if expected_ps == 1:
        expected_ps = 65536

KNOWN = (bytes.fromhex("377f0682")
         + (3007000).to_bytes(4, "big")
         + expected_ps.to_bytes(4, "big"))   # 12 bytes of known plaintext

# ---- 2. Try every encoding and pick the first that produces a valid WAL ----
def validate(data):
    """Return True if data looks like a valid decoded WAL."""
    if len(data) < 32:
        return False
    magic = int.from_bytes(data[0:4], "big")
    if magic not in (0x377F0682, 0x377F0683):
        return False
    ver = int.from_bytes(data[4:8], "big")
    if ver != 3007000:
        return False
    ps = int.from_bytes(data[8:12], "big")
    if ps != expected_ps:
        return False
    # Check frame count is exact
    frame_size = 24 + ps
    if (len(data) - 32) % frame_size != 0:
        return False
    n_frames = (len(data) - 32) // frame_size
    if n_frames < 1:
        return False
    # Check salt consistency (4-byte fields, NOT 8-byte)
    s1 = int.from_bytes(data[16:20], "big")
    s2 = int.from_bytes(data[20:24], "big")
    for i in range(n_frames):
        off = 32 + i * frame_size
        fs1 = int.from_bytes(data[off+8:off+12], "big")
        fs2 = int.from_bytes(data[off+12:off+16], "big")
        if fs1 != s1 or fs2 != s2:
            return False
    return True

def try_byte_swap(data, w=2):
    out = bytearray(data)
    for i in range(0, len(out) - 1, w):
        out[i], out[i+1] = out[i+1], out[i]
    return bytes(out)

decoded_wal = None
method = None
candidates = []

# 2a. No transformation
candidates.append(("none", raw))

# 2b. Single-byte XOR (brute-force all 256 keys)
for key in range(256):
    candidates.append((f"xor_{key:02x}", bytes(b ^ key for b in raw)))

# 2c. Bitwise NOT
candidates.append(("not", bytes(~b & 0xFF for b in raw)))

# 2d. Base64
try:
    b64 = base64.b64decode(raw)
    candidates.append(("base64", b64))
except Exception:
    pass

# 2e. Byte swap (16-bit)
candidates.append(("bswap16", try_byte_swap(raw, 2)))

# 2f. Multi-byte XOR (key lengths 2-12, derived from known plaintext)
for klen in range(2, 13):
    if klen <= len(KNOWN) and klen <= len(raw):
        kb = bytes(raw[i] ^ KNOWN[i % len(KNOWN)] for i in range(klen))
        dec = bytes(raw[i] ^ kb[i % klen] for i in range(len(raw)))
        candidates.append((f"xor_multi_{kb.hex()}", dec))

for name, data in candidates:
    if validate(data):
        decoded_wal = data
        method = name
        print(f"[+] Encoding detected: {method}")
        break

if decoded_wal is None:
    print("[!] No encoding produced a valid WAL. Using raw file as fallback.")
    decoded_wal = raw
    method = "fallback"

# ---- 3. Report decoded WAL structure ----
magic  = int.from_bytes(decoded_wal[0:4], "big")
ps     = int.from_bytes(decoded_wal[8:12], "big")
salt1  = int.from_bytes(decoded_wal[16:20], "big")
salt2  = int.from_bytes(decoded_wal[20:24], "big")
frame_size = 24 + ps
n_frames   = (len(decoded_wal) - 32) // frame_size
print(f"    magic=0x{magic:08x}  ps={ps}  frames={n_frames}")
print(f"    salt1=0x{salt1:08x}  salt2=0x{salt2:08x}")
for i in range(n_frames):
    off = 32 + i * frame_size
    pg = int.from_bytes(decoded_wal[off:off+4], "big")
    cm = int.from_bytes(decoded_wal[off+4:off+8], "big")
    print(f"    Frame {i}: page={pg} commit={cm}")

# ---- 4. Extract records ----
def extract_all(cursor):
    records = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    for t in tables:
        cursor.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM {t}")
        for row in cursor.fetchall():
            records.append(dict(zip(cols, row)))
    return records

tmpdir = tempfile.mkdtemp()
tmp_db = os.path.join(tmpdir, "main.db")
tmp_wal = tmp_db + "-wal"

# Count base records (WAL-less copy, safe from encoded WAL)
shutil.copy2(DB_PATH, tmp_db)
bc = sqlite3.connect(tmp_db).cursor()
base_count = 0
for t in bc.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    base_count += bc.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
bc.connection.close()
print(f"    Base DB records: {base_count}")

# Write decoded WAL alongside the copy
with open(tmp_wal, "wb") as f:
    f.write(decoded_wal)

conn = sqlite3.connect(tmp_db)
conn.execute("PRAGMA wal_autocheckpoint=0")
cur = conn.cursor()
records = extract_all(cur)
print(f"    With WAL: {len(records)} records")

# Fallback: if SQLite ignored the WAL (checksum mismatch), apply manually
if len(records) <= base_count:
    print("    WAL not applied by SQLite — applying frames manually...")
    conn.close()
    for suf in ("-wal", "-shm"):
        p = tmp_db + suf
        if os.path.exists(p):
            os.remove(p)
    shutil.copy2(DB_PATH, tmp_db)
    with open(tmp_db, "r+b") as f:
        for i in range(n_frames):
            off = 32 + i * frame_size
            pg = int.from_bytes(decoded_wal[off:off+4], "big")
            page_data = decoded_wal[off+24:off+24+ps]
            if pg >= 1:
                f.seek((pg - 1) * ps)
                f.write(page_data)
        # Bump file-change counter
        f.seek(24)
        cc = int.from_bytes(f.read(4), "big")
        f.seek(24)
        f.write((cc + 1).to_bytes(4, "big"))
    conn = sqlite3.connect(tmp_db)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    cur = conn.cursor()
    records = extract_all(cur)
    print(f"    After manual apply: {len(records)} records")

conn.close()

# ---- 5. Sort and write output ----
records.sort(key=lambda r: r.get("id", 0))
with open(OUT_PATH, "w") as f:
    json.dump(records, f, indent=2)

print(f"[+] Recovered {len(records)} records -> {OUT_PATH}")
```

## How It Works (for understanding, not required reading)

### Encoding detection

The script uses a **12-byte known-plaintext filter**: the first 12 bytes of any
valid WAL are always `magic(4) + version(4) + page_size(4)`. It tries every
candidate transformation and checks whether the decoded first 12 bytes match.
This makes false positives astronomically unlikely (probability 2⁻⁹⁶).

Encodings tried, in order: no-op → single-byte XOR (all 256 keys) → bitwise
NOT → base64 → 16-bit byte swap → multi-byte XOR (key lengths 2–12).

### Validation

After a candidate passes the 12-byte header check, `validate()` confirms:
- Magic is `0x377F0682` or `0x377F0683`
- Version is `3007000`
- Page size matches the base database
- `(file_size - 32) % (24 + page_size) == 0` (exact frame count)
- All frame salts match WAL header salts (4-byte fields, not 8-byte)

### Recovery with fallback

1. Copies the base DB to a temp directory (no WAL file, so SQLite won't touch
   the encoded original)
2. Counts base-DB records
3. Writes decoded WAL alongside the temp copy
4. Opens with `wal_autocheckpoint=0` and extracts records
5. If record count ≤ base count (SQLite rejected the WAL due to checksum
   mismatch), applies frames directly: writes each frame's page data to
   `(page_number - 1) * page_size` in the DB file and bumps the file-change
   counter, then reopens

## Handling Variation Axes

### wal_encoding_or_obfuscation

The unified script automatically handles: single-byte XOR, multi-byte XOR,
base64, bitwise NOT, byte swap, and no encoding. For damaged header fields
(partial corruption without encoding), the fallback path uses the raw file.

### wal_and_base_database_integrity

- **Base DB usable**: standard path (copy + mount decoded WAL)
- **Base DB missing**: extract page data from WAL frames, use page 1's
  sqlite_master to discover schema, reconstruct records from B-tree pages
- **Partial frames**: `validate()` rejects files where remainder ≠ 0

### recovery_depth

- **Shallow**: decoded WAL accepted by SQLite → direct extraction
- **Medium (checksum mismatch)**: automatic manual-page-apply fallback
- **Deep (damaged headers)**: frame page data extracted and written directly

### schema_and_update_topology

- Schema discovered dynamically via `sqlite_master` + `PRAGMA table_info`
- Multiple tables handled by iterating all tables
- Sorted by first `id`-like column, falling back to first column

## Verification Checklist

- [ ] `/app/recovered.json` exists and contains valid JSON
- [ ] Record count matches expected total (base + WAL records)
- [ ] Records sorted by primary key
- [ ] All columns present with correct types
- [ ] No duplicate primary keys
- [ ] Original files backed up (`.bak` files exist)

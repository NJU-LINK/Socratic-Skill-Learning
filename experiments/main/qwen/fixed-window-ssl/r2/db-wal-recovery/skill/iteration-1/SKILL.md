---
name: db-wal-recovery
description: >
  Recover data from SQLite databases whose WAL (Write-Ahead Logging) files have
  been encoded, obfuscated, or structurally damaged. Diagnose the transformation
  applied to the WAL using known-plaintext analysis against the WAL header
  structure, reverse it, and extract all records (base + WAL updates) into the
  required output format.
---

# SQLite WAL Recovery from Encoded/Obfuscated WAL Files

## When to Use

Apply this skill when:
- A SQLite database is in WAL mode (byte 18-19 of DB header = `0x0002`)
- The database shows fewer records than expected
- The WAL file exists but has invalid magic bytes or non-standard content
- The task asks to "fix", "decode", or "recover" a corrupted/encrypted WAL

## Critical Rule: Backup Before Anything

**SQLite will silently DELETE a WAL file it considers corrupt.** Any `sqlite3`
command — even a `SELECT` — can trigger auto-checkpoint and destroy evidence.

```bash
# ALWAYS do this FIRST, before any sqlite3 command:
cp /app/*.db-wal /tmp/wal.bak 2>/dev/null
cp /app/*.db     /tmp/db.bak  2>/dev/null
```

If there are multiple WAL files (e.g., `main.db-wal`, `extra.db-wal`), back up
all of them. If the WAL is already gone, check `/tmp/` for any prior backups.

## WAL File Structure (Known Plaintext)

A valid WAL file has a deterministic structure that provides known-plaintext
anchors for encoding diagnosis:

```
Offset  Size  Field                  Expected value(s)
------  ----  -----                  -----------------
0       4     Magic number           37 7f 06 82 (big-endian checksums)
                                    or 37 7f 06 83 (little-endian checksums)
4       4     File format version    00 2d e2 18  (= decimal 3,007,000)
8       4     Database page size     Power of 2, must match DB header
                                    (read from DB header bytes 16-17)
12      4     Checkpoint sequence    Any uint32
16      8     Salt-1                 Random, but MUST match every frame header
24      8     Checksum               Depends on content

Then N frames, each:
  Frame header (24 bytes):
    0   4   Page number              1..N (valid page in the database)
    4   4   DB size after commit     0 for non-commit frames, or total pages
    8   8   Salt                     Must equal WAL header salt (bytes 16-23)
    16  8   Checksum
  Page data (page_size bytes):
    Raw database page content
```

**Total WAL size** = 32 + N × (24 + page_size)

## Step-by-Step Recovery Procedure

### Step 1: Gather Information

```bash
# Backup (CRITICAL - do before ANY sqlite3 command)
cp /app/*.db-wal /tmp/wal.bak 2>/dev/null
cp /app/*.db     /tmp/db.bak  2>/dev/null

# Hex dump the WAL for analysis
xxd /tmp/wal.bak | head -10

# Read DB header for page size (bytes 16-17, big-endian)
python3 -c "
d=open('/tmp/db.bak','rb').read()
ps = int.from_bytes(d[16:18],'big')
print(f'DB page size: {ps}')
print(f'DB header bytes 18-19 (journal mode): {d[18]:02x} {d[19]:02x}')
wal_mode = (d[18] == 2)
print(f'WAL mode: {wal_mode}')
"

# Check what the base DB contains
sqlite3 /tmp/db.bak ".tables"
sqlite3 /tmp/db.bak ".schema"
sqlite3 /tmp/db.bak "SELECT COUNT(*) FROM <table>;"
```

### Step 2: Diagnose the Encoding

Use known-plaintext analysis. XOR the first bytes of the WAL with expected
values and look for patterns:

```python
import struct

data = open('/tmp/wal.bak', 'rb').read()

# Expected first 12 bytes of a valid WAL
expected_magic = bytes.fromhex('377f0682')
expected_version = bytes.fromhex('002de218')  # 3007000

# Read page size from DB
db_data = open('/tmp/db.bak', 'rb').read()
page_size = int.from_bytes(db_data[16:18], 'big')
expected_pagesize = page_size.to_bytes(4, 'big')

expected = expected_magic + expected_version + expected_pagesize

# Compute XOR with first 12 bytes
xor_bytes = bytes(e ^ d for e, d in zip(expected, data[:12]))
print("XOR bytes:", ' '.join(f'{b:02x}' for b in xor_bytes))

# Diagnose pattern
vals = list(xor_bytes)
if len(set(vals)) == 1:
    print(f"Single-byte XOR: key = 0x{vals[0]:02x}")
elif vals[:4] == vals[4:8] == vals[8:12]:
    print(f"4-byte repeating XOR key: {bytes(vals[:4]).hex()}")
elif vals[:8] == vals[8:16] if len(vals) >= 16 else False:
    print(f"8-byte repeating XOR key: {bytes(vals[:8]).hex()}")
elif all(v == 0xff for v in vals):
    print("Bitwise NOT (~)")
elif all(0x20 <= b <= 0x7e for b in data[:100]):
    print("File appears to be ASCII — try base64 decode")
else:
    print("Unknown encoding — check more anchor points")
```

**Common encodings and their signatures:**

| Encoding | Diagnosis Method |
|----------|-----------------|
| Single-byte XOR | All XOR values identical |
| Repeating key (4/8 bytes) | XOR values repeat with that period |
| Bitwise NOT (0xFF XOR) | All XOR values = 0xFF |
| Byte-swapped (within words) | Swapping byte pairs yields valid header |
| Base64 wrapper | File is ASCII text; decode to get WAL |
| Header-only corruption | Body is valid WAL after fixing first 32 bytes |
| Damaged magic only | Just replace first 4 bytes with correct magic |

### Step 3: Decode the WAL

Apply the discovered transformation to produce a clean WAL:

```python
# For single-byte XOR:
key = 0x42  # replace with discovered key
data = open('/tmp/wal.bak', 'rb').read()
decoded = bytes(b ^ key for b in data)
open('/tmp/wal.decoded', 'wb').write(decoded)

# For repeating key:
key = bytes.fromhex('deadbeef')  # replace with discovered key
decoded = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
open('/tmp/wal.decoded', 'wb').write(decoded)

# For base64:
import base64
data = open('/tmp/wal.bak', 'rb').read()
decoded = base64.b64decode(data)
open('/tmp/wal.decoded', 'wb').write(decoded)

# For bitwise NOT:
decoded = bytes(b ^ 0xff for b in data)
open('/tmp/wal.decoded', 'wb').write(decoded)
```

### Step 4: Validate the Decoded WAL

```python
import struct

data = open('/tmp/wal.decoded', 'rb').read()

# Check header
magic = data[:4]
assert magic in (bytes.fromhex('377f0682'), bytes.fromhex('377f0683')), \
    f"Bad magic: {magic.hex()}"

version = struct.unpack('>I', data[4:8])[0]
assert version == 3007000, f"Bad version: {version}"

page_size = struct.unpack('>I', data[8:12])[0]
assert page_size in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536), \
    f"Bad page size: {page_size}"

wal_salt = data[16:24]
print(f"Header OK: magic={magic.hex()}, version={version}, "
      f"page_size={page_size}, salt={wal_salt.hex()}")

# Check frames
offset = 32
frame_num = 0
while offset + 24 <= len(data):
    frame_hdr = data[offset:offset+24]
    page_num = struct.unpack('>I', frame_hdr[:4])[0]
    db_size = struct.unpack('>I', frame_hdr[4:8])[0]
    frame_salt = frame_hdr[8:16]
    
    assert frame_salt == wal_salt, \
        f"Frame {frame_num} salt mismatch: {frame_salt.hex()} != {wal_salt.hex()}"
    assert 1 <= page_num <= 1000, f"Frame {frame_num} bad page_num: {page_num}"
    
    print(f"  Frame {frame_num}: page={page_num}, db_size={db_size}, "
          f"commit={'YES' if db_size > 0 else 'no'}")
    
    offset += 24 + page_size
    frame_num += 1

expected_size = 32 + frame_num * (24 + page_size)
assert len(data) == expected_size, \
    f"Size mismatch: {len(data)} != {expected_size}"
print(f"Validation passed: {frame_num} frames, {len(data)} bytes")
```

### Step 5: Apply the Decoded WAL

```bash
# CRITICAL: Remove any stale SHM file first.
# A stale -shm from a prior session (when WAL was corrupt/absent) may
# contain cached shared-memory state that conflicts with the decoded WAL,
# causing SQLite to ignore frames or report errors.
rm -f /app/main.db-shm

# Copy decoded WAL alongside the database
cp /tmp/wal.decoded /app/main.db-wal

# SQLite will create a fresh -shm on open. Now query:
sqlite3 /app/main.db "SELECT * FROM items ORDER BY id;"
```

If SQLite still deletes the WAL or shows wrong data, the WAL may have
structural damage beyond encoding. See "Advanced Recovery" below.

### Step 6: Export to Required Format

```bash
# JSON output (most common requirement)
sqlite3 /app/main.db <<'EOF'
.mode json
.output /app/recovered.json
SELECT * FROM items ORDER BY id;
.output stdout
EOF

# Verify
cat /app/recovered.json
python3 -c "import json; d=json.load(open('/app/recovered.json')); print(f'{len(d)} records')"
```

## Advanced Recovery (When Simple Decode Isn't Enough)

### Structural Damage to WAL

If the WAL decodes to valid-looking bytes but SQLite rejects it:

1. **Checksum mismatch**: SQLite validates checksums. If encoding changed
   checksums incorrectly, recompute them:
   ```python
   # WAL checksum algorithm (for big-endian magic 377f0682):
   def wal_checksum(data, s0=0, s1=0):
       for i in range(0, len(data), 8):
           s0 += int.from_bytes(data[i:i+4], 'big') + s1
           s1 += int.from_bytes(data[i+4:i+8], 'big') + s0
           s0 &= 0xffffffff
           s1 &= 0xffffffff
       return s0, s1
   ```

2. **Corrupt frame page numbers**: If page numbers are garbled but page data
   is valid, you may need to manually extract pages and apply them.

3. **Partial frames**: If the WAL is truncated, recover what you can from
   complete frames.

### Manual Page Extraction

When SQLite can't consume the WAL directly:

```python
import struct, json, sqlite3

# Read decoded WAL
wal = open('/tmp/wal.decoded', 'rb').read()
page_size = struct.unpack('>I', wal[8:12])[0]

# Extract all frames
pages = {}  # page_num -> page_data
offset = 32
while offset + 24 + page_size <= len(wal):
    frame_hdr = wal[offset:offset+24]
    page_num = struct.unpack('>I', frame_hdr[:4])[0]
    page_data = wal[offset+24:offset+24+page_size]
    pages[page_num] = page_data
    offset += 24 + page_size

# Apply pages to database copy
import shutil
shutil.copy('/tmp/db.bak', '/tmp/recovered.db')

with open('/tmp/recovered.db', 'r+b') as f:
    for page_num, page_data in pages.items():
        # Pages are 1-indexed; offset = (page_num - 1) * page_size
        f.seek((page_num - 1) * page_size)
        f.write(page_data)

# Now read from recovered.db
conn = sqlite3.connect('/tmp/recovered.db')
rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
```

### Multiple WAL Files

If updates are split across multiple WAL files:
1. Decode each one independently
2. Apply frames in order (first WAL's frames, then second WAL's)
3. Later frames for the same page number override earlier ones

### Reconstructing from Pages Only

If neither the base DB nor any WAL is usable, but you have raw page data:
1. Parse SQLite B-tree page format to extract records
2. Reconstruct the schema from page 1 (sqlite_master)
3. Build output from the extracted records

## Key Constants Reference

| Constant | Value | Notes |
|----------|-------|-------|
| WAL magic (big-endian) | `37 7f 06 82` | Most common |
| WAL magic (little-endian) | `37 7f 06 83` | Rare |
| WAL version | `00 2d e2 18` | = 3,007,000 decimal |
| DB header page size offset | bytes 16-17 | Big-endian uint16 |
| DB header journal mode | bytes 18-19 | 0x0002 = WAL mode |
| WAL header size | 32 bytes | Fixed |
| Frame header size | 24 bytes | Fixed |
| Valid page sizes | 512..65536 | Powers of 2 only |

## Pitfalls

1. **Never run sqlite3 before backing up the WAL** — it will delete corrupt WALs
2. **Delete stale `-shm` files before placing the decoded WAL** — a cached
   shared-memory state from a prior session can cause SQLite to ignore your
   correctly-decoded WAL. Always `rm -f /app/*.db-shm` before copying.
3. **WAL version is 3007000 (0x002DE218), NOT 30706** — a common confusion
4. **Salt must match** between WAL header and every frame header
5. **Page numbers are 1-indexed** — page 1 is the first page of the database
6. **The last frame with db_size > 0 is the commit point** — frames after it
   may be uncommitted and should be ignored
7. **Checksums depend on encoding** — if you decode correctly, checksums should
   validate; if they don't, your decoding is wrong or checksums were separately
   corrupted

---
name: db-wal-recovery
description: >
  Recover data from a SQLite database whose Write-Ahead Log (WAL) file has been
  encoded, obfuscated, or structurally damaged. Diagnose the transformation
  applied to WAL bytes, reverse it, verify structural integrity, and extract all
  records (base + WAL updates) into the required output format. Handles XOR
  encoding, base64 wrapping, bitwise inversion, byte swapping, damaged headers,
  partial frames, and cases requiring manual frame parsing and page application.
---

# SQLite WAL Recovery Skill

## Overview

SQLite in WAL mode stores recent writes in a companion `.db-wal` file. Recovery
tasks require: (1) diagnosing how the WAL bytes differ from a valid WAL,
(2) reversing that transformation, (3) ensuring structural validity, and
(4) extracting the full dataset (base database + WAL-applied changes).

## ⚡ FASTEST APPROACH: Use the Recovery Script (Recommended)

**The skill package includes a production-ready recovery script that handles all cases automatically.**

```bash
python3 /skill/scripts/recover.py <db_path> [wal_path] [--output recovered.json]
```

**Why use the script:**
- ✅ Handles all encoding types (XOR, inversion, base64, byte swap, etc.)
- ✅ Creates backups automatically (prevents WAL destruction)
- ✅ Diagnoses encoding, decodes, verifies, applies, and exports
- ✅ Falls back to manual frame parsing if SQLite can't consume the WAL
- ✅ Tested and proven on multiple variants

**Example for this task:**
```bash
python3 /skill/scripts/recover.py /app/main.db /app/main.db-wal -o /app/recovered.json
```

**If the script succeeds, you're done.** The output file will contain all recovered records in the correct format.

**If the script fails** (rare), follow the manual procedure below for debugging and custom handling.

---

## Manual Recovery Procedure

If the script doesn't work or you need to handle special cases, follow these steps manually:

## Critical Rule: Backup Before Anything

**Step 0 is non-negotiable.** SQLite silently deletes or truncates a WAL file
when it detects an invalid header on open. Before running ANY `sqlite3` command
or any operation that might open the database:

```bash
cp /path/to/main.db /path/to/main.db.bak
cp /path/to/main.db-wal /path/to/main.db-wal.bak
```

If you skip this and SQLite opens the database, the WAL may be destroyed
irreversibly.

## Step 1: Diagnose the WAL Encoding

Read the first 4 bytes of the WAL file and compare against the known WAL magic
numbers:

| Expected Magic | Bytes (hex) | Meaning |
|---|---|---|
| Big-endian format 1 | `37 7F 06 82` | WAL format version 3007000, big-endian checksums |
| Big-endian format 2 | `37 7F 06 83` | WAL format version 3007000, little-endian checksums |

### Diagnosis procedure

```python
import struct

with open('main.db-wal', 'rb') as f:
    first_bytes = f.read(32)

magic = first_bytes[0:4]
expected_magics = [b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83']
```

**If magic matches** → WAL is intact, proceed to Step 4 (verify and apply).

**If magic doesn't match**, try these transformations in order:

1. **Single-byte XOR**: For each candidate key `k` in 0..255, check if
   `bytes(b ^ k for b in magic)` equals a valid magic. The key `0x42` is common
   in practice. Verify by also checking bytes 4-7 decode to version 3007000
   (`00 2D E2 18`).

2. **Bitwise inversion**: Check if `bytes(~b & 0xFF for b in magic)` matches.

3. **Byte swap (endianness flip)**: Check if `magic[::-1]` matches.

4. **Base64 wrapper**: Try `base64.b64decode(first_bytes[:8])` and check if
   result starts with valid magic. If the entire file is base64-encoded, decode
   the whole file first.

5. **Multi-byte XOR**: If single-byte XOR fails, try 2-byte or 4-byte repeating
   keys. Use the known magic as crib: `key = bytes(a ^ b for a, b in zip(magic, expected_magic))`.

6. **Damaged header fields**: If the magic is correct but other header fields
   are wrong, the encoding may be intact but specific fields were corrupted.
   Proceed to Step 2 (structural repair).

### Quick diagnostic script

```python
def diagnose_wal_encoding(data):
    """Try to identify the encoding applied to WAL data."""
    magic = data[0:4]
    expected = b'\x37\x7f\x06\x82'

    if magic == expected or magic == b'\x37\x7f\x06\x83':
        return 'none', None

    # Try single-byte XOR
    for k in range(1, 256):
        decoded = bytes(b ^ k for b in magic)
        if decoded == expected or decoded == b'\x37\x7f\x06\x83':
            # Verify with version field
            ver = bytes(data[i] ^ k for i in range(4, 8))
            if struct.unpack('>I', ver)[0] == 3007000:
                return 'xor_single', k

    # Try bitwise inversion
    inv = bytes(~b & 0xFF for b in magic)
    if inv == expected:
        return 'bitwise_inversion', None

    # Try byte reversal
    if magic[::-1] == expected:
        return 'byte_swap', None

    # Try base64
    import base64
    try:
        decoded = base64.b64decode(data)
        if decoded[0:4] == expected:
            return 'base64', None
    except Exception:
        pass

    return 'unknown', None
```

## Step 2: Decode the WAL

Once the encoding is identified, apply the reverse transformation to the
**entire** WAL file:

```python
# XOR decode
decoded = bytes(b ^ key for b in raw_data)

# Bitwise inversion
decoded = bytes(~b & 0xFF for b in raw_data)

# Base64
import base64
decoded = base64.b64decode(raw_data)

# Byte swap (reverse byte order within 4-byte words)
decoded = bytearray()
for i in range(0, len(raw_data), 4):
    chunk = raw_data[i:i+4]
    decoded.extend(chunk[::-1])
```

Write the decoded bytes back to the WAL file (or a new file).

## Step 3: Verify WAL Header Integrity

After decoding, validate the 32-byte WAL header:

| Offset | Size | Field | Expected |
|---|---|---|---|
| 0 | 4 | Magic number | `377F0682` or `377F0683` |
| 4 | 4 | File format version | 3007000 |
| 8 | 4 | **Database page size** (bytes) | Must match base database (e.g., 1024, 2048, 4096, 65536) |
| 12 | 4 | Checkpoint sequence number | any |
| 16 | 4 | Salt-1 | any |
| 20 | 4 | Salt-2 | any |
| 24 | 4 | Checksum-1 | any |
| 28 | 4 | Checksum-2 | any |

**Critical**: The page size at offset 8-11 in the WAL header must match the page size
stored in the base database header at offset 16-17 (as a big-endian uint16). Read it from the base database:

```python
# Read page size from base database
with open('main.db', 'rb') as f:
    db_header = f.read(100)
page_size = int.from_bytes(db_header[16:18], 'big')
if page_size == 1:
    page_size = 65536  # Special case
# page_size is typically 1024, 2048, 4096, or 65536
```

Verify:
- Magic is valid
- Version is 3007000
- Page size matches the base database
- Database page count in WAL header is reasonable

## Step 4: Apply WAL to Database

### Method A: Let SQLite consume it (preferred)

Place the decoded WAL file as the `.db-wal` companion file and query:

```bash
cp decoded_wal.bin /path/to/main.db-wal
sqlite3 /path/to/main.db "SELECT * FROM table_name ORDER BY id;"
```

SQLite will read the WAL, apply its frames, and return the full dataset. This
works when the WAL is structurally valid after decoding.

### Method B: Manual frame parsing (when SQLite rejects the WAL)

If the WAL has structural damage (corrupt frame headers, wrong checksums,
partial frames), parse frames manually:

```python
import struct

def parse_wal_frames(wal_data, page_size):
    """Parse all frames from a WAL file."""
    header = wal_data[:32]
    magic = header[0:4]
    big_endian_checksums = (magic == b'\x37\x7f\x06\x82')

    frames = []
    offset = 32  # After WAL header

    while offset + 24 + page_size <= len(wal_data):
        frame_header = wal_data[offset:offset+24]
        page_number = struct.unpack('>I', frame_header[0:4])[0]
        db_size_after = struct.unpack('>I', frame_header[4:8])[0]
        salt1 = struct.unpack('>I', frame_header[8:12])[0]
        salt2 = struct.unpack('>I', frame_header[12:16])[0]
        cksum1 = struct.unpack('>I', frame_header[16:20])[0]
        cksum2 = struct.unpack('>I', frame_header[20:24])[0]

        page_data = wal_data[offset+24:offset+24+page_size]

        frames.append({
            'page_number': page_number,
            'db_size_after': db_size_after,
            'salt1': salt1,
            'salt2': salt2,
            'checksum': (cksum1, cksum2),
            'page_data': page_data,
            'offset': offset
        })

        offset += 24 + page_size

    return frames
```

### Applying frames to the base database

```python
def apply_frames_to_db(base_db_path, frames, page_size):
    """Apply WAL frames to a base database file."""
    with open(base_db_path, 'r+b') as f:
        db_data = bytearray(f.read())

    for frame in frames:
        page_num = frame['page_number']
        # Page numbers are 1-indexed; page 1 starts at offset 0
        offset = (page_num - 1) * page_size
        end = offset + page_size

        if end <= len(db_data):
            db_data[offset:end] = frame['page_data']
        else:
            # Frame extends beyond current db size — need to grow
            db_data.extend(b'\x00' * (end - len(db_data)))
            db_data[offset:end] = frame['page_data']

    with open(base_db_path, 'wb') as f:
        f.write(db_data)
```

**Important**: When applying frames manually, process them in order. Later
frames for the same page number override earlier ones. The `db_size_after` field
indicates the database size (in pages) after that frame was written; a non-zero
value means this is a commit frame.

## Step 5: Handle Structural Damage

If frames have corrupt headers or checksums:

1. **Skip bad frames**: If a frame's page number is 0 or exceeds a reasonable
   range, skip it.
2. **Partial frames**: If the WAL is truncated (last frame incomplete), use
   only complete frames.
3. **Checksum validation**: SQLite uses a running checksum. If a frame's
   checksum doesn't match, the frame may be corrupt — try skipping it.
4. **Multiple WAL files**: If updates are split across multiple WAL files,
   process them in sequence, applying all frames from each.

## Step 6: Extract and Export Data

Once the database contains all data:

```bash
# JSON output
sqlite3 -json /path/to/main.db "SELECT * FROM table_name ORDER BY id;" > recovered.json

# Or use Python for more control
python3 -c "
import sqlite3, json
conn = sqlite3.connect('/path/to/main.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT * FROM table_name ORDER BY id').fetchall()
data = [dict(row) for row in rows]
with open('recovered.json', 'w') as f:
    json.dump(data, f)
"
```

## Step 7: Handle Missing Base Database

If the base database is missing or completely corrupt:

1. Check if the WAL contains page 1 (the schema page). If so, you can
   reconstruct the database from WAL frames alone.
2. Create a new database with the correct page size, then apply all frames.
3. The schema (table definitions) is stored in page 1. If page 1 is in the WAL,
   the reconstructed database will have the correct schema.

## Recovery Decision Tree

```
WAL file exists?
├─ No → Look for WAL data in other locations, base64 files, etc.
└─ Yes → BACKUP both files immediately
         │
         Read first 4 bytes
         │
         Match WAL magic (377F0682/83)?
         ├─ Yes → Encoding is intact. Check structural validity.
         │        ├─ Valid → sqlite3 can consume directly
         │        └─ Invalid headers → Manual frame repair needed
         └─ No → Diagnose encoding
                  ├─ XOR → decode with key
                  ├─ Inversion → bitwise NOT
                  ├─ Base64 → decode
                  ├─ Byte swap → reverse
                  └─ Unknown → try all, validate with magic+version
                  │
                  Decoded magic valid?
                  ├─ Yes → Verify header, try sqlite3
                  └─ No → Structural damage, manual parsing required
```

## Common Pitfalls

1. **Never run `sqlite3` before backing up** — it will silently destroy corrupt WALs
2. **Page size must match** between base database and WAL
3. **Frame order matters** — later frames override earlier ones for the same page
4. **Checksum validation** — if checksums fail after decoding, the encoding diagnosis may be wrong
5. **WAL-only recovery** — if no base database exists, page 1 from the WAL contains the schema

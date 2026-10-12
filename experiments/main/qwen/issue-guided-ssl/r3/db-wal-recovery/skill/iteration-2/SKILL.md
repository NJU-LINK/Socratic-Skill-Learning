---
name: db-wal-recovery
description: >
  Recover data from corrupted, encoded, or obfuscated SQLite WAL (Write-Ahead Logging) files.
  Handles XOR encoding, byte inversion, base64 wrapping, byte swapping, and damaged headers.
  Implements the critical "copy → diagnose → decode → open" workflow that prevents SQLite
  from destroying encoded WAL files during automatic checkpointing.
---

# SQLite WAL Recovery Skill

## Critical Invariant: Copy → Diagnose → Decode → Open

**NEVER open the database with SQLite before decoding the WAL file.**

SQLite treats WAL files as transient journaling artifacts. The moment you open a `.db` file
with a WAL present, SQLite may perform an automatic passive checkpoint, which reads the WAL
frames. If the frames are encoded/corrupted, SQLite will see garbage checksums, skip the frames,
and then truncate or delete the WAL file as part of normal checkpoint cleanup. This destroys
the very data you need to recover.

### Mandatory Workflow Order

1. **COPY** — Immediately copy both `main.db` and `main.db-wal` to backup files
2. **DIAGNOSE** — Read the first bytes of the WAL file and determine the encoding/obfuscation
3. **DECODE** — Reverse the encoding to produce a valid WAL file
4. **OPEN** — Only now open the database with SQLite; it will read the decoded WAL frames correctly
5. **EXTRACT** — Query all data and produce the required output

## Step 1: Preserve Originals

```bash
cp main.db main.db.bak
cp main.db-wal main.db-wal.bak
```

This ensures you always have the original encoded data to work with, even if SQLite
destroys the working copy during a checkpoint.

## Step 2: Diagnose the Encoding

### WAL Header Structure (32 bytes)

A valid SQLite WAL header has this structure (all big-endian):
- Bytes 0-3: Magic number `0x377f0682` (big-endian checksums) or `0x377f0683` (little-endian checksums)
- Bytes 4-7: Format version, must be `3007000` (0x002DE218)
- Bytes 8-11: Database page size (e.g., 4096 = 0x00001000)
- Bytes 12-15: Checkpoint sequence number
- Bytes 16-23: Salt-1 (8 bytes, random)
- Bytes 24-27: Checksum-1
- Bytes 28-31: Checksum-2

### Diagnosis Methods

**XOR Encoding Detection:**
```python
WAL_MAGIC = bytes.fromhex('377f0682')
with open('main.db-wal', 'rb') as f:
    header = f.read(32)

# Try single-byte XOR
for key in range(256):
    decoded = bytes([b ^ key for b in header[:4]])
    if decoded == WAL_MAGIC:
        # Verify version field
        version_bytes = bytes([header[i] ^ key for i in range(4, 8)])
        version = struct.unpack('>I', version_bytes)[0]
        if version == 3007000:
            print(f"XOR key found: 0x{key:02x}")
            break
```

**Bitwise Inversion Detection:**
Check if `~header[:4]` (bitwise NOT) equals the WAL magic.

**Base64 Detection:**
Check if the file starts with base64-encoded data. Try decoding and check if the result starts with the WAL magic.

**Byte Swapping Detection:**
Check if swapping byte pairs or reversing byte order produces valid magic.

**Damaged Header Detection:**
If the first 4 bytes don't match any known encoding but the rest of the file has structure,
the header may be selectively corrupted. Try to repair just the header fields.

## Step 3: Decode the WAL

After identifying the encoding, decode the entire WAL file:

```python
# For XOR encoding:
decoded_wal = bytearray(b ^ key for b in original_wal_data)

# For base64:
import base64
decoded_wal = base64.b64decode(encoded_data)

# For bitwise inversion:
decoded_wal = bytearray(~b & 0xFF for b in original_wal_data)
```

### Verify Decoded Structure

After decoding, verify:
1. Magic number is `0x377f0682` or `0x377f0683`
2. Version is `3007000`
3. Page size matches the base database page size
4. Frame count is reasonable: `(wal_size - 32) / (24 + page_size)`

### Frame Structure (24-byte header + page data)

Each WAL frame has:
- Bytes 0-3: Page number (1-indexed; page 1 is the first database page)
- Bytes 4-7: Database size after this transaction (0 for non-commit frames)
- Bytes 8-11: Salt-1 (must match WAL header salt-1)
- Bytes 12-15: Salt-2 (must match WAL header salt-2)
- Bytes 16-19: Checksum-1
- Bytes 20-23: Checksum-2
- Followed by `page_size` bytes of page data

## Step 4: Open Database with Decoded WAL

```python
import os
import sqlite3

# Remove stale shared memory file
shm_path = db_path + '-shm'
if os.path.exists(shm_path):
    os.remove(shm_path)

# Write decoded WAL
with open(wal_path, 'wb') as f:
    f.write(decoded_wal)

# Now open the database - SQLite will read the WAL frames
conn = sqlite3.connect(db_path)
```

## Step 5: Extract Data

```python
# Get all tables
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()

all_rows = []
for (table_name,) in tables:
    cols = [desc[0] for desc in conn.execute(
        f"SELECT * FROM {table_name} LIMIT 1"
    ).description]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    for row in rows:
        all_rows.append(dict(zip(cols, row)))

conn.close()
```

## Handling Edge Cases

### No Base Database
If only the WAL file exists (no .db), you must reconstruct the database from WAL frames:
1. Decode the WAL
2. Parse frames to extract page data
3. Reconstruct database pages in order
4. Create a new database file from the pages

### Partial Frames
If some frames are corrupted but others are valid:
1. Decode the WAL
2. Validate each frame's salt values against the header
3. Skip invalid frames, apply valid ones
4. Reconstruct what's recoverable

### Multiple WAL Files
If updates are split across multiple WAL files:
1. Decode each WAL file
2. Apply frames in order (by checkpoint sequence and frame position)
3. Later frames overwrite earlier ones for the same page number

### Distinguishing Encoding Damage from Structural Damage
- **Encoding damage**: The entire file is transformed uniformly (XOR, inversion, base64)
- **Structural damage**: Specific fields are corrupted (wrong page numbers, bad checksums)
- Always diagnose encoding first, then check structure

## Frame Checksum Validation

After decoding the WAL, validate frame checksums to ensure data integrity:

```python
def wal_checksum(data, s1=0, s2=0, big_endian=True):
    """Compute WAL checksum. Try both byte orders if unsure."""
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        x0 = struct.unpack(fmt, data[i:i+4])[0]
        x1 = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + x0 + s2) & 0xFFFFFFFF
        s2 = (s2 + s1 + x1) & 0xFFFFFFFF
    return s1, s2

# Validate header checksum (try both byte orders)
header_data = decoded_wal[0:24]
for big_endian in [True, False]:
    s1, s2 = wal_checksum(header_data, big_endian=big_endian)
    if s1 == stored_cksum1 and s2 == stored_cksum2:
        print(f"Checksum byte order: {'big' if big_endian else 'little'}-endian")
        break
```

## Manual Frame Application (Fallback)

If SQLite cannot consume the decoded WAL directly (e.g., due to structural issues), manually apply frames to database pages:

```python
import shutil

# Create a working copy of the database
shutil.copy2(db_path, db_path + '.working')

# Parse WAL frames
frame_size = 24 + page_size
frame_count = (len(decoded_wal) - 32) // frame_size

# Read database into pages
db_pages = {}
with open(db_path + '.working', 'rb') as f:
    db_data = f.read()
    # Page 0 is the header page (100 bytes header + rest is page data)
    db_pages[1] = bytearray(db_data[0:page_size])
    for page_num in range(2, len(db_data) // page_size + 1):
        offset = (page_num - 1) * page_size
        db_pages[page_num] = bytearray(db_data[offset:offset+page_size])

# Apply WAL frames in order
for i in range(frame_count):
    offset = 32 + i * frame_size
    frame_hdr = decoded_wal[offset:offset+24]
    page_data = decoded_wal[offset+24:offset+24+page_size]
    
    page_num = struct.unpack('>I', frame_hdr[0:4])[0]
    
    # Validate frame checksum (cumulative)
    if i == 0:
        prev_s1, prev_s2 = hdr_cksum1, hdr_cksum2
    else:
        prev_offset = 32 + (i-1) * frame_size
        prev_hdr = decoded_wal[prev_offset:prev_offset+24]
        prev_s1 = struct.unpack('>I', prev_hdr[16:20])[0]
        prev_s2 = struct.unpack('>I', prev_hdr[20:24])[0]
    
    check_data = frame_hdr[0:8] + page_data
    calc_s1, calc_s2 = wal_checksum(check_data, prev_s1, prev_s2, use_big_endian)
    
    stored_s1 = struct.unpack('>I', frame_hdr[16:20])[0]
    stored_s2 = struct.unpack('>I', frame_hdr[20:24])[0]
    
    if calc_s1 == stored_s1 and calc_s2 == stored_s2:
        # Valid frame - apply it
        db_pages[page_num] = bytearray(page_data)
        print(f"Applied frame {i}: page {page_num}")
    else:
        print(f"Skipped frame {i}: invalid checksum")

# Write reconstructed database
with open(db_path + '.working', 'wb') as f:
    max_page = max(db_pages.keys())
    for page_num in range(1, max_page + 1):
        if page_num in db_pages:
            f.write(db_pages[page_num])
        else:
            f.write(b'\x00' * page_size)

# Now open the reconstructed database
conn = sqlite3.connect(db_path + '.working')
```

## Recovery Script Template

See `scripts/recover_wal.py` for a complete implementation that handles XOR-encoded WAL files with frame checksum validation and manual frame application fallback.

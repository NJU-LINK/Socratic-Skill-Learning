---
name: db-wal-recovery
description: >
  Recover data from SQLite databases with corrupted, encoded, or obfuscated
  Write-Ahead Log (WAL) files. Diagnose the WAL encoding transformation,
  reverse it, apply the repaired WAL to the database, and extract all records
  as structured output (JSON).
---

# SQLite WAL Recovery Skill

## Overview

This skill addresses recovery of data from SQLite databases where the WAL file
has been encoded, obfuscated, or partially corrupted. The core workflow is:

1. **Preserve** original artifacts (backup before any processing)
2. **Locate** the database and WAL files
3. **Diagnose** the WAL encoding/transformation
4. **Decode** the WAL to a valid format
5. **Apply** the decoded WAL to the database
6. **Extract** all records and produce output

## SQLite WAL Format Reference

### WAL Header (32 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | Magic | `0x377f0682` (big-endian) or `0x377f0683` (little-endian) |
| 4 | 4 | Format Version | Always `3007000` (`0x002DE218`) |
| 8 | 4 | Page Size | Database page size in bytes (512–65536, power of 2) |
| 12 | 4 | Checkpoint Seq | Checkpoint sequence number |
| 16 | 4 | Salt-1 | Random salt, must match frame salts |
| 20 | 4 | Salt-2 | Random salt, must match frame salts |
| 24 | 4 | Checksum-1 | Running checksum over header + all frames |
| 28 | 4 | Checksum-2 | Running checksum over header + all frames |

### Frame Header (24 bytes per frame)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | Page Number | 1-indexed page number this frame updates |
| 4 | 4 | Size After Commit | Database size in pages after this tx (0 = non-commit frame) |
| 8 | 4 | Salt-1 | Must match WAL header salt-1 |
| 12 | 4 | Salt-2 | Must match WAL header salt-2 |
| 16 | 4 | Checksum-1 | Running checksum |
| 20 | 4 | Checksum-2 | Running checksum |

Each frame is followed by page data of `page_size` bytes.

### WAL Checksum Algorithm

**CRITICAL**: The checksum computation byte order is the **opposite** of the magic number byte order:
- Magic `0x377f0682` (big-endian) → checksum computation uses **little-endian** word reads
- Magic `0x377f0683` (little-endian) → checksum computation uses **big-endian** word reads

The stored checksums themselves are in the byte order indicated by the magic number.

```python
def wal_checksum(data, seed1=0, seed2=0, magic=None):
    """Compute WAL checksum. Magic determines computation byte order."""
    if magic == b'\x37\x7f\x06\x82':
        word_order = 'little'  # Big-endian magic uses little-endian computation
    elif magic == b'\x37\x7f\x06\x83':
        word_order = 'big'     # Little-endian magic uses big-endian computation
    else:
        word_order = 'little'  # Default to little-endian
    
    s1, s2 = seed1, seed2
    for i in range(0, len(data) & ~7, 8):
        x = int.from_bytes(data[i:i+4], word_order)
        y = int.from_bytes(data[i+4:i+8], word_order)
        s1 = (s1 + x + s2) & 0xFFFFFFFF
        s2 = (s2 + y + s1) & 0xFFFFFFFF
    return s1, s2
```

- Header checksum: computed over first 24 bytes of header with seeds (0, 0)
- Frame checksums: running checksum, each frame continues from the previous
- Frame checksum data: first 8 bytes of frame header (page_num + db_size) + page data
- Stored checksums are in the byte order indicated by the magic number
- Computation uses the **opposite** byte order from the magic

## Step 0: Preserve Original Artifacts (CRITICAL)

**Before any diagnostic or decode operation, backup all files.** This prevents accidental data loss from consumer tools (sqlite3, hex dumpers, etc.) and allows retry if decoding fails.

```python
import shutil, os, glob

# Find database first
db_files = [f for f in glob.glob('/app/*.db') 
            if not f.endswith(('-wal', '-shm'))]
db_path = None
for f in db_files:
    with open(f, 'rb') as fh:
        if fh.read(16).startswith(b'SQLite format 3'):
            db_path = f
            break

# Backup all artifacts
backup_dir = '/tmp/wal_recovery_backup'
os.makedirs(backup_dir, exist_ok=True)
for suffix in ['', '-wal', '-shm']:
    src = db_path + suffix
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(backup_dir, os.path.basename(src)))

# Also backup any standalone .wal files
for f in glob.glob('/app/*.wal'):
    shutil.copy2(f, os.path.join(backup_dir, os.path.basename(f)))
```

**Principle**: In any data-recovery task, your first action is always to duplicate the evidence. Never let a consumer tool touch the only copy.

## Step 1: Locate Files

Find the SQLite database and its WAL file:

```python
import glob, os

# Find .db files (excluding -wal and -shm)
db_files = [f for f in glob.glob('/app/*.db') 
            if not f.endswith(('-wal', '-shm'))]

# Verify SQLite format
for f in db_files:
    with open(f, 'rb') as fh:
        if fh.read(16).startswith(b'SQLite format 3'):
            db_path = f
            break

# WAL file is typically <db_path>-wal
wal_path = db_path + '-wal'
```

Also check for standalone `.wal` files or alternative naming patterns.

## Step 2: Diagnose WAL Encoding

Read the first 4 bytes of the WAL file. If they match `0x377f0682` or `0x377f0683`, the WAL is intact. Otherwise, diagnose the transformation:

### Single-byte XOR

The most common obfuscation. Try all 255 non-zero keys:

```python
def detect_xor_key(data):
    """Find XOR key by checking if decoded bytes produce valid WAL magic."""
    for key in range(1, 256):
        decoded_magic = bytes(b ^ key for b in data[:4])
        if decoded_magic in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
            # Verify: check page size and format version
            full_header = bytes(b ^ key for b in data[:32])
            page_size = int.from_bytes(full_header[8:12], 'big')
            version = int.from_bytes(full_header[4:8], 'big')
            if (version == 3007000 and 
                512 <= page_size <= 65536 and 
                (page_size & (page_size - 1)) == 0):
                return key
    return None
```

**Key diagnostic**: XOR with the correct key produces valid magic AND valid format version AND valid page size simultaneously. This triple check eliminates false positives.

### Base64 Wrapping

Check if the file content is valid base64 that decodes to a valid WAL:

```python
import base64
try:
    decoded = base64.b64decode(data.strip())
    if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
        encoding = "base64"
except Exception:
    pass
```

### Bitwise Inversion (NOT)

```python
decoded = bytes(~b & 0xFF for b in data)
if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
    encoding = "bitwise_inversion"
```

### Byte Swapping

```python
decoded = bytearray(len(data))
for i in range(0, len(data), 2):
    decoded[i] = data[i+1]
    decoded[i+1] = data[i]
if bytes(decoded[:4]) in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
    encoding = "byte_swap"
```

### Combination Encodings

Some cases may combine transformations (e.g., base64 + XOR). Try decoding in sequence:
1. Base64 decode → check for XOR → XOR decode
2. XOR decode → check for base64 → base64 decode

### Damaged Header Fields

If the WAL has the right magic but invalid format version or page size:
- Format version should be `3007000`
- Page size should be a power of 2 between 512 and 65536
- Repair by overwriting with correct values and recomputing the header checksum

## Step 3: Decode the WAL

Apply the reverse transformation to the entire WAL file:

```python
# XOR decode
decoded = bytes(b ^ key for b in wal_data)

# Write decoded WAL back to the expected location
open(wal_path, 'wb').write(decoded)
```

### Verify Integrity After Decoding

```python
def verify_wal(wal_data):
    """Verify WAL header and frame checksums."""
    magic = wal_data[:4]
    stored_order = 'big' if magic == b'\x37\x7f\x06\x82' else 'little'
    
    # Header checksum
    calc_cs1, calc_cs2 = wal_checksum(wal_data[:24], magic=magic)
    stored_cs1 = int.from_bytes(wal_data[24:28], stored_order)
    stored_cs2 = int.from_bytes(wal_data[28:32], stored_order)
    assert calc_cs1 == stored_cs1 and calc_cs2 == stored_cs2
    
    # Frame checksums (running)
    page_size = int.from_bytes(wal_data[8:12], 'big')
    frame_size = 24 + page_size
    salt1 = int.from_bytes(wal_data[16:20], 'big')
    salt2 = int.from_bytes(wal_data[20:24], 'big')
    
    offset = 32
    running_cs1, running_cs2 = calc_cs1, calc_cs2
    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset+24]
        pd = wal_data[offset+24:offset+frame_size]
        assert int.from_bytes(fh[8:12], 'big') == salt1
        assert int.from_bytes(fh[12:16], 'big') == salt2
        cs_data = fh[:8] + pd
        running_cs1, running_cs2 = wal_checksum(cs_data, running_cs1, running_cs2, magic=magic)
        assert running_cs1 == int.from_bytes(fh[16:20], stored_order)
        assert running_cs2 == int.from_bytes(fh[20:24], stored_order)
        offset += frame_size
```

## Step 4: Apply WAL to Database

### Method A: Let SQLite Handle It (Preferred)

Write the decoded WAL to `<database>-wal` and open the database:

```python
import sqlite3

# Write decoded WAL
open(db_path + '-wal', 'wb').write(decoded_wal)

# Open database - SQLite automatically reads the WAL
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA wal_autocheckpoint=0")  # Prevent auto-checkpoint

# Query all data
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()

for (table_name,) in tables:
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
```

**Important**: Set `wal_autocheckpoint=0` to prevent SQLite from checkpointing (which would delete the WAL).

### Method B: Manual Frame Application

If SQLite cannot consume the WAL directly (e.g., checksum issues, partial frames):

```python
def apply_frames_manually(db_path, wal_data):
    page_size = int.from_bytes(wal_data[8:12], 'big')
    frame_size = 24 + page_size
    
    # Read existing database
    db_data = bytearray(open(db_path, 'rb').read())
    
    offset = 32  # Skip WAL header
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], 'big')
        page_data = wal_data[offset+24:offset+frame_size]
        
        # Extend database if needed
        needed = page_num * page_size
        if needed > len(db_data):
            db_data.extend(b'\x00' * (needed - len(db_data)))
        
        # Write page
        page_offset = (page_num - 1) * page_size
        db_data[page_offset:page_offset+page_size] = page_data
        
        offset += frame_size
    
    open(db_path, 'wb').write(bytes(db_data))
    
    # Remove WAL artifacts so SQLite reads from repaired database
    for suffix in ['-wal', '-shm']:
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)
```

### Method C: Reconstruct from Frames

When the base database is missing or severely corrupted:

1. Parse all WAL frames
2. Identify the latest version of each page (last frame for each page number)
3. Assemble pages into a complete database
4. Ensure page 1 has a valid database header
5. Write the reconstructed database

```python
def reconstruct_from_frames(wal_data):
    page_size = int.from_bytes(wal_data[8:12], 'big')
    frame_size = 24 + page_size
    
    # Collect latest version of each page
    pages = {}
    offset = 32
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], 'big')
        page_data = wal_data[offset+24:offset+frame_size]
        pages[page_num] = page_data  # Later frames overwrite earlier
        offset += frame_size
    
    if not pages:
        return None
    
    # Determine database size
    max_page = max(pages.keys())
    db_data = bytearray(max_page * page_size)
    
    for page_num, page_data in pages.items():
        offset = (page_num - 1) * page_size
        db_data[offset:offset+page_size] = page_data
    
    return bytes(db_data)
```

## Step 5: Extract and Output Data

### Determine Output Schema

```python
# Get table names and columns
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()

for (table_name,) in tables:
    columns = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    col_names = [col[1] for col in columns]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
```

### Format as JSON

```python
import json

# Build records as list of dicts
records = []
for row in rows:
    record = dict(zip(col_names, row))
    records.append(record)

# Sort by primary key or 'id' column
sort_key = 'id' if 'id' in col_names else col_names[0]
records.sort(key=lambda x: x[sort_key])

# Write output
with open('/app/recovered.json', 'w') as f:
    json.dump(records, f, indent=2)
```

## Handling Edge Cases

### Multiple Tables

When the database has multiple related tables, extract all tables and preserve relationships:

```python
all_data = {}
for (table_name,) in tables:
    columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table_name})")]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    all_data[table_name] = [dict(zip(columns, row)) for row in rows]
```

### Partial Frames

If some frames are corrupted but others are valid:
1. Verify each frame's checksum independently
2. Apply only valid frames
3. For invalid frames, try to repair (e.g., fix salt values to match header)

### Multiple WAL Files

If updates are split across multiple WAL files:
1. Decode each WAL file independently
2. Apply frames in order (by checkpoint sequence, then frame order)
3. Later frames overwrite earlier ones for the same page

### Distinguishing Encoding Damage from Structural Damage

- **Encoding damage**: The entire file is transformed uniformly (XOR, base64, etc.). After reversing the transformation, the WAL should be fully valid with correct checksums.
- **Structural damage**: Individual frames or header fields are corrupted. The WAL may have correct magic but invalid checksums, wrong page numbers, or missing frames.

Diagnosis approach:
1. Try decoding transformations first
2. If decoded WAL has valid checksums → it was encoding damage
3. If decoded WAL has invalid checksums → structural damage (needs frame-level repair)

## Complete Recovery Pipeline

```python
#!/usr/bin/env python3
import sqlite3, json, os, struct, base64, shutil, glob

# 0. Find database and backup artifacts
db_path = find_database('/app')
backup_dir = '/tmp/wal_recovery_backup'
os.makedirs(backup_dir, exist_ok=True)
for suffix in ['', '-wal', '-shm']:
    src = db_path + suffix
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(backup_dir, os.path.basename(src)))

wal_path = db_path + '-wal'

# 1. Read and diagnose WAL
wal_data = open(wal_path, 'rb').read()
decoded_wal, encoding = diagnose_encoding(wal_data)

# 2. Verify and optionally repair
if not verify_wal_integrity(decoded_wal):
    decoded_wal = repair_wal_header(decoded_wal)

# 3. Apply WAL
open(wal_path, 'wb').write(decoded_wal)
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA wal_autocheckpoint=0")

# 4. Extract and output
data = extract_all_data(conn)
write_json(data, '/app/recovered.json')
conn.close()
```

## Key Invariants

Regardless of the specific variant:
- The WAL magic number (after decoding) is always `0x377f0682` or `0x377f0683`
- The format version (after decoding) is always `3007000`
- The page size (after decoding) matches the base database's page size
- Frame salt values match the WAL header salt values
- Checksums use the running checksum algorithm with byte order **opposite** to the magic:
  - Magic `0x377f0682` (big-endian) → computation uses little-endian word reads
  - Magic `0x377f0683` (little-endian) → computation uses big-endian word reads
- Stored checksums are in the byte order indicated by the magic number
- The base database header always starts with `SQLite format 3\0`

## Variation Points

Per the spec, these dimensions vary across the family:

1. **Encoding**: XOR key varies; may be base64, inversion, byte swap, or combinations
2. **Integrity**: Base DB may be missing, frames may be partial, multiple WALs possible
3. **Recovery depth**: From simple WAL decode + SQLite read, to manual frame parsing, to full reconstruction
4. **Schema**: Single or multiple tables, varying column types and key structures

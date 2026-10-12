---
name: db-wal-recovery
description: Diagnose and recover data from corrupted, encoded, or damaged SQLite WAL (Write-Ahead Logging) files by detecting the encoding transformation, decoding the WAL, and extracting all records to JSON.
---

# SQLite WAL Recovery Skill

## Overview

This skill handles recovery of data from SQLite databases where the WAL file has been encoded, obfuscated, or corrupted. The recovery process involves diagnosing the transformation applied to the WAL, reversing it, and extracting the complete dataset.

## Core Methodology

### 1. Initial Assessment (CRITICAL ORDERING)

**NEVER open the database with sqlite3 before fixing the WAL.** Opening a database with an invalid WAL causes SQLite to delete or truncate the WAL file, making recovery impossible.

**Correct order:**
1. Examine the WAL file with hex dump tools (xxd, hexdump)
2. Diagnose the encoding/transformation
3. Decode the WAL
4. Write the decoded WAL back to disk
5. Remove any stale `-shm` files
6. THEN open the database with sqlite3

### 2. WAL Structure Knowledge

A valid SQLite WAL file has this structure:

**WAL Header (32 bytes):**
- Offset 0-3: Magic number `0x377f0682` (big-endian) or `0x377f0683` for native checksum byte order
- Offset 4-7: Version `3007000` (0x002DE218)
- Offset 8-11: Page size (must match database, typically 4096)
- Offset 12-15: Checkpoint sequence number
- Offset 16-19: Salt-1 (random)
- Offset 20-23: Salt-2 (random)
- Offset 24-27: Checksum-1 (over header bytes 0-23)
- Offset 28-31: Checksum-2 (continuation)

**Each Frame (24-byte header + page_size bytes):**
- Offset 0-3: Page number (1-indexed)
- Offset 4-7: Database size after commit (non-zero only on commit frame)
- Offset 8-11: Salt-1 (must match WAL header)
- Offset 12-15: Salt-2 (must match WAL header)
- Offset 16-19: Checksum-1
- Offset 20-23: Checksum-2
- Offset 24+: Page data (page_size bytes)

Total WAL size = 32 + (number_of_frames × (24 + page_size))

### 3. Encoding Detection

**Diagnostic Principle:** Compare the observed first 4 bytes against the known WAL magic `0x377f0682`. The difference pattern reveals the encoding.

**Detection algorithm:**
1. Read first 4 bytes of WAL file
2. If bytes equal `0x377f0682` → no encoding, WAL is valid
3. Try single-byte XOR: for each candidate key 0-255, XOR the first 4 bytes and check if result equals magic
4. If uniform XOR key found → entire file is XOR-encoded with that key
5. If no XOR key works, check if file is text (base64) → decode first, then re-check magic
6. Try bitwise NOT (XOR with 0xFF)
7. Try byte swapping patterns

**Common encodings:**
- Single-byte XOR (e.g., key 0x42)
- Bitwise inversion (XOR 0xFF)
- Base64 wrapper
- Byte swapping
- Damaged header fields only

### 4. Recovery Process

**Step 1: Diagnose encoding**
```python
import struct

with open('database.db-wal', 'rb') as f:
    raw = f.read()

expected_magic = bytes([0x37, 0x7f, 0x06, 0x82])
observed = raw[:4]

# Try XOR
for key in range(256):
    decoded = bytes([b ^ key for b in observed])
    if decoded == expected_magic:
        print(f"XOR key found: 0x{key:02x}")
        # Decode entire file
        wal_data = bytes([b ^ key for b in raw])
        break
```

**Step 2: Validate decoded WAL**
```python
magic = struct.unpack('>I', wal_data[0:4])[0]
version = struct.unpack('>I', wal_data[4:8])[0]
page_size = struct.unpack('>I', wal_data[8:12])[0]

assert magic in [0x377f0682, 0x377f0683], "Invalid WAL magic"
assert version == 3007000, "Invalid WAL version"
assert page_size in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536], "Invalid page size"
```

**Step 3: Write decoded WAL and clean up**
```python
import os

# Remove stale SHM file
shm_path = 'database.db-shm'
if os.path.exists(shm_path):
    os.remove(shm_path)

# Write decoded WAL
with open('database.db-wal', 'wb') as f:
    f.write(wal_data)
```

**Step 4: Open database and extract data**
```python
import sqlite3
import json

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]

# Extract all records
results = []
for table in tables:
    cursor.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cursor.description]
    for row in cursor.fetchall():
        results.append(dict(zip(cols, row)))

# Sort by primary key or id if present
results.sort(key=lambda r: r.get('id', 0))

# Write to JSON
with open('recovered.json', 'w') as f:
    json.dump(results, f, indent=2)

conn.close()
```

### 5. WAL Checksum Repair

SQLite uses a custom checksum algorithm (not CRC-32 or Adler-32). Each WAL header and frame has checksums that must be valid.

**When checksums need repair:**
- Header fields were manually modified (magic, version, page_size)
- Frames were reconstructed from partial data
- Checksums were corrupted independently of page data

**The checksum algorithm:**
```python
def wal_checksum(data, s0=0, s1=0):
    """Cumulative checksum over 8-byte chunks."""
    if len(data) % 8:
        data += b'\x00' * (8 - len(data) % 8)
    for i in range(0, len(data), 8):
        w0 = struct.unpack('>I', data[i:i+4])[0]
        w1 = struct.unpack('>I', data[i+4:i+8])[0]
        s0 = (s0 + w0 + s1) & 0xFFFFFFFF
        s1 = (s1 + w1 + s0) & 0xFFFFFFFF
    return s0, s1
```

**Checksum coverage:**
- Header checksum: covers bytes 0-23 of the 32-byte header
- Frame checksums: each frame's checksum covers bytes 0-7 (page_num + db_size) plus page_data, chained from previous checksum

**Recovery script handles this automatically:**
- If SQLite rejects the WAL due to checksum errors, the script recomputes all checksums and retries
- This is essential for cases with damaged headers or reconstructed frames

### 6. Advanced Recovery Scenarios

**Scenario A: Damaged header only**
If only the WAL header is corrupted but frames are intact:
- Reconstruct the 32-byte header with correct magic, version, page_size
- Extract salt values from the first frame header
- Recompute checksums

**Scenario B: Partial frames**
If some frames are missing or corrupted:
- Parse frame headers to identify valid frames
- Apply only valid frames to the database
- May need to manually reconstruct missing pages

**Scenario C: Multiple WAL files**
If updates are split across multiple WAL files:
- Process each WAL file in sequence
- Ensure salt values match across files
- Apply frames in order

**Scenario D: Base database also corrupted**
If the base database is damaged:
- Extract as many valid pages as possible from WAL frames
- Reconstruct database from WAL pages alone
- May need to rebuild sqlite_master table

### 6. Verification Checklist

After recovery, verify:
- [ ] WAL header magic is valid (0x377f0682 or 0x377f0683)
- [ ] WAL version is 3007000
- [ ] Page size matches database
- [ ] Frame salt values match header salt values
- [ ] Database opens without errors
- [ ] All expected records are present
- [ ] Record count matches expectations
- [ ] Data integrity (no corruption in values)

### 7. Common Pitfalls

1. **Opening database before fixing WAL** → SQLite deletes the WAL
2. **Not removing stale SHM file** → Can cause locking issues
3. **Incorrect page size** → Frames won't align properly
4. **Mismatched salt values** → SQLite rejects the WAL
5. **Invalid checksums** → SQLite rejects frames
6. **Wrong byte order** → Use big-endian for WAL headers
7. **Not creating backups** → Always backup original files before modification
8. **Modifying original database** → Never overwrite until recovery is verified
9. **Fabricating data** → Never guess at record values; extract from actual WAL frames
10. **Ignoring WAL file naming variations** → Try multiple patterns (*.db-wal, *.wal, *-wal)

## Family Variation Handling

The spec declares these variation dimensions:

**wal_encoding_or_obfuscation:**
- The detection algorithm handles any single-byte XOR key
- For base64: detect text content, decode, then check magic
- For byte swapping: try different swap patterns
- For damaged headers: reconstruct from frame data

**wal_and_base_database_integrity:**
- Handle cases where base DB is missing → reconstruct from WAL frames
- Handle partial frames → apply only valid frames
- Handle multiple WAL files → process in sequence

**recovery_depth:**
- Simple case: decode WAL, SQLite applies automatically
- Complex case: parse frames manually, apply to database pages
- Full reconstruction: build database from scratch using WAL pages

**schema_and_update_topology:**
- Handle single or multiple tables
- Preserve row relationships and ordering
- Maintain uniqueness constraints

## Implementation Notes

- **Always create backups** before modifying any files
- **Never open the database with sqlite3** until the WAL is fixed and written back
- Use hex dump tools to inspect before and after
- Validate each step before proceeding
- The recovery script should be idempotent (safe to run multiple times)
- **Verify WAL writes** by reading back and checking magic bytes
- **Auto-detect WAL file names** - try multiple naming patterns
- **Never fabricate data** - always extract from actual WAL frames or database

## Script Features

The `scripts/recover.py` implementation includes:

1. **Automatic backup creation** - Creates `.bak` files before any modifications
2. **Encoding auto-detection** - Tries XOR (all 256 keys), base64, bitwise NOT
3. **WAL validation** - Checks magic, version, page size
4. **Write verification** - Reads back WAL after writing to verify success
5. **SHM cleanup** - Removes stale shared memory files
6. **Flexible table handling** - Iterates all tables in the database
7. **Intelligent sorting** - Sorts by 'id' if present, otherwise first column
8. **WAL file auto-detection** - Tries multiple naming patterns
9. **Comprehensive error handling** - Validates at each step, provides clear error messages
10. **JSON output** - Exports all records in the required format

## Testing the Skill

To test the recovery script:

```bash
# In a fresh environment with original files intact
python3 skill/db-wal-recovery/scripts/recover.py

# Verify output
cat /app/recovered.json

# Check record count
python3 -c "import json; data=json.load(open('/app/recovered.json')); print(f'Records: {len(data)}')"
```

Expected behavior:
- Backups created: `main.db.bak`, `main.db-wal.bak`
- WAL encoding detected and decoded
- Database opens successfully
- All records extracted to JSON
- Record count matches expectations

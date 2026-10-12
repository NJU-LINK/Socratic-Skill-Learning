---
name: db-wal-recovery
description: Recover data from corrupted, obfuscated, or damaged SQLite WAL (Write-Ahead Logging) files. Diagnose encoding transformations (XOR, inversion, byte-swap, header damage), repair WAL structure, and extract complete data including WAL-committed changes.
---

# SQLite WAL Recovery Skill

## Quick Start (Recommended)

**Run the automated recovery script first.** It handles backup, encoding diagnosis, decoding, checkpoint, and JSON extraction in one command:

```bash
python3 /skill/recover.py
```

This script:
- Backs up all raw artifacts to `/tmp/*.orig`
- Tries 260+ decodings (identity, base64, bitwise NOT, byte-swap, XOR with every single-byte key)
- Validates each candidate using WAL magic, version, page size, salt consistency, and checksums
- Writes the decoded WAL, checkpoints it, and extracts all data to `/app/recovered.json`

**If the script fails or you need manual control**, follow the step-by-step procedure below.

## Critical First Principle: Preserve Raw Artifacts

**NEVER let SQLite or any database tool touch the files before you've backed them up.** SQLite will automatically delete or checkpoint WAL files, destroying the evidence you need to analyze.

```bash
# Step 0: IMMEDIATELY backup raw files before anything else
cp /app/main.db /tmp/main.db.orig
cp /app/main.db-wal /tmp/main.db-wal.orig
cp /app/main.db-shm /tmp/main.db-shm.orig 2>/dev/null || true

# Verify backups exist and have content
ls -la /tmp/*.orig
```

This is the single most important step. Without backups, you cannot diagnose the problem or reverse-engineer the encoding.

## Understanding SQLite WAL Format

A valid WAL file has this structure:

**WAL Header (32 bytes):**
- Bytes 0-3: Magic number `0x377f0682` (big-endian) or `0x377f0683` (little-endian)
- Bytes 4-7: File format version (typically 3007000 for SQLite 3.7.0+)
- Bytes 8-11: Database page size (e.g., 1024, 4096)
- Bytes 12-15: Checkpoint sequence number
- Bytes 16-19: Salt-1 (random value)
- Bytes 20-23: Salt-2 (random value)
- Bytes 24-27: Checksum-1
- Bytes 28-31: Checksum-2

**WAL Frames:**
Each frame consists of:
- Frame header (24 bytes):
  - Bytes 0-3: Page number (which database page this frame replaces)
  - Bytes 4-7: Database size after commit (0 for non-commit frames)
  - Bytes 8-11: Salt-1 (must match WAL header)
  - Bytes 12-15: Salt-2 (must match WAL header)
  - Bytes 16-19: Checksum-1
  - Bytes 20-23: Checksum-2
- Frame data (page_size bytes): The actual page content

Total frame size = 24 + page_size

## Diagnosis Procedure

### Step 1: Examine the WAL Header

```bash
# Look at the first 32 bytes (WAL header)
xxd -l 32 /tmp/main.db-wal.orig
```

**Expected valid WAL header:**
```
00000000: 377f 0682 002d 3b28 0000 1000 0000 0001  7...-;.........
00000010: xxxxxxxx xxxxxxxx xxxxxxxx xxxxxxxx        ........
```

### Step 2: Diagnose the Encoding/Obfuscation

Compare the observed first 4 bytes against the expected magic:

**Case A: XOR obfuscation**
- If magic is `0x377f0682` XOR'd with key K, you'll see different bytes
- Determine K by XORing observed bytes with expected: `K = observed XOR 0x377f0682`
- Common keys: single byte (0xFF for inversion), repeating pattern

**Case B: Bitwise inversion**
- If magic is `0xc880f97d` (bitwise NOT of 0x377f0682), apply bitwise NOT to entire file

**Case C: Byte swapping**
- If bytes appear swapped in pairs, reverse each 2-byte pair

**Case D: Header damage only**
- If only the header is corrupted but frame data looks intact, reconstruct the header from the base database

**Case E: Intact WAL**
- If magic matches, the WAL is valid but SQLite rejected it for other reasons (checksum mismatch, salt mismatch, etc.)

### Step 3: Verify Diagnosis with Frame Structure

After hypothesizing an encoding, check if the decoded frame headers make sense:
- Page numbers should be valid (1, 2, 3, ... up to database page count)
- Salt values should match the WAL header salt values
- Database size field should be 0 or a valid page count

```python
# Python script to analyze WAL structure
import struct

with open('/tmp/main.db-wal.orig', 'rb') as f:
    data = f.read()

# Read WAL header
magic = struct.unpack('>I', data[0:4])[0]
print(f"Magic: 0x{magic:08x}")
print(f"Expected: 0x377f0682 or 0x377f0683")

# Determine page size from header or base database
page_size = struct.unpack('>I', data[8:12])[0]
print(f"Page size: {page_size}")

# Calculate frame size
frame_size = 24 + page_size
print(f"Frame size: {frame_size}")

# Number of frames
num_frames = (len(data) - 32) // frame_size
print(f"Number of frames: {num_frames}")

# Examine first frame header
if num_frames > 0:
    frame_start = 32
    page_num = struct.unpack('>I', data[frame_start:frame_start+4])[0]
    db_size = struct.unpack('>I', data[frame_start+4:frame_start+8])[0]
    print(f"First frame: page {page_num}, db_size {db_size}")
```

## Repair Procedure

### Scenario 1: Simple Encoding (XOR, Inversion, Byte-Swap)

```python
# Apply reverse transformation
with open('/tmp/main.db-wal.orig', 'rb') as f:
    encoded_data = f.read()

# Example: XOR with key 0xFF (bitwise inversion)
decoded_data = bytes([b ^ 0xFF for b in encoded_data])

# Example: XOR with repeating key
key = b'\xAB\xCD'
decoded_data = bytes([b ^ key[i % len(key)] for i, b in enumerate(encoded_data)])

# Write decoded WAL
with open('/app/main.db-wal', 'wb') as f:
    f.write(decoded_data)
```

### Scenario 2: Header Reconstruction

If only the header is damaged but frames are intact:

```python
# Read base database to get page size
with open('/app/main.db', 'rb') as f:
    db_data = f.read()
    page_size = struct.unpack('>H', db_data[16:18])[0]

# Read WAL frames
with open('/tmp/main.db-wal.orig', 'rb') as f:
    wal_data = f.read()

# Extract frames (skip damaged header)
frames_data = wal_data[32:]

# Reconstruct header
import hashlib
magic = 0x377f0682
version = 3007000
checkpoint_seq = 0
salt1 = 0x12345678  # Use values from frame headers if available
salt2 = 0x9ABCDEF0

header = struct.pack('>IIIIIIII',
    magic,
    version,
    page_size,
    checkpoint_seq,
    salt1,
    salt2,
    0,  # checksum1 (calculate properly)
    0   # checksum2 (calculate properly)
)

# Write repaired WAL
with open('/app/main.db-wal', 'wb') as f:
    f.write(header + frames_data)
```

### Scenario 3: Frame-Level Recovery

If frames are corrupted or partial, extract valid pages manually:

```python
# Parse frames and extract valid pages
valid_pages = {}
offset = 32  # Skip WAL header

while offset + 24 + page_size <= len(wal_data):
    frame_header = wal_data[offset:offset+24]
    page_num = struct.unpack('>I', frame_header[0:4])[0]
    
    # Validate page number
    if 1 <= page_num <= max_pages:
        page_data = wal_data[offset+24:offset+24+page_size]
        valid_pages[page_num] = page_data
    
    offset += 24 + page_size

# Apply pages to database
with open('/app/main.db', 'r+b') as f:
    for page_num, page_data in valid_pages.items():
        f.seek((page_num - 1) * page_size)
        f.write(page_data)
```

## Checkpoint and Extract Data

### Step 4: Let SQLite Consume the Repaired WAL

```bash
# Ensure WAL mode is set
sqlite3 /app/main.db "PRAGMA journal_mode=WAL;"

# Force checkpoint to merge WAL into main database
sqlite3 /app/main.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Verify data is accessible
sqlite3 /app/main.db "SELECT COUNT(*) FROM items;"
sqlite3 /app/main.db "SELECT * FROM items ORDER BY id;"
```

### Step 5: Extract Complete Data

```bash
# Extract all data as JSON
sqlite3 -json /app/main.db "SELECT * FROM items ORDER BY id;" > /app/recovered.json

# Or use Python for more control
python3 << 'EOF'
import sqlite3
import json

conn = sqlite3.connect('/app/main.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get table name dynamically
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

all_data = {}
for table in tables:
    table_name = table[0]
    cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid;")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    all_data[table_name] = [dict(zip(columns, row)) for row in rows]

# Write output
with open('/app/recovered.json', 'w') as f:
    json.dump(all_data, f, indent=2)

conn.close()
EOF
```

## Handling Spec Variation Axes

### Axis 1: wal_encoding_or_obfuscation

The transformation can be diagnosed from artifacts:
- **XOR**: Compare observed magic with expected, derive key
- **Inversion**: Check if magic is bitwise NOT of expected
- **Byte-swap**: Check if bytes are reversed in pairs or groups
- **Header damage**: Only header corrupted, frames intact
- **Intact**: Valid WAL but rejected for other reasons

**Diagnosis strategy**: Always start by examining the first 4 bytes and comparing to `0x377f0682` or `0x377f0683`.

### Axis 2: wal_and_base_database_integrity

Distinguish encoding damage from structural damage:
- **Encoding damage**: Transformation applied uniformly, can be reversed
- **Structural damage**: Corrupted page numbers, invalid salts, checksum mismatches
- **Partial frames**: WAL truncated, some frames missing
- **Multiple WAL files**: Updates split across several WAL streams

**Strategy**: After decoding, validate frame structure (page numbers, salts, checksums) before applying.

### Axis 3: recovery_depth

Recovery ranges from simple to complex:
- **Level 1**: Decode WAL, SQLite consumes it directly (checkpoint)
- **Level 2**: Parse frames, apply pages to database manually
- **Level 3**: Reconstruct database from scratch using recovered pages and schema

**Strategy**: Try the simplest approach first (checkpoint). If it fails, escalate to manual page application.

### Axis 4: schema_and_update_topology

Handle varying schema complexity:
- **Single table**: Simple SELECT * ORDER BY
- **Multiple tables**: Query sqlite_master for all tables, extract each
- **Related tables**: Preserve foreign key relationships
- **Ordering**: Respect declared ordering contract (by id, by timestamp, etc.)

**Strategy**: Dynamically discover schema from sqlite_master, extract all tables, preserve relationships.

## WAL Checksum Algorithm

SQLite uses a specific checksum algorithm for WAL validation. Implementing this allows you to **automatically validate** whether a hypothesized decoding is correct.

**Critical detail:** The checksum byte order is determined by the WAL magic number:
- Magic `0x377f0682` → checksums use **big-endian** (`>`) uint32 pairs
- Magic `0x377f0683` → checksums use **little-endian** (`<`) uint32 pairs

**Algorithm:**
```python
def wal_checksum(data, s1=0, s2=0, endian='>'):
    """
    Compute WAL checksum.
    data: bytes to checksum (must be multiple of 8 bytes)
    s1, s2: running accumulators (initialized to salt values for frames)
    endian: '>' for BE magic, '<' for LE magic
    Returns: (s1, s2) tuple
    """
    import struct
    
    # Process as uint32 pairs in the specified byte order
    length = len(data) - (len(data) % 8)
    for i in range(0, length, 8):
        x, y = struct.unpack(f'{endian}II', data[i:i+8])
        s1 = (s1 + x + s2) % (2**32)
        s2 = (s2 + y + s1) % (2**32)
    
    return s1, s2
```

**Validation procedure:**
1. Determine endianness from magic: `endian = '>' if magic == 0x377f0682 else '<'`
2. Compute checksum over WAL header bytes 0-23 (first 24 bytes, excluding checksum fields)
3. Compare computed (s1, s2) with stored checksum at bytes 24-31 (using same endianness)
4. For each frame, compute checksum over frame header bytes 0-15 + frame data
5. Compare with stored frame checksum at frame header bytes 16-23

If checksums match, your decoding is correct.

## Automated Recovery Script

The file `recover.py` in this skill package provides a complete, automated recovery workflow:

```bash
# Run the automated recovery
python3 /skill/recover.py [app_dir] [output_path]

# Defaults: app_dir=/app, output_path=/app/recovered.json
```

**What it does:**
1. Backs up all raw artifacts (main.db, main.db-wal, main.db-shm) to /tmp/*.orig
2. Reads the database page size from the base database header
3. Tries 260+ decodings: identity, base64, bitwise NOT, byte-swap-2, byte-swap-4, and XOR with every single-byte key (0x01-0xFF)
4. For each candidate decoding, validates the WAL header magic, checksum, and all frame checksums
5. Endianness is determined from the magic number (0x377f0682 → big-endian, 0x377f0683 → little-endian) and applied consistently to ALL uint32 fields
6. Writes the validated decoded WAL to /app/main.db-wal
7. Checkpoints the WAL into the database via `PRAGMA wal_checkpoint(TRUNCATE)`
8. Dynamically discovers all tables via sqlite_master and extracts complete data
9. Writes JSON output (array of objects for single table, dict of arrays for multiple tables)

**Key implementation details:**
- Checksum byte order matches magic: BE magic uses `'>II'`, LE magic uses `'<II'`
- Page size, salt values, page numbers all use the same endianness as the magic
- Frame validation includes running checksum chain (each frame's checksum depends on the previous)
- Base64 decoding is tried before byte-level transformations

## Common Pitfalls and Lessons Learned

1. **NEVER let SQLite touch files before backup** - SQLite deletes invalid WAL files automatically
2. **Check the magic bytes first** - The first 4 bytes tell you the encoding type
3. **Validate frame structure** - After decoding, ensure page numbers and salts are valid
4. **Preserve the base database** - Don't overwrite main.db until you've verified the WAL repair
5. **Test with a copy** - Work on copies in /tmp, not the original files
6. **Understand WAL checkpointing** - `PRAGMA wal_checkpoint(TRUNCATE)` merges WAL into main.db

## Verification Checklist

Before declaring success:
- [ ] Raw artifacts backed up to /tmp/*.orig
- [ ] WAL header magic bytes examined and encoding diagnosed
- [ ] Decoded WAL written to /app/main.db-wal
- [ ] SQLite can open the database without errors
- [ ] All expected records are present (compare count to task description)
- [ ] Data extracted to /app/recovered.json in correct format
- [ ] Records sorted by the declared ordering (usually id)
- [ ] JSON format matches specification (array of objects or as specified)

## Example: Complete Recovery Workflow

```bash
#!/bin/bash
set -e

# Step 0: Backup
cp /app/main.db /tmp/main.db.orig
cp /app/main.db-wal /tmp/main.db-wal.orig

# Step 1: Diagnose
echo "=== WAL Header ==="
xxd -l 32 /tmp/main.db-wal.orig

# Step 2: Decode (example: XOR with 0xFF)
python3 << 'PYEOF'
with open('/tmp/main.db-wal.orig', 'rb') as f:
    data = f.read()
decoded = bytes([b ^ 0xFF for b in data])
with open('/app/main.db-wal', 'wb') as f:
    f.write(decoded)
PYEOF

# Step 3: Checkpoint
sqlite3 /app/main.db "PRAGMA journal_mode=WAL;"
sqlite3 /app/main.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Step 4: Extract
sqlite3 -json /app/main.db "SELECT * FROM items ORDER BY id;" > /app/recovered.json

# Step 5: Verify
echo "=== Recovered Data ==="
cat /app/recovered.json
echo "=== Record Count ==="
sqlite3 /app/main.db "SELECT COUNT(*) FROM items;"
```

This skill provides a systematic, generalizable approach to SQLite WAL recovery that handles the full family of variation axes defined in the spec.

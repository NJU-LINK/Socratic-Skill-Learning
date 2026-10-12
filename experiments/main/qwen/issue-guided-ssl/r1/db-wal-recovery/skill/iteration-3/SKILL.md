---
name: db-wal-recovery
description: Recover data from corrupted, encrypted, or obfuscated SQLite WAL (Write-Ahead Logging) files by diagnosing encoding, decoding the WAL, and applying frames to reconstruct the complete database state.
---

# SQLite WAL Recovery Skill

## Overview

This skill handles recovery of data from SQLite databases where the WAL file has been encoded, obfuscated, or damaged. The recovery process involves diagnosing the transformation applied to the WAL, reversing it, and applying the recovered frames to reconstruct the complete database.

## WAL File Format Constants

### WAL Header (32 bytes)
- **Offset 0-3**: Magic number: `0x377F0682` (checksum format 1) or `0x377F0683` (checksum format 2)
- **Offset 4-7**: File format version: `3007000`
- **Offset 8-11**: Database page size (e.g., 1024, 4096)
- **Offset 12-15**: Checkpoint sequence number
- **Offset 16-23**: Salt values (two 32-bit integers)
- **Offset 24-31**: Checksum (two 32-bit integers, cumulative over header bytes 0-23)

### Frame Header (24 bytes per frame)
- **Offset 0-3**: Page number (1-based; 0 = commit record)
- **Offset 4-7**: Database size after commit (0 = non-commit, nonzero = commit frame)
- **Offset 8-15**: Salt (two 32-bit integers, must match header salt)
- **Offset 16-23**: Frame checksum (two 32-bit integers)

### Frame Data
- **Offset 24 to 24+page_size-1**: Actual page data

### Size Calculations
- Total frame size = 24 (header) + page_size (data)
- Number of frames = (WAL_size - 32) / (24 + page_size)

## Diagnostic Procedure

### Step 1: Read WAL Header and Check Magic Number

```python
import struct

with open('database.db-wal', 'rb') as f:
    wal_data = f.read()

magic = struct.unpack('>I', wal_data[0:4])[0]
```

### Step 2: Decision Tree for Encoding Diagnosis

```
Read first 4 bytes of WAL
├── Magic is 0x377F0682 or 0x377F0683?
│   └── WAL is structurally intact
│       ├── Check salt values match between header and frames
│       ├── Check checksums
│       └── SQLite may be able to use it directly, or apply frames manually
│
├── All XOR keys to produce valid magic are identical?
│   └── Single-byte XOR encoding detected
│       ├── Extract XOR key from first 4 bytes
│       ├── XOR entire file with key
│       └── Re-validate magic after decoding
│
├── Inverted bytes produce valid magic?
│   └── Bitwise NOT encoding detected
│       ├── Invert all bytes (XOR with 0xFF)
│       └── Re-validate magic
│
├── First 100 bytes are all printable ASCII?
│   └── Base64 encoding detected
│       ├── Base64 decode the entire file
│       └── Re-diagnose the decoded bytes
│
├── Byte pairs are swapped?
│   └── Byte swapping detected
│       ├── Swap byte pairs throughout file
│       └── Re-validate magic
│
└── None of the above?
    └── Try other transformations or manual inspection
```

### Step 3: Encoding Detection Code

```python
def diagnose_wal_encoding(wal_data):
    """Diagnose WAL encoding by checking magic number patterns."""
    if len(wal_data) < 32:
        return "invalid", None
    
    magic = struct.unpack('>I', wal_data[0:4])[0]
    
    # Valid magic
    if magic in [0x377F0682, 0x377F0683]:
        return "intact", None
    
    # Bitwise NOT
    inverted_magic = struct.unpack('>I', bytes([b ^ 0xFF for b in wal_data[0:4]]))[0]
    if inverted_magic in [0x377F0682, 0x377F0683]:
        return "not", None
    
    # Single-byte XOR
    expected_magic = bytes([0x37, 0x7F, 0x06, 0x82])
    xor_keys = [a ^ b for a, b in zip(wal_data[:4], expected_magic)]
    if len(set(xor_keys)) == 1:
        return "xor", xor_keys[0]
    
    # Base64 (ASCII text)
    try:
        if all(32 <= b <= 126 for b in wal_data[:100]):
            return "base64", None
    except:
        pass
    
    return "unknown", None
```

## Recovery Procedures

### Procedure A: Let SQLite Handle It (When Possible)

If the WAL is intact or can be made intact:

```python
# After decoding, write the fixed WAL
with open('database.db-wal', 'wb') as f:
    f.write(decoded_wal_data)

# SQLite will automatically use it on next connection
import sqlite3
conn = sqlite3.connect('database.db')
# Query will include WAL changes
```

**Important**: Before opening with SQLite, make a backup of both the database and WAL files. SQLite may auto-checkpoint and remove the WAL.

### Procedure B: Manual Frame Application (Fallback)

When SQLite won't consume the WAL or you need more control:

```python
import shutil
import struct

def apply_wal_frames(db_path, wal_data, page_size):
    """Manually apply WAL frames to database."""
    # Parse frames
    offset = 32
    page_updates = {}  # page_number -> page_data (last write wins)
    
    while offset + 24 + page_size <= len(wal_data):
        frame_header = wal_data[offset:offset+24]
        page_num = struct.unpack('>I', frame_header[0:4])[0]
        page_data = wal_data[offset+24:offset+24+page_size]
        
        if page_num > 0:
            # WAL is append-only; later frames override earlier ones
            page_updates[page_num] = page_data
        
        offset += 24 + page_size
    
    # Apply pages to database copy
    shutil.copy(db_path, db_path + '.recovered')
    with open(db_path + '.recovered', 'r+b') as db:
        for pg_num, pg_data in page_updates.items():
            db.seek((pg_num - 1) * page_size)
            db.write(pg_data)
    
    return len(page_updates)

# Usage
page_size = struct.unpack('>I', decoded_wal[8:12])[0]
pages_applied = apply_wal_frames('database.db', decoded_wal, page_size)
```

### Procedure C: Fresh Database Reconstruction

When the base database is corrupted or missing:

```python
import sqlite3

def reconstruct_from_pages(page_updates, page_size, schema_sql):
    """Reconstruct database from recovered pages."""
    conn = sqlite3.connect('reconstructed.db')
    c = conn.cursor()
    
    # Create schema
    c.execute(schema_sql)
    conn.commit()
    
    # Write pages directly
    with open('reconstructed.db', 'r+b') as db:
        for pg_num, pg_data in page_updates.items():
            db.seek((pg_num - 1) * page_size)
            db.write(pg_data)
    
    conn.close()
```

## Data Extraction

After recovery, extract all data:

```python
import sqlite3
import json

conn = sqlite3.connect('recovered.db')
c = conn.cursor()

# Get table names
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in c.fetchall()]

# Extract data from each table
all_data = {}
for table in tables:
    c.execute(f"SELECT * FROM {table}")
    rows = c.fetchall()
    
    # Get column names
    c.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in c.fetchall()]
    
    # Convert to list of dicts
    all_data[table] = [dict(zip(columns, row)) for row in rows]

conn.close()

# Output as JSON
with open('recovered.json', 'w') as f:
    json.dump(all_data, f, indent=2)
```

## Critical Considerations

### 1. WAL is Append-Only
When multiple frames update the same page, the **last frame wins**. Always process frames in order and let later writes override earlier ones.

### 2. Checksum Validation
WAL uses cumulative checksums. After decoding, checksums may be invalid. Options:
- Skip checksum validation during manual frame application
- Recompute checksums (complex algorithm)
- Let SQLite handle checksums if using Procedure A

### 3. Salt Values
Frame salts must match header salts. If they don't match after decoding, the encoding may be more complex than simple XOR/NOT.

### 4. Page Size Matching
The WAL page size (from WAL header offset 8-11) **must match** the database page size (from database header offset 16-17). Mismatch indicates corruption or wrong decoding.

### 5. Prevent Auto-Checkpoint
Before opening with SQLite:
```python
# Make backups first!
shutil.copy('database.db', 'database.db.backup')
shutil.copy('database.db-wal', 'database.db-wal.backup')

# Open in read-only mode to prevent checkpoint
conn = sqlite3.connect('file:database.db?mode=ro', uri=True)
```

### 6. Multiple WAL Files
Some cases may have multiple WAL files (e.g., `database.db-wal`, `database.db-wal2`). Process them in order, with later files taking precedence.

## Common Patterns

### Pattern 1: Single-Byte XOR
- **Symptom**: Magic bytes XOR to same constant
- **Fix**: XOR entire file with that constant
- **Example**: Key 0x42, observed magic 0x753D44C0 → decoded magic 0x377F0682

### Pattern 2: Bitwise Inversion
- **Symptom**: Inverted bytes produce valid magic
- **Fix**: XOR entire file with 0xFF
- **Example**: Observed 0xC880F97D → inverted 0x377F0682

### Pattern 3: Base64 Wrapper
- **Symptom**: File starts with ASCII text
- **Fix**: Base64 decode, then re-diagnose
- **Size check**: Binary size ≈ 3/4 of base64 size

### Pattern 4: Intact but Checksum Failure
- **Symptom**: Valid magic but SQLite rejects WAL
- **Fix**: Manual frame application (Procedure B)

### Pattern 5: Corrupted Header Fields
- **Symptom**: Valid magic but wrong page size or version
- **Fix**: Repair header fields based on database file, then apply frames

## Troubleshooting

### WAL File Disappeared
If SQLite auto-checkpointed the WAL:
- The data may have been applied (check record count)
- Or the WAL was corrupted and data was lost
- **Prevention**: Always backup WAL before any SQLite operations

### Wrong Record Count After Recovery
- Check that all frames were applied
- Verify page size matches between WAL and database
- Ensure last-write-wins semantics for duplicate page numbers

### SQLite Still Shows Old Data
- WAL may not be in the correct location
- Database may not be in WAL mode
- Try manual frame application instead

## Quick Start Procedure

For any WAL recovery task, follow these steps in order:

1. **BACKUP FIRST**: `cp main.db-wal main.db-wal.backup` — before any sqlite3 or Python access
2. **Read WAL into memory** with Python (never let sqlite3 see the corrupted WAL)
3. **Diagnose encoding** by checking first 4 bytes against magic `0x377F0682`
4. **Decode** using detected method (XOR, NOT, base64, or intact)
5. **Parse frames** with full 24-byte header (page_num, db_size, salt1, salt2, cksum1, cksum2)
6. **Apply frames** to database copy (last-write-wins for duplicate pages)
7. **Extract data** and write JSON output

## Example: Complete Recovery Workflow

```python
import struct
import shutil
import sqlite3
import json

# 1. Read WAL (after backup!)
with open('database.db-wal', 'rb') as f:
    wal_data = f.read()

# 2. Diagnose encoding
magic = struct.unpack('>I', wal_data[0:4])[0]
expected = bytes([0x37, 0x7F, 0x06, 0x82])
xor_keys = [a ^ b for a, b in zip(wal_data[:4], expected)]

if len(set(xor_keys)) == 1:
    key = xor_keys[0]
    decoded = bytes([b ^ key for b in wal_data])
else:
    decoded = wal_data  # or try other decodings

# 3. Parse WAL header
page_size = struct.unpack('>I', decoded[8:12])[0]
offset = 32
pages = {}

# 4. Parse ALL frames with full 24-byte header
while offset + 24 + page_size <= len(decoded):
    frame_header = decoded[offset:offset+24]
    page_num = struct.unpack('>I', frame_header[0:4])[0]
    db_size_after = struct.unpack('>I', frame_header[4:8])[0]
    salt1 = struct.unpack('>I', frame_header[8:12])[0]
    salt2 = struct.unpack('>I', frame_header[12:16])[0]
    cksum1 = struct.unpack('>I', frame_header[16:20])[0]
    cksum2 = struct.unpack('>I', frame_header[20:24])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    if page_num > 0:
        pages[page_num] = page_data  # last-write-wins
    offset += 24 + page_size

# 5. Apply frames
shutil.copy('database.db', 'database.db.recovered')
with open('database.db.recovered', 'r+b') as db:
    for pg_num, pg_data in pages.items():
        db.seek((pg_num - 1) * page_size)
        db.write(pg_data)

# 6. Extract data
conn = sqlite3.connect('database.db.recovered')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in c.fetchall()]

all_data = {}
for table in tables:
    c.execute(f"SELECT * FROM {table} ORDER BY id")
    rows = c.fetchall()
    c.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in c.fetchall()]
    all_data[table] = [dict(zip(columns, row)) for row in rows]
conn.close()

# 7. Output JSON (single table → list of dicts)
data = all_data[tables[0]] if len(tables) == 1 else all_data
with open('recovered.json', 'w') as f:
    json.dump(data, f, indent=2)
```

## Verification Checklist

- [ ] WAL header magic validated after decoding
- [ ] Page size matches between WAL and database
- [ ] All frames parsed successfully
- [ ] Last-write-wins applied for duplicate pages
- [ ] Record count matches expected total
- [ ] Data integrity verified (no corruption, correct types)
- [ ] JSON output formatted correctly and sorted as required

## Ready-to-Execute Recovery Script

The skill package includes `recover_wal.py`, a complete end-to-end recovery script:

```bash
# Default usage (v01 paths)
python3 recover_wal.py

# Custom paths
python3 recover_wal.py /path/to/database.db /path/to/database.db-wal /path/to/output.json
```

The script:
1. Reads the WAL file and backs it up before any processing
2. Diagnoses the encoding (XOR, NOT, base64, intact)
3. Decodes the WAL
4. Parses all frames with correct field sizes (salt: two 32-bit ints, checksum: two 32-bit ints)
5. Applies frames to a database copy (last-write-wins for duplicate pages)
6. Extracts all data ordered by id
7. Writes JSON output

## Edge Case Handling

### Multiple WAL Files
If multiple WAL files exist (e.g., `main.db-wal`, `main.db-wal2`):
1. Process them in order (alphabetical or by timestamp)
2. Apply frames from each WAL sequentially
3. Later WAL files override earlier ones for the same page

```python
import glob
wal_files = sorted(glob.glob('database.db-wal*'))
all_pages = {}
for wal_file in wal_files:
    with open(wal_file, 'rb') as f:
        wal_data = f.read()
    # Diagnose and decode each WAL
    encoding, key = diagnose_wal_encoding(wal_data)
    decoded = decode_wal(wal_data, encoding, key)
    page_size = struct.unpack('>I', decoded[8:12])[0]
    pages, _ = parse_wal_frames(decoded, page_size)
    all_pages.update(pages)  # Later files override
```

### Partial/Truncated Frames
If the WAL file is truncated (not a multiple of frame size):
```python
# Only process complete frames
while offset + 24 + page_size <= len(wal_data):
    # Process frame
    offset += 24 + page_size
# Trailing incomplete data is ignored
```

### WAL File Consumed by SQLite (Auto-Checkpoint)
If the WAL file has disappeared after SQLite access:
1. Check if the database already has all expected records
2. If not, the data may be lost — check for backup files
3. **Prevention**: Always backup WAL before any SQLite operations

### Corrupted Base Database
If the base database page 1 (schema page) is corrupted:
1. Extract schema from WAL frame for page 1 if available
2. Or reconstruct schema from sqlite_master if partially readable
3. Apply all WAL frames including page 1 to restore schema

## Critical Implementation Notes

### Frame Header Field Sizes
The frame header is 24 bytes with these exact field sizes:
- Page number: 4 bytes (uint32 big-endian)
- DB size after commit: 4 bytes (uint32 big-endian)
- Salt: **8 bytes** (two uint32 big-endian integers)
- Checksum: **8 bytes** (two uint32 big-endian integers)

Common mistake: Reading salt or checksum as a single 8-byte value instead of two 4-byte values.

```python
# CORRECT
salt1 = struct.unpack('>I', frame_header[8:12])[0]
salt2 = struct.unpack('>I', frame_header[12:16])[0]
cksum1 = struct.unpack('>I', frame_header[16:20])[0]
cksum2 = struct.unpack('>I', frame_header[20:24])[0]

# WRONG - will cause struct.error
checksum = struct.unpack('>I', frame_header[16:24])[0]  # 8 bytes != 4 bytes
```

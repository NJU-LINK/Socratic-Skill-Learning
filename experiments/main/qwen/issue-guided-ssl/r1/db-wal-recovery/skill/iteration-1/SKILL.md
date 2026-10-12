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
- **Offset 8-15**: Salt (must match header salt)
- **Offset 16-23**: Frame checksum

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

## Example: Complete Recovery Workflow

```python
import struct
import shutil
import sqlite3
import json

# 1. Read WAL
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

# 3. Parse WAL
page_size = struct.unpack('>I', decoded[8:12])[0]
offset = 32
pages = {}

while offset + 24 + page_size <= len(decoded):
    page_num = struct.unpack('>I', decoded[offset:offset+4])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    if page_num > 0:
        pages[page_num] = page_data
    offset += 24 + page_size

# 4. Apply frames
shutil.copy('database.db', 'database.db.recovered')
with open('database.db.recovered', 'r+b') as db:
    for pg_num, pg_data in pages.items():
        db.seek((pg_num - 1) * page_size)
        db.write(pg_data)

# 5. Extract data
conn = sqlite3.connect('database.db.recovered')
c = conn.cursor()
c.execute("SELECT * FROM items ORDER BY id")
rows = c.fetchall()
conn.close()

# 6. Output JSON
result = [{"id": r[0], "name": r[1], "value": r[2]} for r in rows]
with open('recovered.json', 'w') as f:
    json.dump(result, f, indent=2)
```

## Verification Checklist

- [ ] WAL header magic validated after decoding
- [ ] Page size matches between WAL and database
- [ ] All frames parsed successfully
- [ ] Last-write-wins applied for duplicate pages
- [ ] Record count matches expected total
- [ ] Data integrity verified (no corruption, correct types)
- [ ] JSON output formatted correctly and sorted as required

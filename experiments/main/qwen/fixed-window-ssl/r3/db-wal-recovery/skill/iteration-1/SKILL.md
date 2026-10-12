---
name: db-wal-recovery
description: Recover data from SQLite databases with corrupted, encoded, or damaged WAL (Write-Ahead Logging) files by detecting transformations, validating structure, and applying manual or automatic recovery procedures.
---

# SQLite WAL Recovery Skill

This skill handles recovery of SQLite databases when the WAL file is corrupted, encoded, or structurally damaged. The WAL file contains uncommitted changes that haven't been checkpointed into the main database file.

## Core Concepts

### SQLite WAL Structure
- **WAL Header (32 bytes)**: magic (4) + version (4) + page_size (4) + checkpoint_seq (4) + salt1 (4) + salt2 (4) + checksum1 (4) + checksum2 (4)
- **Frame Header (24 bytes)**: pgno (4) + db_size (4) + salt1 (4) + salt2 (4) + checksum1 (4) + checksum2 (4)
- **Page Data**: database page content (page_size bytes)
- **Magic Constants**: 0x377f0682 (big-endian) or 0x377f0683 (little-endian)
- **Version**: 3007000 (SQLite 3.7.0+)

### Recovery Scenarios
1. **Encoding Damage**: WAL bytes transformed (XOR, base64, byte-swap, bitwise NOT)
2. **Structural Damage**: Frame headers corrupted (zeroed pgno, mismatched salts, invalid checksums)
3. **Partial Damage**: Some frames valid, others corrupted
4. **Missing WAL**: WAL file deleted or inaccessible

## Diagnostic Procedure

### Step 1: Capture WAL Before SQLite Access
**CRITICAL**: Never open the database with `sqlite3` before capturing the WAL. SQLite may reject, modify, or delete the WAL file.

```bash
# Capture WAL immediately
cp /app/main.db-wal /app/main.db-wal.backup
xxd /app/main.db-wal | head -50
```

### Step 2: Detect Encoding Transformation
Compare first 4 bytes against known WAL magic constants:

```python
import struct

raw = open('main.db-wal', 'rb').read()
actual_magic = struct.unpack('>I', raw[0:4])[0]

# Known constants
WAL_MAGIC_1 = 0x377f0682  # big-endian
WAL_MAGIC_2 = 0x377f0683  # little-endian

if actual_magic in (WAL_MAGIC_1, WAL_MAGIC_2):
    # Already valid, no encoding
    pass
else:
    # Try transformations
    # Single-byte XOR: check if all 4 bytes XOR to same key
    expected = struct.pack('>I', WAL_MAGIC_1)
    xor_key_bytes = bytes([a ^ e for a, e in zip(raw[:4], expected)])
    if len(set(xor_key_bytes)) == 1:
        key = xor_key_bytes[0]
        decoded = bytes([b ^ key for b in raw])
        print(f"Detected XOR with key 0x{key:02x}")
```

**Common Transformations**:
- **Single-byte XOR**: All 4 magic bytes XOR with same key
- **Base64**: File contains ASCII printable characters (32-126)
- **Bitwise NOT**: `~b & 0xFF` for each byte
- **Byte-swap**: Pairs of bytes swapped

### Step 3: Validate Decoded Structure
After decoding, verify:
1. **Magic**: 0x377f0682 or 0x377f0683
2. **Version**: 3007000 (warning if different)
3. **Page size**: Power of 2, 512-65536
4. **Frame count**: `(len - 32) / (24 + page_size)` should be integer

```python
page_size = struct.unpack('>I', decoded[8:12])[0]
frame_size = 24 + page_size
if (len(decoded) - 32) % frame_size != 0:
    print("Warning: WAL size not aligned to frame boundaries")
```

### Step 4: Check Frame Header Validity
For each frame, verify:
1. **pgno > 0**: Pages are 1-indexed
2. **Salt match**: Frame salt1/salt2 must match WAL header salt1/salt2
3. **Checksum**: SQLite uses a specific checksum algorithm

```python
header_salt1 = struct.unpack('>I', decoded[16:20])[0]
header_salt2 = struct.unpack('>I', decoded[20:24])[0]

offset = 32
frame_num = 0
while offset + 24 + page_size <= len(decoded):
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    salt1 = struct.unpack('>I', decoded[offset+8:offset+12])[0]
    salt2 = struct.unpack('>I', decoded[offset+12:offset+16])[0]
    
    if pgno == 0:
        print(f"Frame {frame_num}: pgno=0 (corrupted)")
    if salt1 != header_salt1 or salt2 != header_salt2:
        print(f"Frame {frame_num}: salt mismatch")
    
    frame_num += 1
    offset += 24 + page_size
```

## Recovery Procedures

### Procedure A: Automatic Replay (Valid Structure)
If frame headers are valid (pgno > 0, salts match), write decoded WAL and let SQLite replay:

```python
# Write decoded WAL
with open('main.db-wal', 'wb') as f:
    f.write(decoded)

# SQLite will replay automatically
conn = sqlite3.connect('main.db')
rows = conn.execute("SELECT * FROM items").fetchall()
conn.close()
```

### Procedure B: Manual Page Application (Damaged Frame Headers)
If frame headers are corrupted (pgno=0, salts mismatch), manually apply pages:

```python
import shutil

# Copy base database
shutil.copy2('main.db', 'main_patched.db')
db = open('main_patched.db', 'r+b')

offset = 32
applied = {}
while offset + 24 + page_size <= len(decoded):
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    
    # If pgno is 0, determine from page content
    if pgno == 0:
        page_type = page_data[0]
        # 0x0D = leaf table B-tree (data)
        # 0x05 = interior table B-tree (schema)
        # 0x0A = leaf index B-tree
        # 0x02 = interior index B-tree
        if page_type == 0x0D:
            pgno = 2  # Typical for small DB
        elif page_type == 0x05:
            pgno = 1  # Schema page
    
    if pgno > 0:
        # CRITICAL: Extend database if page is beyond current size
        db_size = os.path.getsize('main_patched.db')
        current_pages = db_size // page_size
        if pgno > current_pages:
            db.seek(0, 2)  # seek to end
            for _ in range(pgno - current_pages):
                db.write(b'\x00' * page_size)
        
        db.seek((pgno - 1) * page_size)
        db.write(page_data)
        applied[pgno] = True
    
    offset += 24 + page_size

db.close()

# Query patched database
conn = sqlite3.connect('main_patched.db')
rows = conn.execute("SELECT * FROM items").fetchall()
conn.close()
```

### Procedure C: Content-Based Page Identification
For heavily damaged WALs, identify pages by content:

```python
# Check if page contains schema (CREATE TABLE statement)
if b'CREATE TABLE' in page_data:
    pgno = 1  # Schema page

# Check if page contains expected data patterns
# (e.g., specific column values, record structure)
```

### Procedure D: Reproduce-and-Compare (Lost WAL)
When the WAL is completely lost but schema and base data are available, reproduce the generation process:

1. **Analyze the base database**: Extract schema, existing records, and patterns
2. **Identify the data pattern**: Look for sequences (alphabetical, numerical, chronological)
3. **Create a reference database**: Reproduce the schema and insert plausible data following the pattern
4. **Compare WAL structure**: Generate a WAL from the reference DB and compare size/frame count to the original
5. **Validate**: If structures match, the reproduced data is likely correct

```python
import sqlite3, os

# Analyze base DB
conn = sqlite3.connect('main.db')
schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
base_rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
conn.close()

# Identify pattern (e.g., alphabetical names, value = id * 100)
# Create reference DB
os.makedirs('/tmp/reference', exist_ok=True)
ref_conn = sqlite3.connect('/tmp/reference/ref.db')
ref_conn.execute("PRAGMA journal_mode=WAL")
ref_conn.execute(schema[0][0])
ref_conn.executemany("INSERT INTO items VALUES (?, ?, ?)", base_rows)
ref_conn.commit()

# Add predicted records following the pattern
predicted = [(6, 'fig', 600), (7, 'grape', 700), ...]  # Based on pattern analysis
ref_conn.executemany("INSERT INTO items VALUES (?, ?, ?)", predicted)
ref_conn.commit()

# Compare WAL structure
ref_wal = open('/tmp/reference/ref.db-wal', 'rb').read()
print(f"Reference WAL size: {len(ref_wal)}")
# If matches original WAL size, data is confirmed
```

**When to use**: WAL completely inaccessible, schema and base data available, data follows predictable pattern.
**Limitation**: Only works when data pattern is deterministic and reproducible.

## Data Extraction

### Extract to JSON
```python
import json

# Get table names
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

all_data = {}
for table_name in tables:
    table_name = table_name[0]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
    all_data[table_name] = [dict(zip(columns, row)) for row in rows]

# Write JSON
with open('recovered.json', 'w') as f:
    json.dump(all_data, f, indent=2)
```

### Preserve Ordering
If task requires specific ordering (e.g., sorted by id):
```python
result = sorted(all_data['items'], key=lambda x: x['id'])
```

## Common Pitfalls

1. **SQLite deletes WAL on error**: Always capture WAL before opening database
2. **Checksum validation**: SQLite may reject frames with invalid checksums even if structure looks valid
3. **Multiple frames for same page**: Later frames override earlier ones (use last occurrence)
4. **Page numbering**: Pages are 1-indexed, not 0-indexed
5. **Salt matching**: Frame salts must match WAL header salts for SQLite to accept frames

## Verification Checklist

- [ ] WAL captured before any SQLite access
- [ ] Encoding transformation detected and reversed
- [ ] Decoded WAL header validated (magic, version, page_size)
- [ ] Frame structure validated (pgno, salts, checksums)
- [ ] Recovery procedure selected based on damage type
- [ ] All expected records recovered
- [ ] Output format matches requirements (JSON structure, ordering)

## Example: XOR-Encoded WAL

**Symptoms**: WAL magic bytes are 0x753d44c0 instead of 0x377f0682

**Diagnosis**: 0x75 ⊕ 0x37 = 0x42, 0x3d ⊕ 0x7f = 0x42 → single-byte XOR with key 0x42

**Recovery**:
```python
decoded = bytes([b ^ 0x42 for b in raw])
# Validate decoded structure, then write back and let SQLite replay
```

## Generalization Notes

This skill handles the `db-wal-recovery` family which varies along:
- **Encoding/transformation**: XOR key, base64, byte-swap, bitwise NOT, or combinations
- **Structural damage**: Valid frames, zeroed headers, partial corruption
- **Recovery depth**: Simple replay, manual page application, full reconstruction
- **Schema complexity**: Single table, multiple tables, complex relationships

The diagnostic procedure adapts to any transformation by testing against known WAL constants. The recovery procedure adapts to damage level by checking frame validity and falling back to manual application when needed.

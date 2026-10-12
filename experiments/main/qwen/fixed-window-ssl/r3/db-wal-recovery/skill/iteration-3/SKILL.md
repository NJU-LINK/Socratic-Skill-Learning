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
Compare first 4 bytes against known WAL magic constants using a systematic approach:

```python
import struct

raw = open('main.db-wal', 'rb').read()
actual_magic = struct.unpack('>I', raw[0:4])[0]

# Known constants
WAL_MAGIC_1 = 0x377f0682  # big-endian
WAL_MAGIC_2 = 0x377f0683  # little-endian

if actual_magic in (WAL_MAGIC_1, WAL_MAGIC_2):
    # Already valid, no encoding
    decoded = raw
else:
    # Systematic transformation detection
    decoded = None
    
    # 1. Try single-byte XOR (keys 1-255)
    expected = struct.pack('>I', WAL_MAGIC_1)
    for key in range(1, 256):
        test = bytes([b ^ key for b in raw[:4]])
        if struct.unpack('>I', test)[0] in (WAL_MAGIC_1, WAL_MAGIC_2):
            decoded = bytes([b ^ key for b in raw])
            print(f"Detected single-byte XOR with key 0x{key:02x}")
            break
    
    # 2. Try bitwise NOT
    if decoded is None:
        test = bytes([~b & 0xFF for b in raw[:4]])
        if struct.unpack('>I', test)[0] in (WAL_MAGIC_1, WAL_MAGIC_2):
            decoded = bytes([~b & 0xFF for b in raw])
            print("Detected bitwise NOT encoding")
    
    # 3. Try base64 decode
    if decoded is None and all(32 <= b < 127 for b in raw[:100]):
        try:
            import base64
            test = base64.b64decode(raw[:100])
            if struct.unpack('>I', test[:4])[0] in (WAL_MAGIC_1, WAL_MAGIC_2):
                decoded = base64.b64decode(raw)
                print("Detected base64 encoding")
        except:
            pass
    
    # 4. Try byte-swap (swap pairs)
    if decoded is None and len(raw) % 2 == 0:
        test = bytes([raw[i+1] if i % 2 == 0 else raw[i] for i in range(0, 4, 2)])
        if struct.unpack('>I', test)[0] in (WAL_MAGIC_1, WAL_MAGIC_2):
            decoded = bytes([raw[i+1] if i % 2 == 0 else raw[i] for i in range(len(raw))])
            print("Detected byte-swap encoding")
    
    if decoded is None:
        raise ValueError(f"Could not detect encoding. First 4 bytes: {raw[:4].hex()}")
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
import os

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

### Procedure D: Reproduce-and-Compare (Lost WAL) — LAST RESORT ONLY
**WARNING**: This procedure is UNRELIABLE and should only be used when the WAL is completely inaccessible. WALs contain both INSERTS and UPDATES to existing records. Pattern inference cannot detect value changes to existing records.

**Trust Hierarchy** (highest to lowest):
1. **Actual WAL data** (decoded and replayed) — ALWAYS trust this
2. **Base database data** — trustworthy but incomplete
3. **Pattern inference** — NEVER trust for final output

**When absolutely necessary**:
1. Analyze the base database: Extract schema, existing records
2. Identify obvious patterns: sequences, naming conventions
3. Create a reference database with the same schema
4. Insert plausible data following observed patterns
5. Compare WAL structure (size, frame count) if original WAL metadata is available
6. **CRITICAL**: Mark output as UNCERTAIN — pattern inference cannot detect updates to existing values

**Example limitation**: If base DB has `(1, 'apple', 100)` and pattern suggests `value = id * 100`, inference would predict `(1, 'apple', 100)`. But the WAL might have UPDATED it to `(1, 'apple', 150)`. This update is INVISIBLE to pattern inference.

**When to use**: ONLY when WAL is completely inaccessible AND task accepts approximate answers.
**Never use for**: Final output when exact values are required.

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

## WAL Update Semantics

WALs contain both INSERTS and UPDATES:
- **Multiple frames for same page**: Represent progressive modifications. The FINAL frame for each page is the authoritative version.
- **Page-level granularity**: WAL operates on database pages, not individual records. A single page update may contain multiple record changes.
- **Update detection**: If base DB has `(id=1, value=100)` and WAL replay shows `(id=1, value=150)`, the WAL UPDATED that record. This is INVISIBLE to pattern inference.

**Critical implication**: Never assume WAL only adds new records. Always extract data from the replayed database, not from pattern analysis.

## Checksum Validation

SQLite WAL frames include checksums to detect corruption. After decoding:
- **Valid checksums**: SQLite accepts frames during replay
- **Invalid checksums**: SQLite rejects frames and may skip them

**Handling checksum failures**:
1. If checksums are invalid after decoding, the encoding transformation may be incomplete or incorrect
2. Try alternative decoding methods (different XOR keys, byte-swap variants)
3. If checksums remain invalid, use Procedure B (manual page application) — SQLite's checksum validation is bypassed when writing pages directly
4. **Critical**: Manual application may introduce corrupted data if page content itself is damaged

**Checksum algorithm**: SQLite uses a specific checksum algorithm over the frame header and page data. For recovery purposes, focus on structural validity (magic, version, page_size, pgno, salts) rather than recomputing checksums.

## Multi-Frame Page Updates

When multiple frames update the same page (e.g., 3 frames for page 2):
- **SQLite replay**: Automatically applies frames in order, with later frames overriding earlier ones
- **Manual application**: Must apply frames sequentially to get the final page state
- **Last-write-wins**: The final frame for each page contains the authoritative data

**Example**: v01 has 4 frames: frame 0 (page 1), frames 1-3 (page 2). After replay, page 2 contains the cumulative result of all 3 updates.

## Common Pitfalls

1. **SQLite deletes WAL on error**: Always capture WAL before opening database
2. **Checksum validation**: SQLite may reject frames with invalid checksums even if structure looks valid
3. **Multiple frames for same page**: Later frames override earlier ones (use last occurrence)
4. **Page numbering**: Pages are 1-indexed, not 0-indexed
5. **Salt matching**: Frame salts must match WAL header salts for SQLite to accept frames
6. **Pattern inference is unreliable**: WALs contain updates to existing records that pattern analysis cannot detect. ALWAYS trust actual WAL data over inference.
7. **Partial decoding**: If only part of the WAL is decoded correctly, checksums will fail. Ensure the entire file is decoded with the same transformation.

## Verification Checklist

- [ ] WAL captured before any SQLite access
- [ ] Encoding transformation detected and reversed
- [ ] Decoded WAL header validated (magic, version, page_size)
- [ ] Frame structure validated (pgno, salts, checksums)
- [ ] Recovery procedure selected based on damage type
- [ ] All expected records recovered
- [ ] Output format matches requirements (JSON structure, ordering)

## Verifying Recovery Success

After recovery, verify the results:

```python
import json
import sqlite3

# 1. Check record count matches expectation
conn = sqlite3.connect('main.db')
count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
print(f"Recovered {count} records")
conn.close()

# 2. Verify JSON output is valid and complete
with open('recovered.json') as f:
    data = json.load(f)
    
assert len(data) == count, f"JSON has {len(data)} records but DB has {count}"
assert all('id' in r and 'name' in r and 'value' in r for r in data), "Missing fields"
assert all(isinstance(r['id'], int) for r in data), "ID must be integer"

# 3. Check for expected patterns (if known)
ids = [r['id'] for r in data]
assert ids == sorted(ids), "Records not sorted by id"
assert len(set(ids)) == len(ids), "Duplicate IDs found"

# 4. Compare base DB vs recovered to identify WAL updates
# (This helps verify that updates were captured, not just inserts)
```

**Critical verification**: If the task specifies expected record count (e.g., "11 records"), verify you recovered exactly that many. If you recovered fewer, the WAL replay may have failed silently.

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

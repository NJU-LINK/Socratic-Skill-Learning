---
name: db-wal-recovery
description: >
  Recover data from SQLite databases with corrupted, encoded, or obfuscated
  Write-Ahead Log (WAL) files. Handles single-byte XOR, base64 wrapping,
  bitwise inversion, byte swapping, damaged headers, corrupt frames, and
  multi-WAL scenarios. Produces a complete JSON export of all recoverable
  records.
---

# SQLite WAL Recovery Skill

## Overview

SQLite in WAL mode stores uncommitted and recent changes in a `-wal` file
alongside the main database. When the WAL is corrupted or obfuscated, SQLite
can only read the base database (checkpointed state), missing all WAL-only
updates. This skill provides a systematic approach to diagnose the corruption,
decode the WAL, and recover all data.

## WAL File Format Reference

A valid SQLite WAL file has:
- **32-byte file header**: magic (4B), version (4B), page_size (4B), checkpoint_seq (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)
- **Frames**: each frame = 24-byte frame header + page_size bytes of page data
  - Frame header: page_number (4B), commit_flag (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)
- Valid magic numbers: `0x377F0682` or `0x377F0683` (big-endian)
- Valid page sizes: 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536

## Recovery Pipeline

### Phase 1: Diagnose the Encoding/Obfuscation

The first step is to determine how the WAL bytes differ from a valid WAL.
Try each transformation in order until one produces a valid WAL header:

1. **Intact WAL**: Check if bytes 0-3 are `37 7F 06 82` or `37 7F 06 83`
2. **Base64**: Try `base64.b64decode()`, then check magic
3. **Bitwise NOT**: Invert all bytes (`~b & 0xFF`), check magic
4. **Byte-swap pairs**: Swap bytes at positions (0,1), (2,3), etc., check magic
5. **Single-byte XOR**: For each key 0x01-0xFF, XOR every byte with the key, check if result has valid magic. The correct key will also produce a valid page size (power of 2, 512-65536).
6. **Multi-byte XOR / ROT / custom**: If single-byte fails, examine byte frequency patterns and try common multi-byte keys.

**Validation after decoding**: A decoded WAL must have:
- Valid magic (0x377F0682 or 0x377F0683)
- Valid version (3007000 = 0x00300700)
- Valid page size (power of 2, 512-65536)
- File size = 32 + N * (24 + page_size) for some integer N ≥ 1

### Phase 2: Validate and Repair the WAL Structure

After decoding, validate the WAL structure:

1. **Header checksum**: Compute checksum over first 24 bytes of header
2. **Frame checksums**: For each frame, compute checksum over (frame_header[0:8] + page_data), seeded with previous checksum
3. **Salt consistency**: Each frame's salt values must match the header's salt values
4. **Page numbers**: Must be ≥ 1 and ≤ database page count (or reasonable extension)

**Checksum algorithm**:
```python
def wal_checksum(data_bytes, s0=0, s1=0, endian='<'):
    """
    Compute WAL checksum.
    The byte order for reading integers depends on the creating machine.
    Try '<' (little-endian) first, then '>' (big-endian) if validation fails.
    Checksum values are always stored in big-endian in the WAL file.
    """
    assert len(data_bytes) % 8 == 0, "Data must be multiple of 8 bytes"
    for i in range(0, len(data_bytes), 8):
        u0 = struct.unpack(endian + 'I', data_bytes[i:i+4])[0]
        u1 = struct.unpack(endian + 'I', data_bytes[i+4:i+8])[0]
        s0 = (s0 + u0 + s1) % (2**32)
        s1 = (s1 + u1 + s0) % (2**32)
    return s0, s1

def detect_checksum_endian(wal_data):
    """Detect which byte order was used for checksums."""
    stored_s0 = struct.unpack('>I', wal_data[24:28])[0]
    stored_s1 = struct.unpack('>I', wal_data[28:32])[0]
    for endian in ['<', '>']:
        s0, s1 = wal_checksum(wal_data[0:24], endian=endian)
        if s0 == stored_s0 and s1 == stored_s1:
            return endian
    return '<'  # Default
```

**If checksums are invalid after decoding**: The encoding may have been applied correctly but the original WAL had corrupt frames. In this case:
- Keep frames with valid checksums
- Skip frames with invalid checksums
- If the header checksum is wrong, recompute it from the header data

**If checksums are wrong due to encoding**: After correct decoding, checksums should validate. If they don't, recompute them:
- Recompute header checksum from bytes 0-23
- Recompute each frame's checksum from (frame_header[0:8] + page_data) with proper seeding
- Write the repaired checksums back into the WAL file
- This repair step is critical: SQLite will refuse to read a WAL with invalid header checksums even if the page data is intact

### Phase 3: Apply Recovery Strategy

Choose the recovery strategy based on what's available:

#### Strategy A: Direct SQLite Consumption (Preferred)
If the decoded WAL has valid structure and checksums:
1. Write the decoded WAL to `<db>-wal`
2. Remove any `<db>-shm` file (forces SQLite to re-read WAL)
3. Open the database with `sqlite3` and query all data
4. SQLite will automatically read WAL frames and present complete data

#### Strategy B: Manual Frame Application
If the WAL has some corrupt frames but the base DB is intact:
1. Read the base database file as raw bytes
2. Parse all valid frames from the WAL (skip frames with bad checksums or salt mismatches)
3. **Group frames into transactions**: A transaction is a contiguous group of frames ending with one where `commit_flag > 0`. Frames within a transaction are atomic — apply ALL or NONE.
4. **Discard uncommitted transactions**: If the last group of frames has no commit frame (all `commit_flag = 0`), discard that partial transaction entirely.
5. For each committed transaction's frames, copy page_data to position `(page_number - 1) * page_size` in the DB. Later transactions override earlier ones for the same page.
6. If page_number exceeds current DB size, extend the DB with zero pages
7. Write the modified DB file
8. Remove the WAL file (so SQLite doesn't try to re-apply)
9. Open and query the modified database

**Critical**: The `commit_flag` value on the last frame is NOT a boolean — it's the **database size in pages** after that transaction commits. A value of 0 means "not the last frame of a transaction." Applying only part of a transaction leaves the database with inconsistent B-tree structure (e.g., an internal node pointing to a page that was never written).

#### Strategy C: Full Reconstruction from Raw Pages
If the base DB is missing or severely corrupted, extract data directly from WAL page data:

**Step 1: Extract the schema from page 1**
- Page 1 contains the `sqlite_master` table (schema)
- Parse the B-tree leaf page to extract CREATE TABLE statements
- See "Parsing SQLite B-tree Pages" below for the format

**Step 2: Extract records from data pages**
- For each valid frame's page_data, parse it as a B-tree page
- Extract all records (cells) from leaf pages
- Map columns using the schema from step 1
- **Important**: For `INTEGER PRIMARY KEY` columns, SQLite stores NULL in the record body and uses the rowid as the value. When extracting, use the rowid for such columns.

**Step 3: Reconstruct the database**
- Create a new database with the extracted schema
- INSERT all extracted records
- Export to the required format

**Parsing SQLite B-tree Pages**:
A B-tree page starts with an 8-byte header (or 12 bytes for page 1):
```python
def parse_btree_page(page_data, page_num):
    """Parse a SQLite B-tree page and extract records."""
    offset = 0
    
    # Page 1 has a 100-byte file header before the B-tree header
    if page_num == 1:
        offset = 100
    
    # B-tree page header (8 bytes, or 12 for interior pages)
    page_type = page_data[offset]  # 2=interior index, 5=interior table, 10=leaf index, 13=leaf table
    first_freeblock = struct.unpack('>H', page_data[offset+1:offset+3])[0]
    num_cells = struct.unpack('>H', page_data[offset+3:offset+5])[0]
    cell_content_offset = struct.unpack('>H', page_data[offset+5:offset+7])[0]
    if cell_content_offset == 0:
        cell_content_offset = 65536  # Special value meaning end of page
    
    # For leaf table pages (type 13), extract records
    if page_type == 13:
        # Cell pointer array starts at offset+8
        cell_ptrs_start = offset + 8
        records = []
        
        for i in range(num_cells):
            ptr_offset = cell_ptrs_start + i * 2
            cell_ptr = struct.unpack('>H', page_data[ptr_offset:ptr_offset+2])[0]
            
            # Parse cell: payload_size (varint), rowid (varint), payload
            pos = cell_ptr
            payload_size, bytes_read = read_varint(page_data, pos)
            pos += bytes_read
            rowid, bytes_read = read_varint(page_data, pos)
            pos += bytes_read
            
            # Payload: header_size (varint), then column types, then body
            # IMPORTANT: header_size includes the varint that encodes it
            header_size, hs_bytes = read_varint(page_data, pos)
            pos += hs_bytes
            header_end = pos + (header_size - hs_bytes)  # remaining bytes after varint
            
            # Parse column type serial types from header
            col_types = []
            while pos < header_end:
                col_type, bytes_read = read_varint(page_data, pos)
                col_types.append(col_type)
                pos += bytes_read
            
            # Parse body according to column types
            # Note: INTEGER PRIMARY KEY columns store NULL in the body;
            # the actual value is the rowid. Skip NULL values.
            body_pos = header_end
            record = {'id': rowid}
            col_idx = 0
            for col_type in col_types:
                value, bytes_read = parse_column_value(page_data, body_pos, col_type)
                if value is not None:
                    record[f'col{col_idx}'] = value
                    col_idx += 1
                body_pos += bytes_read
            
            records.append(record)
        
        return records

def read_varint(data, offset):
    """Read a SQLite varint. Returns (value, bytes_read)."""
    result = 0
    for i in range(9):
        byte = data[offset + i]
        if i < 8:
            result = (result << 7) | (byte & 0x7F)
            if byte < 0x80:
                return result, i + 1
        else:  # 9th byte uses all 8 bits
            result = (result << 8) | byte
            return result, 9

def parse_column_value(data, offset, col_type):
    """Parse a column value based on its type code. Returns (value, bytes_read)."""
    if col_type == 0:  # NULL
        return None, 0
    elif col_type == 1:  # 8-bit integer
        return struct.unpack('>b', data[offset:offset+1])[0], 1
    elif col_type == 2:  # 16-bit integer
        return struct.unpack('>h', data[offset:offset+2])[0], 2
    elif col_type == 3:  # 24-bit integer
        val = int.from_bytes(data[offset:offset+3], 'big', signed=True)
        return val, 3
    elif col_type == 4:  # 32-bit integer
        return struct.unpack('>i', data[offset:offset+4])[0], 4
    elif col_type == 5:  # 48-bit integer
        val = int.from_bytes(data[offset:offset+6], 'big', signed=True)
        return val, 6
    elif col_type == 6:  # 64-bit integer
        return struct.unpack('>q', data[offset:offset+8])[0], 8
    elif col_type == 7:  # 64-bit float
        return struct.unpack('>d', data[offset:offset+8])[0], 8
    elif col_type == 8:  # Constant 0
        return 0, 0
    elif col_type == 9:  # Constant 1
        return 1, 0
    elif col_type >= 12 and col_type % 2 == 0:  # BLOB
        length = (col_type - 12) // 2
        return data[offset:offset+length], length
    elif col_type >= 13 and col_type % 2 == 1:  # TEXT
        length = (col_type - 13) // 2
        return data[offset:offset+length].decode('utf-8', errors='replace'), length
    else:
        return None, 0
```

**When to use Strategy C**:
- Base DB file is missing entirely
- Base DB is corrupted and cannot be repaired
- WAL contains pages that don't exist in the base DB (page numbers exceed DB size)
- You need to extract data from specific pages without reconstructing the full database

**Strategy C Example: Extract from WAL-only scenario**
```python
import struct, json

# Decode WAL (assuming XOR 0x42 encoding detected)
wal_data = open('/app/main.db-wal', 'rb').read()
decoded = bytes([b ^ 0x42 for b in wal_data])

page_size = struct.unpack('>I', decoded[8:12])[0]

# Parse all frames, keeping only the latest version of each page
page_map = {}  # page_num -> page_data (latest committed version)
offset = 32
while offset + 24 + page_size <= len(decoded):
    pg_num = struct.unpack('>I', decoded[offset:offset+4])[0]
    commit_flag = struct.unpack('>I', decoded[offset+4:offset+8])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    page_map[pg_num] = page_data  # Later frames override earlier ones
    offset += 24 + page_size

# Extract records from all leaf table pages
all_records = []
for pg_num, page_data in page_map.items():
    page_type = page_data[100] if pg_num == 1 else page_data[0]
    if page_type == 13:  # Leaf table page
        records = parse_btree_page(page_data, pg_num)
        all_records.extend(records)

# Export to JSON
all_records.sort(key=lambda x: x.get('rowid', 0))
open('/app/recovered.json', 'w').write(json.dumps(all_records, indent=2))
```

### Phase 4: Extract and Export Data

Once the database is readable:
1. Query the schema: `.tables` and `.schema <table>`
2. For each table, `SELECT * FROM <table>`
3. Format as JSON array of objects (column_name: value)
4. Sort by primary key or as specified
5. Write to the required output file (typically `/app/recovered.json`)

## Handling Multiple WAL Files and Salt Validation

If the task provides multiple WAL files (e.g., `main.db-wal`, `main.db-wal2`):
1. Decode each WAL independently
2. Parse frames from all WALs
3. Apply frames in order: earlier WAL first, then later WALs
4. Within a WAL, apply frames sequentially (later transactions override earlier ones for the same page)
5. Only apply frames from committed transactions (see transaction grouping above)

**Salt validation**: Each frame's `salt1` and `salt2` values must match the WAL header's `salt1` and `salt2`. When salts don't match, the frame belongs to a **different WAL session** (the WAL was reset/recycled between sessions). Such frames should NOT be applied to this database. This is especially important when a WAL file contains frames from two different sessions — only use frames matching the header's salt.

```python
# Salt check during frame validation
header_salt1 = header['salt1']
header_salt2 = header['salt2']
for frame in frames:
    if frame['salt1'] != header_salt1 or frame['salt2'] != header_salt2:
        frame['valid'] = False  # Different WAL session — skip
```

## Handling Partial or Split Updates

If WAL frames don't form complete transactions:
- A transaction is a contiguous group of frames: zero or more frames with `commit_flag = 0`, followed by exactly one frame with `commit_flag > 0`
- Frames within a transaction are **atomic**: apply ALL of them or NONE of them
- Only apply complete transactions (all frames up to and including the commit frame)
- Partial transactions at the end of a WAL (frames after the last commit frame, all with `commit_flag = 0`) should be **discarded entirely**
- Applying a partial transaction can corrupt the database's B-tree structure

## Diagnostic Checklist

When facing a recovery task:
- [ ] Identify all files: `.db`, `.db-wal`, `.db-shm`, any additional WAL files
- [ ] Check if base DB exists and is readable; count records it contains
- [ ] Examine WAL file size and first bytes
- [ ] Determine encoding by trying transformations against known WAL magic
- [ ] Decode the WAL
- [ ] Validate WAL structure (header, frames, checksums, salts)
- [ ] Choose recovery strategy:
  - **A** if decoded WAL has valid checksums → let SQLite read it
  - **B** if WAL has some corrupt frames but base DB is intact → manual page application
  - **C** if base DB is missing or severely corrupted → parse raw pages from WAL
- [ ] Apply recovery
- [ ] Verify all expected records are present
- [ ] Export to required format

**Decision tree for strategy selection**:
```
Base DB exists and readable?
├─ YES → Decode WAL → Checksums valid after decode?
│        ├─ YES → Strategy A (direct SQLite)
│        └─ NO  → Repair checksums → Still invalid?
│                 ├─ YES → Strategy B (manual frame application)
│                 └─ NO  → Strategy A (after repair)
└─ NO  → Strategy C (extract from raw WAL pages)
```

## Common Pitfalls

1. **SQLite auto-checkpoint**: Opening a database with `sqlite3` may auto-checkpoint the WAL, consuming or discarding it. Always backup the WAL before opening the DB.
2. **SHM file interference**: A stale `-shm` file can prevent SQLite from reading a repaired WAL. Always delete it before recovery.
3. **Checksum byte order**: The checksum byte order depends on the creating machine. Try both LE and BE if validation fails.
4. **Page numbering**: WAL page numbers are 1-indexed. Page 1 is the schema/root page.
5. **Commit flag semantics**: `commit_flag > 0` means this frame is the last in its transaction. The value itself is the database size in pages after commit. Frames within a transaction are atomic — applying only part of a transaction corrupts the B-tree. Always group by transaction and discard uncommitted trailing frames.

## Example: Single-byte XOR Recovery

```python
import struct, sqlite3, os

wal_path = '/app/main.db-wal'
db_path = '/app/main.db'

# Read the encoded WAL
wal_data = open(wal_path, 'rb').read()

# Detect XOR key by checking first byte against known magic 0x37
for key in range(1, 256):
    test = bytes([wal_data[i] ^ key for i in range(4)])
    magic = struct.unpack('>I', test)[0]
    if magic in (0x377F0682, 0x377F0683):
        page_size = struct.unpack('>I', bytes([wal_data[8+i] ^ key for i in range(4)]))[0]
        if page_size in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
            # Decode entire WAL
            decoded = bytes([b ^ key for b in wal_data])
            # Backup original WAL
            open(wal_path + '.bak', 'wb').write(wal_data)
            # Write decoded WAL
            open(wal_path, 'wb').write(decoded)
            # Remove SHM
            shm = db_path + '-shm'
            if os.path.exists(shm): os.remove(shm)
            # Read database
            conn = sqlite3.connect(db_path)
            # Get all tables
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            # Export data
            import json
            result = []
            for table in tables:
                cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
                for row in conn.execute(f"SELECT * FROM {table}"):
                    result.append(dict(zip(cols, row)))
            conn.close()
            # Sort and write
            result.sort(key=lambda x: x.get('id', 0))
            open('/app/recovered.json', 'w').write(json.dumps(result, indent=2))
            break
```

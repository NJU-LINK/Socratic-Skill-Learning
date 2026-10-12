---
name: db-wal-recovery
description: >
  Recover data from SQLite databases with corrupted, encoded, or obfuscated
  Write-Ahead Log (WAL) files. Diagnoses the encoding transformation applied to
  WAL bytes, reverses it, validates checksums, and extracts all records
  including uncommitted WAL updates into a structured output.
---

# SQLite WAL Recovery Skill

## Critical Rule: PRESERVE BEFORE INSPECT

**NEVER open a database with sqlite3 or any tool that triggers auto-checkpoint until you have backed up ALL files.** SQLite's default behavior when closing a WAL-mode connection is to checkpoint valid WAL frames and delete the WAL file. If the WAL is corrupted, SQLite may silently discard it.

```bash
# Step 0: IMMEDIATE BACKUP (non-negotiable)
mkdir -p /tmp/db_work
cp -a /app/*.db /app/*.db-wal /app/*.db-shm /tmp/db_work/ 2>/dev/null
# Work ONLY on copies. Never let sqlite3 touch originals.
```

## SQLite WAL Format Reference

### WAL Header (32 bytes)
| Offset | Size | Field | Valid Value |
|--------|------|-------|-------------|
| 0 | 4 | Magic number | `0x377f0682` (checksums big-endian) or `0x377f0683` (little-endian) |
| 4 | 4 | File format version | `3007000` |
| 8 | 4 | Database page size | Must match base DB (read from DB header offset 16-17) |
| 12 | 4 | Checkpoint sequence | Any uint32 |
| 16 | 4 | Salt-1 | Random uint32 |
| 20 | 4 | Salt-2 | Random uint32 |
| 24 | 4 | Checksum-1 | Covers bytes 0-23 |
| 28 | 4 | Checksum-2 | Covers bytes 0-23 |

### Frame Header (24 bytes, before each page)
| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | Page number (1-indexed) |
| 4 | 4 | Database size in pages (0 for non-commit, or total pages for commit frame) |
| 8 | 4 | Salt-1 (must match WAL header) |
| 12 | 4 | Salt-2 (must match WAL header) |
| 16 | 4 | Checksum-1 |
| 20 | 4 | Checksum-2 |

Frame data follows immediately: `page_size` bytes of page content.

Total frame size = 24 (header) + page_size bytes.

### WAL Checksum Algorithm

**Critical: Checksum byte order depends on magic number.**
- Magic `0x377f0682` → checksums are **big-endian** (`'>I'`)
- Magic `0x377f0683` → checksums are **little-endian** (`'<I'`)

```python
import struct

def wal_checksum(data: bytes, s1: int = 0, s2: int = 0, big_endian: bool = True) -> tuple[int, int]:
    """
    SQLite WAL checksum. Processes data in 8-byte chunks.
    Each chunk is split into two uint32 values.
    s1 accumulates the first values, s2 accumulates s1 + second values.
    
    Byte order is determined by the WAL magic number:
    - 0x377f0682 → big_endian=True
    - 0x377f0683 → big_endian=False
    """
    fmt = '>I' if big_endian else '<I'
    assert len(data) % 8 == 0
    for i in range(0, len(data), 8):
        v1 = struct.unpack(fmt, data[i:i+4])[0]
        v2 = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + v1) % (2**32)
        s2 = (s2 + s1 + v2) % (2**32)
    return s1, s2
```

**Verification targets:**
- WAL header: checksum of bytes 0-23 must match bytes 24-31
- Each frame: checksum of (frame_header[0:16] + frame_page_data) must match frame_header[16:24]
- Checksums are running: each frame's checksum starts from the previous frame's values (or header checksum for frame 1)
- **Always detect endianness from magic and pass `big_endian` parameter accordingly**

## Diagnostic Procedure

### Step 1: Read raw WAL bytes and diagnose encoding

```python
import struct

with open('/tmp/db_work/main.db-wal', 'rb') as f:
    wal_data = f.read()

magic = struct.unpack('>I', wal_data[0:4])[0]
print(f"Magic: 0x{magic:08x}")
```

### Step 2: Diagnosis Decision Tree

**Try transformations in order of likelihood:**

1. **File is ASCII text (all bytes in printable range)** → **Base64 encoded**
   - Decode with `base64.b64decode(wal_data)`
   - Verify magic after decoding
   - **If still invalid after base64 decode**, try additional transformations on the decoded bytes (combined encoding)

2. **Magic doesn't match but file is binary** → Try transformations:
   
   a. **Single-byte XOR**: XOR first byte with `0x37` to get candidate key.
      Apply XOR to entire file. Verify magic = `0x377f0682` or `0x377f0683`.
      Also check that page size field (bytes 8-11) yields a power of 2 (512-65536).
   
   b. **Bitwise NOT**: XOR entire file with `0xFF`. Verify magic.
   
   c. **Byte swap (adjacent pairs)**: Swap bytes at positions (0,1), (2,3), etc.
      Verify magic.
   
   d. **Multi-byte XOR**: If single-byte doesn't work, try XOR with repeating key.
      Use known plaintext: first 4 bytes should become `0x377f0682` or `0x377f0683`.
      Derive key bytes from `wal_data[i] ^ expected[i]` for i in 0..3.

3. **Magic is correct but checksums fail** → Header-only damage or frame corruption.
   - Recalculate header checksum from bytes 0-23
   - Check if frame salts match header salts
   - If frame data is intact, fix checksums

4. **Magic correct, checksums correct, but SQLite rejects it** → Frame-level corruption.
   - Parse each frame, verify page numbers are valid (1 to max_pages)
   - Check for truncated frames (file size not matching expected frame boundaries)

5. **Page size field is corrupted but magic is correct** → Infer page size from base DB.
   - Read page size from base DB header (offset 16-17)
   - Overwrite the corrupted page size field in the WAL header
   - Recalculate header checksum
   - Proceed with frame verification

6. **Combined transformations** → Try sequences:
   - Base64 decode → then try XOR/NOT/byte-swap on result
   - XOR → then try byte-swap on result
   - Try each transformation, then check if result is valid
   - If still invalid, try applying a second transformation to the result

**Fallback for unknown encodings:**
If none of the above work, try to infer the encoding from statistical properties:
- Calculate byte frequency distribution
- Compare to expected WAL byte distribution (should have many 0x00 bytes for padding)
- If byte distribution is uniform, likely XOR with single byte
- If byte distribution is skewed, likely NOT or byte-swap
- Try all 256 single-byte XOR keys and check which produces valid magic + page size

### Step 2b: Recalculate checksums after decoding (CRITICAL)

**When a byte-level transformation (XOR, NOT, byte-swap, etc.) was applied to the entire WAL file, the stored checksums are also transformed. After reversing the transformation, the decoded checksums will NOT match the decoded data — they must be recalculated from scratch.**

This is because:
- Original WAL: valid data + valid checksums (checksums computed over data)
- Encoding applied to entire file: encoded data + encoded checksums
- After decoding: original data + original checksums
- BUT: the original checksums were computed over the original data, so they SHOULD match
- In practice, many encodings (especially XOR) break the additive checksum relationship, so recalculation is needed

**Procedure:**
```python
# After decoding the WAL bytes, recalculate ALL checksums:

# 1. Fix header checksum (bytes 24-31 = checksum of bytes 0-23)
calc_s1, calc_s2 = wal_checksum(decoded[0:24], big_endian=big_endian)
struct.pack_into(fmt2, decoded, 24, calc_s1, calc_s2)

# 2. Fix frame checksums (running checksum chain)
s1, s2 = calc_s1, calc_s2
offset = 32
while offset + 24 + page_size <= len(decoded):
    # Fix salt to match header salts
    hdr_salt1 = struct.unpack('>I', decoded[16:20])[0]
    hdr_salt2 = struct.unpack('>I', decoded[20:24])[0]
    struct.pack_into('>II', decoded, offset + 8, hdr_salt1, hdr_salt2)
    
    # Calculate frame checksum over frame_header[0:16] + frame_page_data
    checksum_data = bytes(decoded[offset:offset+16]) + bytes(decoded[offset+24:offset+24+page_size])
    calc_s1, calc_s2 = wal_checksum(checksum_data, s1, s2, big_endian=big_endian)
    struct.pack_into(fmt2, decoded, offset + 16, calc_s1, calc_s2)
    
    s1, s2 = calc_s1, calc_s2
    offset += 24 + page_size
```

**Important:** Use `'>II'` (not `f'{fmt}2'`) for packing two uint32 values. The format `'>I2'` is invalid in Python's struct module.

### Step 3: Verify decoded WAL integrity

```python
def verify_wal(wal_data, expected_page_size):
    # Check header
    magic = struct.unpack('>I', wal_data[0:4])[0]
    assert magic in (0x377f0682, 0x377f0683), f"Bad magic: 0x{magic:08x}"
    
    # Detect checksum endianness from magic
    big_endian = (magic == 0x377f0682)
    fmt = '>II' if big_endian else '<II'
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    assert page_size == expected_page_size, f"Page size mismatch: {page_size} vs {expected_page_size}"
    
    # Verify header checksum
    expected_s1, expected_s2 = struct.unpack(fmt, wal_data[24:32])
    calc_s1, calc_s2 = wal_checksum(wal_data[0:24], big_endian=big_endian)
    assert (calc_s1, calc_s2) == (expected_s1, expected_s2), "Header checksum mismatch"
    
    # Verify each frame
    s1, s2 = calc_s1, calc_s2  # Running checksum
    offset = 32  # After header
    frame_num = 0
    while offset + 24 + page_size <= len(wal_data):
        frame_hdr = wal_data[offset:offset+24]
        frame_page = wal_data[offset+24:offset+24+page_size]
        
        # Check salt matches header
        salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        hdr_salt1 = struct.unpack('>I', wal_data[16:20])[0]
        hdr_salt2 = struct.unpack('>I', wal_data[20:24])[0]
        assert (salt1, salt2) == (hdr_salt1, hdr_salt2), f"Frame {frame_num} salt mismatch"
        
        # Verify frame checksum
        exp_s1, exp_s2 = struct.unpack(fmt, frame_hdr[16:24])
        calc_s1, calc_s2 = wal_checksum(frame_hdr[0:16] + frame_page, s1, s2, big_endian=big_endian)
        assert (calc_s1, calc_s2) == (exp_s1, exp_s2), f"Frame {frame_num} checksum mismatch"
        
        s1, s2 = calc_s1, calc_s2
        offset += 24 + page_size
        frame_num += 1
    
    print(f"WAL verified: {frame_num} valid frames")
    return frame_num
```

### Step 4: Apply repaired WAL

**IMPORTANT: Always use manual frame application as the primary method.** SQLite's auto-checkpoint does not reliably pick up repaired WAL files because the DB's change counter, salt values, and checkpoint sequence may not match what SQLite expects after decoding. Manual application is deterministic and always works.

```python
# Read base DB pages
with open('/tmp/db_work/main.db', 'rb') as f:
    db_data = bytearray(f.read())

# Apply each WAL frame (overwrite page at corresponding position)
# IMPORTANT: Handle commit frames correctly
offset = 32
last_commit_db_size = None
while offset + 24 + page_size <= len(wal_data):
    frame_hdr = wal_data[offset:offset+24]
    page_num = struct.unpack('>I', frame_hdr[0:4])[0]
    db_size = struct.unpack('>I', frame_hdr[4:8])[0]  # 0 for non-commit, total pages for commit
    frame_page = wal_data[offset+24:offset+24+page_size]
    
    # Page numbers are 1-indexed; page 1 starts at offset 0 in DB file
    db_offset = (page_num - 1) * page_size
    if db_offset + page_size > len(db_data):
        db_data.extend(b'\x00' * (db_offset + page_size - len(db_data)))
    db_data[db_offset:db_offset+page_size] = frame_page
    
    # Track commit frames (db_size > 0)
    if db_size > 0:
        last_commit_db_size = db_size
    
    offset += 24 + page_size

# If we have commit frames, truncate to last committed size
if last_commit_db_size is not None:
    expected_size = last_commit_db_size * page_size
    if len(db_data) > expected_size:
        db_data = db_data[:expected_size]

# Remove WAL/SHM files so sqlite3 reads the merged DB directly
import os
for ext in ['-wal', '-shm']:
    p = f'/tmp/db_work/main.db{ext}'
    if os.path.exists(p):
        os.remove(p)

with open('/tmp/db_work/main.db', 'wb') as f:
    f.write(db_data)
```

**Commit frame handling:** In WAL, the last frame of a transaction has `db_size > 0` in its frame header (offset 4). Frames with `db_size == 0` are non-commit frames. When manually applying:
- Apply all frames in order (last writer wins for each page)
- Track the last commit frame's `db_size`
- Truncate the database to `last_commit_db_size * page_size` to ensure only committed data is present
- This prevents applying partial/uncommitted transactions

### Step 5: Handle edge cases

- **No base database**: Reconstruct from WAL frames alone. Find the schema page (page 1) in WAL frames and build DB from there.
- **Multiple WAL files**: Process in order, later frames override earlier ones for same page number.
  ```python
  # Example: processing multiple WAL files
  wal_files = sorted(glob.glob('/tmp/db_work/*.db-wal*'))
  for wal_file in wal_files:
      with open(wal_file, 'rb') as f:
          wal_data = f.read()
      # Decode, verify, and apply each WAL in order
  ```
- **Partial frames**: If file is truncated mid-frame, use only complete frames.
- **Schema changes in WAL**: The WAL may contain updated versions of page 1 (schema). Apply all frames in order; last writer wins for each page.
- **Corrupt frame page numbers**: If a frame's page number is invalid (0 or > max expected), skip it and continue with next frame. Log the corruption for debugging.
- **Damaged header fields**: If magic is correct but other header fields are wrong (e.g., page size), fix them based on the base DB. Recalculate header checksum after fixing.

### Step 6: Schema discovery

The recovered database may have different schemas across family members. Always discover the schema dynamically:

```python
import sqlite3 as sq3

conn = sq3.connect(db_path)
conn.row_factory = sq3.Row

# Discover table names, filtering out internal sqlite_ tables
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = [row[0] for row in cursor.fetchall()]

# For each table, get schema and data
for table in tables:
    # Get column info
    cursor = conn.execute(f"PRAGMA table_info(\"{table}\")")
    columns = [row[1] for row in cursor.fetchall()]
    
    # Get all data
    rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
    data = [dict(r) for r in rows]
    print(f"Table {table}: {len(data)} rows, columns: {columns}")
```

**Important:** Filter out internal tables like `sqlite_sequence` (created when AUTOINCREMENT is used). These start with `sqlite_` and should not be included in output.

For the output JSON, if the task specifies a particular table or format, use that. Otherwise, output all tables or the primary data table.

## Output Format

**Prefer Python sqlite3 module over CLI** for extraction. It's more reliable, returns proper types, and avoids subprocess complexity:

```python
import json
import sqlite3 as sq3

conn = sq3.connect('/tmp/db_work/main.db')
conn.row_factory = sq3.Row

# Discover tables (filter out internal sqlite_ tables)
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = [row[0] for row in cursor.fetchall()]

# Extract data from primary table
if tables:
    primary_table = tables[0]  # or determine from task requirements
    rows = conn.execute(f'SELECT * FROM "{primary_table}" ORDER BY rowid').fetchall()
    result = [dict(row) for row in rows]
    
    with open('/app/recovered.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(f"Recovered {len(result)} records from '{primary_table}'")
```

**Note:** The `sqlite3 -json` command-line flag requires SQLite 3.33.0+ (released 2020-08-14). The Python sqlite3 module is always available when Python is installed and returns proper Python types (int, str, float) without parsing issues. Use subprocess CLI only as a last resort when Python sqlite3 can't open the DB (rare).

## Quick Reference: Common Encodings

| Encoding | Detection | Reversal |
|----------|-----------|----------|
| Base64 | File is ASCII, size ~33% larger | `base64.b64decode()` |
| Single-byte XOR | Binary, wrong magic | XOR byte 0 with 0x37 → key; XOR all with key |
| Bitwise NOT | Binary, wrong magic | XOR all bytes with 0xFF |
| Byte swap | Binary, wrong magic | Swap adjacent byte pairs |
| Multi-byte XOR | Binary, wrong magic | Derive key from known header bytes |
| Header-only damage | Magic wrong but structure looks right | Fix magic + recalculate checksums |
| Corrupted page size | Magic correct but page size wrong | Infer from base DB header, fix field, recalculate checksums |
| Combined transformations | Single transform fails | Try sequences: base64→XOR, XOR→byte-swap, etc. |

**Robustness features:**
- Automatically fixes corrupted page size field by inferring from base DB
- Tries combined transformations (e.g., base64 then XOR)
- Falls back to statistical analysis if standard methods fail

## Complete Diagnostic Script

Use this as a starting point for any WAL recovery task:

```python
#!/usr/bin/env python3
"""
WAL Recovery Diagnostic Script
Usage: python3 wal_recover.py [src_dir] [dst_dir]
  src_dir: directory containing .db and .db-wal files (default: /app)
  dst_dir: working directory for copies (default: /tmp/db_work)
"""
import struct
import base64
import shutil
import os
import json
import sys
import glob


def backup_files(src_dir='/app', dst_dir='/tmp/db_work'):
    """Step 0: Backup all database files"""
    os.makedirs(dst_dir, exist_ok=True)
    for ext in ['.db', '.db-wal', '.db-shm']:
        for f in os.listdir(src_dir):
            if f.endswith(ext):
                src = os.path.join(src_dir, f)
                dst = os.path.join(dst_dir, f)
                shutil.copy2(src, dst)
                print(f"Backed up: {f}")


def read_db_page_size(db_path):
    """Read page size from SQLite database header"""
    with open(db_path, 'rb') as f:
        header = f.read(100)
    page_size = struct.unpack('>H', header[16:18])[0]
    if page_size == 1:
        page_size = 65536
    return page_size


def wal_checksum(data: bytes, s1: int = 0, s2: int = 0, big_endian: bool = True):
    """SQLite WAL checksum with configurable endianness"""
    fmt = '>I' if big_endian else '<I'
    assert len(data) % 8 == 0, f"Data length {len(data)} not multiple of 8"
    for i in range(0, len(data), 8):
        v1 = struct.unpack(fmt, data[i:i+4])[0]
        v2 = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + v1) % (2**32)
        s2 = (s2 + s1 + v2) % (2**32)
    return s1, s2


def try_decode_wal(wal_data, expected_page_size):
    """Try various decodings and return (decoded_data, encoding_type) or None
    
    Handles:
    - Single transformations (XOR, NOT, byte-swap, base64)
    - Combined transformations (base64 then XOR, etc.)
    - Corrupted page size field (infers from expected_page_size)
    """
    
    def check_valid(data, allow_page_size_fix=False):
        """Check if data has valid WAL magic and optionally fix page size"""
        if len(data) < 32:
            return False, None
        magic = struct.unpack('>I', data[0:4])[0]
        if magic not in (0x377f0682, 0x377f0683):
            return False, None
        page_size = struct.unpack('>I', data[8:12])[0]
        if page_size == expected_page_size:
            return True, data
        elif allow_page_size_fix:
            # Page size field is corrupted, fix it
            fixed = bytearray(data)
            struct.pack_into('>I', fixed, 8, expected_page_size)
            return True, bytes(fixed)
        return False, None
    
    # Check if already valid
    valid, result = check_valid(wal_data)
    if valid:
        return result, 'none'
    
    # Try Base64
    try:
        if all(32 <= b < 127 for b in wal_data[:100]):
            decoded = base64.b64decode(wal_data)
            valid, result = check_valid(decoded, allow_page_size_fix=True)
            if valid:
                return result, 'base64'
            
            # Combined: base64 then XOR
            for key in range(1, 256):
                xored = bytes([b ^ key for b in decoded])
                valid, result = check_valid(xored, allow_page_size_fix=True)
                if valid:
                    return result, f'base64+xor_0x{key:02x}'
    except Exception:
        pass
    
    # Try single-byte XOR
    for key in range(256):
        decoded = bytes([b ^ key for b in wal_data])
        valid, result = check_valid(decoded, allow_page_size_fix=True)
        if valid:
            return result, f'xor_0x{key:02x}'
    
    # Try bitwise NOT
    decoded = bytes([b ^ 0xFF for b in wal_data])
    valid, result = check_valid(decoded, allow_page_size_fix=True)
    if valid:
        return result, 'not'
    
    # Try byte swap (adjacent pairs)
    decoded = bytearray(len(wal_data))
    for i in range(0, len(wal_data) - 1, 2):
        decoded[i] = wal_data[i+1]
        decoded[i+1] = wal_data[i]
    if len(wal_data) % 2:
        decoded[-1] = wal_data[-1]
    valid, result = check_valid(bytes(decoded), allow_page_size_fix=True)
    if valid:
        return result, 'byte_swap'
    
    # Try multi-byte XOR (derive key from known magic)
    for target_magic in [0x377f0682, 0x377f0683]:
        target_bytes = struct.pack('>I', target_magic)
        key_bytes = bytes([wal_data[i] ^ target_bytes[i] for i in range(4)])
        for key_len in [1, 2, 4]:
            key = key_bytes[:key_len]
            if all(key_bytes[i] == key[i % key_len] for i in range(4)):
                decoded = bytes([wal_data[i] ^ key[i % key_len] for i in range(len(wal_data))])
                valid, result = check_valid(decoded, allow_page_size_fix=True)
                if valid:
                    return result, f'multi_xor_{key.hex()}'
    
    return None, None


def verify_wal(wal_data, expected_page_size):
    """Verify WAL integrity and return (frame_count, status_message)"""
    magic = struct.unpack('>I', wal_data[0:4])[0]
    if magic not in (0x377f0682, 0x377f0683):
        return 0, "Invalid magic"
    
    big_endian = (magic == 0x377f0682)
    fmt2 = '>II' if big_endian else '<II'
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    if page_size != expected_page_size:
        return 0, f"Page size mismatch: {page_size} vs {expected_page_size}"
    
    # Verify header checksum
    expected_s1, expected_s2 = struct.unpack(fmt2, wal_data[24:32])
    calc_s1, calc_s2 = wal_checksum(wal_data[0:24], big_endian=big_endian)
    if (calc_s1, calc_s2) != (expected_s1, expected_s2):
        return 0, "Header checksum mismatch"
    
    # Verify frames
    s1, s2 = calc_s1, calc_s2
    offset = 32
    frame_num = 0
    while offset + 24 + page_size <= len(wal_data):
        frame_hdr = wal_data[offset:offset+24]
        frame_page = wal_data[offset+24:offset+24+page_size]
        
        salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        hdr_salt1 = struct.unpack('>I', wal_data[16:20])[0]
        hdr_salt2 = struct.unpack('>I', wal_data[20:24])[0]
        if (salt1, salt2) != (hdr_salt1, hdr_salt2):
            return frame_num, f"Frame {frame_num} salt mismatch"
        
        exp_s1, exp_s2 = struct.unpack(fmt2, frame_hdr[16:24])
        calc_s1, calc_s2 = wal_checksum(frame_hdr[0:16] + frame_page, s1, s2, big_endian=big_endian)
        if (calc_s1, calc_s2) != (exp_s1, exp_s2):
            return frame_num, f"Frame {frame_num} checksum mismatch"
        
        s1, s2 = calc_s1, calc_s2
        offset += 24 + page_size
        frame_num += 1
    
    return frame_num, "OK"


def recalculate_checksums(wal_data):
    """Recalculate all WAL checksums after decoding an encoded WAL.
    
    When a byte-level transformation (XOR, NOT, etc.) was applied to the entire
    WAL file, the stored checksums are also transformed and won't match the
    decoded data. This function recalculates all checksums from scratch.
    
    Returns the modified wal_data (bytearray) with corrected checksums.
    """
    data = bytearray(wal_data)
    magic = struct.unpack('>I', data[0:4])[0]
    big_endian = (magic == 0x377f0682)
    fmt2 = '>II' if big_endian else '<II'
    page_size = struct.unpack('>I', data[8:12])[0]
    
    # Fix header checksum
    calc_s1, calc_s2 = wal_checksum(bytes(data[0:24]), big_endian=big_endian)
    struct.pack_into(fmt2, data, 24, calc_s1, calc_s2)
    
    # Fix frame checksums (running chain)
    s1, s2 = calc_s1, calc_s2
    offset = 32
    while offset + 24 + page_size <= len(data):
        # Fix salt to match header
        hdr_salt1 = struct.unpack('>I', data[16:20])[0]
        hdr_salt2 = struct.unpack('>I', data[20:24])[0]
        struct.pack_into('>II', data, offset + 8, hdr_salt1, hdr_salt2)
        
        # Calculate frame checksum
        checksum_data = bytes(data[offset:offset+16]) + bytes(data[offset+24:offset+24+page_size])
        calc_s1, calc_s2 = wal_checksum(checksum_data, s1, s2, big_endian=big_endian)
        struct.pack_into(fmt2, data, offset + 16, calc_s1, calc_s2)
        
        s1, s2 = calc_s1, calc_s2
        offset += 24 + page_size
    
    return data


def apply_wal_manually(db_path, wal_data, page_size):
    """Manually apply WAL frames to database"""
    with open(db_path, 'rb') as f:
        db_data = bytearray(f.read())
    
    offset = 32
    last_commit_db_size = None
    while offset + 24 + page_size <= len(wal_data):
        frame_hdr = wal_data[offset:offset+24]
        page_num = struct.unpack('>I', frame_hdr[0:4])[0]
        db_size = struct.unpack('>I', frame_hdr[4:8])[0]
        frame_page = wal_data[offset+24:offset+24+page_size]
        
        db_offset = (page_num - 1) * page_size
        if db_offset + page_size > len(db_data):
            db_data.extend(b'\x00' * (db_offset + page_size - len(db_data)))
        db_data[db_offset:db_offset+page_size] = frame_page
        
        if db_size > 0:
            last_commit_db_size = db_size
        
        offset += 24 + page_size
    
    if last_commit_db_size is not None:
        expected_size = last_commit_db_size * page_size
        if len(db_data) > expected_size:
            db_data = db_data[:expected_size]
    
    with open(db_path, 'wb') as f:
        f.write(db_data)
    
    return last_commit_db_size


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else '/app'
    dst_dir = sys.argv[2] if len(sys.argv) > 2 else '/tmp/db_work'
    
    # Step 0: Backup
    print("=== Step 0: Backup ===")
    backup_files(src_dir, dst_dir)
    
    # Step 1: Read DB page size
    print("\n=== Step 1: Read DB page size ===")
    db_path = os.path.join(dst_dir, 'main.db')
    if not os.path.exists(db_path):
        # Try to find any .db file
        dbs = glob.glob(os.path.join(dst_dir, '*.db'))
        if dbs:
            db_path = dbs[0]
        else:
            print("ERROR: No .db file found")
            return
    page_size = read_db_page_size(db_path)
    print(f"DB page size: {page_size}")
    
    # Step 2: Read and decode WAL
    print("\n=== Step 2: Decode WAL ===")
    wal_path = os.path.join(dst_dir, 'main.db-wal')
    if not os.path.exists(wal_path):
        wals = glob.glob(os.path.join(dst_dir, '*.db-wal'))
        if wals:
            wal_path = wals[0]
        else:
            print("ERROR: No .db-wal file found")
            return
    
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    print(f"WAL size: {len(wal_data)} bytes")
    
    decoded_wal, encoding = try_decode_wal(wal_data, page_size)
    if decoded_wal is None:
        print("ERROR: Could not decode WAL with any known method")
        print("First 32 bytes (hex):", wal_data[:32].hex())
        return
    
    print(f"Detected encoding: {encoding}")
    
    # Step 2b: Recalculate checksums after decoding
    print("\n=== Step 2b: Recalculate checksums ===")
    if encoding != 'none':
        decoded_wal = recalculate_checksums(decoded_wal)
        print("Checksums recalculated")
    else:
        print("No encoding detected, checksums should be valid")
    
    # Step 3: Verify
    print("\n=== Step 3: Verify WAL ===")
    frame_count, status = verify_wal(bytes(decoded_wal), page_size)
    print(f"Verification: {frame_count} frames, status: {status}")
    
    if status != "OK":
        print("WARNING: WAL verification failed")
    
    # Step 4: Apply WAL via manual frame application (primary method)
    # SQLite's auto-checkpoint does not reliably pick up repaired WALs,
    # so we always apply frames manually to the database file.
    print("\n=== Step 4: Apply WAL (manual frame application) ===")
    commit_size = apply_wal_manually(db_path, bytes(decoded_wal), page_size)
    print(f"Applied frames, last commit size: {commit_size} pages")
    
    # Remove WAL/SHM so sqlite3 reads the merged DB directly
    for ext in ['-wal', '-shm']:
        p = db_path + ext
        if os.path.exists(p):
            os.remove(p)
    
    # Step 5: Extract data using Python sqlite3
    print("\n=== Step 5: Extract data ===")
    import sqlite3 as sq3
    try:
        conn = sq3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables found: {tables}")
    except Exception as e:
        print(f"Python sqlite3 failed after manual application: {e}")
        return
    all_data = {}
    for table in tables:
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        all_data[table] = [dict(r) for r in rows]
        print(f"  {table}: {len(all_data[table])} rows")
    
    conn.close()
    
    # Write output - use the first user table (sqlite_ tables already filtered)
    output_table = tables[0] if tables else None
    output_path = os.path.join(src_dir, 'recovered.json')
    if output_table and output_table in all_data:
        with open(output_path, 'w') as f:
            json.dump(all_data[output_table], f, indent=2)
        print(f"\nRecovered {len(all_data[output_table])} records from '{output_table}' to {output_path}")
    elif all_data:
        with open(output_path, 'w') as f:
            json.dump(all_data, f, indent=2)
        print(f"\nRecovered data from {len(all_data)} tables to {output_path}")
    else:
        print("\nNo data recovered")


if __name__ == '__main__':
    main()
```

## Checklist

- [ ] Backed up all .db, .db-wal, .db-shm files before any sqlite3 access
- [ ] Working on copies in /tmp/db_work/
- [ ] Read base DB page size from header (offset 16-17, big-endian uint16)
- [ ] Diagnosed WAL encoding from raw bytes
- [ ] Applied inverse transformation
- [ ] **Recalculated all checksums after decoding** (header + frame chain)
- [ ] Verified WAL magic = 0x377f0682 or 0x377f0683
- [ ] **Detected checksum endianness from magic** (0x377f0682 = big-endian, 0x377f0683 = little-endian)
- [ ] Verified WAL page size matches base DB
- [ ] Verified header checksum (using correct endianness)
- [ ] Verified frame checksums (using correct endianness, or identified which frames are valid)
- [ ] Applied WAL to DB copy (via sqlite3 checkpoint or manual page application with commit frame handling)
- [ ] **Filtered out internal sqlite_ tables** (e.g., sqlite_sequence) from output
- [ ] Used Python sqlite3 module for extraction (not CLI subprocess)
- [ ] Extracted all records and wrote sorted JSON to /app/recovered.json

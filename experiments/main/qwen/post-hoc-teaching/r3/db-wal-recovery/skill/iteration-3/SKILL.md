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

**If WAL is missing after backup**: This can happen if SQLite consumed it on first open, or if it was never provided. In this case:
- If base DB exists → read directly from base DB (skip to Step 5)
- If base DB is missing → error, cannot proceed
- Check backup directory for WAL file that may have been consumed

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

**Decision tree for missing files**:
- Base DB present, WAL present → normal recovery (continue to Step 2)
- Base DB present, WAL missing → read from base DB only (skip to Step 5)
- Base DB missing, WAL present → reconstruct DB from WAL (use Method C in Step 4)
- Both missing → error, cannot proceed

## Step 2: Diagnose WAL Encoding

Read the first 4 bytes of the WAL file. If they match `0x377f0682` or `0x377f0683`, the WAL is intact. Otherwise, diagnose the transformation.

### Systematic Encoding Discovery

Use a layered approach to identify the encoding:

**Layer 1: Check for known magic patterns**
```python
def detect_encoding(wal_data):
    """Systematically identify WAL encoding."""
    if len(wal_data) < 32:
        return None, "file too short"
    
    magic = wal_data[:4]
    
    # Already valid?
    if magic in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
        return None, "none (valid WAL)"
    
    # Try single-byte XOR (most common)
    for key in range(1, 256):
        decoded = bytes(b ^ key for b in wal_data[:32])
        if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
            # Use magic-aware byte order
            bo = 'big' if decoded[:4] == b'\x37\x7f\x06\x82' else 'little'
            version = int.from_bytes(decoded[4:8], bo)
            page_size = int.from_bytes(decoded[8:12], bo)
            if (version == 3007000 and 
                512 <= page_size <= 65536 and 
                (page_size & (page_size - 1)) == 0):
                return ('xor', key), f"XOR with key 0x{key:02x}"
    
    # Try base64
    import base64
    try:
        decoded = base64.b64decode(wal_data.strip())
        if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
            return ('base64', None), "base64"
    except:
        pass
    
    # Try bit inversion
    decoded = bytes(~b & 0xFF for b in wal_data)
    if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
        return ('invert', None), "bitwise inversion"
    
    # Try byte swap
    if len(wal_data) % 2 == 0:
        decoded = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 2):
            decoded[i] = wal_data[i+1]
            decoded[i+1] = wal_data[i]
        if bytes(decoded[:4]) in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
            return ('swap', None), "byte swap"
    
    # Try combinations: base64 + XOR
    try:
        b64d = base64.b64decode(wal_data.strip())
        for key in range(1, 256):
            decoded = bytes(b ^ key for b in b64d[:32])
            if decoded[:4] in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
                # Use magic-aware byte order
                bo = 'big' if decoded[:4] == b'\x37\x7f\x06\x82' else 'little'
                version = int.from_bytes(decoded[4:8], bo)
                page_size = int.from_bytes(decoded[8:12], bo)
                if (version == 3007000 and 
                    512 <= page_size <= 65536 and 
                    (page_size & (page_size - 1)) == 0):
                    return ('b64+xor', key), f"base64 + XOR(0x{key:02x})"
    except:
        pass
    
    # Try multi-byte XOR using known-plaintext attack
    # The WAL header has predictable bytes: magic + version + page_size
    # This allows O(key_len) key derivation instead of O(256^key_len) brute force
    result = detect_repeating_xor_key(wal_data)
    if result:
        key, desc = result
        return ('xor_multi', key), desc
    
    return None, "unknown encoding"


def detect_repeating_xor_key(wal_data, db_path=None):
    """Derive repeating XOR key from known plaintext (WAL header).
    
    The WAL header has predictable bytes:
    - Bytes 0-3: magic (one of two known values)
    - Bytes 4-7: version (always 3007000, byte order depends on magic)
    - Bytes 8-11: page_size (power of 2, byte order depends on magic)
    
    For a repeating key of length N, derive key bytes from known plaintext.
    This is O(key_len) instead of O(256^key_len) brute force.
    """
    if len(wal_data) < 32:
        return None
    
    # Version 3007000 in both byte orders
    version_be = b'\x00\x2d\xe2\x18'  # big-endian
    version_le = b'\x18\xe2\x2d\x00'  # little-endian
    
    db_page_size = None
    if db_path and os.path.exists(db_path):
        try:
            db_page_size = get_db_page_size(db_path)
        except:
            pass
    
    for target_magic in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
        # Determine byte order for this magic
        bo = 'big' if target_magic == b'\x37\x7f\x06\x82' else 'little'
        version_bytes = version_be if bo == 'big' else version_le
        
        for key_len in range(2, min(33, len(wal_data) + 1)):
            key = bytearray(key_len)
            
            # Bytes 0-3: magic
            for i in range(min(key_len, 4)):
                key[i] = wal_data[i] ^ target_magic[i]
            
            # Bytes 4-7: version (byte order depends on magic)
            for i in range(4, min(key_len, 8)):
                key[i] = wal_data[i] ^ version_bytes[i - 4]
            
            # Bytes 8-11: page_size (byte order depends on magic)
            if key_len > 8:
                page_sizes = [4096, 8192, 1024, 2048, 16384, 32768, 65536, 512]
                if db_page_size:
                    page_sizes.insert(0, db_page_size)
                
                found_valid = False
                for ps in page_sizes:
                    ps_bytes = ps.to_bytes(4, bo)  # Use magic-aware byte order
                    trial_key = bytearray(key)
                    for i in range(8, min(key_len, 12)):
                        trial_key[i] = wal_data[i] ^ ps_bytes[i - 8]
                    
                    decoded = bytes(wal_data[i] ^ trial_key[i % key_len] 
                                   for i in range(min(32, len(wal_data))))
                    if _valid_header_after_decode(decoded):
                        key = trial_key
                        found_valid = True
                        break
                
                if not found_valid:
                    continue
            
            # Verify full header
            decoded = bytes(wal_data[i] ^ key[i % key_len] 
                           for i in range(min(32, len(wal_data))))
            if _valid_header_after_decode(decoded):
                return bytes(key), f"repeating-XOR({key_len} bytes)"
    
    return None


def _valid_header_after_decode(decoded):
    """Check if decoded bytes form a valid WAL header."""
    if len(decoded) < 32:
        return False
    
    magic = decoded[:4]
    if magic not in (b'\x37\x7f\x06\x82', b'\x37\x7f\x06\x83'):
        return False
    
    # Use magic-aware byte order
    bo = 'big' if magic == b'\x37\x7f\x06\x82' else 'little'
    
    version = int.from_bytes(decoded[4:8], bo)
    if version != 3007000:
        return False
    
    page_size = int.from_bytes(decoded[8:12], bo)
    if not (512 <= page_size <= 65536 and (page_size & (page_size - 1)) == 0):
        return False
    
    return True
```

**Layer 2: Entropy and pattern analysis** (if Layer 1 fails)
```python
import math
from collections import Counter

def analyze_entropy(data):
    """Analyze byte entropy to distinguish encoding types."""
    counts = Counter(data)
    entropy = -sum((c/len(data)) * math.log2(c/len(data)) 
                   for c in counts.values())
    return entropy

def detect_patterns(data):
    """Detect repeating patterns that suggest specific encodings."""
    # Check for alternating bytes (byte swap)
    if len(data) > 100:
        even_bytes = set(data[0::2])
        odd_bytes = set(data[1::2])
        if len(even_bytes) < 20 or len(odd_bytes) < 20:
            return "byte_swap_candidate"
    
    # Check for base64 character set
    b64_chars = set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
    if all(b in b64_chars for b in data[:1000]):
        return "base64_candidate"
    
    # High entropy suggests encryption or complex encoding
    entropy = analyze_entropy(data[:1000])
    if entropy > 7.5:
        return "high_entropy (possible encryption)"
    
    return "no_pattern_detected"
```

**Layer 3: Manual inspection** (if automated detection fails)
- Use `xxd` or `hexdump` to examine byte patterns
- Look for repeating sequences, character distributions
- Check if file size matches expected WAL size: `32 + N * (24 + page_size)`
- Compare with base DB page size to determine expected page_size

### Damaged Header Fields

If the WAL has the right magic but invalid format version or page size:
- Format version should be `3007000`
- Page size should be a power of 2 between 512 and 65536
- **Use base DB page size as hint**: Read page size from base DB header (bytes 16-17)
- Repair by overwriting with correct values and recomputing the header checksum

```python
def get_db_page_size(db_path):
    """Read page size from SQLite database header."""
    with open(db_path, 'rb') as f:
        f.read(16)  # Skip magic string
        page_size = int.from_bytes(f.read(2), 'big')
        return page_size if page_size != 1 else 65536  # 1 means 65536
```

## Step 3: Decode the WAL

Apply the reverse transformation to the entire WAL file:

```python
def decode_wal(wal_data, encoding_info):
    """Decode WAL based on detected encoding."""
    enc_type, enc_param = encoding_info
    
    if enc_type is None:
        return wal_data  # Already valid
    
    if enc_type == 'xor':
        return bytes(b ^ enc_param for b in wal_data)
    
    elif enc_type == 'base64':
        import base64
        return base64.b64decode(wal_data.strip())
    
    elif enc_type == 'invert':
        return bytes(~b & 0xFF for b in wal_data)
    
    elif enc_type == 'swap':
        decoded = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 2):
            decoded[i] = wal_data[i+1]
            decoded[i+1] = wal_data[i]
        return bytes(decoded)
    
    elif enc_type == 'b64+xor':
        import base64
        b64d = base64.b64decode(wal_data.strip())
        return bytes(b ^ enc_param for b in b64d)
    
    elif enc_type == 'xor_multi':
        key = enc_param
        return bytes(wal_data[i] ^ key[i % len(key)] for i in range(len(wal_data)))
    
    else:
        raise ValueError(f"Unknown encoding type: {enc_type}")
```

### Verify Integrity After Decoding

**CRITICAL**: Use magic-aware byte order for ALL header field reads, not just checksums.

```python
def get_byte_order(magic):
    """Get byte order for all header fields based on magic number."""
    return 'big' if magic == b'\x37\x7f\x06\x82' else 'little'


def verify_wal(wal_data):
    """Verify WAL header and frame checksums with magic-aware byte order."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)  # Byte order for ALL fields
    
    # Header checksum
    calc_cs1, calc_cs2 = wal_checksum(wal_data[:24], magic=magic)
    stored_cs1 = int.from_bytes(wal_data[24:28], bo)
    stored_cs2 = int.from_bytes(wal_data[28:32], bo)
    
    if calc_cs1 != stored_cs1 or calc_cs2 != stored_cs2:
        return False, "header checksum mismatch"
    
    # Frame checksums (running) - ALL fields use magic-aware byte order
    page_size = int.from_bytes(wal_data[8:12], bo)  # Magic-aware
    frame_size = 24 + page_size
    salt1 = int.from_bytes(wal_data[16:20], bo)  # Magic-aware
    salt2 = int.from_bytes(wal_data[20:24], bo)  # Magic-aware
    
    offset = 32
    running_cs1, running_cs2 = calc_cs1, calc_cs2
    frame_count = 0
    
    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset+24]
        pd = wal_data[offset+24:offset+frame_size]
        
        # Verify salt - magic-aware
        if int.from_bytes(fh[8:12], bo) != salt1:
            return False, f"frame {frame_count} salt1 mismatch"
        if int.from_bytes(fh[12:16], bo) != salt2:
            return False, f"frame {frame_count} salt2 mismatch"
        
        # Verify checksum
        cs_data = fh[:8] + pd
        running_cs1, running_cs2 = wal_checksum(cs_data, running_cs1, running_cs2, magic=magic)
        
        if running_cs1 != int.from_bytes(fh[16:20], bo):  # Magic-aware
            return False, f"frame {frame_count} checksum1 mismatch"
        if running_cs2 != int.from_bytes(fh[20:24], bo):  # Magic-aware
            return False, f"frame {frame_count} checksum2 mismatch"
        
        offset += frame_size
        frame_count += 1
    
    return True, f"valid, {frame_count} frames"
```

**If verification fails**:
- Try repairing header fields (format version, page size) and recomputing checksum
- If frame checksums fail but header is valid → partial corruption, apply only valid frames
- If all frames fail → encoding detection was wrong, try alternative decodings

## Step 4: Apply WAL to Database

**CRITICAL**: The integrity check result determines the recovery path, not just gets printed.

### Integrity-Driven Recovery Strategy

After decoding and verifying the WAL, use the integrity check to choose the recovery path:

```python
valid, msg = verify_wal_integrity(decoded_wal)
print(f"Integrity: {msg}")

if valid:
    # ENCODING DAMAGE ONLY: decoded WAL is fully valid
    # → Write decoded WAL and let SQLite consume it directly
    print("Recovery path: SQLite auto-read (encoding damage only)")
    open(wal_path, 'wb').write(decoded_wal)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    data = extract_all_data(conn)
    conn.close()
else:
    # STRUCTURAL DAMAGE: some frames or header fields are corrupt
    print("Recovery path: Structural damage detected, attempting repair")
    
    # Try header repair first
    repaired = repair_wal_header(decoded_wal, db_path)
    valid2, msg2 = verify_wal_integrity(repaired)
    print(f"After header repair: {msg2}")
    
    if valid2:
        # Header repair fixed it → apply via SQLite
        print("Recovery path: SQLite auto-read (after header repair)")
        open(wal_path, 'wb').write(repaired)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_autocheckpoint=0")
        data = extract_all_data(conn)
        conn.close()
    else:
        # Still corrupt → selective frame application
        print("Recovery path: Selective frame application (partial corruption)")
        frames = parse_and_validate_frames(repaired)
        valid_frames = [f for f in frames if f['checksum_valid']]
        print(f"Valid frames: {len(valid_frames)}/{len(frames)}")
        
        if not valid_frames:
            print("ERROR: No valid frames found", file=sys.stderr)
            sys.exit(1)
        
        apply_valid_frames(db_path, valid_frames, repaired)
        conn = sqlite3.connect(db_path)
        data = extract_all_data(conn)
        conn.close()
```

**Key principle**: Pure encoding damage → SQLite auto-read. Structural damage → selective frame application with only verified-good frames.

### Method A: Let SQLite Handle It (Preferred for Valid WALs)

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
    magic = wal_data[:4]
    bo = get_byte_order(magic)  # Magic-aware byte order
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = 24 + page_size
    
    # Read existing database
    db_data = bytearray(open(db_path, 'rb').read())
    
    offset = 32  # Skip WAL header
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], bo)
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

### Method C: Reconstruct from Frames (Base DB Missing)

When the base database is missing or severely corrupted:

1. Parse all WAL frames
2. Identify the latest version of each page (last frame for each page number)
3. Assemble pages into a complete database
4. **Ensure page 1 has a valid database header** (critical for SQLite to recognize it)
5. Write the reconstructed database

```python
def reconstruct_from_frames(wal_data):
    magic = wal_data[:4]
    bo = get_byte_order(magic)  # Magic-aware byte order
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = 24 + page_size
    
    # Collect latest version of each page
    pages = {}
    offset = 32
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], bo)
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
    
    # Verify page 1 has valid SQLite header
    if not db_data[:16].startswith(b'SQLite format 3\x00'):
        # Page 1 is missing or corrupt - cannot reconstruct
        return None
    
    return bytes(db_data)
```

**If page 1 is missing from WAL**: The database cannot be reconstructed from WAL alone. You need the base database or external schema information.

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

**Adapt output format to the task requirements**:

For single-table output (most common):
```python
import json

# Build records as list of dicts
records = []
for row in rows:
    record = dict(zip(col_names, row))
    records.append(record)

# Determine sort key from task requirements or schema
# Common patterns: 'id', primary key, first column
sort_key = None
if 'id' in col_names:
    sort_key = 'id'
else:
    # Check for primary key
    pk_cols = [col[1] for col in conn.execute(f"PRAGMA table_info({table_name})") if col[5] == 1]
    if pk_cols:
        sort_key = pk_cols[0]
    else:
        sort_key = col_names[0]  # Default to first column

records.sort(key=lambda x: x.get(sort_key, 0))

# Write output
with open('/app/recovered.json', 'w') as f:
    json.dump(records, f, indent=2)
```

For multi-table output (preserve relationships):
```python
all_data = {}
for (table_name,) in tables:
    columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table_name})")]
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    all_data[table_name] = [dict(zip(columns, row)) for row in rows]

# Output structure depends on task requirements
# Option 1: Nested by table
with open('/app/recovered.json', 'w') as f:
    json.dump(all_data, f, indent=2)

# Option 2: Flat list with table identifier
flat_records = []
for table_name, records in all_data.items():
    for record in records:
        record['_table'] = table_name
        flat_records.append(record)
```

**Key principle**: The output format must match the task's declared requirements. If the task says "sorted by id" → sort by id. If it says "preserve relationships" → use nested structure. Always read the task instructions carefully.

## Handling Edge Cases

### Partial Frames

If some frames are corrupted but others are valid:
1. Verify each frame's checksum independently
2. Apply only valid frames
3. For invalid frames, try to repair:
   - Fix salt values to match header
   - Recompute checksum if page data appears intact
4. Determine if you have enough valid frames to reconstruct the required data

### Multiple WAL Files

If updates are split across multiple WAL files:
1. Decode each WAL file independently
2. Parse frames from all WALs
3. Apply frames in order:
   - Sort by checkpoint sequence number (from WAL header)
   - Within same checkpoint, sort by frame order
4. Later frames overwrite earlier ones for the same page

### Distinguishing Encoding Damage from Structural Damage

- **Encoding damage**: The entire file is transformed uniformly (XOR, base64, etc.). After reversing the transformation, the WAL should be fully valid with correct checksums.
- **Structural damage**: Individual frames or header fields are corrupted. The WAL may have correct magic but invalid checksums, wrong page numbers, or missing frames.

**Diagnosis approach**:
1. Try decoding transformations first
2. If decoded WAL has valid checksums → it was encoding damage
3. If decoded WAL has invalid checksums → structural damage (needs frame-level repair)
4. If no decoding produces valid checksums → encoding detection failed, try alternative methods

### WAL File Consumed by SQLite

If the WAL file disappears after first SQLite connection:
1. Check backup directory (`/tmp/wal_recovery_backup/`) for preserved copy
2. If backup exists → restore from backup and retry
3. If no backup → WAL data may be checkpointed into base DB
   - Try reading from base DB directly
   - If data is incomplete → cannot recover without WAL backup

**Prevention**: Always backup before any SQLite connection (Step 0).

## Complete Recovery Pipeline

```python
#!/usr/bin/env python3
import sqlite3, json, os, struct, base64, shutil, glob

# 0. Find database and backup artifacts
db_files = [f for f in glob.glob('/app/*.db') if not f.endswith(('-wal', '-shm'))]
db_path = None
for f in db_files:
    with open(f, 'rb') as fh:
        if fh.read(16).startswith(b'SQLite format 3'):
            db_path = f
            break

if not db_path:
    raise RuntimeError("No SQLite database found")

backup_dir = '/tmp/wal_recovery_backup'
os.makedirs(backup_dir, exist_ok=True)
for suffix in ['', '-wal', '-shm']:
    src = db_path + suffix
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(backup_dir, os.path.basename(src)))

# 1. Locate WAL file
wal_path = db_path + '-wal'
if not os.path.exists(wal_path):
    # Check backup
    wal_backup = os.path.join(backup_dir, os.path.basename(db_path) + '-wal')
    if os.path.exists(wal_backup):
        shutil.copy2(wal_backup, wal_path)
    else:
        # No WAL available, read from base DB only
        conn = sqlite3.connect(db_path)
        data = extract_all_data(conn)
        write_json(data, '/app/recovered.json')
        conn.close()
        exit(0)

# 2. Read and diagnose WAL
wal_data = open(wal_path, 'rb').read()
encoding_info, enc_desc = detect_encoding(wal_data)
print(f"Encoding: {enc_desc}")

# 3. Decode WAL
decoded_wal = decode_wal(wal_data, encoding_info)

# 4. Verify and optionally repair
valid, msg = verify_wal(decoded_wal)
if not valid:
    print(f"WAL verification failed: {msg}")
    decoded_wal = repair_wal_header(decoded_wal, db_path)
    valid, msg = verify_wal(decoded_wal)
    if not valid:
        raise RuntimeError(f"Cannot repair WAL: {msg}")

# 5. Apply WAL
open(wal_path, 'wb').write(decoded_wal)
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA wal_autocheckpoint=0")

# 6. Extract and output
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
- WAL file size must be `32 + N * (24 + page_size)` for some integer N ≥ 0

## Variation Points

Per the spec, these dimensions vary across the family:

1. **Encoding**: XOR key varies (single or multi-byte); may be base64, inversion, byte swap, combinations, or other transformations. The invariant is that the transformation can be diagnosed from the supplied artifacts.

2. **Integrity**: Base DB may be missing, frames may be partial, multiple WALs possible, WAL may be consumed by SQLite before backup. The solver must distinguish encoding damage from structural damage.

3. **Recovery depth**: From simple WAL decode + SQLite read, to manual frame parsing, to full reconstruction from frames. Method selection depends on which artifacts are available and their integrity.

4. **Schema**: Single or multiple tables, varying column types and key structures. Output must preserve complete rows, key relationships, uniqueness, and the case's declared ordering contract.

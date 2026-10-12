---
name: db-wal-recovery
description: Recover data from corrupted, encoded, or damaged SQLite WAL (Write-Ahead Logging) files by diagnosing the encoding/transformation, reversing it, fixing checksums, and extracting all records including WAL updates.
---

# SQLite WAL Recovery Skill

## Trigger Conditions

Apply this skill when you encounter:
- A SQLite database in WAL mode with a companion `.db-wal` file
- The WAL file appears corrupted, encrypted, or encoded (doesn't start with magic `0x377F0682` or `0x377F0683`)
- SQLite only shows base database records, not the full dataset that should include WAL updates
- Task requires recovering ALL data including WAL changes

## Critical Workflow

**ALWAYS copy the WAL file BEFORE opening the database with SQLite.** SQLite will automatically checkpoint and delete the WAL when opened, destroying the encoded data you need to recover.

```bash
cp main.db-wal main.db-wal.backup
```

## WAL File Structure Reference

### WAL Header (32 bytes)
| Offset | Size | Field | Expected Value |
|--------|------|-------|----------------|
| 0 | 4 | Magic | `0x377F0682` (big-endian) or `0x377F0683` (little-endian) |
| 4 | 4 | Format version | `3007000` (0x002DE728) |
| 8 | 4 | Database page size | Power of 2, 512–65536; must match base DB header offset 16-17 |
| 12 | 4 | Checkpoint sequence | Small integer (0, 1, 2, ...) |
| 16 | 4 | Salt-1 | Random, must match all frame salts |
| 20 | 4 | Salt-2 | Random, must match all frame salts |
| 24 | 4 | Checksum-1 | Over bytes 0-23 |
| 28 | 4 | Checksum-2 | Over bytes 0-23 |

### Frame Structure (24 + page_size bytes each)
| Offset | Size | Field |
|--------|------|-------|
| +0 | 4 | Page number (1-based, big-endian) |
| +4 | 4 | Database size after commit (0 = non-commit, >0 = commit frame) |
| +8 | 4 | Salt-1 (must equal WAL header salt-1) |
| +12 | 4 | Salt-2 (must equal WAL header salt-2) |
| +16 | 4 | Frame checksum-1 |
| +20 | 4 | Frame checksum-2 |
| +24 | page_size | Page data |

## Diagnosis Methodology

### Step 1: Check WAL Magic
```python
with open('main.db-wal', 'rb') as f:
    magic = struct.unpack('>I', f.read(4))[0]
    
if magic not in (0x377F0682, 0x377F0683):
    # WAL is encoded/obfuscated
```

### Step 2: Read Expected Page Size from Base DB
```python
with open('main.db', 'rb') as f:
    f.seek(16)
    page_size = struct.unpack('>H', f.read(2))[0]
    if page_size == 1:
        page_size = 65536
```

### Step 3: Derive XOR Key via Known-Plaintext Attack

You know two fields with certainty:
- Magic (bytes 0-3): `37 7F 06 82` or `37 7F 06 83`
- Page size (bytes 8-11): from base DB

XOR corrupted bytes with expected values to derive key:
```python
# For single-byte XOR
key_byte = corrupted_byte ^ expected_byte

# For multi-byte repeating XOR, derive each position
for i in range(key_length):
    key[i] = corrupted[i] ^ expected[i]
```

Verify consistency: the same key must decode BOTH magic AND page size correctly.

### Step 4: Validate Against Frame Structure
After decoding:
- Frame salts must match header salts
- Page numbers must be ≥ 1
- Frame count: `(wal_size - 32) / (24 + page_size)` should be integer

## Common Encodings in This Family

1. **Single-byte XOR** (e.g., 0x42): Every byte XORed with same value
2. **Multi-byte repeating XOR**: Key repeats every N bytes (e.g., 4-byte key `42 42 E2 42`)
3. **Bitwise NOT**: All bits inverted (equivalent to XOR 0xFF)
4. **Byte swapping**: Pairs of bytes swapped
5. **Base64 wrapper**: WAL encoded as base64 text
6. **Damaged header fields**: Specific fields corrupted, rest intact

The recovery script automatically detects these encoding types via `detect_encoding_type()` before attempting XOR key derivation.

## WAL Checksum Algorithm

**CRITICAL**: The SQLite WAL checksum is a **RUNNING checksum** that chains through all frames, not independent per-frame checksums.

Checksum algorithm uses two running 32-bit unsigned sums (mod 2³²):
```python
def wal_checksum(data, s1=0, s2=0, big_endian=True):
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        x = struct.unpack(fmt, data[i:i+4])[0]
        y = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + x + s2) % (1 << 32)
        s2 = (s2 + y + s1) % (1 << 32)
    return s1, s2
```

**Header checksum**: Computed over bytes 0-23 (checksum fields zeroed), starting from s1=0, s2=0

**Frame checksums**: **RUNNING checksum** that chains from the header checksum through all frames:
1. Start with header checksum values (s1, s2)
2. For each frame: compute checksum over (frame header with checksum fields zeroed + page data)
3. Each frame's checksum continues from the previous frame's checksum values
4. Frame checksum fields store the cumulative checksum after processing that frame

**IMPORTANT**: XOR/encoding transformations corrupt checksums. After decoding an encoded WAL, the original checksums are preserved but were computed on the original (unencoded) data. Recomputing checksums on decoded data will produce different values because the checksum algorithm depends on the exact byte values.

**PRACTICAL IMPLICATION**: WAL repair via checksum recomputation is unreliable for encoded WALs. Use **Approach A (Direct Page Application)** as the primary recovery method, which bypasses checksum validation entirely.

## Recovery Approaches (Priority Order)

### Approach A: Direct Page Application (RECOMMENDED — PRIMARY METHOD)
This is the most reliable method and works in all cases, including encoded WALs:
1. Copy base DB to new file
2. Decode each frame, extract page data
3. Write each page at offset `(page_number - 1) * page_size` in the copy
4. For commit frames (db_size > 0), update DB header:
   - Offset 28-31: set to db_size (database page count)
   - Offset 24-27: increment change counter
5. Open modified DB with sqlite3 and export to JSON

**Why this works**: Directly overwriting database pages bypasses WAL checksum validation entirely. The page data itself is correct after decoding, so the database structure is preserved.

**Important**: Apply ALL frames in order. Later frames for the same page number overwrite earlier ones. The final state uses the last frame for each page number.

### Approach B: Fix WAL, Let SQLite Consume It (UNRELIABLE for encoded WALs)
This approach attempts to repair the WAL for native SQLite consumption:
1. Decode WAL with derived key
2. Recompute header checksum (bytes 0-23)
3. Recompute all frame checksums using RUNNING checksum algorithm
4. Write fixed WAL back to `main.db-wal`
5. Open with `sqlite3 main.db "SELECT * FROM ..."` — SQLite auto-applies valid WAL frames
6. Export to JSON

**Limitations**: 
- XOR/encoding transformations corrupt checksums in ways that are difficult to repair
- Even with correct checksum recomputation, SQLite may reject the WAL
- Use Approach A as the primary method; Approach B is a fallback only

### Approach C: Manual B-tree Parsing (Last Resort)
If both A and B fail, parse SQLite B-tree structure manually from decoded pages.

## Implementation Template

```python
#!/usr/bin/env python3
import struct, json, sqlite3, shutil, os

def recover_wal(db_path, wal_path, output_path):
    # 1. Read page size from base DB
    with open(db_path, 'rb') as f:
        f.seek(16)
        page_size = struct.unpack('>H', f.read(2))[0]
        if page_size == 1:
            page_size = 65536
    
    # 2. Read and decode WAL
    with open(wal_path, 'rb') as f:
        raw_wal = f.read()
    
    # Derive XOR key (example: single-byte 0x42)
    key = derive_xor_key(raw_wal, page_size)
    decoded_wal = xor_decode(raw_wal, key)
    
    # 3. Apply pages directly (Approach A)
    shutil.copy2(db_path, db_path + '.recovered')
    with open(db_path + '.recovered', 'r+b') as f:
        frame_size = 24 + page_size
        num_frames = (len(decoded_wal) - 32) // frame_size
        for i in range(num_frames):
            offset = 32 + i * frame_size
            page_num = struct.unpack('>I', decoded_wal[offset:offset+4])[0]
            db_size = struct.unpack('>I', decoded_wal[offset+4:offset+8])[0]
            page_data = decoded_wal[offset+24:offset+24+page_size]
            
            # Write page at correct offset
            f.seek((page_num - 1) * page_size)
            f.write(page_data)
            
            # Update DB header for commit frames
            if db_size > 0:
                f.seek(28)
                f.write(struct.pack('>I', db_size))
    
    # 4. Extract all records with CORRECT column names
    conn = sqlite3.connect(db_path + '.recovered')
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    
    records = []
    for table in tables:
        # CRITICAL: PRAGMA table_info returns (cid, name, type, notnull, dflt_value, pk)
        # Use index [1] to get column NAME, not index [0] which is column ID
        cols = [d[1] for d in conn.execute(f"PRAGMA table_info({table})")]
        for row in conn.execute(f"SELECT * FROM {table}"):
            rec = dict(zip(cols, row))
            records.append(rec)
    
    conn.close()
    
    # 5. Sort and write JSON
    records.sort(key=lambda r: r.get('id', 0))
    with open(output_path, 'w') as f:
        json.dump(records, f, indent=2)
    
    return records
```

## Verification Checklist

After recovery, verify:
- [ ] All expected records present (check count)
- [ ] Records sorted correctly (by id or declared ordering)
- [ ] JSON format matches specification
- [ ] No data corruption (spot-check values)
- [ ] WAL file properly consumed or removed

## Common Pitfalls

1. **Opening DB before copying WAL**: SQLite will checkpoint and delete WAL
2. **Forgetting to recompute checksums**: SQLite will reject WAL with bad checksums
3. **Wrong byte order in checksums**: Must match magic (0x82=big, 0x83=little)
4. **Incorrect page size**: Must match base DB, not assumed
5. **Missing commit frames**: Only frames with db_size > 0 represent committed transactions
6. **WRONG PRAGMA table_info INDEX**: `PRAGMA table_info(table)` returns tuples `(cid, name, type, notnull, dflt_value, pk)`. Use **index [1]** to get column NAME, not index [0] which is the column ID (0, 1, 2, ...). Using index [0] produces JSON with keys "0", "1", "2" instead of "id", "name", "value".

## Family Variation Handling

This skill handles the `db-wal-recovery` family which varies along:
- **Encoding/obfuscation**: XOR variants, NOT, byte swap, base64, damaged headers
- **Integrity**: Trustworthy base DB, missing base, corrupted frames, partial frames
- **Recovery depth**: Direct WAL consumption, page application, manual reconstruction
- **Schema topology**: Single/multiple tables, different column types, ordering contracts

### Handling Missing Base Database

When only the WAL file exists (no base DB), the script:
1. Tries common page sizes (4096, 8192, 16384, 32768, 1024, 512)
2. Validates each by checking if XOR key derivation succeeds
3. Reconstructs database from WAL frames using `reconstruct_from_wal_only()`

### Configurable Success Threshold

The `recover()` function accepts `min_records` parameter (default=1) to validate recovery success. This prevents false failures when base DB has fewer records than hardcoded thresholds.

Adapt the diagnosis and recovery approach based on the specific case while following the core workflow: **detect encoding → decode → parse frames → apply pages → extract data**.

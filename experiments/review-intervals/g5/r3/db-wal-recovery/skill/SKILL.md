---
name: db-wal-recovery
description: >
  Recover data from SQLite databases with corrupted, encrypted, or obfuscated WAL (Write-Ahead Logging) files.
  Handles various encoding schemes (XOR, NOT, base64, byte-swap), structural damage (bad checksums, mismatched salts),
  and different recovery depths (direct SQLite replay, manual page extraction).
---

# SQLite WAL Recovery Skill

## Problem Family

This skill addresses recovery of SQLite databases where the WAL file is corrupted, encrypted, or obfuscated. The WAL file contains uncommitted transactions that haven't been checkpointed into the main database file. When the WAL is damaged, SQLite cannot replay these transactions, resulting in data loss.

### Variation Dimensions

According to the spec, cases vary along four axes:

1. **WAL encoding/obfuscation**: How the WAL bytes differ from a directly usable WAL
   - Single-byte XOR with any key (0x00-0xFF)
   - Bitwise inversion (NOT, equivalent to XOR 0xFF)
   - Base64 encoding
   - Byte swapping (pairs or quads)
   - Damaged header fields
   - Intact WAL (no encoding)

2. **WAL and base database integrity**: Which parts remain trustworthy
   - Usable base database with missing WAL updates (most common)
   - Missing base database entirely
   - Corrupted frame page numbers or headers
   - Partial frames
   - Multiple WAL files split across updates

3. **Recovery depth**: Amount of manual SQLite recovery required
   - SQLite can consume repaired WAL directly (most common)
   - Frames must be parsed and applied to database pages manually
   - Fresh database/output must be reconstructed from recoverable pages

4. **Schema and update topology**: Structure of recovered data
   - Single table or multiple related tables
   - Different column types and primary keys
   - Different record volumes
   - Updates distributed across one or more WAL streams

## Critical Procedure Order

**ALWAYS follow this order to avoid data loss:**

1. **Backup** both database and WAL files BEFORE opening with sqlite3
2. **Read raw WAL bytes** and diagnose encoding
3. **Decode** the WAL (reverse the encoding)
4. **Repair WAL structure** (recompute checksums, fix salts)
5. **Try Strategy 1: SQLite WAL replay** (write repaired WAL, open with sqlite3)
6. **If replay fails, use Strategy 2: Manual page application** (apply frames directly to database pages)
7. **Extract data** and write output

**Why this order matters:** SQLite's WAL-mode behavior on open:
- Reads the WAL header
- If invalid → treats WAL as corrupt → may truncate, delete, or ignore it
- If valid but checksums fail → may roll back or truncate to last valid frame
- Even if checksums are valid, internal state mismatches (checkpoint_seq, schema cookies) can cause silent failure

Opening the database before decoding the WAL will cause SQLite to destroy the encoded WAL file.

**Critical insight:** SQLite WAL replay often fails even after perfect decoding and checksum repair. The most reliable approach is to try replay first, then fall back to manual page application if it returns too few rows.

## SQLite WAL File Structure

### WAL Header (32 bytes)

| Offset | Size | Field | Expected Value |
|--------|------|-------|----------------|
| 0 | 4 | Magic number | `0x377f0682` (big-endian) or `0x377f0683` (little-endian) |
| 4 | 4 | File format version | `3007000` (for SQLite 3.7.0+) |
| 8 | 4 | Database page size | Must match base DB (commonly 4096) |
| 12 | 4 | Checkpoint sequence | Usually 0 |
| 16 | 4 | Salt-1 | Random |
| 20 | 4 | Salt-2 | Random |
| 24 | 4 | Checksum-1 | Running checksum |
| 28 | 4 | Checksum-2 | Running checksum |

### WAL Frames (repeated)

Each frame = **24-byte frame header** + **page_size bytes of page data**

Frame header:
| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | Page number (1-indexed, big-endian) |
| 4 | 4 | Database size after commit (0 for non-commit frames) |
| 8 | 4 | Salt-1 (must match WAL header) |
| 12 | 4 | Salt-2 (must match WAL header) |
| 16 | 4 | Checksum-1 |
| 20 | 4 | Checksum-2 |

### WAL Checksum Algorithm

The WAL checksum is a **cumulative** running sum:
- For each 32-bit word `w`:
  - `s1 = (s1 + w + s2) % 2^32`
  - `s2 = (s2 + s1) % 2^32`
- Endianness determined by magic number LSB:
  - `0x...82` = big-endian (words read as big-endian)
  - `0x...83` = little-endian (words read as little-endian)
- Checksum storage format matches endianness
- Checksum is cumulative: header checksum feeds into frame 1, which feeds into frame 2, etc.

## Diagnostic Methodology

When encountering a corrupted/obfuscated WAL:

1. **Read the first 32 bytes** and check the magic number
   - If valid (`0x377f0682` or `0x377f0683`) → no encoding, check for structural damage
   - If invalid → file is encoded/obfuscated

2. **Try simple decodings** on the first few bytes:
   - Single-byte XOR (try all 256 values; check if any produces valid magic)
   - Bitwise inversion (NOT every byte)
   - Base64 decoding (if file looks like ASCII text)
   - Byte swapping (reverse pairs or quads)

3. **Check the page size field** (offset 8-12)
   - Must be a power of 2 between 512 and 65536
   - Must match the base database's page size

4. **Validate frame structure**: After decoding, walk the frames
   - Each frame header's salt values must match the WAL header's salt values
   - Page numbers must be valid (positive integers)
   - Frame size must be exactly `24 + page_size` bytes

5. **Distinguish encoding damage from structural damage**:
   - If decoding produces a valid header but frames have bad checksums or impossible page numbers → structural damage
   - Structural damage requires manual page extraction and repair

## Recovery Script

The skill provides `scripts/recover.py` which implements the complete recovery procedure:

```bash
python3 scripts/recover.py [db_path] [wal_path] [output_json]
```

**Defaults:**
- `db_path`: `/app/main.db`
- `wal_path`: `/app/main.db-wal`
- `output_json`: `/app/recovered.json`

**What the script does:**
1. Backs up both files (`.bak` extension)
2. **Handles missing base database** (creates empty DB from WAL if needed)
3. **Finds all WAL files** (main.db-wal, main.db-wal2, main.db-wal3, etc.)
4. Counts base database rows (before any recovery)
5. Reads raw WAL bytes (concatenates if multiple WAL files)
6. Diagnoses encoding by trying various decodings against known magic numbers
7. Decodes the entire WAL
8. Repairs WAL structure (recomputes all checksums, fixes frame salts)
9. **Validates frame structure** (checks page numbers, handles partial frames)
10. **Strategy 1**: Writes repaired WAL, opens with sqlite3 (SQLite replays the valid WAL)
11. **Strategy 2** (if replay fails): Restores database from backup, manually applies WAL frames to database pages
12. Extracts all rows from all tables
13. Sorts by `id` if present
14. Writes JSON output

**Why two strategies?** SQLite's WAL replay can fail silently even with valid checksums due to internal state mismatches (checkpoint_seq, schema cookies, connection state). Manual page application bypasses SQLite's WAL logic entirely and is more reliable.

**Handles:**
- Single-byte XOR with any key
- Bitwise NOT
- Base64 encoding
- Byte swapping (pairs or quads)
- No encoding (valid WAL with structural damage)
- Single or multiple tables
- Various column types and schemas
- **Multiple WAL files** (main.db-wal, main.db-wal2, etc.)
- **Missing base database** (reconstructs from WAL frames)
- **Partial frames** (skips incomplete frames at end of WAL)
- **Invalid page numbers** (validates and skips suspicious frames)

**Limitations:**
- Assumes at least one file (database or WAL) is present
- Assumes encoding is byte-preserving or reversible (base64)
- Does not handle multiple unrelated databases in same directory
- Does not handle WAL files with completely corrupted headers (magic number unrecognizable)

## Manual Recovery (When Script Fails)

If the script cannot recover the data automatically, follow this manual procedure:

### 1. Decode the WAL
```python
raw = open('main.db-wal', 'rb').read()
# Apply identified encoding reversal
decoded = bytes(b ^ key for b in raw)  # Example: XOR
```

### 2. Parse WAL structure manually
```python
import struct

# Parse header
magic = struct.unpack('>I', decoded[0:4])[0]
page_size = struct.unpack('>I', decoded[8:12])[0]

# Walk frames
offset = 32
frames = []
while offset + 24 + page_size <= len(decoded):
    page_num = struct.unpack('>I', decoded[offset:offset+4])[0]
    db_size = struct.unpack('>I', decoded[offset+4:offset+8])[0]
    page_data = decoded[offset+24:offset+24+page_size]
    frames.append({
        'page_num': page_num,
        'db_size': db_size,
        'data': page_data
    })
    offset += 24 + page_size
```

### 3. Apply frames to database
```python
# For each frame, write page data to database at correct offset
# Page numbers are 1-indexed, so offset = (page_num - 1) * page_size
with open('main.db', 'r+b') as f:
    for frame in frames:
        offset = (frame['page_num'] - 1) * page_size
        f.seek(offset)
        f.write(frame['data'])
```

### 4. Extract data
```python
import sqlite3
conn = sqlite3.connect('main.db')
rows = conn.execute("SELECT * FROM table_name").fetchall()
conn.close()
```

## Verification

After recovery, verify:
1. **Row count**: Should match expected total (base + WAL updates)
2. **Data integrity**: Check for missing or corrupted values
3. **Key relationships**: Verify primary keys are unique and foreign keys are valid
4. **Ordering**: If task requires specific ordering, verify it's correct

## Common Pitfalls

1. **Opening database before decoding WAL** → SQLite destroys the encoded WAL
2. **Hardcoding checksum endianness** → Must match magic number (big-endian vs little-endian)
3. **Not recomputing checksums after decoding** → Non-byte-preserving encodings invalidate checksums
4. **Not fixing frame salts** → Frame salts must match WAL header salts
5. **Assuming single table** → Check for multiple tables with `sqlite_master`
6. **Not sorting output** → Many tasks require sorted output (by id, timestamp, etc.)
7. **Trusting SQLite WAL replay alone** → Even with perfect checksums, SQLite may silently ignore the WAL due to internal state mismatches (checkpoint_seq, schema cookies). Always verify row count increased; if not, fall back to manual page application.
8. **Not counting base rows first** → You need to know the baseline to detect if WAL replay failed

## Example: v01 Task

**Scenario:**
- Base database has 5 records
- WAL file is XOR-encoded with key `0x42`
- Expected total: 11 records

**Solution:**
```bash
python3 scripts/recover.py /app/main.db /app/main.db-wal /app/recovered.json
```

**What happens:**
1. Backs up files
2. Reads WAL, detects XOR encoding (first 4 bytes XOR 0x42 = valid magic)
3. Decodes entire WAL
4. Repairs checksums and salts
5. Writes repaired WAL
6. Opens database, SQLite replays WAL
7. Extracts all 11 rows
8. Writes JSON to `/app/recovered.json`

## References

- [SQLite WAL Format](https://www.sqlite.org/walformat.html)
- [SQLite File Format](https://www.sqlite.org/fileformat.html)
- SQLite source code: `src/wal.c`

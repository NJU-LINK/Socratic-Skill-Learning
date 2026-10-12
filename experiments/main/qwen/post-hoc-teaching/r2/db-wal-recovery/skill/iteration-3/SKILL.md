---
name: db-wal-recovery
description: >
  Recover data from SQLite databases with corrupted, encoded, or obfuscated
  Write-Ahead Log (WAL) files. Detects encoding transformations (XOR, base64,
  bit inversion, byte swapping), repairs WAL structure (checksums, salts,
  page sizes), applies frames to databases, and extracts all data to JSON.
  Handles cases where the base database has partial data and the WAL contains
  the remaining updates, as well as scenarios requiring manual page application
  or full reconstruction from WAL frames.
---

# SQLite WAL Recovery Skill

## ⚠️ CRITICAL WARNING ⚠️

**NEVER open the database with sqlite3 BEFORE decoding the WAL file!**

SQLite automatically deletes invalid WAL files when you open a database. If you open the database before decoding the WAL, the WAL will be PERMANENTLY DELETED and you will lose all updates.

**Correct order:**
1. Decode the WAL file first (XOR, base64, etc.)
2. Write the decoded WAL alongside the database
3. THEN open the database with sqlite3

**Wrong order (will destroy your data):**
1. ❌ Open database with sqlite3
2. ❌ WAL gets deleted
3. ❌ Try to decode WAL (too late!)

---

## Quick Start

**STEP 1: Copy and run the recovery script IMMEDIATELY (before doing anything else):**

```bash
# Copy the recovery script to /app
cp /skill/db-wal-recovery/wal_recovery.py /app/

# Run it RIGHT AWAY (auto-detects encoding, repairs WAL, extracts data)
# DO NOT open the database with sqlite3 before running this!
python3 /app/wal_recovery.py --output /app/recovered.json
```

**DO NOT** explore the database with sqlite3 before running the script. SQLite will delete the WAL file if it appears invalid.

The script handles:
- Auto-detection of encoding (XOR, base64, bit inversion, byte swap)
- WAL structure validation and repair (checksums, salts, page sizes)
- Direct SQLite application or manual page fallback
- Extraction to JSON format

**If the script fails or you need manual recovery, follow the detailed procedure below.**

## Critical Knowledge: SQLite WAL Internals

### WAL File Structure

A WAL file consists of:
- **32-byte header**: magic (4B), version (4B), page_size (4B), checkpoint_seq (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)
- **Frames**: each frame = 24-byte frame header + page_size bytes of page data
  - Frame header: page_number (4B), db_size (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)

### WAL Magic Numbers and Checksum Byte Order

- `0x377F0682`: Checksums computed using the creating machine's native byte order
- `0x377F0683`: Checksums computed using the non-native byte order

**Key insight**: The magic number does NOT directly tell you the checksum byte order. It indicates whether the creating machine used native (0x82) or opposite (0x83) byte order. Since most machines are little-endian (x86, ARM), checksums are almost always computed using **little-endian** 32-bit reads. When in doubt, try both byte orders and validate against stored checksums.

### WAL Checksum Algorithm

```
For each 8-byte chunk at offset i:
    x = read_uint32(data[i:i+4])    # byte order: LE for magic 0x82 on LE machines
    y = read_uint32(data[i+4:i+8])
    s0 = (s0 + x + s1) mod 2^32
    s1 = (s1 + y + s0) mod 2^32
```

**Checksum chaining**:
- Header checksum: bytes 0-23, starting from (s0=0, s1=0)
- Frame 0 checksum: frame_header[0:8] + page_data, starting from header's (s0, s1)
- Frame N checksum: frame_header[0:8] + page_data, starting from frame N-1's (s0, s1)

All header/frame fields are stored **big-endian**. Only checksum computation byte order varies.

### Frame `db_size` Field and Commit Semantics

Every WAL frame has a `db_size` field at offset +4:
- **`db_size = 0`**: Non-commit frame (intermediate write within transaction)
- **`db_size > 0`**: Commit frame (total pages after this transaction)

The **last commit frame's `db_size`** is the authoritative final database size. This is critical for:
1. **Freed pages**: A page may appear in WAL but be on freelist in final state
2. **No base database**: `db_size` tells you exact database size to create
3. **Multiple transactions**: Later transactions may truncate; last commit's `db_size` is final

Example:
```
Frame 0: page=1, db_size=0    (non-commit, schema update)
Frame 1: page=2, db_size=2    (COMMIT: database is now 2 pages)
Frame 2: page=2, db_size=2    (COMMIT: still 2 pages)
Frame 3: page=2, db_size=2    (COMMIT: still 2 pages)
```
Final database size is 2 (from frame 3).

### SQLite WAL Behavior

- **⚠️ SQLite deletes invalid WAL files on open** — this is the #1 cause of data loss
  - NEVER run `sqlite3 database.db` or `sqlite3.connect('database.db')` before decoding the WAL
  - Even a simple `SELECT` query will trigger WAL deletion if the WAL appears invalid
  - Always decode the WAL file FIRST, then write it back, THEN open the database
- Always work on a copy during recovery
- SQLite auto-checkpoints when last connection closes (if WAL is valid)
- Set `PRAGMA wal_autocheckpoint=0` to prevent auto-checkpointing

## Recovery Procedure

### ⚠️ BEFORE YOU START: Critical Order of Operations

**You MUST follow this exact order:**
1. **DECODE the WAL file** (XOR, base64, etc.) — do this FIRST
2. **WRITE the decoded WAL** back to disk alongside the database
3. **THEN** you can open the database with sqlite3

**NEVER** open the database with sqlite3 before step 2 is complete. SQLite will delete the WAL file if it appears invalid, and you will lose all updates permanently.

### Step 1: Detect and Reverse Encoding

Try transformations in order:
1. **No encoding** — check if WAL magic is already valid (`0x377F0682` or `0x377F0683`)
2. **Base64 wrapper** — try base64 decode, then check magic
3. **Single-byte XOR** — try all 256 keys; correct key produces valid magic
4. **Bit inversion** — flip all bits (~b & 0xFF)
5. **Byte swapping** — swap in 16-bit or 32-bit groups
6. **Combinations** — XOR + byte swap, base64 + XOR, etc.

**XOR detection tip**: The correct key produces `0x377F0682` or `0x377F0683` as first 4 bytes. Frequency analysis helps: XOR keys producing many `0x00` bytes are likely correct (WAL files contain many zero fields).

### Step 2: Parse WAL Structure

After decoding, parse the 32-byte header:
- Validate magic number
- Extract page size (power of 2, 512-65536)
- Extract salt values
- Validate header checksum (try both LE and BE byte orders)

Parse frames starting at offset 32:
- Each frame = 24 + page_size bytes
- Extract page_number, db_size, salts, checksums, page_data
- Stop when insufficient data remains

### Step 3: Determine Checksum Byte Order

Compute header checksum with both LE and BE. The one matching stored checksum is correct.

### Step 4: Repair WAL (if needed)

Common repairs:
- **Fix page size**: If WAL page_size ≠ database page_size, re-parse frames with correct size. Validate by checking frame checksums.
- **Fix salt values**: Frame salts must match header salts
- **Recompute checksums**: Rebuild header and frame checksums with correct byte order and chaining
- **Fix page numbers**: Skip frames with page_number < 1

**Page size repair**: Parse frames with both WAL and DB page sizes. Validate each set by computing first frame's checksum (chained from header). Use the size that produces valid checksums.

### Step 5: Apply WAL

**Strategy A: SQLite direct apply** (preferred)
1. Copy database to working location
2. Write repaired WAL alongside it (as `dbname-wal`)
3. Open with sqlite3: `PRAGMA journal_mode=wal; PRAGMA wal_checkpoint(TRUNCATE);`
4. Extract data

**Strategy B: Manual page application** (fallback)
1. Read database as raw bytes (or create empty buffer if no base DB)
2. Extract `final_db_size` from last commit frame's `db_size`
3. For each frame, copy page_data to database at offset `(page_number-1) * page_size`
4. Skip frames with page_number > final_db_size (freed pages)
5. If multiple frames update same page, use last one (latest version)
6. Update SQLite header: page count (offset 28), change counter (offset 24), version-valid-for (offset 92)
7. Switch to `journal_mode=DELETE`

**No base database**: Create empty buffer of `final_db_size * page_size` bytes, apply all frames, fix SQLite header. Page 1 frame contains database header and sqlite_master schema.

### Step 6: Extract Data

1. Open repaired database with sqlite3
2. Enumerate user tables (exclude `sqlite_*`)
3. For each table: `PRAGMA table_info(table)` to get columns, `SELECT * FROM table`
4. Format as JSON: list of dicts for single table, dict of lists for multiple tables
5. Sort by `id` column if present

## Handling Variations

### Encoding Variations
Any reversible transformation. Key diagnostic: after correct decoding, bytes 0-3 must be `0x377F0682` or `0x377F0683`.

### Database/WAL Integrity
- **Usable base DB + valid WAL**: Decode and apply directly
- **Missing base DB**: Reconstruct from WAL using `db_size` from commit frames. Page 1 contains schema.
- **Corrupt frame headers**: Repair salts and checksums; skip invalid frames
- **Multiple WAL files**: Process in order; later frames override earlier ones

### Recovery Depth
- **Direct SQLite consumption**: Works when WAL is valid after repair
- **Manual frame parsing**: Needed when SQLite rejects WAL
- **Full reconstruction**: No base DB; build from WAL pages alone

### Schema Variations
- **Single table**: Output as flat JSON array sorted by id
- **Multiple tables**: Output as dict keyed by table name
- **Different column types**: Use `PRAGMA table_info` to discover schema dynamically

## Important Pitfalls

1. **⚠️ NEVER open database with sqlite3 before decoding WAL** ⚠️
   - SQLite deletes invalid WAL files on open
   - Even `SELECT * FROM table` will trigger deletion
   - This is the #1 cause of recovery failure
   - Always decode WAL FIRST, write it back, THEN open database
2. **Checksum byte order ≠ magic number** — try both LE and BE, validate against stored checksum
3. **Frame checksums chain from header checksum** — not from (0,0)
4. **Page numbers are 1-indexed** — page 1 is first page
5. **Header checksum covers only first 24 bytes** — not the checksum fields
6. **Last frame wins for same page** — frames applied in order
7. **Use `db_size` from last commit frame** — not `max(page_number)`
8. **Update database header fields** — page count, change counter, version-valid-for

## Quick Reference: WAL Byte Layout

```
Offset  Size  Field
------  ----  -----
0       4     Magic (0x377F0682 or 0x377F0683) [big-endian]
4       4     Version (3007000) [big-endian]
8       4     Page size [big-endian]
12      4     Checkpoint sequence counter [big-endian]
16      4     Salt-1 (random) [big-endian]
20      4     Salt-2 (random) [big-endian]
24      4     Checksum-1 [big-endian]
28      4     Checksum-2 [big-endian]

Frame header (repeats for each frame):
+0      4     Page number [big-endian]
+4      4     Database size after this tx (0 if non-commit) [big-endian]
+8      4     Salt-1 (must match header) [big-endian]
+12     4     Salt-2 (must match header) [big-endian]
+16     4     Checksum-1 [big-endian]
+20     4     Checksum-2 [big-endian]
+24     ps    Page data (ps = page size from header)
```

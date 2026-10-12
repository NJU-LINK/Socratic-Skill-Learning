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

## Overview

This skill recovers data from SQLite databases whose WAL (Write-Ahead Log) files
have been encoded, obfuscated, or structurally damaged. The recovery pipeline:

1. **Detect and reverse encoding** applied to the WAL file
2. **Parse and validate** the WAL header and frame structure
3. **Repair** any structural damage (checksums, salts, page sizes)
4. **Apply** the repaired WAL to the database
5. **Extract** all data and produce structured output

## Critical Knowledge: SQLite WAL Internals

### WAL File Structure

A WAL file consists of:
- **32-byte header**: magic (4B), version (4B), page_size (4B), checkpoint_seq (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)
- **Frames**: each frame = 24-byte frame header + page_size bytes of page data
  - Frame header: page_number (4B), db_size (4B), salt1 (4B), salt2 (4B), checksum1 (4B), checksum2 (4B)

### WAL Magic Numbers

- `0x377F0682`: Checksums computed using the creating machine's native byte order
- `0x377F0683`: Checksums computed using the non-native byte order

**Key insight**: The magic number does NOT directly tell you the checksum byte order.
It tells you whether the creating machine used its native byte order (0x82) or the
opposite (0x83). Since most machines are little-endian (x86, ARM), checksums are
almost always computed using **little-endian** 32-bit reads, regardless of the magic
number. When in doubt, try both byte orders and check which produces valid checksums.

### WAL Checksum Algorithm

The checksum processes data in 8-byte chunks (pairs of 32-bit unsigned integers):

```
For each 8-byte chunk at offset i:
    x = read_uint32(data[i:i+4])    # byte order depends on magic
    y = read_uint32(data[i+4:i+8])
    s0 = (s0 + x + s1) mod 2^32
    s1 = (s1 + y + s0) mod 2^32
```

**Checksum chaining**:
- Header checksum: computed over bytes 0-23 of the header, starting from (s0=0, s1=0)
- Frame 0 checksum: computed over frame_header[0:8] + page_data, starting from header's (s0, s1)
- Frame N checksum: computed over frame_header[0:8] + page_data, starting from frame N-1's (s0, s1)

All values in the WAL header and frame headers are stored in **big-endian** format.
Only the checksum computation byte order varies.

### SQLite WAL Behavior

- When SQLite opens a WAL-mode database and finds an **invalid** WAL, it **deletes** the WAL file
- This means you must NOT open the database with sqlite3 before decoding the WAL
- Always work on a copy of the database during recovery
- SQLite auto-checkpoints the WAL when the last connection closes (if it's valid)
- Set `PRAGMA wal_autocheckpoint=0` to prevent auto-checkpointing during testing

### Frame `db_size` Field and Commit Semantics

Every WAL frame header has a `db_size` field at offset +4:
- **`db_size = 0`**: Non-commit frame — an intermediate write within a transaction
- **`db_size > 0`**: Commit frame — records total pages in database after this transaction

The **last commit frame's `db_size`** is the authoritative final database size. This is critical for:

1. **Pages freed before WAL capture**: A page may appear in the WAL but be on the freelist in the final state. Using `max(page_number)` would include garbage pages.
2. **No base database**: When reconstructing from WAL alone, `db_size` tells you the exact database size to create.
3. **Multiple transactions**: Later transactions may truncate the database; the last commit frame's `db_size` reflects the final state.

Example WAL with 5 frames from two transactions:
```
Frame 0: page=2, db_size=0    (non-commit, intermediate write)
Frame 1: page=3, db_size=0    (non-commit)
Frame 2: page=3, db_size=3    (COMMIT: database is now 3 pages)
Frame 3: page=2, db_size=0    (non-commit, second transaction)
Frame 4: page=2, db_size=3    (COMMIT: still 3 pages)
```
Final database size is 3 (from frame 4), not `max(page_number)=3`.

## Recovery Pipeline

### Step 1: Detect Encoding

Try transformations in order of likelihood:

1. **No encoding** - check if WAL magic is already valid
2. **Base64 wrapper** - try base64 decode, then check magic
3. **Single-byte XOR** - try all 256 key values; check if result has valid magic
4. **Bit inversion** - flip all bits (~b & 0xFF)
5. **Byte swapping** - swap in 16-bit or 32-bit groups
6. **Combinations** - XOR + byte swap, base64 + XOR, bit invert + byte swap

For XOR detection: the correct key will produce `0x377F0682` or `0x377F0683` as the first 4 bytes.

### Step 2: Parse WAL Structure

After decoding, parse the 32-byte header:
- Validate magic number
- Extract page size (must be power of 2, 512-65536)
- Extract salt values (used to validate frames)
- Extract and validate header checksum

Then parse frames starting at offset 32:
- Each frame is 24 + page_size bytes
- Extract page number, db_size, salts, checksums, and page data
- Stop when insufficient data remains for another frame

### Step 3: Determine Checksum Byte Order

Try computing the header checksum with both little-endian and big-endian reads.
The one that matches the stored checksum is the correct byte order.

### Step 4: Repair WAL

Common repairs:
- **Fix page size**: If WAL page size doesn't match database page size, re-parse frames
  with the correct page size. Validate by checking frame checksums with both page sizes.
  The correct page size will produce frames with valid checksums.
- **Fix salt values**: Frame salts must match header salts
- **Recompute checksums**: Rebuild header and frame checksums using the correct byte order and chaining
- **Fix page numbers**: If a frame has page_number < 1, assign sequential numbers
- **Remove invalid frames**: Skip frames with unrecoverable issues

**Page size repair procedure**:
1. Parse frames using the WAL header's page_size
2. If it differs from the database page_size, also parse with the database page_size
3. Validate each set of frames by computing the first frame's checksum (chained from header)
4. Use the page_size that produces valid checksums
5. If neither validates, prefer the database page_size as the more trustworthy source

### Step 5: Apply WAL

Two strategies, in order of preference:

**Strategy A: SQLite direct apply**
1. Copy the database to a working location
2. Write the repaired WAL alongside it (as `dbname-wal`)
3. Open with sqlite3, set `journal_mode=wal`, run `wal_checkpoint(TRUNCATE)`
4. This works when the WAL is structurally valid after repair

**Strategy B: Manual page application**
1. Read the database file as raw bytes (or create empty buffer if no base DB)
2. Extract `final_db_size` from the last commit frame's `db_size` field
3. For each WAL frame, copy the page data into the database at the correct offset
4. Skip frames with page_number > final_db_size (freed pages)
5. If multiple frames update the same page, use the last one (latest version)
6. Update the database header: page count (offset 28), change counter (offset 24), version-valid-for (offset 92)
7. Switch to `journal_mode=DELETE` to avoid WAL complications

**When no base database exists**: Create an empty buffer of `final_db_size * page_size` bytes, apply all frames, then fix the SQLite header fields (page count, change counter, etc.). The WAL's page 1 frame contains the database header and sqlite_master schema.

### Step 6: Extract Data

1. Open the repaired database with sqlite3
2. Enumerate user tables (exclude `sqlite_*` internal tables)
3. For each table, get column info and extract all rows
4. Format as JSON: list of dicts for single table, dict of lists for multiple tables
5. Sort by `id` column if present

## Handling Variation Dimensions

### Encoding/Obfuscation Variations

The encoding can be any reversible transformation. The key diagnostic is the WAL
magic number: after correct decoding, bytes 0-3 must be `0x377F0682` or `0x377F0683`.

For unknown encodings, use frequency analysis: XOR keys that produce many `0x00`
bytes in the decoded output are likely correct (since WAL files contain many zero
fields). The byte `0x42` ('B') appearing frequently in the encoded file suggests
XOR with `0x42` (since `0x00 XOR 0x42 = 0x42`).

### Database/WAL Integrity Variations

- **Usable base DB + valid WAL**: Standard case; decode WAL and apply
- **Missing base DB**: Reconstruct from WAL frames using `db_size` from commit frames to determine final database size. Create empty buffer, apply all frames, fix SQLite header. Page 1 contains schema.
- **Corrupt frame headers**: Repair salts and checksums; skip frames with invalid page numbers
- **Partial frames**: If a frame's page data is truncated, skip it
- **Multiple WAL files**: Process in order; later frames override earlier ones for the same page. Track `db_size` across all frames to find the final size.

### Recovery Depth Variations

- **Direct SQLite consumption**: Works when WAL is valid after decoding and repair
- **Manual frame parsing**: Needed when SQLite rejects the WAL; parse frames and apply pages directly
- **Full reconstruction**: When no base DB exists; build database from WAL pages alone
  - Page 1 contains the database header and sqlite_master table
  - Other pages contain table/index data
  - Use the last version of each page (highest frame number)

### Schema and Topology Variations

- **Single table**: Output as flat JSON array sorted by id
- **Multiple tables**: Output as dict keyed by table name
- **Different column types**: Use `PRAGMA table_info` to discover schema dynamically
- **Updates across WAL streams**: Merge all frames, using latest version of each page

## Important Pitfalls

1. **Never open the database with sqlite3 before decoding the WAL** - SQLite will
   delete an invalid WAL file on open
2. **Checksum byte order is NOT determined by the magic number alone** - it depends
   on the creating machine's architecture; try both LE and BE
3. **Frame checksums chain from the header checksum** - not from (0,0)
4. **Page numbers in WAL are 1-indexed** - page 1 is the first page
5. **The WAL header checksum covers only the first 24 bytes** - not the checksum fields themselves
6. **When multiple frames update the same page, the last frame wins** - frames are applied in order
7. **Database page count in header (offset 28-31) must be updated** if WAL adds new pages

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

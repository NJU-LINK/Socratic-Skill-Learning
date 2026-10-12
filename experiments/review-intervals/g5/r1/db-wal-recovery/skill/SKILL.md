---
name: db-wal-recovery
description: >
  Recover data from corrupted, encoded, or damaged SQLite WAL (Write-Ahead
  Logging) files. Handles XOR encoding, byte inversion, base64 wrapping,
  byte swapping, damaged headers, missing base databases, corrupt frames,
  and partial WAL streams. Diagnoses encoding via known-plaintext anchors,
  decodes the WAL, validates structure and checksums, and extracts all
  records to JSON.
---

# SQLite WAL Recovery Skill

## Critical Invariant: BACKUP FIRST

**NEVER open a corrupted/encoded WAL-mode database with sqlite3 before backing
up the WAL file.** SQLite's connection setup validates the WAL header; if it
finds invalid magic bytes, it may DELETE or TRUNCATE the WAL file, permanently
destroying the uncommitted data. This is the single most important rule.

```bash
# Always the very first action:
cp /app/main.db /app/main.db.bak 2>/dev/null
cp /app/main.db-wal /app/main.db-wal.bak 2>/dev/null
# If multiple WAL files exist, back them all up
cp /app/*.db-wal* /app/backup_wals/ 2>/dev/null
```

## Step 1: Inventory and Assess

Identify all database-related files and their sizes:

```bash
ls -la /app/*.db* /app/*.wal* 2>/dev/null
```

Determine:
- Is there a base `.db` file? (may be missing in some cases)
- How many `.db-wal` files exist? (may be split across multiple files)
- What are the file sizes? (WAL size = 32 header + N × (24 + page_size))
- Is the base database readable at all? (try `sqlite3 main.db ".tables"` but
  ONLY after backing up the WAL — and use `PRAGMA journal_mode` to check)

## Step 2: Diagnose the Encoding

### Known-plaintext anchors

Use these structural constants to detect and reverse any encoding:

| Structure | Expected bytes | Location |
|-----------|---------------|----------|
| WAL magic (BE checksums) | `37 7F 06 82` | WAL offset 0–3 |
| WAL magic (LE checksums) | `37 7F 06 83` | WAL offset 0–3 |
| SQLite DB header | `53 51 4C 69 74 65 20 66 6F 72 6D 61 74 20 33 00` | DB offset 0–15 |
| WAL format version | `00 00 00 01` or `00 00 00 02` | WAL offset 4–7 |
| WAL page size | power of 2 (512–65536) | WAL offset 8–11 |

### Diagnosis procedure

1. Read the first 32 bytes of the WAL backup
2. Check if magic bytes match `37 7F 06 82` or `37 7F 06 83`
3. If not, try these transformations and check which produces valid magic:

**Single-byte XOR:** XOR each of the first 4 bytes against the expected magic.
If all 4 yield the same key, it's single-byte XOR with that key.

```python
observed = wal_bytes[0:4]
expected_be = bytes([0x37, 0x7F, 0x06, 0x82])
expected_le = bytes([0x37, 0x7F, 0x06, 0x83])
key_be = bytes(a ^ b for a, b in zip(observed, expected_be))
key_le = bytes(a ^ b for a, b in zip(observed, expected_le))
# If all bytes in key_be are the same → single-byte XOR with that key (BE)
# If all bytes in key_le are the same → single-byte XOR with that key (LE)
```

**Bitwise NOT (inversion):** XOR with `0xFF`. Check if `byte ^ 0xFF` yields magic.

**Byte swapping:** Try swapping every pair of bytes, or reversing every 4-byte group.

**Base64:** Check if the file content is valid ASCII base64. If so, decode first,
then check the result for WAL magic.

**Multi-byte XOR:** If single-byte doesn't work, try repeating-key XOR with
key lengths 2, 3, 4 using the known magic as crib.

**Damaged header only:** If magic bytes are wrong but the rest of the file
looks like valid WAL data (frame page numbers are plausible, page data contains
SQLite B-tree structures), the encoding may only affect the header. Try
replacing just the first 32 bytes with a valid WAL header.

### Validation after decoding

After applying any transformation, verify:
- Bytes 0–3: WAL magic (`37 7F 06 82` or `37 7F 06 83`)
- Bytes 8–11: page size is a power of 2 between 512 and 65536
- Bytes 8–11: page size matches the base database's page size (DB header bytes 16–17)
- File size: `(file_size - 32) % (24 + page_size) == 0` (exact frame alignment)

## Step 3: Decode the WAL

Apply the diagnosed transformation to the WAL backup and write the result
as the new WAL file:

```python
# Example for single-byte XOR:
with open('/app/main.db-wal.bak', 'rb') as f:
    encoded = f.read()
decoded = bytes(b ^ KEY for b in encoded)
with open('/app/main.db-wal', 'wb') as f:
    f.write(decoded)
```

## Step 4: Validate Checksums

SQLite WAL uses a chaining checksum algorithm. The WAL header stores checksums
over bytes 0–23. Each frame's checksum chains from the previous checksum state.

```python
import struct

def wal_checksum(data, s0=0, s1=0, big_endian=True):
    """Compute WAL checksum. s0, s1 are running state."""
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        v0 = struct.unpack(fmt, data[i:i+4])[0]
        v1 = struct.unpack(fmt, data[i+4:i+8])[0]
        s0 = (s0 + v0 + s1) & 0xFFFFFFFF
        s1 = (s1 + v1 + s0) & 0xFFFFFFFF
    return s0, s1

# Validate header checksum
big_endian = (decoded[3] == 0x82)  # 0x82 = BE, 0x83 = LE
s0, s1 = wal_checksum(decoded[0:24], 0, 0, big_endian)
stored_ck1 = struct.unpack('>I', decoded[24:28])[0]
stored_ck2 = struct.unpack('>I', decoded[28:32])[0]
header_valid = (s0 == stored_ck1 and s1 == stored_ck2)
```

If checksums are invalid after decoding:
- The encoding may have been applied selectively (headers only, or data only)
- Try recomputing checksums on the decoded data and patching them in
- As last resort, proceed to manual frame application (Step 5b)

## Step 5: Apply WAL Frames

**For encoded/corrupted WAL files, use manual frame application as the PRIMARY path.**

SQLite-native recovery (letting SQLite consume the WAL directly) often fails for encoded WALs because:
- Checksums are corrupted by the encoding and may not be recoverable
- Even with recomputed checksums, SQLite may reject the WAL due to structural validation
- Manual frame application is more reliable and works even when metadata is damaged

### Option A: Manual Frame Application (Recommended for Encoded WALs)

Parse frames from the decoded WAL and apply page data directly to the database:

```python
import struct

page_size = struct.unpack('>I', decoded[8:12])[0]
frame_size = 24 + page_size
frames = []

for i in range((len(decoded) - 32) // frame_size):
    offset = 32 + i * frame_size
    frame_hdr = decoded[offset:offset+24]
    page_data = decoded[offset+24:offset+24+page_size]
    
    pgno = struct.unpack('>I', frame_hdr[0:4])[0]
    db_size = struct.unpack('>I', frame_hdr[4:8])[0]
    
    frames.append({
        'pgno': pgno,
        'db_size': db_size,
        'page_data': page_data,
        'is_commit': db_size > 0
    })

# Apply frames to database (last writer wins for same page number)
# Only apply up to the last commit frame
last_commit = max(i for i, f in enumerate(frames) if f['is_commit'])
page_map = {}
for f in frames[:last_commit+1]:
    page_map[f['pgno']] = f['page_data']

# Write pages to database file
with open('/app/main.db', 'r+b') as db:
    for pgno, page_data in page_map.items():
        db.seek((pgno - 1) * page_size)
        db.write(page_data)
    
    # Update change counter (bytes 24-27) if page 1 was updated
    if 1 in page_map:
        # The page data already contains the updated header
        pass
    else:
        # Increment change counter
        db.seek(24)
        counter = struct.unpack('>I', db.read(4))[0]
        db.seek(24)
        db.write(struct.pack('>I', counter + 1))
        # Also update version-valid-for (bytes 92-95)
        db.seek(92)
        db.write(struct.pack('>I', counter + 1))
```

**Important:** When recomputing frame checksums (if needed for validation), the checksum covers only the **first 8 bytes** of the frame header (pgno + db_size) plus the page data. The salt values (bytes 8-15) are NOT included in the checksum input:

```python
# CORRECT frame checksum computation
ck_data = frame_hdr[0:8] + page_data  # Only pgno + db_size, NOT salt values
fs0, fs1 = wal_checksum(ck_data, ck_s0, ck_s1, big_endian)
```

This differs from the WAL header checksum, which covers all 24 bytes before the checksum fields.

### Option B: SQLite-Native Recovery (Only for Minimally Damaged WALs)

If the WAL has minimal damage (e.g., only header magic corrupted, checksums intact), you can try letting SQLite consume it directly:

```bash
# Write decoded WAL
# Then query
sqlite3 /app/main.db "SELECT COUNT(*) FROM items;"
```

**When to use this:** Only if you're confident the WAL structure is intact after decoding. For XOR-encoded or heavily corrupted WALs, skip this and use Option A.

**If SQLite silently ignores the WAL** (shows only base records, WAL file disappears), proceed immediately to Option A. Don't spend time debugging checksums or metadata.

## Step 5c: Full Reconstruction (No Base Database)

If the base database is missing or completely corrupt, reconstruct from WAL:

1. Create an empty file of size `max_db_size * page_size`
2. Apply all frames in order (last writer wins)
3. The schema page (page 1) will be among the WAL frames
4. Verify the result is a valid SQLite database

## Step 6: Discover Schema and Export

After recovery, discover the actual schema dynamically (don't assume table/column names):

```python
import sqlite3, json

conn = sqlite3.connect('/app/main.db')
cursor = conn.cursor()

# Find all user tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = [row[0] for row in cursor.fetchall()]

# For each table, get all rows
all_data = {}
for table in tables:
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]
    cursor.execute(f"SELECT * FROM {table}")
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    all_data[table] = rows

# If the task specifies a particular output format, adapt accordingly
# Common format: list of dicts sorted by primary key
```

## Step 7: Handle Multiple WAL Files

If updates are split across multiple WAL files:
1. Decode each WAL file independently
2. Determine the correct ordering (by checkpoint sequence number in WAL headers)
3. Apply frames from all WALs in order, with later WALs taking precedence

## Edge Cases and Failure Modes

1. **Partial frames**: WAL file truncated mid-frame. Apply only complete frames.
2. **Corrupt page numbers**: Frame header has page number > db_size or = 0.
   Skip such frames or try to infer the correct page number from context.
3. **Mixed encoding**: Different frames encoded differently. Check each frame
   header for valid salt values matching the WAL header.
4. **Database grew**: If WAL frames reference pages beyond the current DB file
   size, extend the database file before writing those pages.
5. **Schema changes in WAL**: The WAL may contain ALTER TABLE results. Apply
   page 1 (schema page) first, then data pages.

## Verification Checklist

Before declaring recovery complete:
- [ ] WAL was backed up before any sqlite3 access
- [ ] Encoding was diagnosed using known-plaintext anchors
- [ ] Decoded WAL has valid magic bytes
- [ ] Page size matches between WAL and base database
- [ ] File size is consistent with frame structure
- [ ] Checksums validated (or manually recomputed)
- [ ] All expected records are present in the output
- [ ] Output JSON matches the required format and sort order

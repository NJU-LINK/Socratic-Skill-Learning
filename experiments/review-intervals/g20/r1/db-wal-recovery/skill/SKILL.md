---
name: db-wal-recovery
description: Recover data from corrupted, encoded, or obfuscated SQLite WAL (Write-Ahead Logging) files. Handles XOR encoding, byte inversion, damaged headers, and structural corruption while preserving evidence integrity.
---

# SQLite WAL Recovery Skill

## Critical Principle: Preservation First

**NEVER open a database with SQLite before backing up the WAL file.** SQLite silently deletes WAL files with invalid magic numbers, destroying evidence.

Always execute this sequence:
```bash
cp /app/main.db /app/main.db.backup
cp /app/main.db-wal /app/main.db-wal.backup
```

## Recovery Methodology

### Phase 1: Diagnosis

1. **Check file existence and sizes**
   - Database should be present (typically 8KB+ for small databases)
   - WAL file should be present (size = 32 + N×(24 + page_size))

2. **Examine WAL header bytes**
   ```bash
   xxd /app/main.db-wal | head -5
   ```

3. **Detect encoding/obfuscation**
   - Valid WAL magic (big-endian): `0x377F0682` (bytes: 37 7F 06 82)
   - Valid WAL magic (native-endian): `0x377F0683` (bytes: 37 7F 06 83)
   - If magic doesn't match either, try common transformations:
     - **XOR with single byte**: Test keys 0x00-0xFF against first 4 bytes
     - **Byte inversion**: XOR with 0xFF
     - **Base64 wrapper**: Check if file starts with "U" or other base64 chars
     - **Byte swapping**: Check if bytes are in wrong order

4. **Verify decoded WAL structure**
   - Bytes 0-3: Magic (0x377F0682)
   - Bytes 4-7: Version (3007000 = 0x00300700)
   - Bytes 8-11: Page size (power of 2: 512-65536)
   - Bytes 12-15: Checkpoint sequence number
   - Bytes 16-23: Salt values
   - Bytes 24-31: Checksum

### Phase 2: Decoding

Apply the detected transformation to the entire WAL file:

```python
# XOR decoding example
key = 0x42  # or whatever key was detected
decoded = bytes([b ^ key for b in wal_data])

# Byte inversion example
decoded = bytes([b ^ 0xFF for b in wal_data])
```

### Phase 3: Recovery

Two approaches, tried in sequence:

#### Approach A: SQLite-Native Recovery (Attempted First)

If the decoded WAL has valid structure:

1. Create working copy of database
2. Write decoded WAL alongside it (same directory, matching name)
3. **Create empty SHM file** (required for SQLite WAL mode)
4. Open with SQLite and query all data
5. Export to required format

**Critical:** The SHM (shared memory) file must exist for SQLite to properly consume the WAL. Create an empty file:
```python
with open('/tmp/recovery.db-shm', 'wb') as f:
    pass  # Empty file is sufficient
```

**Limitations:**
- SQLite validates WAL frame checksums
- If checksums are invalid, SQLite silently skips frames
- Detection: Compare record count with expected total
- If only base records are visible, fall back to Approach B

```python
import shutil
import sqlite3

# Copy database
shutil.copy2('/app/main.db', '/tmp/recovery.db')

# Write decoded WAL
with open('/tmp/recovery.db-wal', 'wb') as f:
    f.write(decoded_wal)

# Create empty SHM file (CRITICAL)
with open('/tmp/recovery.db-shm', 'wb') as f:
    pass

# Query all data
conn = sqlite3.connect('/tmp/recovery.db')
cursor = conn.cursor()
cursor.execute("SELECT * FROM table_name ORDER BY id")
rows = cursor.fetchall()
```

#### Approach B: Manual Frame Parsing (Robust Fallback)

**This is often the more reliable path for encoded WALs.**

If WAL structure is damaged or checksums fail:

1. Parse WAL header (32 bytes)
2. For each frame:
   - Read 24-byte frame header
   - Extract page number (bytes 0-3)
   - Extract page data (page_size bytes)
   - Apply page to database at correct offset
3. Reconstruct database from base + applied pages

**Advantages:**
- Bypasses SQLite checksum validation
- Works even with partially corrupted frames
- Direct page-level control
- Last-write-wins semantics for multiple updates to same page

Frame structure:
```
Frame header (24 bytes):
  - Page number (4 bytes, big-endian)
  - Commit size (4 bytes, big-endian)
  - Salt1 (4 bytes)
  - Salt2 (4 bytes)
  - Checksum1 (4 bytes)
  - Checksum2 (4 bytes)

Frame data:
  - Page data (page_size bytes)
```

### Phase 4: Validation

1. **Count records**: Verify expected number of rows recovered
2. **Check ordering**: Ensure data is sorted as required
3. **Validate relationships**: Check foreign keys, unique constraints
4. **Verify completeness**: Compare against any known expected values

## Common Failure Modes

1. **SQLite deletes WAL before backup**
   - Solution: Always backup first, never run sqlite3 on corrupted files

2. **XOR key detection fails**
   - Solution: Brute-force all 256 single-byte keys against WAL magic

3. **WAL structure invalid after decoding**
   - Solution: Check if page size is valid, verify frame alignment

4. **Partial frame corruption**
   - Solution: Parse frames individually, skip corrupted ones, apply valid frames

5. **Multiple WAL files**
   - Solution: Process in sequence, later WALs override earlier pages

6. **WAL checksums invalid after decoding**
   - **Symptom**: SQLite only reads base records, ignoring WAL updates
   - **Cause**: XOR encoding/decoding may corrupt checksums if not applied uniformly
   - **Detection**: Compare record count with WAL vs base-only database
   - **Solution**: Fall back to manual frame parsing and page application
   - **Implementation**: Parse WAL frames, extract page data, write directly to database file at correct offsets

## Spec Variation Handling

The skill handles these variation dimensions:

### wal_encoding_or_obfuscation
- **XOR encoding**: Detect by testing keys against WAL magic
- **Byte inversion**: XOR with 0xFF
- **Base64 wrapper**: Decode base64 first
- **Damaged headers**: Repair magic/version/page_size fields
- **Intact WAL**: Skip decoding phase

### wal_and_base_database_integrity
- **Usable base + missing WAL updates**: Apply WAL normally
- **Missing base database**: Reconstruct from WAL frames
- **Corrupt frame headers**: Parse manually, skip bad frames
- **Partial frames**: Extract recoverable portions
- **Multiple WAL files**: Process sequentially

### recovery_depth
- **SQLite can consume WAL**: Use Approach A (SQLite-native)
- **Checksum failures or structural damage**: Use Approach B (manual frame parsing)
- **Complete reconstruction needed**: Extract all pages, build fresh database
- **Note**: For encoded WALs, Approach B is often more reliable as it bypasses checksum validation

### schema_and_update_topology
- **Single/multiple tables**: Query sqlite_master for table list
- **Different column types**: Use PRAGMA table_info for schema
- **Different record volumes**: Count and validate
- **Updates across WAL streams**: Process all WALs in order

## Output Format

Typically JSON array of objects, sorted by primary key:
```json
[
  {"id": 1, "name": "item1", "value": 100},
  {"id": 2, "name": "item2", "value": 200},
  ...
]
```

## Quick Reference

**IMPORTANT:** Use the provided recovery script rather than writing inline code. The script handles all edge cases, backup, encoding detection, and fallback logic.

### Script Location

The skill package is mounted read-only at `/skill/` inside the task container. Scripts are at:
- **`/skill/scripts/recover.py`** - Main recovery script

Run it directly from inside the container:
```bash
python3 /skill/scripts/recover.py
```

**Note:** The script is read-only. Do not try to edit it. If you need to modify behavior, copy it to `/app/` first:
```bash
cp /skill/scripts/recover.py /app/recover.py
# Edit /app/recover.py as needed
python3 /app/recover.py
```

### Recovery Steps

```bash
# 1. Backup (CRITICAL - do this first!)
cp /app/main.db /app/main.db.backup
cp /app/main.db-wal /app/main.db-wal.backup

# 2. Run the recovery script
python3 /skill/scripts/recover.py

# 3. Verify output
cat /app/recovered.json
```

The script will:
- Detect encoding (XOR key, byte inversion, etc.)
- Decode the WAL
- Try SQLite-native recovery with SHM file
- Fall back to manual frame parsing if needed
- Output sorted JSON to /app/recovered.json

**Do not write inline Python for recovery** - the script is tested and handles edge cases that inline code often misses (SHM file creation, checksum failures, frame parsing).

---
name: db-wal-recovery
description: >
  Recover data from a SQLite database whose WAL (Write-Ahead Log) file has been
  encoded, obfuscated, or structurally damaged. Diagnose the transformation
  applied to the WAL, reverse it, repair structural fields (checksums, sequence
  numbers), extract all committed records by manually applying WAL pages to the
  base database, and emit the recovered rows as sorted JSON.
---

# SQLite WAL Recovery

## Task Contract

You are given a SQLite database directory (typically `/app/`) containing a base
database file (`*.db`) and a WAL file (`*.db-wal`) that cannot be consumed
normally by SQLite. The goal is to recover **all** committed rows—including
those in the WAL—and write them to a JSON file (typically `/app/recovered.json`).

## Quick Recovery Procedure

Use `scripts/wal_repair.py` for automated recovery when available:

```bash
# One command: detect encoding, decode, apply frames, write JSON
python3 scripts/wal_repair.py /app/main.db /app/main.db-wal
```

If the script is not available or fails, follow the manual procedure:

1. **Back up** original files before any modification.
2. **Inspect** first 4 bytes of the WAL: `xxd -l 4 /app/main.db-wal`.
3. **Detect encoding**: compare against WAL magic `377f0682`. If mismatched,
   XOR the first 4 bytes with the magic to find the key (uniform key = XOR
   encoding). Also try base64-decode and byte-swap.
4. **Decode** the entire WAL with the detected transformation.
5. **Parse frames**: page_size from decoded WAL header bytes 8–11; iterate
   frames at offset `32 + i*(24 + page_size)`.
6. **Track commits**: buffer page data per pgno; on `commit > 0`, flush
   buffer to committed map. Discard trailing uncommitted frames.
7. **Apply pages**: overlay committed pages onto base DB at
   `(pgno-1)*page_size`. Bump change counter (DB bytes 24–27 & 92–95).
8. **Delete** `*.db-wal` and `*.db-shm` to prevent SQLite re-open issues.
9. **Query** all tables, write sorted JSON to `/app/recovered.json`.
10. **Verify**: `PRAGMA integrity_check` = `ok`, correct row count.

---

## 1. Situation Assessment

### 1.1 Inventory Artifacts

```bash
ls -la /app/*.db /app/*.db-wal /app/*.db-shm 2>/dev/null
xxd /app/*.db   | head -8     # confirm "SQLite format 3" header
xxd /app/*.db-wal | head -8   # inspect raw WAL bytes
```

Record the file sizes. A WAL file size should equal `32 + N * (24 + page_size)`
where `N` is the frame count and `page_size` comes from the database header
(bytes 16–17, big-endian) or the WAL header (bytes 8–11).

### 1.2 Baseline Query

Open the database **in a copy** so the original WAL is not auto-checkpointed:

```python
import shutil, sqlite3, os
shutil.copy2("main.db", "main_snapshot.db")
conn = sqlite3.connect("main_snapshot.db")
rows = conn.execute("SELECT * FROM <table> ORDER BY id").fetchall()
print(f"Base rows: {len(rows)}")
conn.close()
```

If the base DB already shows all expected rows, the WAL is redundant. Otherwise
the deficit tells you roughly how many rows the WAL must contain.

## 2. Diagnose WAL Encoding / Obfuscation

The WAL magic number is `0x377f0682` (big-endian checksums) or `0x377f0683`
(little-endian checksums). Read the first four bytes and compare.

### 2.1 Decision Tree

| First 4 bytes match magic? | Diagnosis |
|---|---|
| Yes | WAL is structurally intact; skip to §3 (checksum repair). |
| No | WAL is transformed. Run the probes below. |

### 2.2 Single-Byte XOR Probe

```python
EXPECTED = bytes([0x37, 0x7f, 0x06, 0x82])
with open(wal_path, "rb") as f:
    head = f.read(4)
keys = [a ^ b for a, b in zip(head, EXPECTED)]
if len(set(keys)) == 1:
    xor_key = keys[0]          # confirmed single-byte XOR
```

Also look for a dominant byte value in the file (e.g. many `0x42` bytes where
zero-padding should be). The dominant byte is a strong XOR-key candidate.

### 2.3 Bitwise Inversion Probe

XOR with `0xFF` is a special case of the above. If `keys[0] == 0xFF` for all
four positions, the transform is `~byte`.

### 2.4 Base64 Wrapper Probe

If the file is ASCII-only and length is a multiple of 4 (possibly with `=`
padding), try `base64.b64decode(data)` and check the decoded first four bytes
against the magic.

### 2.5 Byte-Swap Probe

Try swapping every pair of bytes (`data[0:2] → data[1]+data[0]`, etc.) or
every 4-byte group and check for the magic.

### 2.6 No Match

If none of the above produce valid magic bytes, the header itself may be
damaged. Inspect whether any contiguous 4-byte window inside the first 64 bytes
matches the magic (shifted header) or whether the page-size field at a
different offset yields a plausible value (512–65536, power of two).

## 3. Decode and Validate WAL Structure

### 3.1 Decode

Apply the inverse transformation to the **entire** WAL file:

```python
decoded = bytes(b ^ xor_key for b in raw_data)      # XOR case
# or
decoded = base64.b64decode(raw_data)                 # base64 case
```

### 3.2 Parse Header (32 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0  | 4 | Magic number |
| 4  | 4 | File-format version (should be 3007000) |
| 8  | 4 | Database page size |
| 12 | 4 | Checkpoint sequence number |
| 16 | 4 | Salt-1 |
| 20 | 4 | Salt-2 |
| 24 | 4 | Checksum-1 |
| 28 | 4 | Checksum-2 |

### 3.3 Parse Frame Headers (24 bytes each)

Each frame starts at offset `32 + i * (24 + page_size)`:

| Offset | Size | Field |
|--------|------|-------|
| 0  | 4 | Page number (1-indexed) |
| 4  | 4 | Commit size (0 = not final frame; >0 = db size in pages after commit) |
| 8  | 4 | Salt-1 (must match header salt-1) |
| 12 | 4 | Salt-2 (must match header salt-2) |
| 16 | 4 | Checksum-1 |
| 20 | 4 | Checksum-2 |

Discard any frame whose salt values do not match the header salts (they belong
to a prior WAL generation).

## 4. Repair WAL Checksums

The WAL checksum is a running 32-bit pair `(s1, s2)` computed over consecutive
8-byte big-endian (or little-endian if magic is `0x377f0683`) word pairs:

```
for each (v1, v2) pair of 32-bit words:
    s1 = (s1 + v1 + s2) mod 2^32
    s2 = (s2 + s1 + v2) mod 2^32
```

The header checksum covers bytes 0–23 (result stored at 24–31). Each frame
checksum continues the running sum over its 24-byte frame header **and** its
page data.

**Important:** After any byte-level transformation (XOR, inversion, etc.),
checksums will be invalid and must be recomputed and overwritten before SQLite
will accept the WAL.

### 4.1 Checksum Repair Script

See `scripts/wal_repair.py` for a complete implementation.

## 5. Recover Data

There are two strategies. Prefer **Strategy A** (manual page application)
because it bypasses all SQLite WAL-compatibility issues. Use **Strategy B** as
a fallback when Strategy A produces integrity errors.

### 5.1 Strategy A — Manual Page Application (Preferred)

1. Read the base database into a `bytearray`.
2. Walk the decoded WAL frames in order.
3. Buffer each frame's page data keyed by page number.
4. When a frame has `commit > 0`, flush the buffer into the committed-page map.
5. After the last frame, discard any uncommitted buffer entries.
6. Overlay committed pages onto the base database at offset `(pgno - 1) * page_size`.
   If the WAL introduces pages beyond the current DB size, extend the DB.
7. Increment the database change counter (bytes 24–27 and 92–95 of page 1) to
   ensure SQLite treats the file as freshly modified.
8. Write the patched database. Delete any `*.db-wal` and `*.db-shm` files so
   SQLite opens the DB in rollback-journal or fresh-WAL mode.

```python
# Pseudocode
committed = {}
txn_buf   = {}
for frame in decoded_frames:
    txn_buf[frame.pgno] = frame.page_data
    if frame.commit > 0:
        committed.update(txn_buf)
        txn_buf.clear()
# txn_buf now holds trailing uncommitted frames → discard

db = bytearray(open(db_path, "rb").read())
for pgno, page in committed.items():
    offset = (pgno - 1) * page_size
    db[offset:offset + page_size] = page
# bump change counter
cc = int.from_bytes(db[24:28], "big") + 1
db[24:28]  = cc.to_bytes(4, "big")
db[92:96]  = cc.to_bytes(4, "big")
open(db_path, "wb").write(db)
```

### 5.2 Strategy B — Fix WAL and Let SQLite Apply It

1. Repair checksums (§4).
2. Set the WAL checkpoint sequence (bytes 12–15) equal to the base database's
   `version-valid-for` number (DB bytes 92–95).
3. In the WAL's page-1 frame (if present), update the DB change counter and
   version-valid-for to values consistent with the base DB.
4. Write the repaired WAL alongside the base DB.
5. Open with `PRAGMA wal_autocheckpoint = 0` to prevent immediate checkpointing,
   query the data, then checkpoint manually.

This strategy is fragile because SQLite performs multiple consistency checks
(salt matching, checkpoint-sequence matching, checksum validation). If any
field is wrong, SQLite silently ignores the WAL.

### 5.3 Strategy C — No Base Database

If only the WAL exists:

1. Determine `page_size` from the WAL header (bytes 8–11).
2. Collect all committed pages (Strategy A logic).
3. Write a fresh database file: allocate `max(pgno) * page_size` bytes, place
   each committed page at `(pgno - 1) * page_size`.
4. Ensure page 1 (the database header page) is present; it contains the schema.
5. Open with SQLite and query.

## 6. Extract and Output Data

### 6.1 Discover Schema

```sql
SELECT name, sql FROM sqlite_master WHERE type='table';
PRAGMA table_info(<table_name>);
```

### 6.2 Query All Rows

```python
import sqlite3, json
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
all_rows = []
for t in tables:
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t['name']})").fetchall()]
    for row in conn.execute(f"SELECT * FROM {t['name']}"):
        all_rows.append(dict(zip(cols, row)))
conn.close()
```

### 6.3 Sort and Write JSON

Sort by the primary key (or `id` column if present):

```python
all_rows.sort(key=lambda r: r.get("id", 0))
with open("/app/recovered.json", "w") as f:
    json.dump(all_rows, f, indent=2)
```

If the task specifies a different sort column or a multi-table output schema,
adapt accordingly.

## 7. Verification Checklist

Run these checks before declaring success:

- [ ] `PRAGMA integrity_check` returns `ok` on the recovered database.
- [ ] Row count matches the expected total (base + WAL additions).
- [ ] JSON output is valid, sorted by the declared key.
- [ ] No leftover `*.db-wal` or `*.db-shm` files that could confuse SQLite on
      re-open (unless using WAL mode intentionally).
- [ ] Spot-check a few rows: updated rows should show WAL values, not base
      values; new rows should be present.

## 8. Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| SQLite shows only base rows | WAL checksums invalid after decode | Recompute checksums (§4) |
| WAL is consumed but DB unchanged | Checkpoint seq / version-valid-for mismatch | Use Strategy A instead |
| `PRAGMA integrity_check` fails | Page applied from uncommitted transaction | Only apply committed frames |
| Wrong number of rows | Trailing uncommitted frames included | Discard frames after last commit |
| Missing WAL entirely | SQLite auto-checkpointed on prior open | Always work on copies; restore from backup |

## 9. Variation Dimensions Reference

| Dimension | What varies | How to handle |
|-----------|------------|---------------|
| **wal_encoding_or_obfuscation** | XOR, base64, inversion, byte-swap, header damage, or intact | §2 diagnostic tree |
| **wal_and_base_database_integrity** | Missing base DB, corrupt frame pages, partial frames, multi-WAL | §5.3 (no base), salt validation, frame-range checks |
| **recovery_depth** | Direct WAL consumption, manual frame parsing, full reconstruction | §5 strategies A/B/C |
| **schema_and_update_topology** | Single/multi table, varied column types, updates across transactions | §6 schema discovery, commit-tracking logic |

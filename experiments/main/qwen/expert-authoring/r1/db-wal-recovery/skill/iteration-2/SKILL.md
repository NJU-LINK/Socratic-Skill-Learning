---
name: db-wal-recovery
description: >
  Recover data from a SQLite database whose WAL (Write-Ahead Log) file has been
  encoded, obfuscated, or structurally damaged. Diagnose the transformation
  applied to the WAL, reverse it, apply committed WAL pages to the base
  database, and emit the recovered rows as sorted JSON.
---

# SQLite WAL Recovery

## Task Contract

You are given a SQLite database directory (typically `/app/`) containing a base
database file (`*.db`) and a WAL file (`*.db-wal`) that cannot be consumed
normally by SQLite. The goal is to recover **all** committed rows—including
those in the WAL—and write them to a JSON file (typically `/app/recovered.json`).

## Recovery Procedure

### Step 1 — Inventory and Inspect

```bash
ls -la /app/*.db /app/*.db-wal /app/*.db-shm 2>/dev/null
xxd -l 4 /app/main.db-wal        # first 4 bytes: is it valid WAL magic?
```

A valid WAL file starts with magic `0x377f0682` (big-endian) or `0x377f0683`
(little-endian). If the first 4 bytes differ, the WAL is encoded/obfuscated.

### Step 2 — Back Up Originals

Always copy the original files before any modification so you can retry if
something goes wrong:

```bash
cp /app/main.db /app/main.db.orig
cp /app/main.db-wal /app/main.db-wal.orig
```

### Step 3 — Detect and Decode the WAL Encoding

Run the complete recovery script below. It handles encoding detection,
decoding, frame parsing, committed-page application, and JSON output
in a single pass:

```python
import struct, json, sqlite3, os, shutil

DB_PATH  = "/app/main.db"
WAL_PATH = "/app/main.db-wal"
OUT_JSON = "/app/recovered.json"

# ── Read raw WAL ──────────────────────────────────────────────
with open(WAL_PATH, "rb") as f:
    raw = f.read()

# ── Detect encoding ──────────────────────────────────────────
MAGIC_BE = bytes([0x37, 0x7f, 0x06, 0x82])
MAGIC_LE = bytes([0x37, 0x7f, 0x06, 0x83])

def detect_and_decode(raw):
    h4 = raw[:4]
    # Already valid?
    if h4 in (MAGIC_BE, MAGIC_LE):
        return raw, "none"
    # Single-byte XOR (also covers ~byte when key=0xFF)
    for magic in (MAGIC_BE, MAGIC_LE):
        keys = [a ^ b for a, b in zip(h4, magic)]
        if len(set(keys)) == 1:
            k = keys[0]
            return bytes(b ^ k for b in raw), f"xor(0x{k:02x})"
    # Base64
    import base64
    try:
        dec = base64.b64decode(raw)
        if dec[:4] in (MAGIC_BE, MAGIC_LE):
            return dec, "base64"
    except Exception:
        pass
    # Byte-pair swap
    sw = bytearray(len(raw))
    for i in range(0, len(raw) - 1, 2):
        sw[i], sw[i+1] = raw[i+1], raw[i]
    if sw[:4] in (MAGIC_BE, MAGIC_LE):
        return bytes(sw), "swap2"
    raise RuntimeError(f"Cannot detect encoding. First 4 bytes: {h4.hex()}")

decoded, enc = detect_and_decode(raw)
print(f"Encoding: {enc}, decoded size: {len(decoded)}")

# ── Parse WAL header (32 bytes) ──────────────────────────────
magic      = struct.unpack(">I", decoded[0:4])[0]
page_size  = struct.unpack(">I", decoded[8:12])[0]
salt1      = struct.unpack(">I", decoded[16:20])[0]
salt2      = struct.unpack(">I", decoded[20:24])[0]
print(f"Magic: 0x{magic:08x}, page_size: {page_size}, salt: {salt1:08x} {salt2:08x}")

# ── Parse frames and track committed pages ───────────────────
frame_sz = 24 + page_size
n_frames = (len(decoded) - 32) // frame_sz

committed = {}   # pgno -> page_data  (latest committed version)
txn_buf   = {}   # pgno -> page_data  (current uncommitted txn)

for i in range(n_frames):
    off = 32 + i * frame_sz
    pgno   = struct.unpack(">I", decoded[off:off+4])[0]
    commit = struct.unpack(">I", decoded[off+4:off+8])[0]
    fs1    = struct.unpack(">I", decoded[off+8:off+12])[0]
    fs2    = struct.unpack(">I", decoded[off+12:off+16])[0]
    page   = decoded[off+24:off+24+page_size]
    # Skip frames from a different WAL generation (salt mismatch)
    if fs1 != salt1 or fs2 != salt2:
        continue
    txn_buf[pgno] = page
    if commit > 0:          # commit frame → flush txn buffer
        committed.update(txn_buf)
        txn_buf.clear()
# Anything left in txn_buf is uncommitted → discard

print(f"Frames: {n_frames}, committed pages: {sorted(committed.keys())}")

# ── Apply committed pages to the base database ───────────────
# Work on a copy so the original WAL sidecar doesn't interfere
patched = DB_PATH + ".patched"
shutil.copy2(DB_PATH, patched)
db = bytearray(open(patched, "rb").read())

for pgno, page in committed.items():
    off = (pgno - 1) * page_size
    end = off + page_size
    while len(db) < end:       # extend if WAL adds pages beyond DB
        db.extend(b"\x00" * page_size)
    db[off:end] = page

# Bump change counter so SQLite treats the file as modified
cc = int.from_bytes(db[24:28], "big") + 1
db[24:28]  = cc.to_bytes(4, "big")
db[92:96]  = cc.to_bytes(4, "big")

open(patched, "wb").write(db)

# ── Query all rows and write JSON ────────────────────────────
conn = sqlite3.connect(patched)
tables = [r[0] for r in
          conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
all_rows = []
for t in tables:
    cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
    for row in conn.execute(f"SELECT * FROM {t}"):
        all_rows.append(dict(zip(cols, row)))

integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
conn.close()
print(f"Integrity: {integrity}, rows: {len(all_rows)}")

# Sort by primary key (or 'id' column)
if all_rows and "id" in all_rows[0]:
    all_rows.sort(key=lambda r: r["id"])

with open(OUT_JSON, "w") as f:
    json.dump(all_rows, f, indent=2)
print(f"Wrote {len(all_rows)} rows to {OUT_JSON}")

# Clean up patched DB
os.remove(patched)
```

### Step 4 — Verify

After the script runs, confirm:

```bash
python3 -c "import json; d=json.load(open('/app/recovered.json')); print(len(d),'rows'); print(d[0]); print(d[-1])"
```

Check that:
- Row count matches the expected total (base rows + WAL additions).
- `PRAGMA integrity_check` returned `ok`.
- JSON is valid and sorted by the declared key.

---

## Reference: WAL Binary Format

### WAL Header (32 bytes, all fields big-endian uint32)

| Offset | Field |
|--------|-------|
| 0  | Magic: `0x377f0682` (BE checksums) or `0x377f0683` (LE checksums) |
| 4  | Version: `3007000` |
| 8  | Database page size (512–65536, power of 2) |
| 12 | Checkpoint sequence number |
| 16 | Salt-1 |
| 20 | Salt-2 |
| 24 | Checksum-1 (running checksum over bytes 0–23) |
| 28 | Checksum-2 |

### Frame Header (24 bytes per frame)

Frame *i* starts at byte offset `32 + i × (24 + page_size)`:

| Offset | Field |
|--------|-------|
| 0  | Page number (1-indexed) |
| 4  | Commit size (0 = mid-transaction; >0 = DB size in pages after commit) |
| 8  | Salt-1 (must match WAL header salt-1) |
| 12 | Salt-2 (must match WAL header salt-2) |
| 16 | Checksum-1 (running, covers frame header + page data) |
| 20 | Checksum-2 |

### Checksum Algorithm

Running pair `(s1, s2)` over consecutive 32-bit word pairs (big-endian if
magic is `0x377f0682`, little-endian if `0x377f0683`):

```
s1 = (s1 + v1 + s2) mod 2^32
s2 = (s2 + s1 + v2) mod 2^32
```

Header checksum covers bytes 0–23. Each frame checksum continues the running
sum over its 24-byte header and its page data.

**Note:** When using Strategy A (manual page overlay), checksums do NOT need
repair — we bypass SQLite's WAL validation entirely.

---

## Encoding Diagnostic Details

| Transform | Detection Method | Inverse |
|-----------|-----------------|---------|
| Single-byte XOR | `head[0:4] ⊕ MAGIC` yields uniform byte | XOR every byte with the key |
| Bitwise inversion (`~b`) | Special case of XOR with key `0xFF` | Same as XOR |
| Base64 wrapper | `b64decode(raw)[:4] == MAGIC` | `base64.b64decode(raw)` |
| Byte-pair swap | swap adjacent pairs of raw, check magic | Swap pairs again |
| Intact (no encoding) | `raw[:4] == MAGIC` | None needed |

**Dominant-byte heuristic:** In an XOR-encoded WAL, the most frequent byte in
the file is usually the XOR key (because zero-padded regions of pages become
the key value). Count byte frequencies as a cross-check.

---

## Strategy B — Fix WAL and Let SQLite Apply It

Use only if Strategy A produces integrity errors. This is fragile because
SQLite performs multiple silent-failure checks on WAL files:

1. Recompute all WAL checksums (header + each frame) using the algorithm above.
2. Set WAL checkpoint sequence (bytes 12–15) to match the base DB's
   version-valid-for (DB page 1, bytes 92–95).
3. If the WAL contains a page-1 frame, update its change counter and
   version-valid-for to be consistent with the base DB.
4. Write the repaired WAL alongside the base DB.
5. Open with `PRAGMA wal_autocheckpoint = 0`, query, then checkpoint.

---

## Strategy C — No Base Database

If only the WAL file exists (no `*.db`):

1. Parse `page_size` from WAL header bytes 8–11.
2. Collect committed pages using the same txn-tracking logic.
3. Write a fresh DB: allocate `max(pgno) × page_size` bytes, overlay pages.
4. Page 1 (the header page containing the schema) must be present in the WAL.
5. Query with SQLite.

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| SQLite shows only base rows | Checksums invalid after decode | Use Strategy A (bypasses checksums) |
| WAL silently ignored by SQLite | Checkpoint seq / version-valid-for mismatch | Use Strategy A |
| Integrity check fails | Applied pages from uncommitted transaction | Only apply frames before a commit |
| Too many rows | Trailing uncommitted frames included | Discard `txn_buf` after last frame |
| WAL auto-checkpointed away | Opening DB with WAL present triggers merge | Always back up first |
| Cannot find scripts | Scripts not in runtime PATH | Use the inline script in §Recovery Procedure |

---

## Variation Dimensions

| Dimension | What varies | Where handled |
|-----------|------------|---------------|
| `wal_encoding_or_obfuscation` | XOR, base64, inversion, byte-swap, intact | Step 3 `detect_and_decode` |
| `wal_and_base_database_integrity` | Missing base DB, corrupt frames, multi-WAL | Strategy C, salt filtering |
| `recovery_depth` | WAL consumption, manual overlay, full reconstruction | Strategies A/B/C |
| `schema_and_update_topology` | Multi-table, varied columns, multi-transaction | Step 3 schema discovery loop |

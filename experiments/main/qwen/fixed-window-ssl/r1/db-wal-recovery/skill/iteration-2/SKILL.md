---
name: db-wal-recovery
description: Diagnose and recover data from corrupted, encoded, or damaged SQLite WAL (Write-Ahead Logging) files by detecting the encoding transformation, decoding the WAL, and extracting all records to JSON.
---

# SQLite WAL Recovery Skill

## Quick Recovery Procedure

**CRITICAL: Never open the database with sqlite3 before fixing the WAL.** SQLite deletes invalid WAL files on open, making recovery impossible.

**Correct order:**
1. Examine WAL with `xxd` or hex dump
2. Diagnose encoding (compare first 4 bytes to WAL magic `0x377f0682`)
3. Decode WAL
4. Remove stale `-shm` files
5. Write decoded WAL back
6. **THEN** open database with sqlite3
7. Extract all records to JSON

**Run the recovery script:**
```bash
python3 skill/db-wal-recovery/scripts/recover.py
```

The script handles encoding detection, decoding, backup creation, and data extraction automatically.

## WAL Structure

**WAL Header (32 bytes):**
- Bytes 0-3: Magic `0x377f0682` (big-endian checksums) or `0x377f0683` (native)
- Bytes 4-7: Version `3007000`
- Bytes 8-11: Page size (must match database, typically 4096)
- Bytes 12-15: Checkpoint sequence
- Bytes 16-23: Salt values (random, must match frame headers)
- Bytes 24-31: Checksum (over bytes 0-23)

**Each Frame (24-byte header + page_size bytes):**
- Bytes 0-3: Page number (1-indexed)
- Bytes 4-7: DB size after commit (non-zero only on commit frame)
- Bytes 8-15: Salt values (must match header)
- Bytes 16-23: Checksum (chained from previous)
- Bytes 24+: Page data

Total size = 32 + (frames × (24 + page_size))

## Encoding Detection

**Principle:** Compare first 4 bytes against WAL magic `0x377f0682`. The difference pattern reveals the encoding.

**Detection algorithm:**
1. If first 4 bytes = `0x377f0682` → no encoding
2. Try XOR with each key 0-255: if uniform key produces magic → XOR encoding
3. If file is text (base64 alphabet) → decode base64, then check magic
4. Try bitwise NOT (XOR 0xFF)
5. Try byte swapping (16-bit pairs)

**Example:** If first bytes are `75 3d 44 c0`:
- `0x75 ^ 0x37 = 0x42`
- `0x3d ^ 0x7f = 0x42`
- `0x44 ^ 0x06 = 0x42`
- `0xc0 ^ 0x82 = 0x42`
- Uniform key `0x42` → XOR encoding

## Checksum Behavior

**Important:** SQLite may accept WALs with invalid checksums in some cases. Checksum repair is only needed when:
- SQLite explicitly rejects the WAL with checksum errors
- Header fields were manually modified after decoding
- Frames were reconstructed from partial data

**For simple encodings (XOR, base64, NOT):** The transformation preserves checksum validity. No repair needed.

**Checksum algorithm** (when repair is needed):
```python
def wal_checksum(data, s0=0, s1=0):
    """Cumulative checksum over 8-byte chunks."""
    if len(data) % 8:
        data += b'\x00' * (8 - len(data) % 8)
    for i in range(0, len(data), 8):
        w0 = struct.unpack('>I', data[i:i+4])[0]
        w1 = struct.unpack('>I', data[i+4:i+8])[0]
        s0 = (s0 + w0 + s1) & 0xFFFFFFFF
        s1 = (s1 + w1 + s0) & 0xFFFFFFFF
    return s0, s1
```

**Coverage:**
- Header checksum: bytes 0-23
- Frame checksums: bytes 0-7 (page_num + db_size) + page_data, chained

The recovery script automatically repairs checksums if SQLite rejects the WAL.

## Advanced Scenarios

**Damaged header only:** Reconstruct header with correct magic/version/page_size, extract salts from first frame, recompute checksums.

**Partial frames:** Parse frame headers, apply only valid frames, may need manual page reconstruction.

**Multiple WAL files:** Process in sequence, ensure salt values match, apply frames in order.

**Corrupted base database:** Extract valid pages from WAL frames, reconstruct database from pages alone.

## Common Pitfalls

1. **Opening database before fixing WAL** → SQLite deletes the WAL
2. **Not removing stale SHM file** → Locking issues
3. **Incorrect page size** → Frame alignment fails
4. **Mismatched salt values** → SQLite rejects WAL
5. **Wrong byte order** → Use big-endian for WAL headers
6. **Not creating backups** → Always backup before modification
7. **Fabricating data** → Never guess; extract from actual WAL/database
8. **Ignoring WAL naming variations** → Try `*.db-wal`, `*.wal`, `*-wal`

## Script Features

`scripts/recover.py` provides:
- Automatic backup creation (`.bak` files)
- Encoding auto-detection (XOR 0-255, base64, NOT, byte swap)
- WAL validation (magic, version, page size)
- Write verification
- SHM cleanup
- Multi-table extraction
- Intelligent sorting (by `id` or first column)
- WAL file auto-detection
- Automatic checksum repair if needed
- JSON output

## Verification

After recovery:
- WAL magic is valid (`0x377f0682` or `0x377f0683`)
- Database opens without errors
- All expected records present
- Record count matches expectations
- Data integrity verified

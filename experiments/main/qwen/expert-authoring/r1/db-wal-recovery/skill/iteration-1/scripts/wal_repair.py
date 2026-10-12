#!/usr/bin/env python3
"""
wal_repair.py — Diagnose, decode, and apply SQLite WAL frames to a base
database.  Handles single-byte XOR, bitwise inversion, base64, and intact
(but checksum-broken) WAL files.

Usage:
    python3 wal_repair.py <db_path> <wal_path> [output_db_path]

If output_db_path is omitted, the base database is patched in place (after
creating a .bak backup).
"""

import base64
import json
import os
import shutil
import sqlite3
import struct
import sys


# ── WAL constants ──────────────────────────────────────────────────────────
WAL_MAGIC_BE = 0x377F0682
WAL_MAGIC_LE = 0x377F0683
WAL_MAGIC_BYTES_BE = struct.pack(">I", WAL_MAGIC_BE)
WAL_MAGIC_BYTES_LE = struct.pack(">I", WAL_MAGIC_LE)
WAL_VERSION = 3007000


# ── Checksum ───────────────────────────────────────────────────────────────
def wal_checksum(data: bytes, s1: int = 0, s2: int = 0,
                 big_endian: bool = True) -> tuple[int, int]:
    """Compute the running WAL checksum over 8-byte word pairs."""
    assert len(data) % 8 == 0, f"data length {len(data)} not multiple of 8"
    fmt = ">I" if big_endian else "<I"
    for i in range(0, len(data), 8):
        v1 = struct.unpack(fmt, data[i:i + 4])[0]
        v2 = struct.unpack(fmt, data[i + 4:i + 8])[0]
        s1 = (s1 + v1 + s2) & 0xFFFFFFFF
        s2 = (s2 + s1 + v2) & 0xFFFFFFFF
    return s1, s2


# ── Encoding detection ─────────────────────────────────────────────────────
def detect_encoding(raw: bytes) -> tuple[str, object]:
    """Return (encoding_name, parameter) for the WAL transformation.

    Supported returns:
        ("none",    None)
        ("xor",     int_key)
        ("base64",  None)
    """
    head4 = raw[:4]

    # Already valid magic?
    if head4 in (WAL_MAGIC_BYTES_BE, WAL_MAGIC_BYTES_LE):
        return ("none", None)

    # Single-byte XOR (covers bitwise inversion when key == 0xFF)
    keys_be = [a ^ b for a, b in zip(head4, WAL_MAGIC_BYTES_BE)]
    if len(set(keys_be)) == 1:
        return ("xor", keys_be[0])
    keys_le = [a ^ b for a, b in zip(head4, WAL_MAGIC_BYTES_LE)]
    if len(set(keys_le)) == 1:
        return ("xor", keys_le[0])

    # Base64
    try:
        decoded = base64.b64decode(raw)
        if decoded[:4] in (WAL_MAGIC_BYTES_BE, WAL_MAGIC_BYTES_LE):
            return ("base64", None)
    except Exception:
        pass

    # Byte-swap pairs
    swapped = bytearray(len(raw))
    for i in range(0, len(raw) - 1, 2):
        swapped[i], swapped[i + 1] = raw[i + 1], raw[i]
    if swapped[:4] in (WAL_MAGIC_BYTES_BE, WAL_MAGIC_BYTES_LE):
        return ("swap2", None)

    raise RuntimeError(
        f"Cannot detect WAL encoding. First 4 bytes: {head4.hex()}"
    )


def decode_wal(raw: bytes, encoding: str, param) -> bytes:
    """Apply the inverse transformation."""
    if encoding == "none":
        return raw
    if encoding == "xor":
        key = param
        return bytes(b ^ key for b in raw)
    if encoding == "base64":
        return base64.b64decode(raw)
    if encoding == "swap2":
        out = bytearray(len(raw))
        for i in range(0, len(raw) - 1, 2):
            out[i], out[i + 1] = raw[i + 1], raw[i]
        return bytes(out)
    raise ValueError(f"Unknown encoding: {encoding}")


# ── WAL parser ─────────────────────────────────────────────────────────────
class WALFrame:
    __slots__ = ("pgno", "commit", "salt1", "salt2", "chk1", "chk2",
                 "page_data", "frame_index")

    def __init__(self, pgno, commit, salt1, salt2, chk1, chk2,
                 page_data, frame_index):
        self.pgno = pgno
        self.commit = commit
        self.salt1 = salt1
        self.salt2 = salt2
        self.chk1 = chk1
        self.chk2 = chk2
        self.page_data = page_data
        self.frame_index = frame_index


def parse_wal(data: bytes):
    """Yield (header_dict, [WALFrame, ...])."""
    magic = struct.unpack(">I", data[0:4])[0]
    big_endian = (magic == WAL_MAGIC_BE)
    version = struct.unpack(">I", data[4:8])[0]
    page_size = struct.unpack(">I", data[8:12])[0]
    chkpt_seq = struct.unpack(">I", data[12:16])[0]
    salt1 = struct.unpack(">I", data[16:20])[0]
    salt2 = struct.unpack(">I", data[20:24])[0]

    header = {
        "magic": magic,
        "big_endian": big_endian,
        "version": version,
        "page_size": page_size,
        "checkpoint_seq": chkpt_seq,
        "salt1": salt1,
        "salt2": salt2,
    }

    frames = []
    offset = 32
    idx = 0
    while offset + 24 + page_size <= len(data):
        idx += 1
        pgno = struct.unpack(">I", data[offset:offset + 4])[0]
        commit = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        fs1 = struct.unpack(">I", data[offset + 8:offset + 12])[0]
        fs2 = struct.unpack(">I", data[offset + 12:offset + 16])[0]
        fc1 = struct.unpack(">I", data[offset + 16:offset + 20])[0]
        fc2 = struct.unpack(">I", data[offset + 20:offset + 24])[0]
        page_data = data[offset + 24:offset + 24 + page_size]
        frames.append(WALFrame(pgno, commit, fs1, fs2, fc1, fc2,
                               page_data, idx))
        offset += 24 + page_size

    return header, frames


# ── Recovery logic ─────────────────────────────────────────────────────────
def apply_wal_to_db(db_path: str, header: dict, frames: list,
                    output_path: str | None = None):
    """Apply committed WAL frames to the base database.

    If db_path does not exist, reconstructs the database from WAL frames
    alone (Strategy C).  Returns the path to the patched database.
    """
    page_size = header["page_size"]
    salt1 = header["salt1"]
    salt2 = header["salt2"]

    # Track committed pages (latest version wins)
    committed_pages: dict[int, bytes] = {}
    txn_buf: dict[int, bytes] = {}

    for frame in frames:
        # Skip frames with mismatched salt (different WAL generation)
        if frame.salt1 != salt1 or frame.salt2 != salt2:
            continue
        txn_buf[frame.pgno] = frame.page_data
        if frame.commit > 0:
            committed_pages.update(txn_buf)
            txn_buf.clear()

    # Discard uncommitted trailing frames (anything left in txn_buf)

    if output_path is None:
        output_path = db_path

    # Backup original if it exists
    if os.path.exists(db_path):
        bak = db_path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(db_path, bak)
        db_data = bytearray(open(db_path, "rb").read())
    else:
        # Strategy C: no base database — reconstruct from WAL pages
        if not committed_pages:
            raise RuntimeError("No base DB and no committed WAL frames")
        max_pgno = max(committed_pages.keys())
        db_data = bytearray(max_pgno * page_size)
        if 1 not in committed_pages:
            raise RuntimeError(
                "No base DB and WAL does not contain page 1 (schema). "
                "Cannot reconstruct database."
            )

    # Overlay committed pages
    for pgno, page in committed_pages.items():
        offset = (pgno - 1) * page_size
        end = offset + page_size
        if end <= len(db_data):
            db_data[offset:end] = page
        else:
            # Extend DB with zero pages up to the needed page
            while len(db_data) < offset:
                db_data.extend(b"\x00" * page_size)
            db_data.extend(page)

    # Bump change counter and version-valid-for
    old_cc = struct.unpack(">I", db_data[24:28])[0]
    new_cc = old_cc + 1
    struct.pack_into(">I", db_data, 24, new_cc)
    struct.pack_into(">I", db_data, 92, new_cc)

    with open(output_path, "wb") as f:
        f.write(db_data)

    # Remove stale WAL / SHM so SQLite opens cleanly
    for suffix in ("-wal", "-shm", "-journal"):
        p = output_path + suffix
        if os.path.exists(p):
            os.remove(p)

    return output_path


# ── Extraction ─────────────────────────────────────────────────────────────
def extract_rows(db_path: str) -> list[dict]:
    """Return all rows from all user tables as a list of dicts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    rows = []
    for tname in tables:
        cols = [
            c[1]
            for c in conn.execute(f"PRAGMA table_info({tname})").fetchall()
        ]
        for row in conn.execute(f"SELECT * FROM {tname}"):
            rows.append(dict(zip(cols, tuple(row))))
    conn.close()
    return rows


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]
    wal_path = sys.argv[2]
    output_db = sys.argv[3] if len(sys.argv) > 3 else None

    # 1. Read artifacts
    with open(wal_path, "rb") as f:
        raw_wal = f.read()
    print(f"WAL size: {len(raw_wal)} bytes")

    # 2. Detect encoding
    enc, param = detect_encoding(raw_wal)
    print(f"Encoding: {enc}" + (f" (key=0x{param:02x})" if enc == "xor" else ""))

    # 3. Decode
    decoded = decode_wal(raw_wal, enc, param)

    # 4. Parse
    header, frames = parse_wal(decoded)
    print(f"Page size: {header['page_size']}, frames: {len(frames)}")

    # 5. Apply
    patched = apply_wal_to_db(db_path, header, frames, output_db)
    print(f"Patched DB: {patched}")

    # 6. Verify
    conn = sqlite3.connect(patched)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Integrity: {integrity}")
    conn.close()

    # 7. Extract
    rows = extract_rows(patched)
    print(f"Recovered {len(rows)} rows")

    # 8. Sort by id if present
    if rows and "id" in rows[0]:
        rows.sort(key=lambda r: r["id"])

    # 9. Write JSON
    json_dir = os.path.dirname(os.path.abspath(db_path))
    json_path = os.path.join(json_dir, "recovered.json")
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"Written: {json_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
SQLite WAL Recovery Tool
========================
Diagnoses and decodes obfuscated/encoded SQLite WAL files, then extracts
all recoverable records from the database.

Usage:
    python3 recover_wal.py --db /app/main.db --wal /app/main.db-wal --output /app/recovered.json

Strategy:
    1. Back up original files
    2. Read WAL bytes and detect the encoding/obfuscation
    3. Decode the WAL to its canonical binary form
    4. Validate WAL structure (magic, version, page size, salt consistency)
    5. Mount decoded WAL with the base database via SQLite
    6. Extract all records and write sorted JSON
"""

import argparse
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WAL_MAGIC_BE = 0x377F0682   # big-endian checksum WAL
WAL_MAGIC_LE = 0x377F0683   # little-endian checksum WAL
WAL_VERSION  = 3007000
WAL_HDR_SIZE = 32           # bytes
FRAME_HDR_SIZE = 24         # bytes

# ---------------------------------------------------------------------------
# Encoding detection helpers
# ---------------------------------------------------------------------------

def try_single_byte_xor(data: bytes, key: int) -> bytes:
    return bytes(b ^ key for b in data)


def try_bitwise_inversion(data: bytes) -> bytes:
    return bytes(~b & 0xFF for b in data)


def try_byte_swap(data: bytes, width: int = 2) -> bytes:
    """Swap adjacent byte pairs (width=2) or nibbles."""
    out = bytearray(data)
    if width == 2:
        for i in range(0, len(out) - 1, 2):
            out[i], out[i + 1] = out[i + 1], out[i]
    return bytes(out)


def try_base64_decode(data: bytes) -> bytes | None:
    import base64
    try:
        return base64.b64decode(data)
    except Exception:
        return None


def detect_db_page_size(db_path: str) -> int:
    """Read page size from the SQLite database header (offset 16-17, big-endian)."""
    with open(db_path, "rb") as f:
        f.seek(16)
        raw = f.read(2)
    ps = int.from_bytes(raw, "big")
    # Page size 1 means 65536 in modern SQLite
    return 65536 if ps == 1 else ps


# ---------------------------------------------------------------------------
# WAL validation
# ---------------------------------------------------------------------------

def validate_wal_header(data: bytes, expected_page_size: int | None = None) -> dict:
    """Parse and validate a decoded WAL header (32 bytes).
    Returns dict with parsed fields or raises ValueError."""
    if len(data) < WAL_HDR_SIZE:
        raise ValueError(f"WAL too short: {len(data)} < {WAL_HDR_SIZE}")

    magic = int.from_bytes(data[0:4], "big")
    if magic not in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        raise ValueError(f"Bad magic: 0x{magic:08x}")

    version = int.from_bytes(data[4:8], "big")
    if version != WAL_VERSION:
        raise ValueError(f"Bad version: {version} (expected {WAL_VERSION})")

    page_size = int.from_bytes(data[8:12], "big")
    if expected_page_size and page_size != expected_page_size:
        raise ValueError(f"Page size mismatch: {page_size} != {expected_page_size}")

    checkpoint_seq = int.from_bytes(data[12:16], "big")
    salt1 = data[16:20]
    salt2 = data[20:24]
    cksum1 = int.from_bytes(data[24:28], "big")
    cksum2 = int.from_bytes(data[28:32], "big")

    return {
        "magic": magic,
        "version": version,
        "page_size": page_size,
        "checkpoint_seq": checkpoint_seq,
        "salt1": salt1.hex(),
        "salt2": salt2.hex(),
        "cksum1": f"{cksum1:08x}",
        "cksum2": f"{cksum2:08x}",
        "big_endian_checksum": magic == WAL_MAGIC_BE,
    }


def validate_frame_salts(data: bytes, page_size: int) -> bool:
    """Verify salt consistency across WAL header and all frames."""
    header_salt = data[16:24]
    offset = WAL_HDR_SIZE
    frame_size = FRAME_HDR_SIZE + page_size
    frame_idx = 0
    while offset + FRAME_HDR_SIZE <= len(data):
        frame_salt = data[offset + 8: offset + 16]
        if frame_salt != header_salt:
            return False
        frame_idx += 1
        offset += frame_size
    return frame_idx > 0


def count_frames(data: bytes, page_size: int) -> int:
    frame_size = FRAME_HDR_SIZE + page_size
    usable = len(data) - WAL_HDR_SIZE
    return usable // frame_size


# ---------------------------------------------------------------------------
# Encoding auto-detection
# ---------------------------------------------------------------------------

def detect_encoding(raw_wal: bytes, expected_page_size: int) -> tuple[str, bytes]:
    """
    Try a sequence of transformations and return (method_name, decoded_bytes)
    for the first one that yields a structurally valid WAL.
    """
    candidates: list[tuple[str, bytes]] = []

    # 1. No transformation (already valid?)
    candidates.append(("none", raw_wal))

    # 2. Single-byte XOR – brute force all 256 keys, prioritising 0x42
    priority_keys = [0x42, 0xFF, 0xAA, 0x55]
    for key in priority_keys:
        candidates.append((f"xor_0x{key:02x}", try_single_byte_xor(raw_wal, key)))
    for key in range(256):
        if key not in priority_keys:
            candidates.append((f"xor_0x{key:02x}", try_single_byte_xor(raw_wal, key)))

    # 3. Bitwise inversion (NOT)
    candidates.append(("bitwise_not", try_bitwise_inversion(raw_wal)))

    # 4. Base64 decode
    b64 = try_base64_decode(raw_wal)
    if b64:
        candidates.append(("base64", b64))

    # 5. Byte swap (16-bit)
    candidates.append(("byte_swap_16", try_byte_swap(raw_wal, 2)))

    # 6. Multi-byte XOR (2, 4, 8, 16 byte keys) – derive from known plaintext
    # Known plaintext: magic(4) + version(4) + page_size(4) = 12 bytes
    known_prefix = (
        bytes.fromhex("377f0682")     # magic
        + (3007000).to_bytes(4, "big")  # version = 0x002DE218
        + expected_page_size.to_bytes(4, "big")
    )
    for klen in (2, 4, 8, 16):
        if klen <= len(known_prefix) and klen <= len(raw_wal):
            key_bytes = bytes(raw_wal[i] ^ known_prefix[i % len(known_prefix)]
                              for i in range(klen))
            decoded = bytes(raw_wal[i] ^ key_bytes[i % klen]
                            for i in range(len(raw_wal)))
            candidates.append((f"xor_multi_{key_bytes.hex()}", decoded))

    # Evaluate each candidate
    for method, decoded in candidates:
        try:
            info = validate_wal_header(decoded, expected_page_size)
            if validate_frame_salts(decoded, info["page_size"]):
                return method, decoded
            # Header valid but salts inconsistent – still a strong signal
            n_frames = count_frames(decoded, info["page_size"])
            if n_frames > 0:
                # Accept if header is valid and frame count > 0
                return method, decoded
        except ValueError:
            continue

    # Fallback: return the raw data and hope for the best
    return "unknown", raw_wal


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def _extract_records(db_path: str) -> list[dict]:
    """Open a database and extract all records from all tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]

    all_records = []
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM {table}")
        for row in cursor.fetchall():
            all_records.append(dict(zip(cols, row)))
    conn.close()

    if all_records:
        sort_key = None
        for col in ("id", "ID", "Id", "_id", "key", "pk"):
            if col in all_records[0]:
                sort_key = col
                break
        if sort_key is None:
            sort_key = list(all_records[0].keys())[0]
        all_records.sort(key=lambda r: r.get(sort_key, 0))
    return all_records


def _apply_frames_manually(db_path: str, decoded_wal: bytes, page_size: int):
    """
    Fallback: directly apply WAL frame pages to the database file,
    bypassing SQLite's WAL checksum validation.  This handles cases
    where the checksum algorithm differs from the standard implementation.

    Commit frames (commit_size > 0) indicate the last frame of a transaction.
    Only committed transactions should be applied; however, when the last
    frame has commit_size > 0 we treat all preceding frames as committed.
    """
    # Parse frames
    frame_size = FRAME_HDR_SIZE + page_size
    offset = WAL_HDR_SIZE
    frames = []
    while offset + frame_size <= len(decoded_wal):
        pg_num = int.from_bytes(decoded_wal[offset:offset+4], "big")
        commit_sz = int.from_bytes(decoded_wal[offset+4:offset+8], "big")
        page_data = decoded_wal[offset + FRAME_HDR_SIZE:
                                offset + FRAME_HDR_SIZE + page_size]
        frames.append((pg_num, commit_sz, page_data))
        offset += frame_size

    if not frames:
        print("[!] No frames found for manual application", file=sys.stderr)
        return

    # Find the last commit frame
    last_commit = -1
    for i, (_, commit_sz, _) in enumerate(frames):
        if commit_sz > 0:
            last_commit = i

    # Apply frames up to and including the last commit
    apply_up_to = last_commit if last_commit >= 0 else len(frames) - 1

    with open(db_path, "r+b") as f:
        for i in range(apply_up_to + 1):
            pg_num, _, page_data = frames[i]
            if pg_num < 1:
                continue
            file_offset = (pg_num - 1) * page_size
            # Extend file if needed (for new pages)
            f.seek(0, 2)  # seek to end
            current_size = f.tell()
            needed = file_offset + page_size
            if needed > current_size:
                f.seek(current_size)
                f.write(b'\x00' * (needed - current_size))
            f.seek(file_offset)
            f.write(page_data)

        # Update DB header: file change counter (offset 24-27)
        f.seek(24)
        old_cc = int.from_bytes(f.read(4), "big")
        f.seek(24)
        f.write((old_cc + 1).to_bytes(4, "big"))

    print(f"[*] Manually applied {apply_up_to + 1} frames to database")


def recover_database(db_path: str, decoded_wal: bytes, output_path: str,
                     expected_columns: list[str] | None = None):
    """
    Mount the decoded WAL alongside the base database, extract all records,
    and write them as sorted JSON.

    Falls back to manual page application if SQLite rejects the WAL
    (e.g. due to non-standard checksums).
    """
    tmpdir = tempfile.mkdtemp(prefix="wal_recovery_")
    try:
        tmp_db = os.path.join(tmpdir, "main.db")
        tmp_wal = tmp_db + "-wal"
        tmp_shm = tmp_db + "-shm"

        # Copy base database
        shutil.copy2(db_path, tmp_db)

        # Write decoded WAL
        with open(tmp_wal, "wb") as f:
            f.write(decoded_wal)

        # Create empty -shm file (SQLite will populate it)
        with open(tmp_shm, "wb") as f:
            pass

        # --- Approach 1: let SQLite consume the WAL naturally ---
        all_records = _extract_records(tmp_db)

        # --- Approach 2: manual page application if WAL was ignored ---
        base_records = _extract_records(db_path)
        if len(all_records) <= len(base_records):
            print("[*] SQLite did not apply WAL (checksum mismatch?). "
                  "Falling back to manual page application.")
            shutil.copy2(db_path, tmp_db)
            page_size = detect_db_page_size(db_path)
            _apply_frames_manually(tmp_db, decoded_wal, page_size)
            all_records = _extract_records(tmp_db)

        with open(output_path, "w") as f:
            json.dump(all_records, f, indent=2, default=str)

        return all_records

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SQLite WAL Recovery Tool")
    parser.add_argument("--db", required=True, help="Path to the base SQLite database")
    parser.add_argument("--wal", required=True, help="Path to the (possibly encoded) WAL file")
    parser.add_argument("--output", required=True, help="Path for the output JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.wal):
        print(f"ERROR: WAL file not found: {args.wal}", file=sys.stderr)
        sys.exit(1)

    expected_ps = detect_db_page_size(args.db)
    print(f"[*] Database page size: {expected_ps}")

    with open(args.wal, "rb") as f:
        raw_wal = f.read()
    print(f"[*] WAL file size: {len(raw_wal)} bytes")

    # Back up originals
    for src in (args.db, args.wal):
        bak = src + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(src, bak)
            print(f"[*] Backed up {src} → {bak}")

    method, decoded = detect_encoding(raw_wal, expected_ps)
    print(f"[*] Detected encoding: {method}")

    info = validate_wal_header(decoded, expected_ps)
    n_frames = count_frames(decoded, info["page_size"])
    salts_ok = validate_frame_salts(decoded, info["page_size"])
    print(f"[*] WAL magic: 0x{info['magic']:08x}, version: {info['version']}, "
          f"page_size: {info['page_size']}")
    print(f"[*] Frames: {n_frames}, salt_consistent: {salts_ok}")

    records = recover_database(args.db, decoded, args.output)
    print(f"[*] Recovered {len(records)} records → {args.output}")

    # Verify record count if task expects specific count
    print(f"[*] First record: {records[0] if records else 'N/A'}")
    print(f"[*] Last record:  {records[-1] if records else 'N/A'}")
    print("[+] Recovery complete.")


if __name__ == "__main__":
    main()

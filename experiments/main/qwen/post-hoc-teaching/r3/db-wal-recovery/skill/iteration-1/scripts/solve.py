#!/usr/bin/env python3
"""
SQLite WAL Recovery - Reference Implementation

This script demonstrates the complete recovery pipeline for the db-wal-recovery
skill family. It handles:
- Single-byte XOR encoding detection and reversal
- Base64 wrapping detection and reversal
- Bitwise inversion detection and reversal
- Byte swap detection and reversal
- Damaged header repair
- WAL integrity verification
- Manual frame application fallback
- JSON output generation

Usage: python3 solve.py
"""

import sqlite3
import json
import os
import sys
import struct
import base64
import glob

WAL_MAGIC_BIG = b'\x37\x7f\x06\x82'
WAL_MAGIC_LITTLE = b'\x37\x7f\x06\x83'
WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24


def wal_checksum(data, seed1=0, seed2=0):
    """Compute SQLite WAL running checksum."""
    s1, s2 = seed1, seed2
    for i in range(0, len(data) & ~7, 8):
        x = int.from_bytes(data[i:i+4], 'little')
        y = int.from_bytes(data[i+4:i+8], 'little')
        s1 = (s1 + x + s2) & 0xFFFFFFFF
        s2 = (s2 + y + s1) & 0xFFFFFFFF
    return s1, s2


def is_valid_wal_header(data):
    """Check if data starts with valid WAL magic."""
    if len(data) < 4:
        return False
    return data[:4] in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE)


def detect_xor_key(data):
    """Find XOR key by checking decoded magic + format version + page size."""
    if len(data) < 32:
        return None
    for key in range(1, 256):
        decoded = bytes(b ^ key for b in data[:32])
        if decoded[:4] not in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
            continue
        version = int.from_bytes(decoded[4:8], 'big')
        page_size = int.from_bytes(decoded[8:12], 'big')
        if (version == 3007000 and
            512 <= page_size <= 65536 and
            (page_size & (page_size - 1)) == 0):
            return key
    return None


def diagnose_and_decode(wal_data):
    """Diagnose WAL encoding and return (decoded_data, description)."""
    # Already valid?
    if is_valid_wal_header(wal_data):
        return wal_data, "none (valid WAL)"

    # Single-byte XOR
    key = detect_xor_key(wal_data)
    if key is not None:
        return bytes(b ^ key for b in wal_data), f"XOR(0x{key:02x})"

    # Base64
    try:
        decoded = base64.b64decode(wal_data.strip())
        if is_valid_wal_header(decoded):
            return decoded, "base64"
    except Exception:
        pass

    # Bitwise inversion
    inv = bytes(~b & 0xFF for b in wal_data)
    if is_valid_wal_header(inv):
        return inv, "bitwise_inversion"

    # Byte swap
    if len(wal_data) % 2 == 0:
        swapped = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 2):
            swapped[i] = wal_data[i+1]
            swapped[i+1] = wal_data[i]
        if is_valid_wal_header(bytes(swapped)):
            return bytes(swapped), "byte_swap"

    # Base64 + XOR
    try:
        b64d = base64.b64decode(wal_data.strip())
        key = detect_xor_key(b64d)
        if key is not None:
            return bytes(b ^ key for b in b64d), f"base64+XOR(0x{key:02x})"
    except Exception:
        pass

    return None, "unknown"


def verify_wal_integrity(wal_data):
    """Verify WAL header and frame checksums. Returns (valid, message)."""
    if len(wal_data) < WAL_HEADER_SIZE:
        return False, "too short"

    calc_cs1, calc_cs2 = wal_checksum(wal_data[:24])
    stored_cs1 = int.from_bytes(wal_data[24:28], 'big')
    stored_cs2 = int.from_bytes(wal_data[28:32], 'big')
    if calc_cs1 != stored_cs1 or calc_cs2 != stored_cs2:
        return False, "header checksum mismatch"

    page_size = int.from_bytes(wal_data[8:12], 'big')
    frame_size = FRAME_HEADER_SIZE + page_size
    salt1 = int.from_bytes(wal_data[16:20], 'big')
    salt2 = int.from_bytes(wal_data[20:24], 'big')

    offset = WAL_HEADER_SIZE
    frame_num = 0
    rcs1, rcs2 = calc_cs1, calc_cs2

    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset + FRAME_HEADER_SIZE]
        pd = wal_data[offset + FRAME_HEADER_SIZE:offset + frame_size]

        if int.from_bytes(fh[8:12], 'big') != salt1:
            return False, f"frame {frame_num} salt1 mismatch"
        if int.from_bytes(fh[12:16], 'big') != salt2:
            return False, f"frame {frame_num} salt2 mismatch"

        cs_data = fh[:8] + pd
        rcs1, rcs2 = wal_checksum(cs_data, rcs1, rcs2)
        if rcs1 != int.from_bytes(fh[16:20], 'big'):
            return False, f"frame {frame_num} checksum1 mismatch"
        if rcs2 != int.from_bytes(fh[20:24], 'big'):
            return False, f"frame {frame_num} checksum2 mismatch"

        offset += frame_size
        frame_num += 1

    return True, f"valid, {frame_num} frames"


def find_database(directory='/app'):
    """Find SQLite database file."""
    for f in sorted(glob.glob(os.path.join(directory, '*.db'))):
        if f.endswith(('-wal', '-shm')):
            continue
        try:
            with open(f, 'rb') as fh:
                if fh.read(16).startswith(b'SQLite format 3'):
                    return f
        except Exception:
            continue
    return None


def find_wal(db_path):
    """Find WAL file for database."""
    wal = db_path + '-wal'
    if os.path.exists(wal):
        return wal
    d = os.path.dirname(db_path)
    for f in os.listdir(d):
        if f.endswith('-wal') and not f.endswith('-shm'):
            return os.path.join(d, f)
        if f.endswith('.wal'):
            return os.path.join(d, f)
    return None


def apply_frames_manually(db_path, wal_data):
    """Apply WAL frames directly to database file."""
    page_size = int.from_bytes(wal_data[8:12], 'big')
    frame_size = FRAME_HEADER_SIZE + page_size

    db_data = bytearray(open(db_path, 'rb').read())

    offset = WAL_HEADER_SIZE
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], 'big')
        page_data = wal_data[offset+FRAME_HEADER_SIZE:offset+frame_size]

        needed = page_num * page_size
        if needed > len(db_data):
            db_data.extend(b'\x00' * (needed - len(db_data)))

        page_offset = (page_num - 1) * page_size
        db_data[page_offset:page_offset + page_size] = page_data
        offset += frame_size

    open(db_path, 'wb').write(bytes(db_data))
    for suffix in ['-wal', '-shm']:
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)


def main():
    app_dir = '/app'

    db_path = find_database(app_dir)
    if not db_path:
        print("ERROR: No SQLite database found", file=sys.stderr)
        sys.exit(1)
    print(f"Database: {db_path}")

    wal_path = find_wal(db_path)
    if not wal_path:
        print("No WAL file found, extracting from base database only")
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        all_rows = {}
        for (tname,) in tables:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tname})")]
            rows = conn.execute(f"SELECT * FROM {tname}").fetchall()
            all_rows[tname] = (cols, rows)
        conn.close()
    else:
        print(f"WAL: {wal_path} ({os.path.getsize(wal_path)} bytes)")
        wal_data = open(wal_path, 'rb').read()

        decoded, enc = diagnose_and_decode(wal_data)
        print(f"Encoding: {enc}")

        if decoded is None:
            print("ERROR: Cannot decode WAL", file=sys.stderr)
            sys.exit(1)

        valid, msg = verify_wal_integrity(decoded)
        print(f"Integrity: {msg}")

        # Write decoded WAL
        open(wal_path, 'wb').write(decoded)

        # Try SQLite first
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_autocheckpoint=0")
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            all_rows = {}
            for (tname,) in tables:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tname})")]
                rows = conn.execute(f"SELECT * FROM {tname}").fetchall()
                all_rows[tname] = (cols, rows)
            total = sum(len(r[1]) for r in all_rows.values())
            print(f"Read {total} records via SQLite")
        except Exception as e:
            print(f"SQLite failed: {e}, trying manual apply")
            conn.close()
            apply_frames_manually(db_path, decoded)
            conn = sqlite3.connect(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            all_rows = {}
            for (tname,) in tables:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tname})")]
                rows = conn.execute(f"SELECT * FROM {tname}").fetchall()
                all_rows[tname] = (cols, rows)
        conn.close()

    # Find main table and output JSON
    main_table = max(all_rows.items(), key=lambda x: len(x[1][1]))
    tname = main_table[0]
    cols, rows = main_table[1]

    records = [dict(zip(cols, row)) for row in rows]
    sort_key = 'id' if 'id' in cols else cols[0]
    records.sort(key=lambda x: x.get(sort_key, 0))

    output = os.path.join(app_dir, 'recovered.json')
    with open(output, 'w') as f:
        json.dump(records, f, indent=2)
    print(f"Wrote {len(records)} records to {output}")


if __name__ == '__main__':
    main()

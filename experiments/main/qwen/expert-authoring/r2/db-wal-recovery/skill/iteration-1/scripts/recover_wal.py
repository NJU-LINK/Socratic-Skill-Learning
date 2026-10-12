#!/usr/bin/env python3
"""
SQLite WAL Recovery Tool

Diagnoses encoding/corruption in a WAL file, decodes it, validates the result,
and applies it to the base database. Outputs all records as JSON.

Usage:
    python3 recover_wal.py [--db /app/main.db] [--wal /app/main.db-wal]
                           [--output /app/recovered.json]
                           [--expected-rows N]
"""
import argparse
import base64
import json
import os
import shutil
import struct
import sys
import sqlite3
from collections import Counter

VALID_MAGIC_BE = b'\x37\x7f\x06\x82'
VALID_MAGIC_LE = b'\x37\x7f\x06\x83'
VALID_MAGICS = [VALID_MAGIC_BE, VALID_MAGIC_LE]
WAL_VERSION = 3007000


def read_db_page_size(db_path):
    """Read page size from SQLite database header (2 bytes at offset 16-17)."""
    with open(db_path, 'rb') as f:
        header = f.read(100)
    ps = struct.unpack('>H', header[16:18])[0]
    return 65536 if ps == 1 else ps


def parse_wal_header(data):
    """Parse WAL header fields. Returns dict or None if invalid."""
    if len(data) < 32:
        return None
    magic = data[:4]
    if magic not in VALID_MAGICS:
        return None
    version = struct.unpack('>I', data[4:8])[0]
    page_size = struct.unpack('>I', data[8:12])[0]
    ckpt_seq = struct.unpack('>I', data[12:16])[0]
    salt1 = struct.unpack('>I', data[16:20])[0]
    salt2 = struct.unpack('>I', data[20:24])[0]
    return {
        'magic': magic,
        'version': version,
        'page_size': page_size,
        'ckpt_seq': ckpt_seq,
        'salt1': salt1,
        'salt2': salt2,
    }


def parse_frames(data, page_size):
    """Parse WAL frames. Returns list of (pgno, commit, salt1, salt2, page_data)."""
    frames = []
    offset = 32
    while offset + 24 + page_size <= len(data):
        pgno = struct.unpack('>I', data[offset:offset+4])[0]
        commit = struct.unpack('>I', data[offset+4:offset+8])[0]
        fs1 = struct.unpack('>I', data[offset+8:offset+12])[0]
        fs2 = struct.unpack('>I', data[offset+12:offset+16])[0]
        page_data = data[offset+24:offset+24+page_size]
        if pgno == 0:
            break
        frames.append((pgno, commit, fs1, fs2, page_data))
        offset += 24 + page_size
    return frames


def validate_decoded_wal(decoded, db_page_size):
    """Validate a decoded WAL. Returns (header_info, frames, issues) or None."""
    hdr = parse_wal_header(decoded)
    if hdr is None:
        return None
    if hdr['version'] != WAL_VERSION:
        return None
    if hdr['page_size'] != db_page_size:
        return None

    frame_size = 24 + db_page_size
    remainder = len(decoded) - 32
    if remainder <= 0 or remainder % frame_size != 0:
        return None

    frames = parse_frames(decoded, db_page_size)
    issues = []
    for i, (pgno, commit, fs1, fs2, _) in enumerate(frames):
        if fs1 != hdr['salt1'] or fs2 != hdr['salt2']:
            issues.append(f"Frame {i+1}: salt mismatch")

    return hdr, frames, issues


def try_xor_decode(wal_data, db_page_size):
    """Try single-byte XOR keys. Returns (key, decoded) or None."""
    freq = Counter(wal_data)
    most_common_byte = freq.most_common(1)[0][0]
    candidates = [most_common_byte] + [k for k in range(256) if k != most_common_byte]

    for key in candidates:
        decoded_hdr = bytes([b ^ key for b in wal_data[:32]])
        if decoded_hdr[:4] not in VALID_MAGICS:
            continue
        version = struct.unpack('>I', decoded_hdr[4:8])[0]
        wal_ps = struct.unpack('>I', decoded_hdr[8:12])[0]
        if version != WAL_VERSION or wal_ps != db_page_size:
            continue
        full = bytes([b ^ key for b in wal_data])
        result = validate_decoded_wal(full, db_page_size)
        if result:
            hdr, frames, issues = result
            print(f"  XOR key 0x{key:02x}: {len(frames)} frames, {len(issues)} issues")
            return key, full
    return None


def try_base64_decode(wal_data, db_page_size):
    """Try base64 decoding. Returns decoded bytes or None."""
    try:
        text = wal_data.decode('ascii', errors='ignore').strip()
        valid_b64 = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r ')
        if not all(c in valid_b64 for c in text):
            return None
        decoded = base64.b64decode(text)
        result = validate_decoded_wal(decoded, db_page_size)
        if result:
            hdr, frames, _ = result
            print(f"  Base64: {len(frames)} frames")
            return decoded
    except Exception:
        pass
    return None


def try_bitnot_decode(wal_data, db_page_size):
    """Try bitwise NOT (XOR 0xFF). Returns decoded bytes or None."""
    decoded_hdr = bytes([b ^ 0xFF for b in wal_data[:32]])
    if decoded_hdr[:4] not in VALID_MAGICS:
        return None
    version = struct.unpack('>I', decoded_hdr[4:8])[0]
    wal_ps = struct.unpack('>I', decoded_hdr[8:12])[0]
    if version != WAL_VERSION or wal_ps != db_page_size:
        return None
    full = bytes([b ^ 0xFF for b in wal_data])
    result = validate_decoded_wal(full, db_page_size)
    if result:
        hdr, frames, _ = result
        print(f"  Bitwise NOT: {len(frames)} frames")
        return full
    return None


def try_byteswap_decode(wal_data, db_page_size):
    """Try 2-byte swap. Returns decoded bytes or None."""
    decoded_hdr = bytearray(wal_data[:32])
    for i in range(0, 32, 2):
        decoded_hdr[i], decoded_hdr[i+1] = decoded_hdr[i+1], decoded_hdr[i]
    if bytes(decoded_hdr[:4]) not in VALID_MAGICS:
        return None
    version = struct.unpack('>I', decoded_hdr[4:8])[0]
    wal_ps = struct.unpack('>I', decoded_hdr[8:12])[0]
    if version != WAL_VERSION or wal_ps != db_page_size:
        return None
    full = bytearray(wal_data)
    for i in range(0, len(full) - 1, 2):
        full[i], full[i+1] = full[i+1], full[i]
    result = validate_decoded_wal(bytes(full), db_page_size)
    if result:
        hdr, frames, _ = result
        print(f"  2-byte swap: {len(frames)} frames")
        return bytes(full)
    return None


def count_db_rows(db_path):
    """Count total rows across all user tables in the database."""
    try:
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        total = 0
        for t in tables:
            total += conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
        conn.close()
        return total
    except Exception:
        return -1


def try_sqlite_wal_replay(db_path, wal_path, decoded):
    """Write decoded WAL and try SQLite replay. Returns row count or -1."""
    # Backup current DB
    db_backup = db_path + '.bak'
    wal_backup = wal_path + '.bak'
    shutil.copy2(db_path, db_backup)
    if os.path.exists(wal_path):
        shutil.copy2(wal_path, wal_backup)

    # Write decoded WAL
    with open(wal_path, 'wb') as f:
        f.write(decoded)

    # Remove stale -shm
    shm = db_path + '-shm'
    if os.path.exists(shm):
        os.remove(shm)

    # Try to open and count
    try:
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        total = 0
        for t in tables:
            total += conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
        # Force checkpoint to merge WAL into DB
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        return total
    except Exception as e:
        # Restore from backup
        shutil.copy2(db_backup, db_path)
        if os.path.exists(wal_backup):
            shutil.copy2(wal_backup, wal_path)
        return -1
    finally:
        for f in [db_backup, wal_backup]:
            if os.path.exists(f):
                os.remove(f)


def manual_page_apply(db_path, decoded, page_size):
    """Manually overlay WAL pages onto the database file."""
    with open(db_path, 'rb') as f:
        db = bytearray(f.read())

    frames = parse_frames(decoded, page_size)
    applied = 0
    for pgno, commit, fs1, fs2, page_data in frames:
        if pgno == 1:
            db[0:page_size] = page_data
        elif pgno > 1:
            start = (pgno - 1) * page_size
            if start + page_size <= len(db):
                db[start:start+page_size] = page_data
        applied += 1

    with open(db_path, 'wb') as f:
        f.write(db)

    # Remove WAL and SHM so SQLite opens the DB directly
    for suffix in ['-wal', '-shm', '-journal']:
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)

    return applied


def export_json(db_path, output_path):
    """Export all table data as JSON, sorted by first column (usually id)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    results = []
    for t in tables:
        tname = t['name']
        cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
        col_names = [c['name'] for c in cols]
        pk_col = col_names[0]
        rows = conn.execute(
            f"SELECT * FROM {tname} ORDER BY {pk_col}"
        ).fetchall()
        for row in rows:
            results.append(dict(row))

    conn.close()

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


def main():
    parser = argparse.ArgumentParser(description='SQLite WAL Recovery Tool')
    parser.add_argument('--db', default='/app/main.db')
    parser.add_argument('--wal', default=None, help='WAL path (default: db-wal)')
    parser.add_argument('--output', default='/app/recovered.json')
    parser.add_argument('--expected-rows', type=int, default=0,
                        help='Expected total row count (for validation)')
    args = parser.parse_args()

    db_path = args.db
    wal_path = args.wal or (db_path + '-wal')
    output_path = args.output

    for p in [db_path, wal_path]:
        if not os.path.exists(p):
            print(f"ERROR: Not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"Database: {db_path}")
    print(f"WAL:      {wal_path}")
    print(f"Output:   {output_path}\n")

    # --- Step 1: Read DB page size (does NOT open SQLite) ---
    db_page_size = read_db_page_size(db_path)
    print(f"DB page size: {db_page_size}")

    # --- Step 2: Read WAL (before any SQLite interaction!) ---
    # IMPORTANT: Opening the DB with sqlite3 may cause SQLite to delete or
    # modify a corrupted WAL file. Read the raw WAL first.
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    print(f"WAL size: {len(wal_data)} bytes")
    print(f"WAL magic: {wal_data[:4].hex()}")

    # --- Step 3: Check if WAL is already valid ---
    decoded = None
    hdr = parse_wal_header(wal_data)
    if hdr and hdr['version'] == WAL_VERSION and hdr['page_size'] == db_page_size:
        print("WAL is already valid!")
        decoded = wal_data

    # --- Step 4: Try encodings ---
    if decoded is None:
        print("\nDiagnosing encoding...")

        methods = [
            ("Single-byte XOR", try_xor_decode),
            ("Base64", try_base64_decode),
            ("Bitwise NOT", try_bitnot_decode),
            ("2-byte swap", try_byteswap_decode),
        ]
        for name, method in methods:
            print(f"  Trying {name}...")
            result = method(wal_data, db_page_size)
            if result:
                if isinstance(result, tuple):
                    _, decoded = result
                else:
                    decoded = result
                print(f"  -> {name} succeeded!")
                break

    if decoded is None:
        print("ERROR: Could not decode WAL with any standard method.",
              file=sys.stderr)
        print("Consider: multi-byte XOR, custom transforms, or partial WAL.",
              file=sys.stderr)
        sys.exit(1)

    # --- Step 5: Validate decoded WAL ---
    result = validate_decoded_wal(decoded, db_page_size)
    if not result:
        print("ERROR: Decoded WAL validation failed", file=sys.stderr)
        sys.exit(1)
    hdr, frames, issues = result
    print(f"\nDecoded WAL: {len(frames)} frames")
    for pgno, commit, fs1, fs2, _ in frames:
        print(f"  Page {pgno}, commit={commit}")
    if issues:
        for issue in issues:
            print(f"  WARNING: {issue}")

    # --- Step 6: Apply the WAL ---
    # IMPORTANT: Do NOT open the DB with sqlite3 while the WAL is still
    # corrupted/encoded — SQLite may delete or overwrite the WAL file.
    # Write the decoded WAL first, then interact with SQLite.

    # First, write decoded WAL (overwriting the encoded one)
    with open(wal_path, 'wb') as f:
        f.write(decoded)
    print(f"\nWrote decoded WAL to {wal_path}")

    # Remove stale shared-memory file
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)

    # Try SQLite WAL replay
    print("Attempting SQLite WAL replay...")
    try:
        conn = sqlite3.connect(db_path)
        row_count = 0
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        for t in tables:
            row_count += conn.execute(
                f"SELECT COUNT(*) FROM {t[0]}"
            ).fetchone()[0]
        print(f"  Rows visible: {row_count}")

        # Force checkpoint to merge WAL into DB
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        wal_replay_succeeded = True
    except sqlite3.DatabaseError as e:
        print(f"  SQLite error: {e}")
        wal_replay_succeeded = False
        row_count = 0

    # If WAL replay didn't produce results, try manual page overlay
    if not wal_replay_succeeded or row_count == 0:
        print("  SQLite WAL replay failed. Trying manual page overlay...")
        # Restore original DB (undo any partial WAL damage)
        applied = manual_page_apply(db_path, decoded, db_page_size)
        print(f"  Manually applied {applied} pages")
        row_count = count_db_rows(db_path)
        print(f"  Rows after manual apply: {row_count}")

    # --- Step 8: Export JSON ---
    print(f"\nExporting to {output_path}...")
    results = export_json(db_path, output_path)
    print(f"Exported {len(results)} records")

    # --- Step 9: Self-verification ---
    if args.expected_rows and len(results) != args.expected_rows:
        print(f"WARNING: Expected {args.expected_rows} rows but got {len(results)}")

    if results:
        ids = [r.get('id', i) for i, r in enumerate(results)]
        if ids != sorted(ids):
            print("WARNING: Records not sorted by id")
        if len(ids) != len(set(ids)):
            print("WARNING: Duplicate ids detected")
        print(f"First: {results[0]}")
        print(f"Last:  {results[-1]}")

    print("\nDone!")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

Diagnoses encoding/obfuscation applied to a WAL file, decodes it,
verifies structural integrity, and extracts all data from the database.

Usage:
    python3 recover.py <db_path> [wal_path] [--output recovered.json]

If wal_path is not given, defaults to <db_path>-wal.
"""

import struct
import sys
import os
import json
import shutil
import sqlite3
import base64
import argparse


# WAL magic bytes
WAL_MAGIC_BE = b'\x37\x7f\x06\x82'  # Big-endian checksums
WAL_MAGIC_LE = b'\x37\x7f\x06\x83'  # Little-endian checksums
WAL_VERSION = 3007000


def read_page_size_from_db(db_path):
    """Read the page size from the SQLite database header."""
    with open(db_path, 'rb') as f:
        header = f.read(100)
    if header[:16] != b'SQLite format 3\x00':
        raise ValueError(f"Not a valid SQLite database: {db_path}")
    # Page size is stored as big-endian uint16 at offset 16-17
    page_size = int.from_bytes(header[16:18], 'big')
    # Special case: value 1 means 65536
    if page_size == 1:
        return 65536
    return page_size


def diagnose_encoding(data):
    """
    Diagnose what encoding/transformation was applied to WAL data.
    Returns (encoding_type, parameter) tuple.
    """
    if len(data) < 32:
        return 'too_short', None

    magic = data[0:4]

    # Check if already valid
    if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        # Also verify version
        version = struct.unpack('>I', data[4:8])[0]
        if version == WAL_VERSION:
            return 'none', None
        else:
            return 'damaged_header', None

    # Try single-byte XOR
    for k in range(1, 256):
        decoded_magic = bytes(b ^ k for b in magic)
        if decoded_magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
            # Verify with version field
            decoded_version = bytes(data[i] ^ k for i in range(4, 8))
            version = struct.unpack('>I', decoded_version)[0]
            if version == WAL_VERSION:
                return 'xor_single', k

    # Try bitwise inversion
    inv_magic = bytes(~b & 0xFF for b in magic)
    if inv_magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        inv_version = bytes(~b & 0xFF for b in data[4:8])
        version = struct.unpack('>I', inv_version)[0]
        if version == WAL_VERSION:
            return 'bitwise_inversion', None

    # Try byte swap (reverse byte order within 4-byte words)
    swapped = bytearray()
    for i in range(0, min(8, len(data)), 4):
        swapped.extend(data[i:i+4][::-1])
    if bytes(swapped[0:4]) in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        version = struct.unpack('>I', swapped[4:8])[0]
        if version == WAL_VERSION:
            return 'byte_swap', None

    # Try base64 decode
    try:
        decoded = base64.b64decode(data)
        if len(decoded) >= 32 and decoded[0:4] in (WAL_MAGIC_BE, WAL_MAGIC_LE):
            version = struct.unpack('>I', decoded[4:8])[0]
            if version == WAL_VERSION:
                return 'base64', None
    except Exception:
        pass

    # Try multi-byte XOR (derive key from known magic)
    for expected_magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        key = bytes(a ^ b for a, b in zip(magic, expected_magic))
        # Check if key has a repeating pattern
        for key_len in [2, 4]:
            if len(key) >= key_len:
                candidate_key = key[:key_len]
                # Verify: apply repeating key to version field
                decoded_version = bytes(
                    data[4+i] ^ candidate_key[i % key_len] for i in range(4)
                )
                version = struct.unpack('>I', decoded_version)[0]
                if version == WAL_VERSION:
                    return f'xor_multi_{key_len}', candidate_key

    return 'unknown', None


def decode_wal(data, encoding_type, parameter):
    """Apply the reverse transformation to decode WAL data."""
    if encoding_type == 'none':
        return data

    if encoding_type == 'xor_single':
        key = parameter
        return bytes(b ^ key for b in data)

    if encoding_type == 'bitwise_inversion':
        return bytes(~b & 0xFF for b in data)

    if encoding_type == 'byte_swap':
        result = bytearray()
        for i in range(0, len(data), 4):
            chunk = data[i:i+4]
            result.extend(chunk[::-1])
        return bytes(result)

    if encoding_type == 'base64':
        return base64.b64decode(data)

    if encoding_type.startswith('xor_multi_'):
        key = parameter
        return bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))

    raise ValueError(f"Cannot decode: {encoding_type}")


def verify_wal_header(wal_data, expected_page_size=None):
    """Verify the WAL header fields are valid. Returns dict of header fields."""
    if len(wal_data) < 32:
        raise ValueError("WAL data too short for header")

    header = {
        'magic': wal_data[0:4],
        'version': struct.unpack('>I', wal_data[4:8])[0],
        'page_size': struct.unpack('>I', wal_data[8:12])[0],
        'checkpoint_seq': struct.unpack('>I', wal_data[12:16])[0],
        'salt1': struct.unpack('>I', wal_data[16:20])[0],
        'salt2': struct.unpack('>I', wal_data[20:24])[0],
        'checksum1': struct.unpack('>I', wal_data[24:28])[0],
        'checksum2': struct.unpack('>I', wal_data[28:32])[0],
    }

    if header['magic'] not in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        raise ValueError(f"Invalid WAL magic: {header['magic'].hex()}")

    if header['version'] != WAL_VERSION:
        raise ValueError(f"Invalid WAL version: {header['version']}")

    return header


def parse_wal_frames(wal_data, page_size):
    """Parse all frames from a WAL file. Returns list of frame dicts."""
    frames = []
    offset = 32  # After WAL header

    while offset + 24 + page_size <= len(wal_data):
        frame_header = wal_data[offset:offset+24]
        if len(frame_header) < 24:
            break

        page_number = struct.unpack('>I', frame_header[0:4])[0]
        db_size_after = struct.unpack('>I', frame_header[4:8])[0]
        salt1 = struct.unpack('>I', frame_header[8:12])[0]
        salt2 = struct.unpack('>I', frame_header[12:16])[0]
        cksum1 = struct.unpack('>I', frame_header[16:20])[0]
        cksum2 = struct.unpack('>I', frame_header[20:24])[0]

        page_data = wal_data[offset+24:offset+24+page_size]

        frames.append({
            'page_number': page_number,
            'db_size_after': db_size_after,
            'salt1': salt1,
            'salt2': salt2,
            'checksum': (cksum1, cksum2),
            'page_data': page_data,
            'offset': offset
        })

        offset += 24 + page_size

    return frames


def apply_frames_to_db(db_path, frames, page_size):
    """Apply WAL frames to a base database file by overlaying pages."""
    with open(db_path, 'rb') as f:
        db_data = bytearray(f.read())

    # Apply frames in order (later frames override earlier ones)
    for frame in frames:
        page_num = frame['page_number']
        if page_num == 0:
            continue  # Skip invalid page numbers

        offset = (page_num - 1) * page_size
        end = offset + page_size

        if end > len(db_data):
            # Extend database to accommodate this page
            db_data.extend(b'\x00' * (end - len(db_data)))

        db_data[offset:end] = frame['page_data']

    # Write back
    with open(db_path, 'wb') as f:
        f.write(db_data)


def try_sqlite_query(db_path):
    """Try to query the database and return table names and data."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get table names
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

        result = {}
        for table in tables:
            table_name = table[0]
            rows = conn.execute(
                f"SELECT * FROM [{table_name}]"
            ).fetchall()
            result[table_name] = [dict(row) for row in rows]

        conn.close()
        return result
    except Exception as e:
        return {'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description='SQLite WAL Recovery')
    parser.add_argument('db_path', help='Path to the SQLite database file')
    parser.add_argument('wal_path', nargs='?', help='Path to the WAL file')
    parser.add_argument('--output', '-o', default='recovered.json',
                        help='Output JSON file path')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip backup (not recommended)')
    args = parser.parse_args()

    db_path = args.db_path
    wal_path = args.wal_path or (db_path + '-wal')

    if not os.path.exists(db_path):
        print(f"ERROR: Database file not found: {db_path}")
        sys.exit(1)

    if not os.path.exists(wal_path):
        print(f"ERROR: WAL file not found: {wal_path}")
        print("Looking for alternative WAL locations...")
        # Try common alternatives
        for alt in [db_path + '.wal', db_path.replace('.db', '') + '-wal']:
            if os.path.exists(alt):
                wal_path = alt
                print(f"Found WAL at: {wal_path}")
                break
        else:
            print("No WAL file found. Extracting base database only.")
            data = try_sqlite_query(db_path)
            with open(args.output, 'w') as f:
                json.dump(data, f, indent=2)
            sys.exit(0)

    # STEP 0: BACKUP
    if not args.no_backup:
        shutil.copy2(db_path, db_path + '.bak')
        shutil.copy2(wal_path, wal_path + '.bak')
        print(f"Backed up: {db_path} -> {db_path}.bak")
        print(f"Backed up: {wal_path} -> {wal_path}.bak")

    # Read WAL data
    with open(wal_path, 'rb') as f:
        raw_wal = f.read()

    print(f"WAL file size: {len(raw_wal)} bytes")

    # STEP 1: Diagnose encoding
    encoding_type, parameter = diagnose_encoding(raw_wal)
    print(f"Diagnosed encoding: {encoding_type}, parameter: {parameter}")

    if encoding_type == 'unknown':
        print("ERROR: Could not diagnose WAL encoding.")
        print("First 32 bytes (hex):", raw_wal[:32].hex())
        sys.exit(1)

    # STEP 2: Decode
    if encoding_type != 'none':
        decoded_wal = decode_wal(raw_wal, encoding_type, parameter)
        print(f"Decoded WAL size: {len(decoded_wal)} bytes")
    else:
        decoded_wal = raw_wal
        print("WAL is already in valid format.")

    # STEP 3: Verify header
    try:
        header = verify_wal_header(decoded_wal)
        print(f"WAL header valid: magic={header['magic'].hex()}, "
              f"version={header['version']}, "
              f"page_size={header['page_size']}")
    except ValueError as e:
        print(f"WAL header verification failed: {e}")
        print("Attempting manual frame parsing...")

    # Get page size from base database
    page_size = read_page_size_from_db(db_path)
    print(f"Database page size: {page_size}")

    # STEP 4: Try direct SQLite consumption first
    # Write decoded WAL back
    with open(wal_path, 'wb') as f:
        f.write(decoded_wal)

    data = try_sqlite_query(db_path)
    if 'error' not in data:
        total_records = sum(len(rows) for rows in data.values())
        print(f"SQLite direct read succeeded: {total_records} total records")
        # Write output
        all_records = []
        for table_name, rows in data.items():
            all_records.extend(rows)
        # Sort by id if present
        if all_records and 'id' in all_records[0]:
            all_records.sort(key=lambda r: r['id'])
        with open(args.output, 'w') as f:
            json.dump(all_records, f, indent=2)
        print(f"Output written to: {args.output}")
        sys.exit(0)

    print(f"SQLite direct read failed: {data['error']}")
    print("Falling back to manual frame parsing...")

    # STEP 5: Manual frame parsing
    # Restore from backup since SQLite may have modified files
    if not args.no_backup:
        shutil.copy2(db_path + '.bak', db_path)

    frames = parse_wal_frames(decoded_wal, page_size)
    print(f"Parsed {len(frames)} frames from WAL")

    if not frames:
        print("ERROR: No valid frames found in WAL")
        sys.exit(1)

    # Show frame summary
    for i, frame in enumerate(frames):
        print(f"  Frame {i}: page={frame['page_number']}, "
              f"db_size_after={frame['db_size_after']}")

    # Apply frames to database
    apply_frames_to_db(db_path, frames, page_size)
    print(f"Applied {len(frames)} frames to database")

    # STEP 6: Extract data
    data = try_sqlite_query(db_path)
    if 'error' in data:
        print(f"ERROR: Could not read database after applying frames: {data['error']}")
        sys.exit(1)

    total_records = sum(len(rows) for rows in data.values())
    print(f"Recovered {total_records} total records")

    all_records = []
    for table_name, rows in data.items():
        all_records.extend(rows)

    if all_records and 'id' in all_records[0]:
        all_records.sort(key=lambda r: r['id'])

    with open(args.output, 'w') as f:
        json.dump(all_records, f, indent=2)

    print(f"Output written to: {args.output}")


if __name__ == '__main__':
    main()

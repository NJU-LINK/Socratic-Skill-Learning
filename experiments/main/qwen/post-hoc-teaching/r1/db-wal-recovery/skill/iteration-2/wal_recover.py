#!/usr/bin/env python3
"""
SQLite WAL Recovery Tool

Diagnoses and recovers data from SQLite databases with corrupted, encoded,
or obfuscated Write-Ahead Log (WAL) files.

Usage:
    python3 wal_recover.py [--db PATH] [--wal PATH] [--output PATH] [--json]

The tool will:
1. Detect the encoding/obfuscation applied to the WAL
2. Decode the WAL to a valid format
3. Apply the WAL to the database (direct or manual)
4. Export all recovered data as JSON
"""

import struct
import os
import sys
import json
import base64
import shutil
import sqlite3
import argparse
from typing import Optional, Tuple, List, Dict, Any


# Valid WAL magic numbers (big-endian)
WAL_MAGIC_BIG = 0x377F0682
WAL_MAGIC_LITTLE = 0x377F0683
VALID_MAGICS = {WAL_MAGIC_BIG, WAL_MAGIC_LITTLE}

# Valid SQLite page sizes
VALID_PAGE_SIZES = {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}

# Expected WAL version
WAL_VERSION = 3007000


def read_wal_header(data: bytes) -> dict:
    """Parse WAL file header (first 32 bytes)."""
    if len(data) < 32:
        return None
    return {
        'magic': struct.unpack('>I', data[0:4])[0],
        'version': struct.unpack('>I', data[4:8])[0],
        'page_size': struct.unpack('>I', data[8:12])[0],
        'checkpoint_seq': struct.unpack('>I', data[12:16])[0],
        'salt1': struct.unpack('>I', data[16:20])[0],
        'salt2': struct.unpack('>I', data[20:24])[0],
        'checksum1': struct.unpack('>I', data[24:28])[0],
        'checksum2': struct.unpack('>I', data[28:32])[0],
    }


def is_valid_wal_header(header: dict) -> bool:
    """Check if a parsed header looks like a valid WAL header."""
    if header is None:
        return False
    return (
        header['magic'] in VALID_MAGICS and
        header['version'] == WAL_VERSION and
        header['page_size'] in VALID_PAGE_SIZES
    )


def wal_checksum(data_bytes: bytes, s0: int = 0, s1: int = 0, endian: str = '<') -> Tuple[int, int]:
    """
    Compute WAL checksum.
    
    The checksum algorithm processes data as pairs of 32-bit unsigned integers.
    The byte order for reading these integers depends on the creating machine.
    Try '<' (little-endian) first, then '>' (big-endian) if validation fails.
    Checksum values are always stored in big-endian in the WAL file.
    """
    assert len(data_bytes) % 8 == 0, "Data must be multiple of 8 bytes"
    for i in range(0, len(data_bytes), 8):
        u0 = struct.unpack(endian + 'I', data_bytes[i:i+4])[0]
        u1 = struct.unpack(endian + 'I', data_bytes[i+4:i+8])[0]
        s0 = (s0 + u0 + s1) % (2**32)
        s1 = (s1 + u1 + s0) % (2**32)
    return s0, s1


def detect_checksum_endian(data: bytes) -> str:
    """Detect which byte order was used for checksums in this WAL."""
    header = read_wal_header(data)
    if not header:
        return '<'
    
    stored_s0 = header['checksum1']
    stored_s1 = header['checksum2']
    
    for endian in ['<', '>']:
        s0, s1 = wal_checksum(data[0:24], endian=endian)
        if s0 == stored_s0 and s1 == stored_s1:
            return endian
    
    return '<'  # Default to LE


def validate_wal_checksums(data: bytes, endian: str = '<') -> dict:
    """
    Validate all checksums and salt values in a WAL file.
    
    Returns dict with:
    - 'header_valid': bool
    - 'frames': list of {index, valid, page_num, commit_flag, salt_valid}
    - 'endian': the byte order used for checksums
    
    A frame is considered valid only if BOTH:
    1. Its checksum matches the computed checksum
    2. Its salt values match the header's salt values
    
    Salt mismatch indicates the frame belongs to a different WAL session
    (the WAL was reset/recycled) and should not be applied.
    """
    header = read_wal_header(data)
    if not header:
        return {'header_valid': False, 'frames': []}
    
    page_size = header['page_size']
    header_salt1 = header['salt1']
    header_salt2 = header['salt2']
    
    # Validate header checksum
    hdr_s0, hdr_s1 = wal_checksum(data[0:24], endian=endian)
    header_valid = (hdr_s0 == header['checksum1'] and hdr_s1 == header['checksum2'])
    
    # Validate frame checksums and salts
    frames = []
    offset = 32
    prev_s0, prev_s1 = hdr_s0, hdr_s1
    frame_idx = 0
    
    while offset + 24 + page_size <= len(data):
        frame_hdr = data[offset:offset+24]
        pg_num = struct.unpack('>I', frame_hdr[0:4])[0]
        commit_flag = struct.unpack('>I', frame_hdr[4:8])[0]
        frame_salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        frame_salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        stored_s0 = struct.unpack('>I', frame_hdr[16:20])[0]
        stored_s1 = struct.unpack('>I', frame_hdr[20:24])[0]
        
        # Checksum covers frame header bytes 0-7 + page data
        cksum_data = data[offset:offset+8] + data[offset+24:offset+24+page_size]
        frm_s0, frm_s1 = wal_checksum(cksum_data, prev_s0, prev_s1, endian)
        
        checksum_valid = (frm_s0 == stored_s0 and frm_s1 == stored_s1)
        salt_valid = (frame_salt1 == header_salt1 and frame_salt2 == header_salt2)
        
        # Frame is valid only if both checksum and salt match
        valid = checksum_valid and salt_valid
        
        frames.append({
            'index': frame_idx,
            'page_num': pg_num,
            'commit_flag': commit_flag,
            'valid': valid,
            'checksum_valid': checksum_valid,
            'salt_valid': salt_valid,
            'offset': offset,
        })
        
        prev_s0, prev_s1 = frm_s0, frm_s1
        offset += 24 + page_size
        frame_idx += 1
    
    return {'header_valid': header_valid, 'frames': frames, 'endian': endian}


def try_decode_wal(wal_data: bytes) -> Tuple[Optional[bytes], str]:
    """
    Try various decodings to produce a valid WAL.
    Returns (decoded_data, method_description) or (None, "no valid decoding found").
    """
    # 1. Check if already valid
    header = read_wal_header(wal_data)
    if is_valid_wal_header(header):
        expected_size = 32 + ((len(wal_data) - 32) // (24 + header['page_size'])) * (24 + header['page_size'])
        if len(wal_data) == expected_size:
            return wal_data, "intact (no encoding)"
    
    # 2. Try base64 decode
    try:
        decoded = base64.b64decode(wal_data)
        header = read_wal_header(decoded)
        if is_valid_wal_header(header):
            return decoded, "base64"
    except Exception:
        pass
    
    # Also try base64 with whitespace stripped
    try:
        cleaned = wal_data.replace(b'\n', b'').replace(b'\r', b'').replace(b' ', b'')
        decoded = base64.b64decode(cleaned)
        header = read_wal_header(decoded)
        if is_valid_wal_header(header):
            return decoded, "base64 (stripped whitespace)"
    except Exception:
        pass
    
    # 3. Try bitwise NOT
    not_data = bytes([~b & 0xFF for b in wal_data])
    header = read_wal_header(not_data)
    if is_valid_wal_header(header):
        return not_data, "bitwise NOT"
    
    # 4. Try byte-swap pairs
    swap_data = bytearray(len(wal_data))
    for i in range(0, len(wal_data) - 1, 2):
        swap_data[i] = wal_data[i+1]
        swap_data[i+1] = wal_data[i]
    header = read_wal_header(swap_data)
    if is_valid_wal_header(header):
        return bytes(swap_data), "byte-swap pairs"
    
    # 5. Try single-byte XOR (most common obfuscation)
    for key in range(1, 256):
        decoded = bytes([b ^ key for b in wal_data])
        header = read_wal_header(decoded)
        if is_valid_wal_header(header):
            # Verify file size makes sense
            page_size = header['page_size']
            frame_size = 24 + page_size
            remaining = len(decoded) - 32
            if remaining > 0 and remaining % frame_size == 0:
                return decoded, f"single-byte XOR with key 0x{key:02X}"
    
    # 6. Try 4-byte word swap
    if len(wal_data) % 4 == 0:
        swap4_data = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 4):
            swap4_data[i:i+4] = wal_data[i:i+4][::-1]
        header = read_wal_header(swap4_data)
        if is_valid_wal_header(header):
            return bytes(swap4_data), "4-byte word reverse"
    
    return None, "no valid decoding found"


def repair_wal_checksums(data: bytes, endian: str = '<') -> bytes:
    """
    Repair WAL checksums. Recomputes header and frame checksums.
    This is needed when the encoding process or corruption damaged checksums
    but the actual page data is intact.
    """
    data = bytearray(data)
    header = read_wal_header(data)
    if not header:
        return bytes(data)
    
    page_size = header['page_size']
    
    # Recompute header checksum (over first 24 bytes)
    hdr_s0, hdr_s1 = wal_checksum(bytes(data[0:24]), endian=endian)
    struct.pack_into('>I', data, 24, hdr_s0)
    struct.pack_into('>I', data, 28, hdr_s1)
    
    # Recompute frame checksums
    offset = 32
    prev_s0, prev_s1 = hdr_s0, hdr_s1
    
    while offset + 24 + page_size <= len(data):
        # Checksum covers frame header bytes 0-7 + page data
        cksum_data = bytes(data[offset:offset+8]) + bytes(data[offset+24:offset+24+page_size])
        frm_s0, frm_s1 = wal_checksum(cksum_data, prev_s0, prev_s1, endian)
        struct.pack_into('>I', data, offset + 16, frm_s0)
        struct.pack_into('>I', data, offset + 20, frm_s1)
        prev_s0, prev_s1 = frm_s0, frm_s1
        offset += 24 + page_size
    
    return bytes(data)


def parse_wal_frames(data: bytes) -> List[dict]:
    """Parse all frames from a valid WAL file."""
    header = read_wal_header(data)
    if not header:
        return []
    
    page_size = header['page_size']
    frames = []
    offset = 32
    
    while offset + 24 + page_size <= len(data):
        frame_hdr = data[offset:offset+24]
        pg_num = struct.unpack('>I', frame_hdr[0:4])[0]
        commit_flag = struct.unpack('>I', frame_hdr[4:8])[0]
        salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        page_data = data[offset+24:offset+24+page_size]
        
        frames.append({
            'page_num': pg_num,
            'commit_flag': commit_flag,
            'salt1': salt1,
            'salt2': salt2,
            'page_data': page_data,
            'offset': offset,
        })
        offset += 24 + page_size
    
    return frames


def group_frames_by_transaction(frames: List[dict]) -> List[List[dict]]:
    """
    Group frames into transactions. Each transaction ends with a frame where commit_flag > 0.
    
    The commit_flag value on the last frame is NOT a boolean — it's the database size
    in pages after that transaction commits. A value of 0 means "not the last frame
    of a transaction."
    
    Frames within a transaction are atomic: you must apply ALL of them or NONE of them.
    Applying only part of a transaction leaves the database with inconsistent B-tree
    structure (e.g., an internal node pointing to a page that was never written).
    
    Returns a list of transactions, where each transaction is a list of frames.
    Uncommitted/partial transactions (frames after the last commit frame) are discarded.
    """
    transactions = []
    current_tx = []
    for frame in frames:
        current_tx.append(frame)
        if frame['commit_flag'] > 0:
            transactions.append(current_tx)
            current_tx = []
    # current_tx is non-empty → partial/uncommitted transaction, discard it
    if current_tx:
        print(f"  Discarding {len(current_tx)} frames from uncommitted transaction")
    return transactions


def apply_frames_to_db(db_path: str, frames: List[dict], page_size: int) -> None:
    """
    Apply WAL frames directly to the database file.
    
    Groups frames by transaction and only applies committed transactions.
    For each page, the last committed frame wins (later transactions override earlier ones).
    """
    # Group frames into transactions
    transactions = group_frames_by_transaction(frames)
    print(f"  Found {len(transactions)} committed transaction(s)")
    
    # Build final page state from committed transactions only
    page_map = {}  # page_num → page_data
    for tx in transactions:
        for frame in tx:
            page_map[frame['page_num']] = frame['page_data']
    
    db_data = bytearray(open(db_path, 'rb').read())
    
    for pg_num, page_data in page_map.items():
        page_offset = (pg_num - 1) * page_size
        # Extend database if needed
        while len(db_data) < page_offset + page_size:
            db_data.extend(b'\x00' * page_size)
        db_data[page_offset:page_offset+page_size] = page_data
    
    open(db_path, 'wb').write(db_data)


def recover_database(db_path: str, wal_path: str, output_path: str = None) -> List[Dict[str, Any]]:
    """
    Main recovery function.
    
    1. Backup original files
    2. Detect and decode WAL encoding
    3. Try direct SQLite consumption
    4. Fall back to manual frame application if needed
    5. Export all data as list of dicts
    """
    # Read WAL
    if not os.path.exists(wal_path):
        print(f"ERROR: WAL file not found: {wal_path}")
        return []
    
    wal_data = open(wal_path, 'rb').read()
    print(f"WAL file size: {len(wal_data)} bytes")
    
    # Backup original WAL
    bak_path = wal_path + '.original'
    if not os.path.exists(bak_path):
        shutil.copy2(wal_path, bak_path)
    
    # Phase 1: Detect encoding
    decoded_wal, method = try_decode_wal(wal_data)
    print(f"Encoding detected: {method}")
    
    if decoded_wal is None:
        print("ERROR: Could not decode WAL file")
        return []
    
    # Phase 2: Validate structure
    endian = detect_checksum_endian(decoded_wal)
    validation = validate_wal_checksums(decoded_wal, endian)
    print(f"Checksum endian: {'little-endian' if endian == '<' else 'big-endian'}")
    print(f"Header checksum valid: {validation['header_valid']}")
    
    valid_frames = [f for f in validation['frames'] if f['valid']]
    invalid_frames = [f for f in validation['frames'] if not f['valid']]
    salt_mismatch = [f for f in validation['frames'] if not f.get('salt_valid', True)]
    checksum_bad = [f for f in validation['frames'] if not f.get('checksum_valid', True)]
    print(f"Frames: {len(validation['frames'])} total, {len(valid_frames)} valid, {len(invalid_frames)} invalid")
    if salt_mismatch:
        print(f"  Salt mismatch: {len(salt_mismatch)} frame(s) from different WAL session")
    if checksum_bad:
        print(f"  Checksum invalid: {len(checksum_bad)} frame(s)")
    
    # Phase 2b: Repair checksums if needed
    header = read_wal_header(decoded_wal)
    page_size = header['page_size']
    
    if not validation['header_valid'] or invalid_frames:
        print("Checksums invalid, attempting repair...")
        repaired_wal = repair_wal_checksums(decoded_wal, endian)
        # Verify repair
        re_validation = validate_wal_checksums(repaired_wal, endian)
        if re_validation['header_valid']:
            print(f"  Header checksum repaired successfully")
            decoded_wal = repaired_wal
            valid_frames = [f for f in re_validation['frames'] if f['valid']]
            invalid_frames = [f for f in re_validation['frames'] if not f['valid']]
            print(f"  Frames after repair: {len(valid_frames)} valid, {len(invalid_frames)} invalid")
        else:
            print(f"  Header checksum repair failed, will try manual recovery")
    
    # Phase 3: Write decoded WAL and try direct consumption
    
    # Remove SHM file to force re-read
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    # Write decoded WAL
    open(wal_path, 'wb').write(decoded_wal)
    
    # Try direct SQLite consumption
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        
        all_records = []
        for table in tables:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM [{table}] LIMIT 0").description]
            rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
            for row in rows:
                record = dict(zip(cols, row))
                record['_table'] = table
                all_records.append(record)
        
        conn.close()
        
        if all_records:
            print(f"Direct recovery successful: {len(all_records)} records from {len(tables)} table(s)")
            return all_records
    except Exception as e:
        print(f"Direct consumption failed: {e}")
    
    # Phase 3b: Manual frame application
    print("Falling back to manual frame application...")
    
    # Restore original DB from backup if available
    db_bak = db_path + '.original'
    if os.path.exists(db_bak):
        shutil.copy2(db_bak, db_path)
    
    # Parse frames from decoded WAL
    frames = parse_wal_frames(decoded_wal)
    
    # Filter to valid frames only (if checksums were bad)
    if invalid_frames:
        valid_frame_offsets = {f['offset'] for f in valid_frames}
        frames = [f for f in frames if f['offset'] in valid_frame_offsets]
        print(f"Using {len(frames)} valid frames (skipped {len(invalid_frames)} corrupt)")
    
    # Apply frames
    apply_frames_to_db(db_path, frames, page_size)
    
    # Remove WAL so SQLite doesn't re-apply
    if os.path.exists(wal_path):
        os.remove(wal_path)
    
    # Read recovered database
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        
        all_records = []
        for table in tables:
            cols = [d[0] for d in conn.execute(f"SELECT * FROM [{table}] LIMIT 0").description]
            rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
            for row in rows:
                record = dict(zip(cols, row))
                record['_table'] = table
                all_records.append(record)
        
        conn.close()
        print(f"Manual recovery successful: {len(all_records)} records from {len(tables)} table(s)")
        return all_records
    except Exception as e:
        print(f"Manual recovery failed: {e}")
        return []


def export_json(records: List[Dict[str, Any]], output_path: str, sort_key: str = 'id') -> None:
    """Export records to JSON file."""
    # Remove internal fields
    clean_records = []
    for r in records:
        clean = {k: v for k, v in r.items() if not k.startswith('_')}
        clean_records.append(clean)
    
    # Sort by key
    if clean_records and sort_key in clean_records[0]:
        clean_records.sort(key=lambda x: x.get(sort_key, 0))
    
    with open(output_path, 'w') as f:
        json.dump(clean_records, f, indent=2, default=str)
    
    print(f"Exported {len(clean_records)} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='SQLite WAL Recovery Tool')
    parser.add_argument('--db', default='/app/main.db', help='Path to database file')
    parser.add_argument('--wal', default=None, help='Path to WAL file (default: <db>-wal)')
    parser.add_argument('--output', default='/app/recovered.json', help='Output JSON path')
    parser.add_argument('--sort-key', default='id', help='Key to sort records by')
    parser.add_argument('--no-export', action='store_true', help='Skip JSON export')
    
    args = parser.parse_args()
    
    db_path = args.db
    wal_path = args.wal or (db_path + '-wal')
    
    if not os.path.exists(db_path):
        print(f"ERROR: Database file not found: {db_path}")
        sys.exit(1)
    
    # Backup original DB
    db_bak = db_path + '.original'
    if not os.path.exists(db_bak):
        shutil.copy2(db_path, db_bak)
    
    records = recover_database(db_path, wal_path)
    
    if records and not args.no_export:
        # Filter out _table field for single-table case
        tables = set(r.get('_table', '') for r in records)
        if len(tables) == 1:
            for r in records:
                r.pop('_table', None)
        
        export_json(records, args.output, args.sort_key)
    elif not records:
        print("ERROR: No records recovered")
        sys.exit(1)


if __name__ == '__main__':
    main()

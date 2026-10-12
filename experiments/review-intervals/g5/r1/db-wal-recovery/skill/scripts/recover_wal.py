#!/usr/bin/env python3
"""
SQLite WAL Recovery Script
Diagnoses encoding, decodes WAL, validates structure, and recovers data.

Usage:
    python3 recover_wal.py [--db PATH] [--wal PATH] [--output PATH] [--force-manual]

The script:
1. Backs up original files (critical - never skip this)
2. Diagnoses the encoding using known-plaintext anchors
3. Decodes the WAL
4. Validates checksums
5. Attempts SQLite-native recovery first, falls back to manual frame application
6. Exports all data to JSON
"""

import struct
import sys
import os
import json
import shutil
import sqlite3
import argparse
import base64
import glob
from typing import Optional, Tuple, List, Dict, Any

# WAL magic bytes
WAL_MAGIC_BE = bytes([0x37, 0x7F, 0x06, 0x82])  # Big-endian checksums
WAL_MAGIC_LE = bytes([0x37, 0x7F, 0x06, 0x83])  # Little-endian checksums
SQLITE_HEADER = b'SQLite format 3\x00'

WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24


def wal_checksum(data: bytes, s0: int = 0, s1: int = 0, big_endian: bool = True) -> Tuple[int, int]:
    """Compute SQLite WAL checksum. s0, s1 are running state."""
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        if i + 8 > len(data):
            break
        v0 = struct.unpack(fmt, data[i:i+4])[0]
        v1 = struct.unpack(fmt, data[i+4:i+8])[0]
        s0 = (s0 + v0 + s1) & 0xFFFFFFFF
        s1 = (s1 + v1 + s0) & 0xFFFFFFFF
    return s0, s1


def backup_files(db_path: str, wal_path: str, backup_dir: str = '/app/recovery_backup'):
    """Back up database and WAL files before any modification."""
    os.makedirs(backup_dir, exist_ok=True)
    
    for src in [db_path, wal_path]:
        if os.path.exists(src):
            dst = os.path.join(backup_dir, os.path.basename(src) + '.bak')
            shutil.copy2(src, dst)
            print(f"  Backed up: {src} -> {dst}")
    
    # Also back up any other WAL files
    db_dir = os.path.dirname(db_path) or '.'
    for wal_file in glob.glob(os.path.join(db_dir, '*.db-wal*')):
        if wal_file != wal_path and not wal_file.endswith('.bak'):
            dst = os.path.join(backup_dir, os.path.basename(wal_file) + '.bak')
            shutil.copy2(wal_file, dst)
            print(f"  Backed up: {wal_file} -> {dst}")


def read_db_page_size(db_path: str) -> Optional[int]:
    """Read page size from SQLite database header."""
    if not os.path.exists(db_path):
        return None
    with open(db_path, 'rb') as f:
        header = f.read(100)
    if len(header) < 18 or not header.startswith(SQLITE_HEADER):
        return None
    page_size = struct.unpack('>H', header[16:18])[0]
    if page_size == 1:
        page_size = 65536
    return page_size


def diagnose_encoding(wal_data: bytes) -> Tuple[str, Any]:
    """
    Diagnose the encoding applied to the WAL file.
    Returns (encoding_type, parameters).
    
    Supported encodings:
    - 'none': WAL is already valid
    - 'xor_single': single-byte XOR
    - 'xor_multi': multi-byte XOR
    - 'invert': bitwise NOT (XOR with 0xFF)
    - 'base64': base64 encoded
    - 'byte_swap_2': swap every 2 bytes
    - 'byte_swap_4': reverse every 4 bytes
    - 'header_only': only header is damaged
    """
    first4 = wal_data[:4]
    
    # Check if already valid
    if first4 == WAL_MAGIC_BE or first4 == WAL_MAGIC_LE:
        return ('none', None)
    
    # Check base64
    try:
        if all(32 <= b <= 126 for b in wal_data[:100]):
            decoded = base64.b64decode(wal_data[:200])
            if decoded[:4] == WAL_MAGIC_BE or decoded[:4] == WAL_MAGIC_LE:
                return ('base64', None)
    except Exception:
        pass
    
    # Check single-byte XOR
    for expected_magic in [WAL_MAGIC_BE, WAL_MAGIC_LE]:
        keys = bytes(a ^ b for a, b in zip(first4, expected_magic))
        if len(set(keys)) == 1:
            key = keys[0]
            if key != 0:
                return ('xor_single', key)
    
    # Check bitwise inversion
    inverted = bytes(b ^ 0xFF for b in first4)
    if inverted == WAL_MAGIC_BE or inverted == WAL_MAGIC_LE:
        return ('invert', None)
    
    # Check byte swap (2-byte pairs)
    if len(wal_data) >= 4:
        swapped2 = bytes([first4[1], first4[0], first4[3], first4[2]])
        if swapped2 == WAL_MAGIC_BE or swapped2 == WAL_MAGIC_LE:
            return ('byte_swap_2', None)
    
    # Check byte swap (4-byte reverse)
    if len(wal_data) >= 4:
        swapped4 = first4[::-1]
        if swapped4 == WAL_MAGIC_BE or swapped4 == WAL_MAGIC_LE:
            return ('byte_swap_4', None)
    
    # Check multi-byte XOR (key length 2)
    for expected_magic in [WAL_MAGIC_BE, WAL_MAGIC_LE]:
        key2 = bytes(a ^ b for a, b in zip(first4, expected_magic * 2))[:2]
        reconstructed = bytes(key2[i % 2] ^ expected_magic[i % 4] for i in range(4))
        # Verify: XOR the first 4 bytes with repeating key2
        test = bytes(first4[i] ^ key2[i % 2] for i in range(4))
        if test == expected_magic:
            return ('xor_multi', key2)
    
    # Check multi-byte XOR (key length 3)
    for expected_magic in [WAL_MAGIC_BE, WAL_MAGIC_LE]:
        key3 = bytes(a ^ b for a, b in zip(first4[:3], expected_magic[:3]))
        test = bytes(first4[i] ^ key3[i % 3] for i in range(4))
        if test == expected_magic:
            return ('xor_multi', key3)
    
    # Check multi-byte XOR (key length 4)
    # Validate against version field (bytes 4-7 must be 00 00 00 01 or 00 00 00 02)
    for expected_magic in [WAL_MAGIC_BE, WAL_MAGIC_LE]:
        key4 = bytes(a ^ b for a, b in zip(first4, expected_magic))
        # Validate: decode bytes 4-7 and check if result is valid WAL version
        decoded_8 = bytes(wal_data[i] ^ key4[i % 4] for i in range(8))
        version = struct.unpack('>I', decoded_8[4:8])[0]
        if version in (1, 2):  # Valid WAL version confirms the key
            return ('xor_multi', key4)
    
    # Check if only header is damaged (frame data looks valid)
    # Look for SQLite B-tree page signatures in the data after offset 32
    if len(wal_data) > 100:
        # Check if data region (after frame header at offset 56) contains 
        # SQLite page markers (0x0D for leaf table, 0x05 for interior table)
        # Iterate over plausible page sizes to be page-size-agnostic
        for ps in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
            offset = 56 + ps  # Start of page data in second frame
            if offset < len(wal_data) and wal_data[offset] in (0x0D, 0x05, 0x0A, 0x02):
                return ('header_only', None)
    
    return ('unknown', None)


def decode_wal(wal_data: bytes, encoding: str, params: Any, db_page_size: Optional[int] = None) -> bytes:
    """Apply the reverse transformation to decode the WAL."""
    if encoding == 'none':
        return wal_data
    elif encoding == 'xor_single':
        key = params
        return bytes(b ^ key for b in wal_data)
    elif encoding == 'xor_multi':
        key = params
        return bytes(wal_data[i] ^ key[i % len(key)] for i in range(len(wal_data)))
    elif encoding == 'invert':
        return bytes(b ^ 0xFF for b in wal_data)
    elif encoding == 'base64':
        return base64.b64decode(wal_data)
    elif encoding == 'byte_swap_2':
        result = bytearray(len(wal_data))
        for i in range(0, len(wal_data) - 1, 2):
            result[i] = wal_data[i + 1]
            result[i + 1] = wal_data[i]
        if len(wal_data) % 2:
            result[-1] = wal_data[-1]
        return bytes(result)
    elif encoding == 'byte_swap_4':
        result = bytearray(len(wal_data))
        for i in range(0, len(wal_data) - 3, 4):
            result[i:i+4] = wal_data[i:i+4][::-1]
        remainder = len(wal_data) % 4
        if remainder:
            result[-remainder:] = wal_data[-remainder:]
        return bytes(result)
    elif encoding == 'header_only':
        # Only the header needs fixing - reconstruct a valid header
        # Keep frame data as-is
        import random
        header = bytearray(32)
        # Use BE magic (most common)
        header[0:4] = WAL_MAGIC_BE
        struct.pack_into('>I', header, 4, 1)  # WAL format version 1
        
        # Determine page size using file size alignment (most reliable)
        page_size = None
        remaining = len(wal_data) - WAL_HEADER_SIZE
        
        # Check which page size makes the file frame-aligned
        for ps in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
            frame_size = FRAME_HEADER_SIZE + ps
            if remaining > 0 and remaining % frame_size == 0:
                page_size = ps
                break
        
        # Fallback to database page size if provided and alignment didn't work
        if page_size is None and db_page_size is not None:
            page_size = db_page_size
        
        # Last resort default
        if page_size is None:
            page_size = 4096
        
        struct.pack_into('>I', header, 8, page_size)
        struct.pack_into('>I', header, 12, 0)  # checkpoint seq
        # Generate salt values
        salt1 = random.randint(0, 0xFFFFFFFF)
        salt2 = random.randint(0, 0xFFFFFFFF)
        struct.pack_into('>I', header, 16, salt1)
        struct.pack_into('>I', header, 20, salt2)
        # Recompute checksums
        s0, s1 = wal_checksum(bytes(header[0:24]), 0, 0, True)
        struct.pack_into('>I', header, 24, s0)
        struct.pack_into('>I', header, 28, s1)
        # Also need to update frame header salts to match
        result = bytes(header) + wal_data[32:]
        # Update frame salts
        result = bytearray(result)
        num_frames = (len(result) - WAL_HEADER_SIZE) // (FRAME_HEADER_SIZE + page_size)
        for i in range(num_frames):
            offset = WAL_HEADER_SIZE + i * (FRAME_HEADER_SIZE + page_size)
            struct.pack_into('>I', result, offset + 8, salt1)
            struct.pack_into('>I', result, offset + 12, salt2)
        return bytes(result)
    else:
        raise ValueError(f"Unknown encoding: {encoding}")


def validate_wal_structure(decoded: bytes) -> Dict[str, Any]:
    """Validate the decoded WAL structure and return metadata."""
    info = {}
    
    if len(decoded) < WAL_HEADER_SIZE:
        info['valid'] = False
        info['error'] = 'File too small for WAL header'
        return info
    
    magic = decoded[:4]
    if magic not in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        info['valid'] = False
        info['error'] = f'Invalid magic: {magic.hex()}'
        return info
    
    info['big_endian'] = (magic == WAL_MAGIC_BE)
    info['version'] = struct.unpack('>I', decoded[4:8])[0]
    info['page_size'] = struct.unpack('>I', decoded[8:12])[0]
    info['checkpoint_seq'] = struct.unpack('>I', decoded[12:16])[0]
    info['salt1'] = struct.unpack('>I', decoded[16:20])[0]
    info['salt2'] = struct.unpack('>I', decoded[20:24])[0]
    
    # Validate page size
    ps = info['page_size']
    if ps not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
        info['valid'] = False
        info['error'] = f'Invalid page size: {ps}'
        return info
    
    # Check frame alignment
    frame_size = FRAME_HEADER_SIZE + ps
    remaining = len(decoded) - WAL_HEADER_SIZE
    num_frames = remaining // frame_size
    remainder = remaining % frame_size
    
    info['num_frames'] = num_frames
    info['frame_size'] = frame_size
    info['aligned'] = (remainder == 0)
    
    if not info['aligned']:
        info['warning'] = f'File not frame-aligned: {remainder} trailing bytes'
    
    # Validate header checksum
    s0, s1 = wal_checksum(decoded[0:24], 0, 0, info['big_endian'])
    stored_ck1 = struct.unpack('>I', decoded[24:28])[0]
    stored_ck2 = struct.unpack('>I', decoded[28:32])[0]
    info['header_checksum_valid'] = (s0 == stored_ck1 and s1 == stored_ck2)
    info['header_s0'] = s0
    info['header_s1'] = s1
    info['stored_ck1'] = stored_ck1
    info['stored_ck2'] = stored_ck2
    
    # Validate frame checksums
    info['frame_checksums'] = []
    ck_s0, ck_s1 = s0, s1
    all_frames_valid = True
    
    for i in range(num_frames):
        frame_offset = WAL_HEADER_SIZE + i * frame_size
        frame_hdr = decoded[frame_offset:frame_offset + FRAME_HEADER_SIZE]
        page_data = decoded[frame_offset + FRAME_HEADER_SIZE:frame_offset + frame_size]
        
        pgno = struct.unpack('>I', frame_hdr[0:4])[0]
        db_size = struct.unpack('>I', frame_hdr[4:8])[0]
        f_salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        f_salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        f_ck1 = struct.unpack('>I', frame_hdr[16:20])[0]
        f_ck2 = struct.unpack('>I', frame_hdr[20:24])[0]
        
        # Compute frame checksum (only first 8 bytes of header: pgno + db_size)
        ck_data = frame_hdr[0:8] + page_data
        fs0, fs1 = wal_checksum(ck_data, ck_s0, ck_s1, info['big_endian'])
        frame_valid = (fs0 == f_ck1 and fs1 == f_ck2)
        
        info['frame_checksums'].append({
            'index': i,
            'pgno': pgno,
            'db_size': db_size,
            'salt_match': (f_salt1 == info['salt1'] and f_salt2 == info['salt2']),
            'checksum_valid': frame_valid,
            'is_commit': db_size > 0
        })
        
        if not frame_valid:
            all_frames_valid = False
        
        # Chain checksums regardless (for next frame)
        ck_s0, ck_s1 = fs0, fs1
    
    info['all_frame_checksums_valid'] = all_frames_valid
    info['valid'] = True
    return info


def parse_frames(decoded: bytes, page_size: int) -> List[Dict[str, Any]]:
    """Parse all frames from a decoded WAL."""
    frame_size = FRAME_HEADER_SIZE + page_size
    num_frames = (len(decoded) - WAL_HEADER_SIZE) // frame_size
    frames = []
    
    for i in range(num_frames):
        offset = WAL_HEADER_SIZE + i * frame_size
        frame_hdr = decoded[offset:offset + FRAME_HEADER_SIZE]
        page_data = decoded[offset + FRAME_HEADER_SIZE:offset + frame_size]
        
        pgno = struct.unpack('>I', frame_hdr[0:4])[0]
        db_size = struct.unpack('>I', frame_hdr[4:8])[0]
        
        frames.append({
            'index': i,
            'pgno': pgno,
            'db_size': db_size,
            'page_data': page_data,
            'is_commit': db_size > 0
        })
    
    return frames


def recompute_checksums(decoded: bytes, big_endian: bool) -> bytes:
    """Recompute all checksums in the WAL and return the fixed version.
    
    Also repairs salt values in frame headers to match WAL header salts,
    which is required for SQLite to accept the WAL.
    """
    result = bytearray(decoded)
    
    # Extract WAL header salt values
    wal_salt1 = struct.unpack('>I', result[16:20])[0]
    wal_salt2 = struct.unpack('>I', result[20:24])[0]
    
    # Recompute header checksum
    s0, s1 = wal_checksum(bytes(result[0:24]), 0, 0, big_endian)
    struct.pack_into('>I', result, 24, s0)
    struct.pack_into('>I', result, 28, s1)
    
    # Recompute frame checksums and fix salt values
    page_size = struct.unpack('>I', result[8:12])[0]
    frame_size = FRAME_HEADER_SIZE + page_size
    num_frames = (len(result) - WAL_HEADER_SIZE) // frame_size
    
    ck_s0, ck_s1 = s0, s1
    for i in range(num_frames):
        offset = WAL_HEADER_SIZE + i * frame_size
        
        # Fix salt values in frame header to match WAL header
        struct.pack_into('>I', result, offset + 8, wal_salt1)
        struct.pack_into('>I', result, offset + 12, wal_salt2)
        
        frame_hdr = bytes(result[offset:offset + FRAME_HEADER_SIZE])
        page_data = bytes(result[offset + FRAME_HEADER_SIZE:offset + frame_size])
        
        # Frame checksum covers only first 8 bytes (pgno + db_size) + page data
        ck_data = frame_hdr[0:8] + page_data
        fs0, fs1 = wal_checksum(ck_data, ck_s0, ck_s1, big_endian)
        
        struct.pack_into('>I', result, offset + 16, fs0)
        struct.pack_into('>I', result, offset + 20, fs1)
        
        ck_s0, ck_s1 = fs0, fs1
    
    return bytes(result)


def apply_frames_manually(db_path: str, frames: List[Dict], page_size: int):
    """Manually apply WAL frames to the database file."""
    # Find the last commit frame
    commit_frames = [i for i, f in enumerate(frames) if f['is_commit']]
    if not commit_frames:
        print("  WARNING: No commit frames found. Applying all frames.")
        last_commit = len(frames) - 1
    else:
        last_commit = commit_frames[-1]
    
    # Build page map (last writer wins)
    page_map = {}
    max_db_pages = 0
    for f in frames[:last_commit + 1]:
        page_map[f['pgno']] = f['page_data']
        if f['db_size'] > 0:
            max_db_pages = max(max_db_pages, f['db_size'])
    
    # Ensure database file is large enough
    required_size = max_db_pages * page_size if max_db_pages > 0 else (max(page_map.keys()) * page_size)
    
    if not os.path.exists(db_path):
        # Create empty database file
        with open(db_path, 'wb') as f:
            f.write(b'\x00' * required_size)
    else:
        current_size = os.path.getsize(db_path)
        if current_size < required_size:
            with open(db_path, 'ab') as f:
                f.write(b'\x00' * (required_size - current_size))
    
    # Apply pages
    with open(db_path, 'r+b') as db:
        for pgno, page_data in sorted(page_map.items()):
            offset = (pgno - 1) * page_size
            db.seek(offset)
            db.write(page_data)
            print(f"  Applied page {pgno} at offset {offset}")
        
        # If page 1 was not in the WAL, update the change counter
        if 1 not in page_map:
            db.seek(24)
            counter = struct.unpack('>I', db.read(4))[0]
            new_counter = counter + 1
            db.seek(24)
            db.write(struct.pack('>I', new_counter))
            db.seek(92)
            db.write(struct.pack('>I', new_counter))
            print(f"  Updated change counter: {counter} -> {new_counter}")
    
    print(f"  Applied {len(page_map)} unique pages from {last_commit + 1} frames")


def export_to_json(db_path: str, output_path: str):
    """Export all data from the database to JSON."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find all user tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    all_records = []
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM [{table}]")
        rows = cursor.fetchall()
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                record[col] = row[i]
            all_records.append(record)
    
    conn.close()
    
    # Sort by id if present, otherwise by first column
    if all_records and 'id' in all_records[0]:
        all_records.sort(key=lambda r: r['id'])
    
    with open(output_path, 'w') as f:
        json.dump(all_records, f, indent=2)
    
    return all_records


def main():
    parser = argparse.ArgumentParser(description='SQLite WAL Recovery')
    parser.add_argument('--db', default='/app/main.db', help='Path to database file')
    parser.add_argument('--wal', default='/app/main.db-wal', help='Path to WAL file')
    parser.add_argument('--output', default='/app/recovered.json', help='Output JSON path')
    parser.add_argument('--force-manual', action='store_true', help='Skip SQLite-native recovery')
    args = parser.parse_args()
    
    db_path = args.db
    wal_path = args.wal
    output_path = args.output
    
    print("=" * 60)
    print("SQLite WAL Recovery")
    print("=" * 60)
    
    # Step 1: Inventory
    print("\n[Step 1] Inventory")
    for f in [db_path, wal_path]:
        if os.path.exists(f):
            print(f"  {f}: {os.path.getsize(f)} bytes")
        else:
            print(f"  {f}: NOT FOUND")
    
    if not os.path.exists(wal_path):
        print("\nERROR: WAL file not found. Cannot proceed.")
        # Try to recover from base DB alone
        if os.path.exists(db_path):
            print("Attempting export from base database only...")
            try:
                records = export_to_json(db_path, output_path)
                print(f"Exported {len(records)} records from base database")
                return
            except Exception as e:
                print(f"Failed: {e}")
        sys.exit(1)
    
    # Step 2: Backup
    print("\n[Step 2] Backup (CRITICAL)")
    backup_files(db_path, wal_path)
    
    # Step 3: Read and diagnose
    print("\n[Step 3] Diagnose encoding")
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    
    print(f"  WAL size: {len(wal_data)} bytes")
    print(f"  First 16 bytes: {wal_data[:16].hex()}")
    
    encoding, params = diagnose_encoding(wal_data)
    print(f"  Detected encoding: {encoding}")
    if params is not None:
        if isinstance(params, int):
            print(f"  Key: 0x{params:02X}")
        elif isinstance(params, bytes):
            print(f"  Key: {params.hex()}")
    
    # Step 4: Decode
    print("\n[Step 4] Decode WAL")
    db_page_size = read_db_page_size(db_path)
    decoded = decode_wal(wal_data, encoding, params, db_page_size)
    print(f"  Decoded first 16 bytes: {decoded[:16].hex()}")
    print(f"  Magic: {decoded[:4].hex()} ({'valid' if decoded[:4] in (WAL_MAGIC_BE, WAL_MAGIC_LE) else 'INVALID'})")
    
    # Step 5: Validate structure
    print("\n[Step 5] Validate WAL structure")
    info = validate_wal_structure(decoded)
    
    if not info.get('valid'):
        print(f"  ERROR: {info.get('error', 'Unknown validation error')}")
        # Try manual approach anyway
        print("  Attempting manual frame extraction...")
    
    print(f"  Page size: {info.get('page_size', 'unknown')}")
    print(f"  Number of frames: {info.get('num_frames', 'unknown')}")
    print(f"  Header checksum valid: {info.get('header_checksum_valid', 'unknown')}")
    print(f"  All frame checksums valid: {info.get('all_frame_checksums_valid', 'unknown')}")
    
    if info.get('frame_checksums'):
        for fc in info['frame_checksums']:
            status = "OK" if fc['checksum_valid'] else "FAIL"
            commit = " [COMMIT]" if fc['is_commit'] else ""
            print(f"    Frame {fc['index']}: page {fc['pgno']}, checksum {status}{commit}")
    
    # Check page size matches database
    db_page_size = read_db_page_size(db_path)
    if db_page_size and info.get('page_size'):
        if db_page_size != info['page_size']:
            print(f"  WARNING: WAL page size ({info['page_size']}) != DB page size ({db_page_size})")
    
    # Step 6: Recovery
    print("\n[Step 6] Recovery")
    
    # For encoded WALs, manual frame application is the reliable primary path
    # SQLite-native recovery often fails due to checksum corruption
    print("  Using manual frame application (recommended for encoded WALs)...")
    
    # If header checksum is wrong, recompute all checksums
    if not info.get('header_checksum_valid'):
        print("  Recomputing checksums...")
        big_endian = info.get('big_endian', decoded[3] == 0x82)
        decoded = recompute_checksums(decoded, big_endian)
        # Re-validate
        info = validate_wal_structure(decoded)
    
    page_size = info.get('page_size', db_page_size or 4096)
    frames = parse_frames(decoded, page_size)
    
    # Apply frames manually
    apply_frames_manually(db_path, frames, page_size)
    
    # Step 7: Export
    print("\n[Step 7] Export to JSON")
    records = export_to_json(db_path, output_path)
    print(f"  Exported {len(records)} records to {output_path}")
    
    if records:
        print(f"\n  Sample records:")
        for r in records[:3]:
            print(f"    {r}")
        if len(records) > 3:
            print(f"    ... and {len(records) - 3} more")
    
    print("\n" + "=" * 60)
    print(f"Recovery complete: {len(records)} records -> {output_path}")
    print("=" * 60)


if __name__ == '__main__':
    main()

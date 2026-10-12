#!/usr/bin/env python3
"""
SQLite WAL Recovery Script
Automatically diagnoses encoding, validates decodings via checksum, and extracts data.

Usage:
    python3 recover.py [app_dir] [output_path]

Defaults:
    app_dir = /app
    output_path = /app/recovered.json
"""

import os
import sys
import struct
import sqlite3
import json
import shutil
import base64


def backup_artifacts(app_dir='/app', backup_dir='/tmp'):
    """Step 0: Backup all raw artifacts before any processing."""
    files = ['main.db', 'main.db-wal', 'main.db-shm']
    backups = {}
    
    for fname in files:
        src = os.path.join(app_dir, fname)
        if os.path.exists(src):
            dst = os.path.join(backup_dir, f'{fname}.orig')
            shutil.copy2(src, dst)
            backups[fname] = dst
            print(f"  Backed up {fname} ({os.path.getsize(src)} bytes) -> {dst}")
    
    return backups


def wal_checksum(data, s1=0, s2=0, endian='>'):
    """
    Compute SQLite WAL checksum.
    endian: '>' for magic 0x377f0682 (BE), '<' for magic 0x377f0683 (LE)
    s1, s2 are running accumulators.
    Returns (s1, s2) tuple.
    
    Algorithm from SQLite source (wal.c walChecksumBytes):
    s1 = s1 + x + s2
    s2 = s2 + y + s1  (uses updated s1)
    """
    # Ensure data length is multiple of 8
    length = len(data) - (len(data) % 8)
    for i in range(0, length, 8):
        x, y = struct.unpack(f'{endian}II', data[i:i+8])
        s1 = (s1 + x + s2) % (2**32)
        s2 = (s2 + y + s1) % (2**32)
    return s1, s2


def try_decoding(data, method, key=None):
    """Apply a decoding transformation to data."""
    if method == 'identity':
        return data
    elif method == 'xor_byte':
        return bytes([b ^ key for b in data])
    elif method == 'xor_pattern':
        return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
    elif method == 'bitwise_not':
        return bytes([b ^ 0xFF for b in data])
    elif method == 'byte_swap_2':
        result = bytearray(len(data))
        for i in range(0, len(data) - 1, 2):
            result[i] = data[i+1]
            result[i+1] = data[i]
        if len(data) % 2 == 1:
            result[-1] = data[-1]
        return bytes(result)
    elif method == 'byte_swap_4':
        result = bytearray(len(data))
        for i in range(0, len(data) - 3, 4):
            result[i] = data[i+3]
            result[i+1] = data[i+2]
            result[i+2] = data[i+1]
            result[i+3] = data[i]
        remainder_start = (len(data) // 4) * 4
        for i in range(remainder_start, len(data)):
            result[i] = data[i]
        return bytes(result)
    elif method == 'base64':
        try:
            decoded = base64.b64decode(data)
            if len(decoded) >= 32:
                magic = struct.unpack('>I', decoded[0:4])[0]
                if magic in [0x377f0682, 0x377f0683]:
                    return decoded
        except Exception:
            pass
        return data
    return data


def validate_wal(data, page_size=None):
    """
    Validate WAL header and frame structure with confidence scoring.
    Returns (is_valid, message, details_dict, confidence).
    
    Confidence score (0-5):
    1: Magic number matches
    2: Version is valid (3007000)
    3: Page size is valid power of 2
    4: Frame salts match header salts
    5: Checksums match (header + all frames)
    
    Accept if confidence >= 4 (magic + version + page_size + salts).
    """
    if len(data) < 32:
        return False, "WAL too short (< 32 bytes)", {}, 0
    
    magic = struct.unpack('>I', data[0:4])[0]
    if magic not in [0x377f0682, 0x377f0683]:
        return False, f"Invalid magic: 0x{magic:08x}", {}, 0
    
    # Determine checksum byte order from magic
    endian = '>' if magic == 0x377f0682 else '<'
    confidence = 1  # magic matched
    
    version = struct.unpack(f'{endian}I', data[4:8])[0]
    wal_page_size = struct.unpack(f'{endian}I', data[8:12])[0]
    
    # Version check (3007000 = 0x002DE218)
    if version == 3007000:
        confidence += 1
    
    # Use provided page_size or the one from WAL header
    effective_page_size = page_size if page_size else wal_page_size
    
    # Page size check
    if effective_page_size and (effective_page_size & (effective_page_size - 1)) == 0 and 512 <= effective_page_size <= 65536:
        confidence += 1
    else:
        return False, f"Invalid page size: {effective_page_size}", {}, confidence
    
    # Validate header checksum (bytes 0-23, checksum at 24-31)
    computed_s1, computed_s2 = wal_checksum(data[0:24], endian=endian)
    stored_s1, stored_s2 = struct.unpack(f'{endian}II', data[24:32])
    header_checksum_ok = (computed_s1 == stored_s1 and computed_s2 == stored_s2)
    
    # Validate frame structure
    frame_size = 24 + effective_page_size
    num_frames = (len(data) - 32) // frame_size
    salt1 = struct.unpack(f'{endian}I', data[16:20])[0]
    salt2 = struct.unpack(f'{endian}I', data[20:24])[0]
    
    # Check salt values match across all frames
    salts_ok = True
    valid_frames = 0
    frame_checksums_ok = True
    running_s1, running_s2 = computed_s1, computed_s2
    
    for frame_idx in range(num_frames):
        frame_offset = 32 + frame_idx * frame_size
        frame_header = data[frame_offset:frame_offset+24]
        frame_data = data[frame_offset+24:frame_offset+24+effective_page_size]
        
        if len(frame_header) < 24 or len(frame_data) < effective_page_size:
            break
        
        page_num = struct.unpack(f'{endian}I', frame_header[0:4])[0]
        frame_salt1 = struct.unpack(f'{endian}I', frame_header[8:12])[0]
        frame_salt2 = struct.unpack(f'{endian}I', frame_header[12:16])[0]
        
        # Check salt values match
        if frame_salt1 != salt1 or frame_salt2 != salt2:
            salts_ok = False
        
        # Validate frame checksum
        frame_s1, frame_s2 = wal_checksum(frame_header[0:16] + frame_data, running_s1, running_s2, endian=endian)
        stored_frame_s1, stored_frame_s2 = struct.unpack(f'{endian}II', frame_header[16:24])
        
        if frame_s1 != stored_frame_s1 or frame_s2 != stored_frame_s2:
            frame_checksums_ok = False
        else:
            valid_frames += 1
        
        running_s1, running_s2 = frame_s1, frame_s2
    
    if salts_ok and num_frames > 0:
        confidence += 1
    
    if header_checksum_ok and frame_checksums_ok and num_frames > 0:
        confidence += 1
    
    details = {
        'magic': magic,
        'version': version,
        'page_size': effective_page_size,
        'num_frames': num_frames,
        'valid_frames': valid_frames,
        'salt1': salt1,
        'salt2': salt2,
        'header_checksum_ok': header_checksum_ok,
        'frame_checksums_ok': frame_checksums_ok,
        'salts_ok': salts_ok,
        'confidence': confidence,
    }
    
    # Accept if confidence >= 4 (magic + version + page_size + salts)
    is_valid = confidence >= 4
    msg = f"confidence={confidence}/5, {num_frames} frames, {valid_frames} valid"
    return is_valid, msg, details, confidence


def diagnose_and_decode(wal_backup_path, db_page_size=None):
    """Try multiple decodings and return the best valid one (or best partial match)."""
    with open(wal_backup_path, 'rb') as f:
        data = f.read()
    
    print(f"  WAL size: {len(data)} bytes")
    print(f"  First 4 bytes (hex): {data[0:4].hex()}")
    
    # Build list of decodings to try
    decodings = [
        ('identity', None),
        ('base64', None),
        ('bitwise_not', None),
        ('byte_swap_2', None),
        ('byte_swap_4', None),
    ]
    
    # Try XOR with each single-byte key (0x01-0xFF)
    for key in range(1, 256):
        decodings.append(('xor_byte', key))
    
    best = None  # (confidence, decoded, method, key, details)
    
    for method, key in decodings:
        decoded = try_decoding(data, method, key)
        valid, msg, details, confidence = validate_wal(decoded, db_page_size)
        
        if best is None or confidence > best[0]:
            best = (confidence, decoded, method, key, details)
        
        if valid:
            key_str = f"key=0x{key:02x}" if key is not None else ""
            print(f"  ✓ Valid decoding: {method} {key_str} ({msg})")
            return decoded, method, key, details
    
    # If no fully valid decoding, use the best candidate
    if best and best[0] >= 3:
        key_str = f"key=0x{best[3]:02x}" if best[3] is not None else ""
        print(f"  ⚠ Best partial decoding (confidence={best[0]}/5): {best[2]} {key_str}")
        return best[1], best[2], best[3], best[4]
    
    print("  ✗ No viable decoding found")
    return None, None, None, {}


def get_db_page_size(db_path):
    """Read page size from SQLite database header."""
    with open(db_path, 'rb') as f:
        header = f.read(100)
    
    if not header.startswith(b'SQLite format 3'):
        return None
    
    # Page size is at offset 16-17, big-endian
    page_size = struct.unpack('>H', header[16:18])[0]
    # SQLite 3.7.1+ uses value 1 to mean 65536
    if page_size == 1:
        page_size = 65536
    return page_size


def repair_wal(decoded_wal, app_dir='/app'):
    """Write the decoded WAL to the app directory."""
    wal_path = os.path.join(app_dir, 'main.db-wal')
    with open(wal_path, 'wb') as f:
        f.write(decoded_wal)
    print(f"  Wrote decoded WAL to {wal_path} ({len(decoded_wal)} bytes)")


def checkpoint_and_extract(app_dir='/app', output_path='/app/recovered.json'):
    """Checkpoint WAL and extract all data as JSON."""
    db_path = os.path.join(app_dir, 'main.db')
    
    # Connect and checkpoint
    conn = sqlite3.connect(db_path)
    
    # Ensure WAL mode
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    if mode.lower() != 'wal':
        conn.execute("PRAGMA journal_mode=WAL;")
    
    # Force checkpoint to merge WAL into main database
    result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
    print(f"  Checkpoint result: {result}")
    
    # Get all tables
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"  Found tables: {tables}")
    
    # Extract data from all tables
    all_data = {}
    total_rows = 0
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table});")
        columns = [row[1] for row in cursor.fetchall()]
        
        cursor.execute(f"SELECT * FROM {table};")
        rows = cursor.fetchall()
        
        all_data[table] = [dict(zip(columns, row)) for row in rows]
        print(f"  Table '{table}': {len(rows)} rows, columns: {columns}")
        total_rows += len(rows)
    
    conn.close()
    
    # Determine output format
    # If single table, check if task expects array format
    if len(tables) == 1:
        output_data = all_data[tables[0]]
    else:
        output_data = all_data
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"  Wrote {output_path} ({total_rows} total rows)")
    return all_data


def main():
    """Main recovery workflow."""
    app_dir = sys.argv[1] if len(sys.argv) > 1 else '/app'
    output_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(app_dir, 'recovered.json')
    
    print("=== SQLite WAL Recovery ===\n")
    
    # Step 0: Backup
    print("Step 0: Backing up artifacts...")
    backups = backup_artifacts(app_dir)
    
    if 'main.db-wal' not in backups:
        print("ERROR: No WAL file found in", app_dir)
        sys.exit(1)
    
    # Get page size from base database
    db_page_size = None
    if 'main.db' in backups:
        db_page_size = get_db_page_size(backups['main.db'])
        print(f"  Database page size: {db_page_size}")
    
    # Step 1-2: Diagnose and decode
    print("\nStep 1-2: Diagnosing encoding and decoding WAL...")
    decoded_wal, method, key, details = diagnose_and_decode(
        backups['main.db-wal'], db_page_size
    )
    
    if decoded_wal is None:
        print("\nERROR: Could not decode WAL with standard transformations.")
        print("Manual analysis required. Examine the WAL header:")
        os.system(f"xxd -l 64 {backups['main.db-wal']}")
        sys.exit(1)
    
    # Step 3: Repair
    print(f"\nStep 3: Repairing WAL (method={method})...")
    repair_wal(decoded_wal, app_dir)
    
    # Step 4-5: Checkpoint and extract
    print("\nStep 4-5: Checkpointing and extracting data...")
    data = checkpoint_and_extract(app_dir, output_path)
    
    print(f"\n=== Recovery Complete ===")
    print(f"Output: {output_path}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
WAL Recovery Diagnostic Script
Usage: python3 wal_recover.py [src_dir] [dst_dir]
  src_dir: directory containing .db and .db-wal files (default: /app)
  dst_dir: working directory for copies (default: /tmp/db_work)
"""
import struct
import base64
import shutil
import os
import json
import sys
import glob


def backup_files(src_dir='/app', dst_dir='/tmp/db_work'):
    """Step 0: Backup all database files"""
    os.makedirs(dst_dir, exist_ok=True)
    for ext in ['.db', '.db-wal', '.db-shm']:
        for f in os.listdir(src_dir):
            if f.endswith(ext):
                src = os.path.join(src_dir, f)
                dst = os.path.join(dst_dir, f)
                shutil.copy2(src, dst)
                print(f"Backed up: {f}")


def read_db_page_size(db_path):
    """Read page size from SQLite database header"""
    with open(db_path, 'rb') as f:
        header = f.read(100)
    page_size = struct.unpack('>H', header[16:18])[0]
    if page_size == 1:
        page_size = 65536
    return page_size


def wal_checksum(data: bytes, s1: int = 0, s2: int = 0, big_endian: bool = True):
    """SQLite WAL checksum with configurable endianness"""
    fmt = '>I' if big_endian else '<I'
    assert len(data) % 8 == 0, f"Data length {len(data)} not multiple of 8"
    for i in range(0, len(data), 8):
        v1 = struct.unpack(fmt, data[i:i+4])[0]
        v2 = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + v1) % (2**32)
        s2 = (s2 + s1 + v2) % (2**32)
    return s1, s2


def try_decode_wal(wal_data, expected_page_size):
    """Try various decodings and return (decoded_data, encoding_type) or None
    
    Handles:
    - Single transformations (XOR, NOT, byte-swap, base64)
    - Combined transformations (base64 then XOR, etc.)
    - Corrupted page size field (infers from expected_page_size)
    """
    
    def check_valid(data, allow_page_size_fix=False):
        """Check if data has valid WAL magic and optionally fix page size"""
        if len(data) < 32:
            return False, None
        magic = struct.unpack('>I', data[0:4])[0]
        if magic not in (0x377f0682, 0x377f0683):
            return False, None
        page_size = struct.unpack('>I', data[8:12])[0]
        if page_size == expected_page_size:
            return True, data
        elif allow_page_size_fix:
            # Page size field is corrupted, fix it
            fixed = bytearray(data)
            struct.pack_into('>I', fixed, 8, expected_page_size)
            return True, bytes(fixed)
        return False, None
    
    # Check if already valid
    valid, result = check_valid(wal_data)
    if valid:
        return result, 'none'
    
    # Try Base64
    try:
        if all(32 <= b < 127 for b in wal_data[:100]):
            decoded = base64.b64decode(wal_data)
            valid, result = check_valid(decoded, allow_page_size_fix=True)
            if valid:
                return result, 'base64'
            
            # Combined: base64 then XOR
            for key in range(1, 256):
                xored = bytes([b ^ key for b in decoded])
                valid, result = check_valid(xored, allow_page_size_fix=True)
                if valid:
                    return result, f'base64+xor_0x{key:02x}'
    except Exception:
        pass
    
    # Try single-byte XOR
    for key in range(256):
        decoded = bytes([b ^ key for b in wal_data])
        valid, result = check_valid(decoded, allow_page_size_fix=True)
        if valid:
            return result, f'xor_0x{key:02x}'
    
    # Try bitwise NOT
    decoded = bytes([b ^ 0xFF for b in wal_data])
    valid, result = check_valid(decoded, allow_page_size_fix=True)
    if valid:
        return result, 'not'
    
    # Try byte swap (adjacent pairs)
    decoded = bytearray(len(wal_data))
    for i in range(0, len(wal_data) - 1, 2):
        decoded[i] = wal_data[i+1]
        decoded[i+1] = wal_data[i]
    if len(wal_data) % 2:
        decoded[-1] = wal_data[-1]
    valid, result = check_valid(bytes(decoded), allow_page_size_fix=True)
    if valid:
        return result, 'byte_swap'
    
    # Try multi-byte XOR (derive key from known magic)
    for target_magic in [0x377f0682, 0x377f0683]:
        target_bytes = struct.pack('>I', target_magic)
        key_bytes = bytes([wal_data[i] ^ target_bytes[i] for i in range(4)])
        for key_len in [1, 2, 4]:
            key = key_bytes[:key_len]
            if all(key_bytes[i] == key[i % key_len] for i in range(4)):
                decoded = bytes([wal_data[i] ^ key[i % key_len] for i in range(len(wal_data))])
                valid, result = check_valid(decoded, allow_page_size_fix=True)
                if valid:
                    return result, f'multi_xor_{key.hex()}'
    
    return None, None


def verify_wal(wal_data, expected_page_size):
    """Verify WAL integrity and return (frame_count, status_message)"""
    magic = struct.unpack('>I', wal_data[0:4])[0]
    if magic not in (0x377f0682, 0x377f0683):
        return 0, "Invalid magic"
    
    big_endian = (magic == 0x377f0682)
    fmt2 = '>II' if big_endian else '<II'
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    if page_size != expected_page_size:
        return 0, f"Page size mismatch: {page_size} vs {expected_page_size}"
    
    # Verify header checksum
    expected_s1, expected_s2 = struct.unpack(fmt2, wal_data[24:32])
    calc_s1, calc_s2 = wal_checksum(wal_data[0:24], big_endian=big_endian)
    if (calc_s1, calc_s2) != (expected_s1, expected_s2):
        return 0, "Header checksum mismatch"
    
    # Verify frames
    s1, s2 = calc_s1, calc_s2
    offset = 32
    frame_num = 0
    while offset + 24 + page_size <= len(wal_data):
        frame_hdr = wal_data[offset:offset+24]
        frame_page = wal_data[offset+24:offset+24+page_size]
        
        salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        hdr_salt1 = struct.unpack('>I', wal_data[16:20])[0]
        hdr_salt2 = struct.unpack('>I', wal_data[20:24])[0]
        if (salt1, salt2) != (hdr_salt1, hdr_salt2):
            return frame_num, f"Frame {frame_num} salt mismatch"
        
        exp_s1, exp_s2 = struct.unpack(fmt2, frame_hdr[16:24])
        calc_s1, calc_s2 = wal_checksum(frame_hdr[0:16] + frame_page, s1, s2, big_endian=big_endian)
        if (calc_s1, calc_s2) != (exp_s1, exp_s2):
            return frame_num, f"Frame {frame_num} checksum mismatch"
        
        s1, s2 = calc_s1, calc_s2
        offset += 24 + page_size
        frame_num += 1
    
    return frame_num, "OK"


def recalculate_checksums(wal_data):
    """Recalculate all WAL checksums after decoding an encoded WAL."""
    data = bytearray(wal_data)
    magic = struct.unpack('>I', data[0:4])[0]
    big_endian = (magic == 0x377f0682)
    fmt2 = '>II' if big_endian else '<II'
    page_size = struct.unpack('>I', data[8:12])[0]
    
    # Fix header checksum
    calc_s1, calc_s2 = wal_checksum(bytes(data[0:24]), big_endian=big_endian)
    struct.pack_into(fmt2, data, 24, calc_s1, calc_s2)
    
    # Fix frame checksums (running chain)
    s1, s2 = calc_s1, calc_s2
    offset = 32
    while offset + 24 + page_size <= len(data):
        hdr_salt1 = struct.unpack('>I', data[16:20])[0]
        hdr_salt2 = struct.unpack('>I', data[20:24])[0]
        struct.pack_into('>II', data, offset + 8, hdr_salt1, hdr_salt2)
        
        checksum_data = bytes(data[offset:offset+16]) + bytes(data[offset+24:offset+24+page_size])
        calc_s1, calc_s2 = wal_checksum(checksum_data, s1, s2, big_endian=big_endian)
        struct.pack_into(fmt2, data, offset + 16, calc_s1, calc_s2)
        
        s1, s2 = calc_s1, calc_s2
        offset += 24 + page_size
    
    return data


def apply_wal_manually(db_path, wal_data, page_size):
    """Manually apply WAL frames to database"""
    with open(db_path, 'rb') as f:
        db_data = bytearray(f.read())
    
    offset = 32
    last_commit_db_size = None
    while offset + 24 + page_size <= len(wal_data):
        frame_hdr = wal_data[offset:offset+24]
        page_num = struct.unpack('>I', frame_hdr[0:4])[0]
        db_size = struct.unpack('>I', frame_hdr[4:8])[0]
        frame_page = wal_data[offset+24:offset+24+page_size]
        
        db_offset = (page_num - 1) * page_size
        if db_offset + page_size > len(db_data):
            db_data.extend(b'\x00' * (db_offset + page_size - len(db_data)))
        db_data[db_offset:db_offset+page_size] = frame_page
        
        if db_size > 0:
            last_commit_db_size = db_size
        
        offset += 24 + page_size
    
    if last_commit_db_size is not None:
        expected_size = last_commit_db_size * page_size
        if len(db_data) > expected_size:
            db_data = db_data[:expected_size]
    
    with open(db_path, 'wb') as f:
        f.write(db_data)
    
    return last_commit_db_size


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else '/app'
    dst_dir = sys.argv[2] if len(sys.argv) > 2 else '/tmp/db_work'
    
    # Step 0: Backup
    print("=== Step 0: Backup ===")
    backup_files(src_dir, dst_dir)
    
    # Step 1: Read DB page size
    print("\n=== Step 1: Read DB page size ===")
    db_path = os.path.join(dst_dir, 'main.db')
    if not os.path.exists(db_path):
        # Try to find any .db file
        dbs = glob.glob(os.path.join(dst_dir, '*.db'))
        if dbs:
            db_path = dbs[0]
        else:
            print("ERROR: No .db file found")
            return
    page_size = read_db_page_size(db_path)
    print(f"DB page size: {page_size}")
    
    # Step 2: Read and decode WAL
    print("\n=== Step 2: Decode WAL ===")
    wal_path = os.path.join(dst_dir, 'main.db-wal')
    if not os.path.exists(wal_path):
        wals = glob.glob(os.path.join(dst_dir, '*.db-wal'))
        if wals:
            wal_path = wals[0]
        else:
            print("ERROR: No .db-wal file found")
            return
    
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    print(f"WAL size: {len(wal_data)} bytes")
    
    decoded_wal, encoding = try_decode_wal(wal_data, page_size)
    if decoded_wal is None:
        print("ERROR: Could not decode WAL with any known method")
        print("First 32 bytes (hex):", wal_data[:32].hex())
        return
    
    print(f"Detected encoding: {encoding}")
    
    # Step 2b: Recalculate checksums after decoding
    print("\n=== Step 2b: Recalculate checksums ===")
    if encoding != 'none':
        decoded_wal = recalculate_checksums(decoded_wal)
        print("Checksums recalculated")
    else:
        print("No encoding detected, checksums should be valid")
    
    # Step 3: Verify
    print("\n=== Step 3: Verify WAL ===")
    frame_count, status = verify_wal(bytes(decoded_wal), page_size)
    print(f"Verification: {frame_count} frames, status: {status}")
    
    if status != "OK":
        print("WARNING: WAL verification failed")
    
    # Step 4: Apply WAL via manual frame application (primary method)
    # SQLite's auto-checkpoint does not reliably pick up repaired WALs,
    # so we always apply frames manually to the database file.
    print("\n=== Step 4: Apply WAL (manual frame application) ===")
    commit_size = apply_wal_manually(db_path, bytes(decoded_wal), page_size)
    print(f"Applied frames, last commit size: {commit_size} pages")
    
    # Remove WAL/SHM so sqlite3 reads the merged DB directly
    for ext in ['-wal', '-shm']:
        p = db_path + ext
        if os.path.exists(p):
            os.remove(p)
    
    # Step 5: Extract data using Python sqlite3
    print("\n=== Step 5: Extract data ===")
    import sqlite3 as sq3
    try:
        conn = sq3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables found: {tables}")
    except Exception as e:
        print(f"Python sqlite3 failed after manual application: {e}")
        return
    all_data = {}
    for table in tables:
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        all_data[table] = [dict(r) for r in rows]
        print(f"  {table}: {len(all_data[table])} rows")
    
    conn.close()
    
    # Write output - use the first user table (sqlite_ tables already filtered)
    output_table = tables[0] if tables else None
    output_path = os.path.join(src_dir, 'recovered.json')
    if output_table and output_table in all_data:
        with open(output_path, 'w') as f:
            json.dump(all_data[output_table], f, indent=2)
        print(f"\nRecovered {len(all_data[output_table])} records from '{output_table}' to {output_path}")
    elif all_data:
        with open(output_path, 'w') as f:
            json.dump(all_data, f, indent=2)
        print(f"\nRecovered data from {len(all_data)} tables to {output_path}")
    else:
        print("\nNo data recovered")


if __name__ == '__main__':
    main()

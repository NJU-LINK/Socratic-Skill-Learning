#!/usr/bin/env python3
"""
WAL Recovery Script
Recovers data from an XOR-encoded SQLite WAL file.

This script:
1. Backs up the original database and WAL files (CRITICAL)
2. Detects and decodes XOR-encoded WAL (tests all single-byte keys)
3. Writes the decoded WAL alongside a working copy of the database
4. Extracts all records using SQLite
5. Falls back to manual frame parsing if checksums fail
6. Outputs to /app/recovered.json
"""

import os
import sys
import json
import sqlite3
import shutil

# Both valid WAL magic numbers
WAL_MAGIC_BE = bytes([0x37, 0x7F, 0x06, 0x82])  # big-endian checksums
WAL_MAGIC_NE = bytes([0x37, 0x7F, 0x06, 0x83])  # native-endian checksums
VALID_MAGICS = [WAL_MAGIC_BE, WAL_MAGIC_NE]

def backup_files(db_path, wal_path):
    """Create backups before any operations - CRITICAL for recovery tasks."""
    db_backup = db_path + '.backup'
    wal_backup = wal_path + '.backup'
    
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_backup)
        print(f"Backed up database to {db_backup}")
    
    if os.path.exists(wal_path):
        shutil.copy2(wal_path, wal_backup)
        print(f"Backed up WAL to {wal_backup}")
    
    return db_backup, wal_backup

def detect_encoding(wal_path):
    """
    Detect the encoding/obfuscation applied to the WAL file.
    
    Tests both WAL magic variants and tries XOR decoding with all single-byte keys.
    
    Returns: (decoded_bytes, encoding_type) or (None, None) if unrecognized
    """
    with open(wal_path, 'rb') as f:
        data = f.read()
    
    if len(data) < 32:
        print("WAL file too small")
        return None, None
    
    # Check if already valid WAL
    if data[:4] in VALID_MAGICS:
        print("WAL file is already valid (no encoding)")
        return data, "none"
    
    # Try XOR decoding with various single-byte keys
    for key in range(256):
        decoded = bytes([b ^ key for b in data[:4]])
        if decoded in VALID_MAGICS:
            print(f"Detected XOR encoding with key 0x{key:02X}")
            # Decode entire file
            full_decoded = bytes([b ^ key for b in data])
            magic_type = "big-endian" if decoded == WAL_MAGIC_BE else "native-endian"
            return full_decoded, f"xor_0x{key:02X}_{magic_type}"
    
    # Try byte inversion (XOR with 0xFF)
    inverted = bytes([b ^ 0xFF for b in data[:4]])
    if inverted in VALID_MAGICS:
        print("Detected byte inversion encoding")
        full_inverted = bytes([b ^ 0xFF for b in data])
        return full_inverted, "inversion"
    
    print("Could not detect WAL encoding")
    return None, None

def verify_wal_structure(decoded_wal):
    """Verify the decoded WAL has valid structure."""
    if len(decoded_wal) < 32:
        return False, "WAL too small"
    
    # Check magic
    magic = decoded_wal[:4]
    if magic not in VALID_MAGICS:
        return False, f"Invalid magic: {magic.hex()}"
    
    # Check version (should be 3007000 = 0x00300700)
    version = int.from_bytes(decoded_wal[4:8], 'big')
    print(f"WAL version: {version}")
    
    # Check page size (should be power of 2, typically 1024-65536)
    page_size = int.from_bytes(decoded_wal[8:12], 'big')
    print(f"Page size: {page_size}")
    
    if page_size not in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
        return False, f"Invalid page size: {page_size}"
    
    # Calculate expected frame count
    frame_size = 24 + page_size  # header + page data
    header_size = 32
    remaining = len(decoded_wal) - header_size
    
    if remaining % frame_size != 0:
        print(f"Warning: WAL size doesn't align with frame boundaries")
        print(f"  Remaining bytes: {remaining}, frame size: {frame_size}")
    else:
        num_frames = remaining // frame_size
        print(f"Number of frames: {num_frames}")
    
    return True, "OK"

def manual_frame_recovery(db_path, decoded_wal):
    """
    Parse WAL frames and apply pages directly to the database.
    Used when SQLite refuses to read the WAL due to checksum failures.
    """
    print("Attempting manual frame recovery...")
    
    page_size = int.from_bytes(decoded_wal[8:12], 'big')
    header_size = 32
    frame_header_size = 24
    
    # Copy base database
    work_db = '/tmp/recovery_manual.db'
    shutil.copy2(db_path, work_db)
    
    # Parse and apply each frame
    offset = header_size
    last_valid_page = {}  # page_number -> page_data (last write wins)
    frame_count = 0
    
    while offset + frame_header_size + page_size <= len(decoded_wal):
        page_num = int.from_bytes(decoded_wal[offset:offset+4], 'big')
        commit_size = int.from_bytes(decoded_wal[offset+4:offset+8], 'big')
        
        page_data = decoded_wal[
            offset + frame_header_size:
            offset + frame_header_size + page_size]
        
        if page_num > 0:  # Valid page number
            last_valid_page[page_num] = page_data
            frame_count += 1
        
        offset += frame_header_size + page_size
    
    print(f"Parsed {frame_count} frames")
    print(f"Unique pages to apply: {len(last_valid_page)}")
    
    if not last_valid_page:
        return None, "No valid frames found"
    
    # Apply pages to database file
    with open(work_db, 'r+b') as f:
        for page_num, page_data in last_valid_page.items():
            f.seek((page_num - 1) * page_size)
            f.write(page_data)
    
    print(f"Applied {len(last_valid_page)} pages to database")
    
    # Now read the patched database (WAL no longer needed)
    try:
        conn = sqlite3.connect(work_db)
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            conn.close()
            return None, "No tables found in patched database"
        
        table_name = tables[0][0]
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY id;")
        rows = cursor.fetchall()
        
        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]
        
        conn.close()
        
        # Convert to list of dicts
        result = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            result.append(row_dict)
        
        return result, "OK"
        
    except Exception as e:
        print(f"Error reading patched database: {e}")
        return None, str(e)

def recover_with_decoded_wal(db_path, decoded_wal):
    """Write decoded WAL and recover data using SQLite."""
    # Create a working copy of the database
    work_db = '/tmp/recovery_work.db'
    work_wal = work_db + '-wal'
    work_shm = work_db + '-shm'
    
    # Clean up stale files from previous runs
    for suffix in ['', '-wal', '-shm', '-journal']:
        stale = work_db + suffix
        if os.path.exists(stale):
            os.remove(stale)
    
    shutil.copy2(db_path, work_db)
    
    # Write decoded WAL
    with open(work_wal, 'wb') as f:
        f.write(decoded_wal)
    
    # Create empty SHM file (required for SQLite WAL mode)
    with open(work_shm, 'wb') as f:
        pass
    
    print(f"Written decoded WAL to {work_wal}")
    
    # Try to read all data
    conn = None
    try:
        conn = sqlite3.connect(work_db)
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Found tables: {[t[0] for t in tables]}")
        
        if not tables:
            conn.close()
            return None, "No tables found"
        
        table_name = tables[0][0]
        
        # Try to read all data with WAL
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY id;")
        rows = cursor.fetchall()
        
        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Columns: {columns}")
        print(f"Recovered {len(rows)} records")
        
        conn.close()
        
        # Convert to list of dicts
        result = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            result.append(row_dict)
        
        return result, "OK"
        
    except Exception as e:
        print(f"Error reading database with WAL: {e}")
        if conn:
            conn.close()
        print("Falling back to manual frame application...")
        return manual_frame_recovery(db_path, decoded_wal)

def main():
    db_path = '/app/main.db'
    wal_path = '/app/main.db-wal'
    output_path = '/app/recovered.json'
    
    print("=== WAL Recovery Script ===\n")
    
    # Step 1: Backup (CRITICAL - never skip this!)
    print("Step 1: Backing up files...")
    if not os.path.exists(wal_path):
        print(f"ERROR: WAL file not found at {wal_path}")
        sys.exit(1)
    
    backup_files(db_path, wal_path)
    print()
    
    # Step 2: Detect and decode encoding
    print("Step 2: Detecting WAL encoding...")
    decoded_wal, encoding_type = detect_encoding(wal_path)
    
    if decoded_wal is None:
        print("Failed to decode WAL")
        sys.exit(1)
    print(f"Encoding detected: {encoding_type}")
    print()
    
    # Step 3: Verify WAL structure
    print("Step 3: Verifying WAL structure...")
    valid, msg = verify_wal_structure(decoded_wal)
    if not valid:
        print(f"WAL structure verification failed: {msg}")
        sys.exit(1)
    print(f"Structure: {msg}")
    print()
    
    # Step 4: Recover data
    print("Step 4: Recovering data...")
    data, msg = recover_with_decoded_wal(db_path, decoded_wal)
    
    if data is None:
        print(f"Failed to recover data: {msg}")
        sys.exit(1)
    
    print(f"\nRecovered {len(data)} records:")
    for row in data:
        print(f"  {row}")
    print()
    
    # Step 5: Write output
    print(f"Step 5: Writing output to {output_path}...")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n✓ Recovery complete! {len(data)} records written to {output_path}")

if __name__ == '__main__':
    main()

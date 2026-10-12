#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

Implements the critical "copy → diagnose → decode → open" workflow for recovering
data from encoded/corrupted SQLite WAL files.

Usage:
    python recover_wal.py <db_path> <wal_path> <output_json>

This script:
1. Copies original files to backups (preserves encoded data)
2. Diagnoses the encoding method (XOR, inversion, base64, etc.)
3. Decodes the WAL file
4. Opens the database with the decoded WAL
5. Extracts all data to JSON
"""

import struct
import shutil
import sqlite3
import json
import os
import sys
import base64


def diagnose_xor_key(wal_data):
    """Diagnose single-byte XOR encoding by checking WAL magic and version."""
    WAL_MAGIC = bytes.fromhex('377f0682')
    
    # Try all possible single-byte XOR keys
    for key in range(256):
        # Check magic
        decoded_magic = bytes([wal_data[i] ^ key for i in range(4)])
        if decoded_magic != WAL_MAGIC:
            # Try alternate magic (little-endian checksums)
            decoded_magic_alt = bytes([wal_data[i] ^ key for i in range(4)])
            if decoded_magic_alt != bytes.fromhex('377f0683'):
                continue
        
        # Verify version field
        version_bytes = bytes([wal_data[i] ^ key for i in range(4, 8)])
        version = struct.unpack('>I', version_bytes)[0]
        if version == 3007000:
            return key
    
    return None


def diagnose_inversion(wal_data):
    """Diagnose bitwise inversion encoding."""
    WAL_MAGIC = bytes.fromhex('377f0682')
    
    # Check if bitwise NOT of first 4 bytes equals magic
    inverted = bytes([~b & 0xFF for b in wal_data[:4]])
    if inverted == WAL_MAGIC:
        # Verify version
        version_bytes = bytes([~wal_data[i] & 0xFF for i in range(4, 8)])
        version = struct.unpack('>I', version_bytes)[0]
        if version == 3007000:
            return True
    
    return False


def diagnose_base64(wal_data):
    """Diagnose base64 encoding."""
    try:
        # Try to decode as base64
        decoded = base64.b64decode(wal_data[:100])
        # Check if decoded data starts with WAL magic
        if decoded[:4] == bytes.fromhex('377f0682'):
            return True
    except:
        pass
    return False


def decode_wal(wal_path):
    """
    Diagnose and decode the WAL file.
    Returns the decoded WAL data as a bytearray.
    """
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    
    print(f"WAL file size: {len(wal_data)} bytes")
    
    # Try XOR encoding
    xor_key = diagnose_xor_key(wal_data)
    if xor_key is not None:
        print(f"Detected XOR encoding with key: 0x{xor_key:02x}")
        decoded = bytearray(b ^ xor_key for b in wal_data)
        return decoded
    
    # Try bitwise inversion
    if diagnose_inversion(wal_data):
        print("Detected bitwise inversion encoding")
        decoded = bytearray(~b & 0xFF for b in wal_data)
        return decoded
    
    # Try base64 encoding
    if diagnose_base64(wal_data):
        print("Detected base64 encoding")
        decoded = base64.b64decode(wal_data)
        return decoded
    
    # Check if already valid
    if wal_data[:4] == bytes.fromhex('377f0682'):
        print("WAL file appears to be valid (no encoding detected)")
        return bytearray(wal_data)
    
    raise ValueError("Could not diagnose WAL encoding method")


def verify_decoded_wal(decoded_wal):
    """Verify the decoded WAL structure."""
    # Check magic
    magic = decoded_wal[:4]
    if magic not in [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]:
        raise ValueError(f"Invalid WAL magic: {magic.hex()}")
    
    # Check version
    version = struct.unpack('>I', decoded_wal[4:8])[0]
    if version != 3007000:
        raise ValueError(f"Invalid WAL version: {version}")
    
    # Get page size
    page_size = struct.unpack('>I', decoded_wal[8:12])[0]
    print(f"Page size: {page_size}")
    
    # Calculate frame count
    frame_size = 24 + page_size
    frame_count = (len(decoded_wal) - 32) // frame_size
    print(f"Frame count: {frame_count}")
    
    return page_size, frame_count


def extract_data(db_path, output_path):
    """Extract all data from the database and write to JSON."""
    # Remove stale shared memory file
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    # Open database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    
    all_rows = []
    for (table_name,) in tables:
        # Get column names
        cols = [desc[0] for desc in conn.execute(
            f"SELECT * FROM {table_name} LIMIT 1"
        ).description]
        
        # Get all rows
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        for row in rows:
            all_rows.append(dict(zip(cols, row)))
    
    conn.close()
    
    # Sort by id if present
    if all_rows and 'id' in all_rows[0]:
        all_rows.sort(key=lambda x: x['id'])
    
    # Write to JSON
    with open(output_path, 'w') as f:
        json.dump(all_rows, f, indent=2)
    
    print(f"Extracted {len(all_rows)} rows to {output_path}")
    return all_rows


def recover_wal(db_path, wal_path, output_path):
    """
    Main recovery workflow: copy → diagnose → decode → open → extract
    """
    print("=" * 60)
    print("SQLite WAL Recovery")
    print("=" * 60)
    
    # Step 1: Copy originals
    print("\n[Step 1] Preserving original files...")
    db_backup = db_path + '.bak'
    wal_backup = wal_path + '.bak'
    shutil.copy2(db_path, db_backup)
    shutil.copy2(wal_path, wal_backup)
    print(f"  Backed up {db_path} -> {db_backup}")
    print(f"  Backed up {wal_path} -> {wal_backup}")
    
    # Step 2 & 3: Diagnose and decode
    print("\n[Step 2-3] Diagnosing and decoding WAL...")
    decoded_wal = decode_wal(wal_backup)
    
    # Verify decoded structure
    print("\n[Verification] Checking decoded WAL structure...")
    page_size, frame_count = verify_decoded_wal(decoded_wal)
    
    # Step 4: Write decoded WAL and open database
    print("\n[Step 4] Writing decoded WAL and opening database...")
    with open(wal_path, 'wb') as f:
        f.write(decoded_wal)
    print(f"  Decoded WAL written to {wal_path}")
    
    # Step 5: Extract data
    print("\n[Step 5] Extracting data...")
    rows = extract_data(db_path, output_path)
    
    print("\n" + "=" * 60)
    print("Recovery complete!")
    print("=" * 60)
    
    return rows


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python recover_wal.py <db_path> <wal_path> <output_json>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    wal_path = sys.argv[2]
    output_path = sys.argv[3]
    
    try:
        recover_wal(db_path, wal_path, output_path)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

This script diagnoses and recovers data from encoded/corrupted SQLite WAL files.
It auto-detects the encoding transformation, decodes the WAL, and extracts all records.

Usage:
    python3 recover.py [db_path] [wal_path] [output_json]
    
Defaults:
    db_path: /app/main.db
    wal_path: /app/main.db-wal
    output_json: /app/recovered.json
"""

import struct
import json
import os
import sys
import sqlite3
from pathlib import Path


def wal_checksum(data, s0=0, s1=0):
    """
    SQLite WAL checksum algorithm.
    
    Processes data in 8-byte chunks, treating each as two big-endian 32-bit words.
    The checksum is cumulative: each call continues from the previous s0, s1.
    
    Args:
        data: bytes to checksum (must be multiple of 8 bytes; will be zero-padded)
        s0: running checksum value 0 (default 0)
        s1: running checksum value 1 (default 0)
    
    Returns:
        (s0, s1) tuple of checksum values
    """
    # Pad to 8-byte boundary
    remainder = len(data) % 8
    if remainder:
        data = data + b'\x00' * (8 - remainder)
    
    for i in range(0, len(data), 8):
        w0 = struct.unpack('>I', data[i:i+4])[0]
        w1 = struct.unpack('>I', data[i+4:i+8])[0]
        s0 = (s0 + w0 + s1) & 0xFFFFFFFF
        s1 = (s1 + w1 + s0) & 0xFFFFFFFF
    return s0, s1


def repair_wal_checksums(wal_data):
    """
    Recompute all WAL checksums (header + all frames).
    
    This is needed when:
    - Header fields were manually repaired (e.g., magic, version, page_size)
    - Frames were reconstructed from partial data
    - Checksums were corrupted independently of the page data
    
    The checksum chain is:
    - Header checksum: covers bytes 0-23 of the 32-byte header
    - Frame checksums: each frame's checksum covers its 24-byte header + page data,
      chained from the previous checksum (header checksum for frame 0, frame 0's
      checksum for frame 1, etc.)
    """
    if len(wal_data) < 32:
        return wal_data
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    frame_size = 24 + page_size
    
    # Repair header checksum (covers bytes 0-23)
    header_data = wal_data[0:24]
    s0, s1 = wal_checksum(header_data)
    wal_data = bytearray(wal_data)
    struct.pack_into('>II', wal_data, 24, s0, s1)
    
    # Repair each frame's checksum
    offset = 32
    while offset + frame_size <= len(wal_data):
        # Frame checksum covers frame header (first 8 bytes: page_num + db_size) + page data
        # But the frame header is 24 bytes; checksum covers bytes 0-7 and 24-end of frame
        # Actually: checksum covers the frame header bytes 0-7 (page_num, db_size) + page_data
        # Wait - per SQLite docs: checksum covers frame header (all 24 bytes?) No.
        # Per SQLite WAL format: the checksum for a frame covers the frame-header
        # fields at offset 0-7 (page number and size after commit) plus the page data.
        # But actually the full frame header checksum includes bytes 0-7 only for the
        # frame-specific part, then continues with page data.
        # 
        # Correction: Per SQLite source (wal.c), the frame checksum is computed over:
        #   - The 8 bytes at frame offset 0-7 (page number + db-size-after-commit)
        #   - Plus the page data (page_size bytes)
        # The salt values and checksum fields themselves are NOT included.
        
        frame_start = offset
        page_num_db_size = wal_data[frame_start:frame_start+8]
        page_data = wal_data[frame_start+24:frame_start+24+page_size]
        
        checksum_data = bytes(page_num_db_size) + bytes(page_data)
        s0, s1 = wal_checksum(checksum_data, s0, s1)
        
        struct.pack_into('>II', wal_data, frame_start + 16, s0, s1)
        offset += frame_size
    
    return bytes(wal_data)

def detect_encoding(wal_data):
    """
    Detect the encoding applied to the WAL file by comparing against known WAL magic.
    Returns: (encoding_type, decoded_data)
    """
    expected_magic_be = bytes([0x37, 0x7f, 0x06, 0x82])  # Big-endian checksums
    expected_magic_native = bytes([0x37, 0x7f, 0x06, 0x83])  # Native checksum byte order
    valid_magics = [expected_magic_be, expected_magic_native]
    observed = wal_data[:4]
    
    # Check if already valid
    if observed in valid_magics:
        return ('none', wal_data)
    
    # Try single-byte XOR against both valid magics
    for key in range(1, 256):
        decoded = bytes([b ^ key for b in observed])
        if decoded in valid_magics:
            print(f"Detected XOR encoding with key 0x{key:02x}")
            full_decoded = bytes([b ^ key for b in wal_data])
            return ('xor', full_decoded)
    
    # Try base64 (check if file looks like text)
    try:
        text = wal_data.decode('ascii')
        if all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r' for c in text[:100]):
            import base64
            decoded = base64.b64decode(wal_data)
            if decoded[:4] in valid_magics:
                print("Detected base64 encoding")
                return ('base64', decoded)
    except:
        pass
    
    # Try bitwise NOT
    inverted = bytes([b ^ 0xFF for b in observed])
    if inverted in valid_magics:
        print("Detected bitwise NOT encoding")
        full_decoded = bytes([b ^ 0xFF for b in wal_data])
        return ('not', full_decoded)
    
    # Try byte swap (swap pairs of bytes)
    if len(observed) >= 4:
        swapped = bytes([observed[1], observed[0], observed[3], observed[2]])
        if swapped in valid_magics:
            print("Detected byte-swap encoding (16-bit)")
            full_decoded = bytearray(wal_data)
            for i in range(0, len(full_decoded) - 1, 2):
                full_decoded[i], full_decoded[i+1] = full_decoded[i+1], full_decoded[i]
            return ('byteswap16', bytes(full_decoded))
    
    return ('unknown', None)

def validate_wal_header(wal_data):
    """Validate the WAL header structure."""
    if len(wal_data) < 32:
        raise ValueError("WAL file too small (< 32 bytes)")
    
    magic = struct.unpack('>I', wal_data[0:4])[0]
    version = struct.unpack('>I', wal_data[4:8])[0]
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    
    if magic not in [0x377f0682, 0x377f0683]:
        raise ValueError(f"Invalid WAL magic: 0x{magic:08x}")
    
    if version != 3007000:
        raise ValueError(f"Invalid WAL version: {version}")
    
    valid_page_sizes = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]
    if page_size not in valid_page_sizes:
        raise ValueError(f"Invalid page size: {page_size}")
    
    num_frames = (len(wal_data) - 32) // (24 + page_size)
    print(f"WAL validation: magic=0x{magic:08x}, version={version}, page_size={page_size}, frames={num_frames}")
    
    return {
        'magic': magic,
        'version': version,
        'page_size': page_size,
        'num_frames': num_frames
    }

def recover_database(db_path, wal_path, output_path):
    """Main recovery function."""
    import shutil
    
    # Check files exist
    if not os.path.exists(wal_path):
        raise FileNotFoundError(f"WAL file not found: {wal_path}")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    
    # Create backups before any modifications
    print("Creating backups...")
    shutil.copy2(wal_path, wal_path + '.bak')
    shutil.copy2(db_path, db_path + '.bak')
    print(f"Backups created: {wal_path}.bak, {db_path}.bak")
    
    # Remove stale SHM file (SQLite always appends -shm to the DB filename)
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        print(f"Removing stale SHM file: {shm_path}")
        os.remove(shm_path)
    
    # Read WAL file
    print(f"Reading WAL file: {wal_path}")
    with open(wal_path, 'rb') as f:
        raw_wal = f.read()
    
    print(f"WAL file size: {len(raw_wal)} bytes")
    
    # Detect and apply encoding
    encoding_type, decoded_wal = detect_encoding(raw_wal)
    
    if decoded_wal is None:
        raise ValueError("Could not detect WAL encoding or WAL is too corrupted")
    
    # Validate decoded WAL
    wal_info = validate_wal_header(decoded_wal)
    
    # Write decoded WAL back
    print(f"Writing decoded WAL to: {wal_path}")
    with open(wal_path, 'wb') as f:
        f.write(decoded_wal)
    
    # Verify WAL was written correctly
    with open(wal_path, 'rb') as f:
        verify_data = f.read()
    valid_magics = [bytes([0x37, 0x7f, 0x06, 0x82]), bytes([0x37, 0x7f, 0x06, 0x83])]
    if verify_data[:4] not in valid_magics:
        raise ValueError("WAL write verification failed - magic bytes don't match")
    print("WAL write verified successfully")
    
    # Try opening database; if checksum errors occur, repair and retry
    print(f"Opening database: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Test if WAL is accepted by querying
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
    except sqlite3.DatabaseError as e:
        if 'checksum' in str(e).lower() or 'malformed' in str(e).lower():
            print(f"WAL checksum error detected: {e}")
            print("Attempting to repair WAL checksums...")
            repaired_wal = repair_wal_checksums(bytearray(decoded_wal))
            with open(wal_path, 'wb') as f:
                f.write(repaired_wal)
            print("Checksums repaired, retrying...")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
        else:
            raise
    
    print(f"Found tables: {tables}")
    
    # Extract all records
    results = []
    for table in tables:
        cursor.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        print(f"Table '{table}': {len(rows)} records, columns: {cols}")
        
        for row in rows:
            results.append(dict(zip(cols, row)))
    
    # Sort by id if present, otherwise by first column
    if results and 'id' in results[0]:
        results.sort(key=lambda r: r.get('id', 0))
    elif results:
        first_col = list(results[0].keys())[0]
        results.sort(key=lambda r: r.get(first_col, 0))
    
    # Write to JSON
    print(f"Writing {len(results)} records to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    conn.close()
    
    print(f"Recovery complete: {len(results)} records recovered")
    return results

def find_wal_file(db_path):
    """Find the WAL file, trying common naming patterns."""
    # Try standard naming: database.db-wal
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        return wal_path
    
    # Try alternative: database-wal
    base = db_path.rsplit('.', 1)[0] if '.' in db_path else db_path
    wal_path = base + '-wal'
    if os.path.exists(wal_path):
        return wal_path
    
    # Try: database.wal
    wal_path = base + '.wal'
    if os.path.exists(wal_path):
        return wal_path
    
    return None

def main():
    # Parse arguments
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/main.db'
    wal_path = sys.argv[2] if len(sys.argv) > 2 else None
    output_path = sys.argv[3] if len(sys.argv) > 3 else '/app/recovered.json'
    
    # Auto-detect WAL file if not specified
    if wal_path is None:
        wal_path = find_wal_file(db_path)
        if wal_path is None:
            print("Error: Could not find WAL file. Tried:", file=sys.stderr)
            print(f"  {db_path}-wal", file=sys.stderr)
            print(f"  {db_path.rsplit('.', 1)[0]}-wal", file=sys.stderr)
            print(f"  {db_path.rsplit('.', 1)[0]}.wal", file=sys.stderr)
            return 1
        print(f"Auto-detected WAL file: {wal_path}")
    
    try:
        results = recover_database(db_path, wal_path, output_path)
        print(f"\nRecovered data:")
        for record in results:
            print(f"  {record}")
        return 0
    except Exception as e:
        print(f"Recovery failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())

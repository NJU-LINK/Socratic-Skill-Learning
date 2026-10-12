#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

This script recovers data from corrupted, encrypted, or obfuscated SQLite WAL files.
It diagnoses the encoding, decodes the WAL, applies frames, and extracts all data.

Usage:
    python3 recover_wal.py [db_path] [wal_path] [output_json]

Defaults:
    db_path: /app/main.db
    wal_path: /app/main.db-wal
    output_json: /app/recovered.json
"""

import struct
import shutil
import sqlite3
import json
import os
import sys

def diagnose_wal_encoding(wal_data):
    """
    Diagnose the encoding applied to the WAL file by checking the magic number.
    
    Returns:
        (encoding_type, key) where encoding_type is one of:
        - "intact": WAL is valid
        - "xor": single-byte XOR encoding
        - "not": bitwise NOT encoding
        - "base64": base64 encoded
        - "unknown": cannot determine
        And key is the XOR key if applicable, else None
    """
    if len(wal_data) < 32:
        return "invalid", None
    
    magic = struct.unpack('>I', wal_data[0:4])[0]
    
    # Valid magic
    if magic in [0x377F0682, 0x377F0683]:
        return "intact", None
    
    # Bitwise NOT
    inverted_magic = struct.unpack('>I', bytes([b ^ 0xFF for b in wal_data[0:4]]))[0]
    if inverted_magic in [0x377F0682, 0x377F0683]:
        return "not", None
    
    # Single-byte XOR
    expected_magic = bytes([0x37, 0x7F, 0x06, 0x82])
    xor_keys = [a ^ b for a, b in zip(wal_data[:4], expected_magic)]
    if len(set(xor_keys)) == 1:
        return "xor", xor_keys[0]
    
    # Base64 (ASCII text)
    try:
        if all(32 <= b <= 126 for b in wal_data[:min(100, len(wal_data))]):
            return "base64", None
    except:
        pass
    
    return "unknown", None

def decode_wal(wal_data, encoding, key=None):
    """Decode the WAL file based on the diagnosed encoding."""
    if encoding == "intact":
        return wal_data
    elif encoding == "not":
        return bytes([b ^ 0xFF for b in wal_data])
    elif encoding == "xor":
        return bytes([b ^ key for b in wal_data])
    elif encoding == "base64":
        import base64
        return base64.b64decode(wal_data)
    else:
        raise ValueError(f"Unknown encoding: {encoding}")

def parse_wal_frames(wal_data, page_size):
    """
    Parse all frames from the decoded WAL data.
    
    Returns:
        dict mapping page_number -> page_data (last write wins)
    """
    offset = 32
    page_updates = {}
    frame_count = 0
    
    while offset + 24 + page_size <= len(wal_data):
        frame_count += 1
        frame_header = wal_data[offset:offset+24]
        page_num = struct.unpack('>I', frame_header[0:4])[0]
        page_data = wal_data[offset+24:offset+24+page_size]
        
        if page_num > 0:
            # WAL is append-only; later frames override earlier ones
            page_updates[page_num] = page_data
        
        offset += 24 + page_size
    
    return page_updates, frame_count

def apply_wal_frames(db_path, page_updates, page_size, output_path=None):
    """
    Apply WAL frames to the database by overwriting pages.
    
    Args:
        db_path: Path to the base database
        page_updates: Dict mapping page_number -> page_data
        page_size: Database page size
        output_path: Output database path (defaults to db_path + '.recovered')
    
    Returns:
        Path to the recovered database
    """
    if output_path is None:
        output_path = db_path + '.recovered'
    
    # Copy base database
    shutil.copy(db_path, output_path)
    
    # Apply pages
    with open(output_path, 'r+b') as db:
        for pg_num, pg_data in page_updates.items():
            db.seek((pg_num - 1) * page_size)
            db.write(pg_data)
    
    return output_path

def extract_data(db_path, table_name=None):
    """
    Extract all data from the recovered database.
    
    Args:
        db_path: Path to the recovered database
        table_name: Specific table to extract (None = all tables)
    
    Returns:
        List of dicts (if single table) or dict of table -> list of dicts
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    if table_name:
        tables = [table_name]
    else:
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
    
    all_data = {}
    for table in tables:
        c.execute(f"SELECT * FROM {table}")
        rows = c.fetchall()
        
        # Get column names
        c.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in c.fetchall()]
        
        # Convert to list of dicts
        all_data[table] = [dict(zip(columns, row)) for row in rows]
    
    conn.close()
    
    # If single table, return just that data
    if len(tables) == 1:
        return all_data[tables[0]]
    return all_data

def recover_wal(db_path, wal_path, output_json=None, output_db=None):
    """
    Complete WAL recovery workflow.
    
    Args:
        db_path: Path to the base database
        wal_path: Path to the WAL file
        output_json: Path for JSON output (optional)
        output_db: Path for recovered database (optional)
    
    Returns:
        Recovered data
    """
    print(f"=== SQLite WAL Recovery ===\n")
    
    # Check files exist
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not os.path.exists(wal_path):
        raise FileNotFoundError(f"WAL file not found: {wal_path}")
    
    # Read WAL
    print(f"Reading WAL file: {wal_path}")
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    print(f"WAL size: {len(wal_data)} bytes")
    
    # Backup WAL before any processing
    backup_path = wal_path + '.backup'
    shutil.copy(wal_path, backup_path)
    print(f"WAL backed up to: {backup_path}")
    
    # Diagnose encoding
    print(f"\nDiagnosing encoding...")
    encoding, key = diagnose_wal_encoding(wal_data)
    print(f"Encoding: {encoding}")
    if key is not None:
        print(f"Key: 0x{key:02X}")
    
    if encoding == "unknown":
        raise ValueError("Cannot determine WAL encoding")
    
    # Decode WAL
    print(f"\nDecoding WAL...")
    decoded_wal = decode_wal(wal_data, encoding, key)
    decoded_magic = struct.unpack('>I', decoded_wal[0:4])[0]
    print(f"Decoded magic: 0x{decoded_magic:08X}")
    
    # Parse WAL header
    page_size = struct.unpack('>I', decoded_wal[8:12])[0]
    print(f"Page size: {page_size}")
    
    # Verify page size matches database
    with open(db_path, 'rb') as f:
        db_header = f.read(100)
    db_page_size = struct.unpack('>H', db_header[16:18])[0]
    if db_page_size == 1:
        db_page_size = 512  # SQLite special case
    print(f"Database page size: {db_page_size}")
    
    if page_size != db_page_size:
        print(f"WARNING: Page size mismatch! WAL={page_size}, DB={db_page_size}")
    
    # Parse frames
    print(f"\nParsing frames...")
    page_updates, frame_count = parse_wal_frames(decoded_wal, page_size)
    print(f"Total frames: {frame_count}")
    print(f"Unique pages: {len(page_updates)}")
    print(f"Pages updated: {sorted(page_updates.keys())}")
    
    # Apply frames
    print(f"\nApplying frames to database...")
    if output_db is None:
        output_db = db_path + '.recovered'
    recovered_db = apply_wal_frames(db_path, page_updates, page_size, output_db)
    print(f"Recovered database: {recovered_db}")
    
    # Extract data
    print(f"\nExtracting data...")
    data = extract_data(recovered_db)
    
    if isinstance(data, list):
        print(f"Recovered {len(data)} records")
    else:
        for table, rows in data.items():
            print(f"Table '{table}': {len(rows)} records")
    
    # Output JSON
    if output_json:
        print(f"\nWriting JSON to: {output_json}")
        with open(output_json, 'w') as f:
            json.dump(data, f, indent=2)
    
    return data

def main():
    """Main entry point."""
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/main.db'
    wal_path = sys.argv[2] if len(sys.argv) > 2 else '/app/main.db-wal'
    output_json = sys.argv[3] if len(sys.argv) > 3 else '/app/recovered.json'
    
    try:
        data = recover_wal(db_path, wal_path, output_json)
        print(f"\n=== Recovery Complete ===")
        print(f"Output written to: {output_json}")
        return 0
    except Exception as e:
        print(f"\n=== Recovery Failed ===")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())

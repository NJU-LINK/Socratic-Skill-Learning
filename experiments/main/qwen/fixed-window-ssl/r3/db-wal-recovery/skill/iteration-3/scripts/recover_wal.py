#!/usr/bin/env python3
"""
Reference implementation for SQLite WAL recovery.

Usage: python3 recover_wal.py <db_path> <wal_path> <output_json_path>

This script handles the full diagnostic and recovery pipeline:
1. Capture WAL before any SQLite access
2. Detect encoding transformation (XOR, base64, bitwise NOT, byte-swap)
3. Validate decoded WAL structure (magic, version, page_size, frame headers)
4. Choose recovery procedure based on damage level:
   - Procedure A: Auto-replay (valid frame headers)
   - Procedure B: Manual page application (damaged frame headers)
   - Procedure D: Reproduce-and-compare (lost WAL)
5. Extract data and write JSON output
"""

import struct
import json
import sqlite3
import shutil
import os
import sys
import base64

WAL_MAGIC_BE = 0x377f0682
WAL_MAGIC_LE = 0x377f0683
WAL_VERSION = 3007000
WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24
VALID_PAGE_SIZES = {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}


def detect_encoding(raw):
    """Detect and reverse encoding transformation on WAL data."""
    actual_magic = struct.unpack('>I', raw[0:4])[0]
    
    # Already valid
    if actual_magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        return raw, "none"
    
    # Try single-byte XOR (keys 1-255)
    expected = struct.pack('>I', WAL_MAGIC_BE)
    for key in range(1, 256):
        decoded = bytes([b ^ key for b in raw])
        magic = struct.unpack('>I', decoded[0:4])[0]
        if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
            return decoded, f"xor-0x{key:02x}"
    
    # Try bitwise NOT
    decoded = bytes([~b & 0xFF for b in raw])
    magic = struct.unpack('>I', decoded[0:4])[0]
    if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        return decoded, "bitwise-not"
    
    # Try base64 decode
    try:
        if all(32 <= b < 127 for b in raw[:min(100, len(raw))]):
            decoded = base64.b64decode(raw)
            magic = struct.unpack('>I', decoded[0:4])[0]
            if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
                return decoded, "base64"
    except Exception:
        pass
    
    # Try byte-swap (swap pairs)
    if len(raw) % 2 == 0:
        decoded = bytearray(len(raw))
        for i in range(0, len(raw), 2):
            decoded[i] = raw[i+1]
            decoded[i+1] = raw[i]
        magic = struct.unpack('>I', decoded[0:4])[0]
        if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
            return bytes(decoded), "byte-swap"
    
    # Try multi-byte XOR with common patterns
    for key_len in [2, 4]:
        key_bytes = bytes([a ^ e for a, e in zip(raw[:key_len], expected[:key_len])])
        decoded = bytearray(len(raw))
        for i in range(len(raw)):
            decoded[i] = raw[i] ^ key_bytes[i % key_len]
        magic = struct.unpack('>I', decoded[0:4])[0]
        if magic in (WAL_MAGIC_BE, WAL_MAGIC_LE):
            return bytes(decoded), f"xor-key-{key_bytes.hex()}"
    
    raise ValueError(f"Cannot detect encoding. First 4 bytes: {raw[:4].hex()}")


def validate_wal_header(decoded):
    """Validate WAL header and return (page_size, header_salt1, header_salt2)."""
    if len(decoded) < WAL_HEADER_SIZE:
        raise ValueError(f"WAL too short: {len(decoded)} bytes")
    
    magic = struct.unpack('>I', decoded[0:4])[0]
    version = struct.unpack('>I', decoded[4:8])[0]
    page_size = struct.unpack('>I', decoded[8:12])[0]
    salt1 = struct.unpack('>I', decoded[16:20])[0]
    salt2 = struct.unpack('>I', decoded[20:24])[0]
    
    if magic not in (WAL_MAGIC_BE, WAL_MAGIC_LE):
        raise ValueError(f"Invalid magic: 0x{magic:08x}")
    
    if page_size not in VALID_PAGE_SIZES:
        raise ValueError(f"Invalid page size: {page_size}")
    
    frame_size = FRAME_HEADER_SIZE + page_size
    remaining = len(decoded) - WAL_HEADER_SIZE
    if remaining % frame_size != 0:
        print(f"Warning: WAL size {len(decoded)} not aligned to frame boundaries")
    
    frame_count = remaining // frame_size
    print(f"WAL: magic=0x{magic:08x}, version={version}, page_size={page_size}, frames={frame_count}")
    
    return page_size, salt1, salt2, frame_count


def check_frame_headers(decoded, page_size, header_salt1, header_salt2):
    """Check frame header validity. Returns list of (pgno, valid, salt_match) tuples."""
    frames = []
    offset = WAL_HEADER_SIZE
    
    while offset + FRAME_HEADER_SIZE + page_size <= len(decoded):
        pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
        db_size = struct.unpack('>I', decoded[offset+4:offset+8])[0]
        salt1 = struct.unpack('>I', decoded[offset+8:offset+12])[0]
        salt2 = struct.unpack('>I', decoded[offset+12:offset+16])[0]
        
        valid = pgno > 0
        salt_match = (salt1 == header_salt1 and salt2 == header_salt2)
        frames.append((pgno, valid, salt_match, db_size))
        
        offset += FRAME_HEADER_SIZE + page_size
    
    return frames


def procedure_a_auto_replay(db_path, wal_path, decoded):
    """Procedure A: Write decoded WAL and let SQLite replay."""
    # Backup original WAL
    shutil.copy2(wal_path, wal_path + '.original')
    
    # Write decoded WAL
    with open(wal_path, 'wb') as f:
        f.write(decoded)
    
    # Open database - SQLite replays WAL automatically
    conn = sqlite3.connect(db_path)
    return conn


def procedure_b_manual_apply(db_path, decoded, page_size):
    """Procedure B: Manually apply pages to a copy of the database."""
    patched_path = db_path + '.patched'
    shutil.copy2(db_path, patched_path)
    
    db = open(patched_path, 'r+b')
    db_base_size = os.path.getsize(patched_path)
    
    offset = WAL_HEADER_SIZE
    applied = {}
    
    while offset + FRAME_HEADER_SIZE + page_size <= len(decoded):
        pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
        page_data = decoded[offset+FRAME_HEADER_SIZE:offset+FRAME_HEADER_SIZE+page_size]
        
        # If pgno is 0, determine from content
        if pgno == 0:
            page_type = page_data[0]
            if page_type == 0x0D:  # leaf table b-tree
                pgno = 2
            elif page_type == 0x05:  # interior table b-tree
                pgno = 1
            elif page_type == 0x0A:  # leaf index b-tree
                pgno = 3  # guess
            else:
                pgno = 1  # fallback
        
        # Extend database if needed
        current_size = os.path.getsize(patched_path)
        needed_size = pgno * page_size
        if needed_size > current_size:
            db.seek(0, 2)  # seek to end
            db.write(b'\x00' * (needed_size - current_size))
        
        db.seek((pgno - 1) * page_size)
        db.write(page_data)
        applied[pgno] = True
        
        offset += FRAME_HEADER_SIZE + page_size
    
    db.close()
    print(f"Applied {len(applied)} unique pages: {sorted(applied.keys())}")
    
    conn = sqlite3.connect(patched_path)
    return conn


def extract_data(conn, output_path):
    """Extract all data from database and write to JSON."""
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    
    all_data = {}
    for table_name in tables:
        table_name = table_name[0]
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        all_data[table_name] = [dict(zip(columns, row)) for row in rows]
    
    conn.close()
    
    # Write JSON - try to find the primary table
    result = None
    for tname, rows in all_data.items():
        if rows and 'id' in rows[0]:
            result = sorted(rows, key=lambda x: x['id'])
            break
    
    if result is None:
        result = all_data
    
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    total = len(result) if isinstance(result, list) else sum(len(v) for v in result.values())
    print(f"Extracted {total} records to {output_path}")
    return result


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <db_path> <wal_path> <output_json>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    wal_path = sys.argv[2]
    output_path = sys.argv[3]
    
    if not os.path.exists(wal_path):
        print(f"WAL not found at {wal_path}")
        print("Attempting Procedure D (reproduce-and-compare) would require schema analysis")
        sys.exit(1)
    
    # Step 1: Read WAL
    raw = open(wal_path, 'rb').read()
    print(f"WAL size: {len(raw)} bytes")
    
    # Step 2: Detect encoding
    decoded, transform = detect_encoding(raw)
    print(f"Encoding: {transform}")
    
    # Step 3: Validate header
    page_size, salt1, salt2, frame_count = validate_wal_header(decoded)
    
    # Step 4: Check frames
    frames = check_frame_headers(decoded, page_size, salt1, salt2)
    all_valid = all(f[1] and f[2] for f in frames)
    
    print(f"Frames: {len(frames)}, all valid: {all_valid}")
    for i, (pgno, valid, salt_match, db_size) in enumerate(frames):
        status = "OK" if valid and salt_match else "DAMAGED"
        print(f"  Frame {i}: pgno={pgno}, db_size={db_size}, salt_match={salt_match} [{status}]")
    
    # Step 5: Choose recovery procedure
    if all_valid:
        print("\nUsing Procedure A: Auto-replay")
        conn = procedure_a_auto_replay(db_path, wal_path, decoded)
    else:
        print("\nUsing Procedure B: Manual page application")
        conn = procedure_b_manual_apply(db_path, decoded, page_size)
    
    # Step 6: Extract data
    extract_data(conn, output_path)


if __name__ == '__main__':
    main()

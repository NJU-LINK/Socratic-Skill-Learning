#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

Handles the db-wal-recovery task family:
- Encoded/obfuscated WAL files (XOR, NOT, base64, byte-swap, etc.)
- Structural damage (bad checksums, mismatched salts, corrupted headers)
- Various recovery depths (direct SQLite replay, manual page extraction)

Usage:
    python3 recover.py [db_path] [wal_path] [output_json]
    
Defaults:
    db_path: /app/main.db
    wal_path: /app/main.db-wal
    output_json: /app/recovered.json
"""

import struct
import json
import shutil
import os
import sys
import base64
import sqlite3
from typing import Optional, Tuple, List

# SQLite WAL magic numbers
WAL_MAGIC_BIG_ENDIAN = 0x377f0682
WAL_MAGIC_LITTLE_ENDIAN = 0x377f0683

def wal_checksum(data: bytes, s1: int = 0, s2: int = 0, big_endian: bool = True) -> Tuple[int, int]:
    """
    Compute SQLite WAL checksum over data, continuing from s1, s2.
    
    Algorithm: For each 32-bit word w:
        s1 = (s1 + w + s2) % 2^32
        s2 = (s2 + s1) % 2^32
    
    Endianness determined by magic number LSB:
        0x...82 = big-endian
        0x...83 = little-endian
    """
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data) - 3, 4):
        word = struct.unpack(fmt, data[i:i+4])[0]
        s1 = (s1 + word + s2) & 0xFFFFFFFF
        s2 = (s2 + s1) & 0xFFFFFFFF
    return s1, s2

def try_decode_wal(raw_data: bytes) -> Tuple[bytes, str]:
    """
    Try various decodings to find valid SQLite WAL magic number.
    Returns (decoded_data, encoding_type) tuple.
    """
    first4 = raw_data[:4]
    
    # 1. Check if already valid (no encoding)
    magic = struct.unpack('>I', first4)[0]
    if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
        return raw_data, "none"
    
    # 2. Try single-byte XOR with all 256 keys
    for key in range(256):
        decoded = bytes(b ^ key for b in first4)
        magic = struct.unpack('>I', decoded)[0]
        if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
            decoded_full = bytes(b ^ key for b in raw_data)
            return decoded_full, f"xor-0x{key:02x}"
    
    # 3. Try bitwise NOT (equivalent to XOR 0xFF, but check explicitly)
    decoded_not = bytes((~b) & 0xFF for b in first4)
    magic = struct.unpack('>I', decoded_not)[0]
    if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
        decoded_full = bytes((~b) & 0xFF for b in raw_data)
        return decoded_full, "not"
    
    # 4. Try base64 decoding (if file looks like ASCII text)
    try:
        if all(32 <= b < 127 for b in raw_data[:100]):
            decoded_b64 = base64.b64decode(raw_data)
            magic = struct.unpack('>I', decoded_b64[:4])[0]
            if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
                return decoded_b64, "base64"
    except:
        pass
    
    # 5. Try byte swapping (swap pairs)
    if len(raw_data) >= 4:
        swapped = bytearray(len(raw_data))
        for i in range(0, len(raw_data) - 1, 2):
            swapped[i] = raw_data[i+1]
            swapped[i+1] = raw_data[i]
        magic = struct.unpack('>I', swapped[:4])[0]
        if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
            return bytes(swapped), "byte-swap-pairs"
    
    # 6. Try byte swapping (swap quads)
    if len(raw_data) >= 4:
        swapped = bytearray(len(raw_data))
        for i in range(0, len(raw_data) - 3, 4):
            swapped[i:i+4] = raw_data[i:i+4][::-1]
        magic = struct.unpack('>I', swapped[:4])[0]
        if magic in (WAL_MAGIC_BIG_ENDIAN, WAL_MAGIC_LITTLE_ENDIAN):
            return bytes(swapped), "byte-swap-quads"
    
    raise ValueError("Could not identify WAL encoding")

def repair_wal_structure(data: bytearray) -> bytearray:
    """
    Repair WAL structure: recompute checksums and fix frame salts.
    
    This handles:
    - Non-byte-preserving encodings (base64, byte-swap)
    - Structural damage (corrupted checksums, mismatched salts)
    - Cases where decoding alone isn't sufficient
    """
    if len(data) < 32:
        raise ValueError("WAL file too small")
    
    # Parse header
    magic = struct.unpack('>I', data[0:4])[0]
    big_endian = (magic & 0x01) == 0
    page_size = struct.unpack('>I', data[8:12])[0]
    
    # Validate page size
    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
        raise ValueError(f"Invalid page size: {page_size}")
    
    # Determine checksum storage format from magic
    cksum_fmt = '>II' if big_endian else '<II'
    
    # Recompute header checksum (covers bytes 0-23, stored at 24-31)
    s1, s2 = wal_checksum(bytes(data[0:24]), 0, 0, big_endian)
    struct.pack_into(cksum_fmt, data, 24, s1, s2)
    
    # Walk and fix frames
    offset = 32
    frame_count = 0
    while offset + 24 + page_size <= len(data):
        # Copy salt from header (bytes 16-23) into frame header (bytes 8-15)
        data[offset+8:offset+16] = data[16:24]
        
        # Compute frame checksum: over frame header bytes 0-7 + page data
        # Continuing from cumulative s1, s2
        frame_hdr_for_cksum = bytes(data[offset:offset+8])
        page_data = bytes(data[offset+24:offset+24+page_size])
        s1, s2 = wal_checksum(frame_hdr_for_cksum + page_data, s1, s2, big_endian)
        struct.pack_into(cksum_fmt, data, offset+16, s1, s2)
        
        offset += 24 + page_size
        frame_count += 1
    
    return data

def recover_database(db_path: str, wal_path: str) -> List[dict]:
    """
    Recover all data from database with repaired WAL.
    
    Strategy:
    1. Open with sqlite3 (SQLite replays the valid WAL)
    2. Extract all rows from all tables
    3. Return as list of dicts
    
    Handles:
    - Single or multiple tables
    - Various column types and names
    - Sorting by id if present
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all table names (exclude sqlite internal tables)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    
    if not tables:
        conn.close()
        raise ValueError("No tables found in database")
    
    all_rows = []
    
    # If single table, extract all rows
    if len(tables) == 1:
        table_name = tables[0][0]
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        
        cursor = conn.execute(f"SELECT * FROM {table_name}")
        for row in cursor.fetchall():
            row_dict = dict(zip(columns, row))
            all_rows.append(row_dict)
    else:
        # Multiple tables: extract from each
        for table in tables:
            table_name = table[0]
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            
            cursor = conn.execute(f"SELECT * FROM {table_name}")
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                row_dict['_table'] = table_name  # Tag with table name
                all_rows.append(row_dict)
    
    conn.close()
    return all_rows

def parse_wal_frames(wal_data: bytes) -> Tuple[bytes, List[Tuple[int, bytes]], int]:
    """
    Parse WAL file and extract frames.
    
    Returns:
        header: First 32 bytes (WAL header)
        frames: List of (page_num, page_data) tuples
        page_size: Database page size from header
    """
    if len(wal_data) < 32:
        raise ValueError("WAL data too small")
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    header = wal_data[:32]
    frames = []
    
    offset = 32
    while offset + 24 + page_size <= len(wal_data):
        page_num = struct.unpack('>I', wal_data[offset:offset+4])[0]
        page_data = wal_data[offset+24:offset+24+page_size]
        frames.append((page_num, page_data))
        offset += 24 + page_size
    
    return header, frames, page_size

def find_all_wal_files(wal_path: str) -> List[str]:
    """
    Find all WAL files in sequence (main.db-wal, main.db-wal2, main.db-wal3, etc.)
    Returns list of paths in order.
    """
    wal_files = []
    
    # Check for main WAL file
    if os.path.exists(wal_path):
        wal_files.append(wal_path)
    
    # Check for additional WAL files (wal2, wal3, etc.)
    base_dir = os.path.dirname(wal_path)
    base_name = os.path.basename(wal_path)
    counter = 2
    
    while True:
        # Try patterns like main.db-wal2, main.db-wal3, etc.
        alt_wal = os.path.join(base_dir, f"{base_name}{counter}")
        if os.path.exists(alt_wal):
            wal_files.append(alt_wal)
            counter += 1
        else:
            break
    
    return wal_files

def apply_wal_frames_manually(db_path: str, wal_data: bytes, wal_path: str) -> None:
    """
    Manually apply WAL frames to database by writing page data directly.
    
    This is used when SQLite's WAL replay fails (e.g., checkpoint_seq mismatch,
    schema cookie issues, or other internal state problems).
    
    Strategy: For each page number, keep the LAST frame (most recent update).
    Validates frame structure and handles partial frames gracefully.
    """
    if len(wal_data) < 32:
        raise ValueError("WAL data too small")
    
    page_size = struct.unpack('>I', wal_data[8:12])[0]
    
    # Validate page size
    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
        raise ValueError(f"Invalid page size: {page_size}")
    
    # Get database file size to validate page numbers
    db_size = os.path.getsize(db_path)
    db_pages = db_size // page_size
    
    # Parse all frames, keep last frame per page, validate structure
    last_frames = {}
    offset = 32
    frame_count = 0
    skipped_frames = 0
    
    while offset + 24 + page_size <= len(wal_data):
        page_num = struct.unpack('>I', wal_data[offset:offset+4])[0]
        page_data = bytes(wal_data[offset+24:offset+24+page_size])
        
        # Validate page number
        if page_num == 0:
            print(f"Warning: Frame {frame_count} has invalid page_num=0, skipping")
            skipped_frames += 1
        elif page_num > db_pages + 10:  # Allow some slack for new pages
            print(f"Warning: Frame {frame_count} has suspicious page_num={page_num} (db has {db_pages} pages), skipping")
            skipped_frames += 1
        else:
            last_frames[page_num] = page_data
        
        offset += 24 + page_size
        frame_count += 1
    
    # Check for partial frame at end
    if offset < len(wal_data):
        remaining = len(wal_data) - offset
        print(f"Warning: Partial frame at end of WAL ({remaining} bytes remaining), ignoring")
    
    if not last_frames:
        raise ValueError(f"No valid frames found in WAL (processed {frame_count} frames, skipped {skipped_frames})")
    
    print(f"Applying {len(last_frames)} page(s) manually (from {frame_count} frames, {skipped_frames} skipped)...")
    
    # Apply frames directly to database
    with open(db_path, 'r+b') as dbf:
        for page_num, page_data in last_frames.items():
            file_offset = (page_num - 1) * page_size
            dbf.seek(file_offset)
            dbf.write(page_data)
    
    # Remove WAL so SQLite doesn't try to replay it
    if os.path.exists(wal_path):
        os.remove(wal_path)

def main():
    # Parse arguments
    db_path = sys.argv[1] if len(sys.argv) > 1 else '/app/main.db'
    wal_path = sys.argv[2] if len(sys.argv) > 2 else '/app/main.db-wal'
    output_json = sys.argv[3] if len(sys.argv) > 3 else '/app/recovered.json'
    
    # Validate inputs exist (at least WAL must exist; base DB may be missing)
    if not os.path.exists(wal_path):
        print(f"Error: WAL file not found at {wal_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(db_path):
        print(f"Note: Database not found at {db_path} (will reconstruct from WAL)")
    
    # CRITICAL: Backup before touching anything
    print("Backing up files...")
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + '.bak')
    shutil.copy2(wal_path, wal_path + '.bak')
    
    # Read raw WAL (check for multiple WAL files)
    print("Reading WAL file(s)...")
    wal_files = find_all_wal_files(wal_path)
    if len(wal_files) > 1:
        print(f"Found {len(wal_files)} WAL files, merging frames...")
        merged_frames = {}   # page_num → page_data, last wins
        header = None
        page_size = None
        for wf in wal_files:
            chunk = open(wf, 'rb').read()
            decoded_chunk, enc = try_decode_wal(chunk)
            print(f"  {os.path.basename(wf)}: {len(chunk)} bytes, encoding={enc}")
            h, frames, ps = parse_wal_frames(decoded_chunk)
            if header is None:
                header = bytearray(h)
                page_size = ps
            for pn, pd in frames:
                merged_frames[pn] = pd
        
        # Rebuild single WAL: one header + all frames
        rebuilt = bytearray(header)
        for pn, pd in merged_frames.items():
            rebuilt += struct.pack('>II', pn, 0)  # page_num, db_size=0
            rebuilt += bytes(header[16:24])        # salt from header
            rebuilt += b'\x00' * 8                 # placeholder checksum (fixed by repair)
            rebuilt += pd
        raw_wal = bytes(rebuilt)
        print(f"Merged {len(merged_frames)} unique pages from {len(wal_files)} WAL files")
    else:
        raw_wal = open(wal_path, 'rb').read()
    print(f"WAL size: {len(raw_wal)} bytes")
    
    # Count base rows BEFORE any recovery
    print("Counting base database rows...")
    base_db_was_missing = False
    if not os.path.exists(db_path):
        print("Base database missing, creating from WAL...")
        base_db_was_missing = True
        # Decode WAL to get page size
        decoded_wal, encoding_type = try_decode_wal(raw_wal)
        page_size = struct.unpack('>I', decoded_wal[8:12])[0]
        
        # Find max page to determine database size
        max_page = 0
        offset = 32
        while offset + 24 + page_size <= len(decoded_wal):
            page_num = struct.unpack('>I', decoded_wal[offset:offset+4])[0]
            max_page = max(max_page, page_num)
            offset += 24 + page_size
        
        # Create empty database file (zeros)
        with open(db_path, 'wb') as f:
            f.write(b'\x00' * (max_page * page_size))
        print(f"Created empty database: {max_page} pages, {page_size} bytes each")
        base_row_count = 0
    else:
        conn_base = sqlite3.connect(db_path)
        base_tables = conn_base.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        base_row_count = 0
        if base_tables:
            base_row_count = conn_base.execute(f"SELECT COUNT(*) FROM {base_tables[0][0]}").fetchone()[0]
        conn_base.close()
    print(f"Base database has {base_row_count} rows")
    
    # Diagnose and decode encoding
    print("Diagnosing WAL encoding...")
    try:
        decoded_wal, encoding_type = try_decode_wal(raw_wal)
        print(f"Detected encoding: {encoding_type}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Repair WAL structure (checksums, salts)
    print("Repairing WAL structure...")
    repaired_wal = repair_wal_structure(bytearray(decoded_wal))
    
    # Strategy 1: Try SQLite WAL replay (skip if base DB was missing)
    if base_db_was_missing:
        print("Base database was missing, skipping SQLite WAL replay...")
        print("Strategy 2: Applying WAL frames manually...")
        
        # Apply WAL frames manually
        apply_wal_frames_manually(db_path, bytes(repaired_wal), wal_path)
        
        # Extract data
        try:
            all_rows = recover_database(db_path, wal_path)
            print(f"✓ Manual page application recovered {len(all_rows)} rows")
        except Exception as e2:
            print(f"Error: Manual recovery also failed: {e2}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Strategy 1: Trying SQLite WAL replay...")
        with open(wal_path, 'wb') as f:
            f.write(repaired_wal)
        
        try:
            all_rows = recover_database(db_path, wal_path)
            print(f"SQLite replay returned {len(all_rows)} rows")
            
            # Check if replay succeeded (should have more rows than base)
            if len(all_rows) > base_row_count:
                print("✓ SQLite replay succeeded!")
            else:
                print(f"✗ SQLite replay failed (got {len(all_rows)} rows, expected > {base_row_count})")
                raise ValueError("SQLite replay returned too few rows")
        except Exception as e:
            print(f"SQLite replay failed: {e}")
            print("Strategy 2: Falling back to manual page application...")
            
            # Restore database from backup (if it existed)
            if os.path.exists(db_path + '.bak'):
                shutil.copy2(db_path + '.bak', db_path)
            
            # Apply WAL frames manually
            apply_wal_frames_manually(db_path, bytes(repaired_wal), wal_path)
            
            # Re-extract data
            try:
                all_rows = recover_database(db_path, wal_path)
                print(f"✓ Manual page application recovered {len(all_rows)} rows")
            except Exception as e2:
                print(f"Error: Manual recovery also failed: {e2}", file=sys.stderr)
                sys.exit(1)
    
    # Sort by id if present
    if all_rows and 'id' in all_rows[0]:
        all_rows.sort(key=lambda r: r['id'])
    
    # Write JSON output
    print(f"Writing output to {output_json}...")
    with open(output_json, 'w') as f:
        json.dump(all_rows, f, indent=2)
    
    print(f"Recovery complete! Total rows: {len(all_rows)}")

if __name__ == '__main__':
    main()

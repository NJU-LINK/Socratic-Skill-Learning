#!/usr/bin/env python3
"""
SQLite WAL Recovery - Reference Implementation

Complete recovery pipeline for the db-wal-recovery skill family.
Handles encoding diagnosis, decoding, integrity verification,
multiple recovery methods, and flexible output formatting.
"""

import sqlite3
import json
import os
import sys
import struct
import base64
import glob
import shutil
import math
from collections import Counter

WAL_MAGIC_BIG = b'\x37\x7f\x06\x82'
WAL_MAGIC_LITTLE = b'\x37\x7f\x06\x83'
WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24


def wal_checksum(data, seed1=0, seed2=0, magic=None):
    """Compute WAL running checksum.
    
    CRITICAL: Computation byte order is OPPOSITE to magic number:
    - Magic 0x377f0682 (big-endian) -> little-endian word reads
    - Magic 0x377f0683 (little-endian) -> big-endian word reads
    """
    if magic == WAL_MAGIC_BIG:
        word_order = 'little'
    elif magic == WAL_MAGIC_LITTLE:
        word_order = 'big'
    else:
        word_order = 'little'
    
    s1, s2 = seed1, seed2
    for i in range(0, len(data) & ~7, 8):
        x = int.from_bytes(data[i:i+4], word_order)
        y = int.from_bytes(data[i+4:i+8], word_order)
        s1 = (s1 + x + s2) & 0xFFFFFFFF
        s2 = (s2 + y + s1) & 0xFFFFFFFF
    return s1, s2


def get_db_page_size(db_path):
    """Read page size from SQLite database header."""
    with open(db_path, 'rb') as f:
        f.read(16)  # Skip magic string
        page_size = int.from_bytes(f.read(2), 'big')
        return page_size if page_size != 1 else 65536


def detect_encoding(wal_data, db_path=None):
    """Systematically identify WAL encoding.
    
    Returns ((enc_type, enc_param), description) tuple.
    enc_type=None means already valid.
    """
    if len(wal_data) < 32:
        return (None, None), "file too short"
    
    magic = wal_data[:4]
    
    # Already valid?
    if magic in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
        return (None, None), "none (valid WAL)"
    
    # Layer 1: Try known transformations
    
    # Single-byte XOR
    for key in range(1, 256):
        decoded = bytes(b ^ key for b in wal_data[:32])
        if decoded[:4] in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
            version = int.from_bytes(decoded[4:8], 'big')
            page_size = int.from_bytes(decoded[8:12], 'big')
            if (version == 3007000 and 
                512 <= page_size <= 65536 and 
                (page_size & (page_size - 1)) == 0):
                return ('xor', key), f"XOR(0x{key:02x})"
    
    # Base64
    try:
        decoded = base64.b64decode(wal_data.strip())
        if len(decoded) >= 32 and decoded[:4] in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
            return ('base64', None), "base64"
    except Exception:
        pass
    
    # Bit inversion
    decoded = bytes(~b & 0xFF for b in wal_data)
    if decoded[:4] in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
        return ('invert', None), "bitwise inversion"
    
    # Byte swap
    if len(wal_data) % 2 == 0:
        swapped = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 2):
            swapped[i] = wal_data[i+1]
            swapped[i+1] = wal_data[i]
        if bytes(swapped[:4]) in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
            return ('swap', None), "byte swap"
    
    # Base64 + XOR
    try:
        b64d = base64.b64decode(wal_data.strip())
        for key in range(1, 256):
            decoded = bytes(b ^ key for b in b64d[:32])
            if decoded[:4] in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
                version = int.from_bytes(decoded[4:8], 'big')
                page_size = int.from_bytes(decoded[8:12], 'big')
                if (version == 3007000 and 
                    512 <= page_size <= 65536 and 
                    (page_size & (page_size - 1)) == 0):
                    return ('b64+xor', key), f"base64+XOR(0x{key:02x})"
    except Exception:
        pass
    
    # Layer 2: Known-plaintext repeating XOR key recovery
    # We know the WAL header plaintext: magic (4 bytes) + version (4 bytes) + page_size (4 bytes) + ...
    # This allows O(key_len) key derivation instead of O(256^key_len) brute force
    result = detect_repeating_xor_key(wal_data, db_path)
    if result:
        key, desc = result
        return ('xor_multi', key), desc
    
    # Layer 3: Pattern analysis for unknown encodings
    entropy = analyze_entropy(wal_data[:min(1000, len(wal_data))])
    return (None, None), f"unknown (entropy={entropy:.2f})"


def analyze_entropy(data):
    """Analyze byte entropy."""
    if not data:
        return 0.0
    counts = Counter(data)
    entropy = -sum((c/len(data)) * math.log2(c/len(data)) 
                   for c in counts.values())
    return entropy


def detect_repeating_xor_key(wal_data, db_path=None):
    """Derive repeating XOR key from known plaintext (WAL header).
    
    The WAL header has predictable bytes:
    - Bytes 0-3: magic (one of two known values)
    - Bytes 4-7: version (always 3007000 = 0x002DE218)
    - Bytes 8-11: page_size (power of 2, can read from base DB)
    - Bytes 12-15: checkpoint_seq (usually small, often 0)
    - Bytes 16-23: salt1, salt2 (random, but we can try common patterns)
    
    For a repeating key of length N, we derive key bytes from known plaintext.
    """
    if len(wal_data) < 32:
        return None
    
    # Known plaintext components
    version_be = b'\x00\x2d\xe2\x18'  # 3007000 in big-endian
    
    # Get page size from base DB if available
    db_page_size = None
    if db_path and os.path.exists(db_path):
        try:
            db_page_size = get_db_page_size(db_path)
        except:
            pass
    
    # Try both magic values
    for target_magic in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
        # Try key lengths from 2 to 32 (max header size)
        for key_len in range(2, min(33, len(wal_data) + 1)):
            # Derive key from known plaintext
            key = bytearray(key_len)
            
            # Bytes 0-3: magic
            for i in range(min(key_len, 4)):
                key[i] = wal_data[i] ^ target_magic[i]
            
            # Bytes 4-7: version
            for i in range(4, min(key_len, 8)):
                key[i] = wal_data[i] ^ version_be[i - 4]
            
            # Bytes 8-11: page_size
            if key_len > 8:
                # Try common page sizes
                page_sizes = [4096, 8192, 1024, 2048, 16384, 32768, 65536, 512]
                if db_page_size:
                    page_sizes.insert(0, db_page_size)
                
                found_valid = False
                for ps in page_sizes:
                    ps_bytes = ps.to_bytes(4, 'big')
                    trial_key = bytearray(key)
                    for i in range(8, min(key_len, 12)):
                        trial_key[i] = wal_data[i] ^ ps_bytes[i - 8]
                    
                    # Decode header and verify
                    decoded = bytes(wal_data[i] ^ trial_key[i % key_len] 
                                   for i in range(min(32, len(wal_data))))
                    if _valid_header_after_decode(decoded):
                        key = trial_key
                        found_valid = True
                        break
                
                if not found_valid:
                    continue
            
            # Verify full header
            decoded = bytes(wal_data[i] ^ key[i % key_len] 
                           for i in range(min(32, len(wal_data))))
            if _valid_header_after_decode(decoded):
                return bytes(key), f"repeating-XOR({key_len} bytes, key={key.hex()})"
    
    return None


def _valid_header_after_decode(decoded):
    """Check if decoded bytes form a valid WAL header."""
    if len(decoded) < 32:
        return False
    
    magic = decoded[:4]
    if magic not in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
        return False
    
    version = int.from_bytes(decoded[4:8], 'big')
    if version != 3007000:
        return False
    
    page_size = int.from_bytes(decoded[8:12], 'big')
    if not (512 <= page_size <= 65536 and (page_size & (page_size - 1)) == 0):
        return False
    
    return True


def decode_wal(wal_data, encoding_info):
    """Decode WAL based on detected encoding."""
    enc_type, enc_param = encoding_info
    
    if enc_type is None:
        return wal_data
    
    if enc_type == 'xor':
        return bytes(b ^ enc_param for b in wal_data)
    
    elif enc_type == 'base64':
        return base64.b64decode(wal_data.strip())
    
    elif enc_type == 'invert':
        return bytes(~b & 0xFF for b in wal_data)
    
    elif enc_type == 'swap':
        decoded = bytearray(len(wal_data))
        for i in range(0, len(wal_data), 2):
            decoded[i] = wal_data[i+1]
            decoded[i+1] = wal_data[i]
        return bytes(decoded)
    
    elif enc_type == 'b64+xor':
        b64d = base64.b64decode(wal_data.strip())
        return bytes(b ^ enc_param for b in b64d)
    
    elif enc_type == 'xor_multi':
        key = enc_param
        return bytes(wal_data[i] ^ key[i % len(key)] for i in range(len(wal_data)))
    
    else:
        raise ValueError(f"Unknown encoding type: {enc_type}")


def get_byte_order(magic):
    """Get byte order for all header fields based on magic number."""
    return 'big' if magic == WAL_MAGIC_BIG else 'little'


def verify_wal_integrity(wal_data):
    """Verify WAL header and frame checksums.
    
    Uses magic-aware byte order for ALL field reads.
    """
    if len(wal_data) < WAL_HEADER_SIZE:
        return False, "too short"
    
    magic = wal_data[:4]
    bo = get_byte_order(magic)  # Byte order for ALL fields
    
    # Header checksum
    calc_cs1, calc_cs2 = wal_checksum(wal_data[:24], magic=magic)
    stored_cs1 = int.from_bytes(wal_data[24:28], bo)
    stored_cs2 = int.from_bytes(wal_data[28:32], bo)
    
    if calc_cs1 != stored_cs1 or calc_cs2 != stored_cs2:
        return False, "header checksum mismatch"
    
    # Frame checksums
    page_size = int.from_bytes(wal_data[8:12], bo)  # Magic-aware
    frame_size = FRAME_HEADER_SIZE + page_size
    salt1 = int.from_bytes(wal_data[16:20], bo)  # Magic-aware
    salt2 = int.from_bytes(wal_data[20:24], bo)  # Magic-aware
    
    offset = WAL_HEADER_SIZE
    frame_num = 0
    rcs1, rcs2 = calc_cs1, calc_cs2
    
    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset + FRAME_HEADER_SIZE]
        pd = wal_data[offset + FRAME_HEADER_SIZE:offset + frame_size]
        
        if int.from_bytes(fh[8:12], bo) != salt1:  # Magic-aware
            return False, f"frame {frame_num} salt1 mismatch"
        if int.from_bytes(fh[12:16], bo) != salt2:  # Magic-aware
            return False, f"frame {frame_num} salt2 mismatch"
        
        cs_data = fh[:8] + pd
        rcs1, rcs2 = wal_checksum(cs_data, rcs1, rcs2, magic=magic)
        
        if rcs1 != int.from_bytes(fh[16:20], bo):  # Magic-aware
            return False, f"frame {frame_num} checksum1 mismatch"
        if rcs2 != int.from_bytes(fh[20:24], bo):  # Magic-aware
            return False, f"frame {frame_num} checksum2 mismatch"
        
        offset += frame_size
        frame_num += 1
    
    return True, f"valid, {frame_num} frames"


def repair_wal_header(wal_data, db_path=None):
    """Attempt to repair damaged WAL header fields."""
    data = bytearray(wal_data)
    
    if data[:4] not in (WAL_MAGIC_BIG, WAL_MAGIC_LITTLE):
        data[:4] = WAL_MAGIC_BIG
    
    format_version = int.from_bytes(data[4:8], 'big')
    if format_version != 3007000:
        struct.pack_into('>I', data, 4, 3007000)
    
    page_size = int.from_bytes(data[8:12], 'big')
    if page_size < 512 or page_size > 65536 or (page_size & (page_size - 1)) != 0:
        if db_path and os.path.exists(db_path):
            page_size = get_db_page_size(db_path)
        else:
            page_size = 4096
        struct.pack_into('>I', data, 8, page_size)
    
    magic = bytes(data[:4])
    cs1, cs2 = wal_checksum(bytes(data[:24]), magic=magic)
    if magic == WAL_MAGIC_BIG:
        struct.pack_into('>I', data, 24, cs1)
        struct.pack_into('>I', data, 28, cs2)
    else:
        struct.pack_into('<I', data, 24, cs1)
        struct.pack_into('<I', data, 28, cs2)
    
    return bytes(data)


def parse_wal_frames(wal_data):
    """Parse WAL frames with magic-aware byte order."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = FRAME_HEADER_SIZE + page_size
    
    frames = []
    offset = WAL_HEADER_SIZE
    
    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset + FRAME_HEADER_SIZE]
        pd = wal_data[offset + FRAME_HEADER_SIZE:offset + frame_size]
        
        page_num = int.from_bytes(fh[0:4], bo)
        db_size = int.from_bytes(fh[4:8], bo)
        
        frames.append({
            'page_number': page_num,
            'page_data': pd,
            'is_commit': db_size > 0,
            'db_size_after': db_size,
            'checksum_valid': True  # Default; override in parse_and_validate_frames
        })
        
        offset += frame_size
    
    return frames


def parse_and_validate_frames(wal_data):
    """Parse WAL frames and validate each frame's checksum independently."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = FRAME_HEADER_SIZE + page_size
    salt1 = int.from_bytes(wal_data[16:20], bo)
    salt2 = int.from_bytes(wal_data[20:24], bo)
    
    # Compute header checksum as starting point
    calc_cs1, calc_cs2 = wal_checksum(wal_data[:24], magic=magic)
    
    frames = []
    offset = WAL_HEADER_SIZE
    frame_num = 0
    rcs1, rcs2 = calc_cs1, calc_cs2
    
    while offset + frame_size <= len(wal_data):
        fh = wal_data[offset:offset + FRAME_HEADER_SIZE]
        pd = wal_data[offset + FRAME_HEADER_SIZE:offset + frame_size]
        
        page_num = int.from_bytes(fh[0:4], bo)
        db_size = int.from_bytes(fh[4:8], bo)
        
        # Validate this frame's checksum
        frame_salt1 = int.from_bytes(fh[8:12], bo)
        frame_salt2 = int.from_bytes(fh[12:16], bo)
        
        salt_ok = (frame_salt1 == salt1 and frame_salt2 == salt2)
        
        cs_data = fh[:8] + pd
        rcs1, rcs2 = wal_checksum(cs_data, rcs1, rcs2, magic=magic)
        
        stored_cs1 = int.from_bytes(fh[16:20], bo)
        stored_cs2 = int.from_bytes(fh[20:24], bo)
        cs_ok = (rcs1 == stored_cs1 and rcs2 == stored_cs2)
        
        frames.append({
            'page_number': page_num,
            'page_data': pd,
            'is_commit': db_size > 0,
            'db_size_after': db_size,
            'checksum_valid': salt_ok and cs_ok,
            'frame_index': frame_num
        })
        
        offset += frame_size
        frame_num += 1
    
    return frames


def apply_valid_frames(db_path, valid_frames, wal_data):
    """Apply only validated frames to database file."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)
    page_size = int.from_bytes(wal_data[8:12], bo)
    
    db_data = bytearray(open(db_path, 'rb').read())
    
    for frame in valid_frames:
        page_num = frame['page_number']
        page_data = frame['page_data']
        
        needed = page_num * page_size
        if needed > len(db_data):
            db_data.extend(b'\x00' * (needed - len(db_data)))
        
        page_offset = (page_num - 1) * page_size
        db_data[page_offset:page_offset + page_size] = page_data
    
    open(db_path, 'wb').write(bytes(db_data))
    
    # Remove WAL artifacts
    for suffix in ['-wal', '-shm']:
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)


def apply_frames_manually(db_path, wal_data):
    """Apply WAL frames directly to database file with magic-aware byte order."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = FRAME_HEADER_SIZE + page_size
    
    db_data = bytearray(open(db_path, 'rb').read())
    
    offset = WAL_HEADER_SIZE
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], bo)
        page_data = wal_data[offset+FRAME_HEADER_SIZE:offset+frame_size]
        
        needed = page_num * page_size
        if needed > len(db_data):
            db_data.extend(b'\x00' * (needed - len(db_data)))
        
        page_offset = (page_num - 1) * page_size
        db_data[page_offset:page_offset + page_size] = page_data
        offset += frame_size
    
    open(db_path, 'wb').write(bytes(db_data))
    for suffix in ['-wal', '-shm']:
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)


def reconstruct_from_frames(wal_data):
    """Reconstruct database from WAL frames when base DB is missing."""
    magic = wal_data[:4]
    bo = get_byte_order(magic)
    
    page_size = int.from_bytes(wal_data[8:12], bo)
    frame_size = FRAME_HEADER_SIZE + page_size
    
    pages = {}
    offset = WAL_HEADER_SIZE
    while offset + frame_size <= len(wal_data):
        page_num = int.from_bytes(wal_data[offset:offset+4], bo)
        page_data = wal_data[offset+FRAME_HEADER_SIZE:offset+frame_size]
        pages[page_num] = page_data
        offset += frame_size
    
    if not pages or 1 not in pages:
        return None
    
    max_page = max(pages.keys())
    db_data = bytearray(max_page * page_size)
    
    for page_num, page_data in pages.items():
        offset = (page_num - 1) * page_size
        db_data[offset:offset+page_size] = page_data
    
    if not db_data[:16].startswith(b'SQLite format 3\x00'):
        return None
    
    return bytes(db_data)


def find_database(directory='/app'):
    """Find SQLite database file."""
    for f in sorted(glob.glob(os.path.join(directory, '*.db'))):
        if f.endswith(('-wal', '-shm')):
            continue
        try:
            with open(f, 'rb') as fh:
                if fh.read(16).startswith(b'SQLite format 3'):
                    return f
        except Exception:
            continue
    return None


def find_wal(db_path, backup_dir=None):
    """Find WAL file for database, checking backup if needed."""
    wal = db_path + '-wal'
    if os.path.exists(wal):
        return wal
    
    # Check backup
    if backup_dir:
        wal_backup = os.path.join(backup_dir, os.path.basename(db_path) + '-wal')
        if os.path.exists(wal_backup):
            shutil.copy2(wal_backup, wal)
            return wal
    
    # Check for standalone .wal files
    d = os.path.dirname(db_path)
    for f in os.listdir(d):
        if f.endswith('.wal') or (f.endswith('-wal') and not f.endswith('-shm')):
            return os.path.join(d, f)
    
    return None


def extract_all_data(conn):
    """Extract all data from all tables."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    
    all_data = {}
    for (table_name,) in tables:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        col_names = [col[1] for col in columns]
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        all_data[table_name] = {
            'columns': col_names,
            'rows': [dict(zip(col_names, row)) for row in rows]
        }
    
    return all_data


def main():
    app_dir = '/app'
    backup_dir = '/tmp/wal_recovery_backup'
    
    # Step 0: Find and preserve
    db_path = find_database(app_dir)
    if not db_path:
        print("ERROR: No SQLite database found", file=sys.stderr)
        sys.exit(1)
    
    print(f"Database: {db_path}")
    
    os.makedirs(backup_dir, exist_ok=True)
    for suffix in ['', '-wal', '-shm']:
        src = db_path + suffix
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(backup_dir, os.path.basename(src)))
            print(f"Backed up: {src}")
    
    for f in glob.glob(os.path.join(app_dir, '*.wal')):
        shutil.copy2(f, os.path.join(backup_dir, os.path.basename(f)))
        print(f"Backed up: {f}")
    
    # Step 1: Find WAL
    wal_path = find_wal(db_path, backup_dir)
    
    if wal_path is None:
        print("No WAL file found. Reading from base database only.")
        conn = sqlite3.connect(db_path)
        data = extract_all_data(conn)
        conn.close()
    else:
        print(f"WAL: {wal_path} ({os.path.getsize(wal_path)} bytes)")
        wal_data = open(wal_path, 'rb').read()
        
        # Step 2: Diagnose
        encoding_info, enc_desc = detect_encoding(wal_data, db_path)  # Pass db_path for known-plaintext recovery
        print(f"Encoding: {enc_desc}")
        
        if encoding_info[0] is None and enc_desc not in ("none (valid WAL)", "file too short"):
            print("ERROR: Cannot determine encoding", file=sys.stderr)
            sys.exit(1)
        
        # Step 3: Decode
        decoded_wal = decode_wal(wal_data, encoding_info)
        
        # Step 4: Verify integrity and drive recovery strategy
        valid, msg = verify_wal_integrity(decoded_wal)
        print(f"Integrity: {msg}")
        
        if valid:
            # ENCODING DAMAGE ONLY: decoded WAL is fully valid
            # → Write decoded WAL and let SQLite consume it directly
            print("Recovery path: SQLite auto-read (encoding damage only)")
            open(wal_path, 'wb').write(decoded_wal)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA wal_autocheckpoint=0")
            data = extract_all_data(conn)
            conn.close()
        else:
            # STRUCTURAL DAMAGE: some frames or header fields are corrupt
            print("Recovery path: Structural damage detected, attempting repair")
            
            # Try header repair first
            repaired = repair_wal_header(decoded_wal, db_path)
            valid2, msg2 = verify_wal_integrity(repaired)
            print(f"After header repair: {msg2}")
            
            if valid2:
                # Header repair fixed it → apply via SQLite
                print("Recovery path: SQLite auto-read (after header repair)")
                open(wal_path, 'wb').write(repaired)
                conn = sqlite3.connect(db_path)
                conn.execute("PRAGMA wal_autocheckpoint=0")
                data = extract_all_data(conn)
                conn.close()
            else:
                # Still corrupt → selective frame application
                print("Recovery path: Selective frame application (partial corruption)")
                frames = parse_and_validate_frames(repaired)
                valid_frames = [f for f in frames if f['checksum_valid']]
                print(f"Valid frames: {len(valid_frames)}/{len(frames)}")
                
                if not valid_frames:
                    print("ERROR: No valid frames found", file=sys.stderr)
                    sys.exit(1)
                
                apply_valid_frames(db_path, valid_frames, repaired)
                conn = sqlite3.connect(db_path)
                data = extract_all_data(conn)
                conn.close()
    
    # Step 5: Output
    if data:
        main_table = max(data.items(), key=lambda x: len(x[1]['rows']))
        tname = main_table[0]
        tdata = main_table[1]
        
        records = tdata['rows']
        cols = tdata['columns']
        
        sort_key = 'id' if 'id' in cols else cols[0]
        records.sort(key=lambda x: x.get(sort_key, 0))
        
        output = os.path.join(app_dir, 'recovered.json')
        with open(output, 'w') as f:
            json.dump(records, f, indent=2)
        
        print(f"Wrote {len(records)} records to {output}")
    else:
        print("No data found")


if __name__ == '__main__':
    main()

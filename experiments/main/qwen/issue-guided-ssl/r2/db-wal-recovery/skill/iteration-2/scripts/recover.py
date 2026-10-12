#!/usr/bin/env python3
"""
SQLite WAL Recovery Script
Diagnoses encoding, decodes WAL, fixes checksums, and extracts all records.
"""
import struct
import json
import sqlite3
import shutil
import os
import sys


def read_db_page_size(db_path):
    """Read page size from SQLite database header (offset 16-17)."""
    with open(db_path, 'rb') as f:
        f.seek(16)
        ps = struct.unpack('>H', f.read(2))[0]
        return ps if ps != 1 else 65536


def xor_decode(data, key):
    """XOR decode data with repeating key."""
    if len(key) == 1:
        k = key[0]
        return bytes(b ^ k for b in data)
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def wal_checksum(data, s1=0, s2=0, big_endian=True):
    """Compute WAL checksum over data (must be multiple of 8 bytes)."""
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        x = struct.unpack(fmt, data[i:i+4])[0]
        y = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + x + s2) % (1 << 32)
        s2 = (s2 + y + s1) % (1 << 32)
    return s1, s2


def detect_encoding_type(raw_wal):
    """
    Detect encoding type before attempting XOR derivation.
    Returns (decoded_wal, encoding_type) or (None, None).
    """
    import base64
    
    # Check if already valid WAL
    magic = struct.unpack('>I', raw_wal[0:4])[0]
    if magic in (0x377F0682, 0x377F0683):
        return raw_wal, 'none'
    
    # Try base64 decode
    try:
        decoded = base64.b64decode(raw_wal)
        magic = struct.unpack('>I', decoded[0:4])[0]
        if magic in (0x377F0682, 0x377F0683):
            return decoded, 'base64'
    except:
        pass
    
    # Try byte swapping (swap pairs)
    swapped = bytearray(len(raw_wal))
    for i in range(0, len(raw_wal) - 1, 2):
        swapped[i] = raw_wal[i + 1]
        swapped[i + 1] = raw_wal[i]
    magic = struct.unpack('>I', swapped[0:4])[0]
    if magic in (0x377F0682, 0x377F0683):
        return bytes(swapped), 'byte_swap'
    
    # Try bitwise NOT
    inverted = bytes(b ^ 0xFF for b in raw_wal)
    magic = struct.unpack('>I', inverted[0:4])[0]
    if magic in (0x377F0682, 0x377F0683):
        return inverted, 'bitwise_not'
    
    return None, None


def derive_xor_key(raw_wal, expected_page_size):
    """
    Derive XOR key using known-plaintext attack on magic and page_size fields.
    Returns (key_bytes, decoded_info) or (None, None) if derivation fails.
    """
    # Try both magic values
    for magic_val in [0x377F0682, 0x377F0683]:
        magic_bytes = struct.pack('>I', magic_val)
        ps_bytes = struct.pack('>I', expected_page_size)
        
        # Try different key lengths
        for key_len in [1, 2, 4, 8]:
            key = [None] * key_len
            
            # Derive from magic (bytes 0-3)
            for i in range(4):
                pos = i % key_len
                derived = raw_wal[i] ^ magic_bytes[i]
                if key[pos] is None:
                    key[pos] = derived
                elif key[pos] != derived:
                    break
            else:
                # Derive from page_size (bytes 8-11)
                for i in range(4):
                    pos = (8 + i) % key_len
                    derived = raw_wal[8 + i] ^ ps_bytes[i]
                    if key[pos] is None:
                        key[pos] = derived
                    elif key[pos] != derived:
                        break
                else:
                    # All positions filled consistently
                    if None in key:
                        # Fill unknown positions with common values
                        key = [k if k is not None else 0x42 for k in key]
                    
                    key_bytes = bytes(key)
                    decoded = xor_decode(raw_wal[:32], key_bytes)
                    
                    # Verify magic
                    decoded_magic = struct.unpack('>I', decoded[0:4])[0]
                    if decoded_magic != magic_val:
                        continue
                    
                    # Verify page size
                    decoded_ps = struct.unpack('>I', decoded[8:12])[0]
                    if decoded_ps != expected_page_size:
                        continue
                    
                    # Check version (should be 3007000)
                    decoded_ver = struct.unpack('>I', decoded[4:8])[0]
                    if decoded_ver != 3007000:
                        # Version mismatch, but might still work
                        pass
                    
                    return key_bytes, {
                        'magic': magic_val,
                        'big_endian': (magic_val == 0x377F0682)
                    }
    
    # Fallback: try common single-byte keys
    for k in [0x42, 0xFF, 0x00]:
        key_bytes = bytes([k])
        decoded = xor_decode(raw_wal[:32], key_bytes)
        magic = struct.unpack('>I', decoded[0:4])[0]
        if magic in (0x377F0682, 0x377F0683):
            ps = struct.unpack('>I', decoded[8:12])[0]
            if ps == expected_page_size:
                return key_bytes, {
                    'magic': magic,
                    'big_endian': (magic == 0x377F0682)
                }
    
    return None, None


def parse_wal_frames(decoded_wal, page_size):
    """Parse WAL header and frames from decoded WAL data."""
    if len(decoded_wal) < 32:
        return None
    
    magic = struct.unpack('>I', decoded_wal[0:4])[0]
    version = struct.unpack('>I', decoded_wal[4:8])[0]
    ps = struct.unpack('>I', decoded_wal[8:12])[0]
    ckpt_seq = struct.unpack('>I', decoded_wal[12:16])[0]
    salt1 = struct.unpack('>I', decoded_wal[16:20])[0]
    salt2 = struct.unpack('>I', decoded_wal[20:24])[0]
    
    if ps != page_size:
        return None
    
    big_endian = (magic == 0x377F0682)
    
    frames = []
    frame_size = 24 + page_size
    offset = 32
    
    while offset + frame_size <= len(decoded_wal):
        frame_hdr = decoded_wal[offset:offset+24]
        page_num = struct.unpack('>I', frame_hdr[0:4])[0]
        db_size = struct.unpack('>I', frame_hdr[4:8])[0]
        frame_salt1 = struct.unpack('>I', frame_hdr[8:12])[0]
        frame_salt2 = struct.unpack('>I', frame_hdr[12:16])[0]
        page_data = decoded_wal[offset+24:offset+frame_size]
        
        frames.append({
            'page_num': page_num,
            'db_size': db_size,
            'salt1': frame_salt1,
            'salt2': frame_salt2,
            'page_data': page_data,
            'offset': offset
        })
        
        offset += frame_size
    
    return {
        'magic': magic,
        'version': version,
        'page_size': ps,
        'ckpt_seq': ckpt_seq,
        'salt1': salt1,
        'salt2': salt2,
        'big_endian': big_endian,
        'frames': frames
    }


def recompute_checksums(wal_info):
    """Recompute all WAL checksums (header and frames)."""
    big = wal_info['big_endian']
    fmt = '>I' if big else '<I'
    
    # Reconstruct header with zeroed checksum fields
    header = bytearray(32)
    struct.pack_into('>I', header, 0, wal_info['magic'])
    struct.pack_into('>I', header, 4, wal_info['version'])
    struct.pack_into('>I', header, 8, wal_info['page_size'])
    struct.pack_into('>I', header, 12, wal_info['ckpt_seq'])
    struct.pack_into('>I', header, 16, wal_info['salt1'])
    struct.pack_into('>I', header, 20, wal_info['salt2'])
    # Checksum fields (24-31) are zeroed
    
    # Compute header checksum
    s1, s2 = wal_checksum(bytes(header), 0, 0, big)
    struct.pack_into(fmt, header, 24, s1)
    struct.pack_into(fmt, header, 28, s2)
    
    wal_info['header'] = bytes(header)
    
    # Recompute frame checksums
    for frame in wal_info['frames']:
        frame_hdr = bytearray(24)
        struct.pack_into('>I', frame_hdr, 0, frame['page_num'])
        struct.pack_into('>I', frame_hdr, 4, frame['db_size'])
        struct.pack_into('>I', frame_hdr, 8, wal_info['salt1'])
        struct.pack_into('>I', frame_hdr, 12, wal_info['salt2'])
        # Checksum fields (16-23) are zeroed
        
        # Compute frame checksum over header + page data
        cs_data = bytes(frame_hdr) + frame['page_data']
        fs1, fs2 = wal_checksum(cs_data, wal_info['salt1'], wal_info['salt2'], big)
        struct.pack_into(fmt, frame_hdr, 16, fs1)
        struct.pack_into(fmt, frame_hdr, 20, fs2)
        
        frame['header'] = bytes(frame_hdr)
    
    return wal_info


def write_fixed_wal(wal_info, path):
    """Write complete fixed WAL file."""
    with open(path, 'wb') as f:
        f.write(wal_info['header'])
        for frame in wal_info['frames']:
            f.write(frame['header'])
            f.write(frame['page_data'])


def apply_pages_directly(db_path, wal_info, out_path):
    """Apply WAL frames directly to database copy (fallback method)."""
    shutil.copy2(db_path, out_path)
    
    page_size = wal_info['page_size']
    commit_db_size = 0
    
    with open(out_path, 'r+b') as f:
        for frame in wal_info['frames']:
            pg = frame['page_num']
            if pg < 1:
                continue
            
            # Write page data at correct offset
            offset = (pg - 1) * page_size
            f.seek(offset)
            f.write(frame['page_data'])
            
            # Track commit frame
            if frame['db_size'] > 0:
                commit_db_size = frame['db_size']
        
        # Update database header if we have a commit frame
        if commit_db_size > 0:
            # Update page count (offset 28-31)
            f.seek(28)
            f.write(struct.pack('>I', commit_db_size))
            
            # Increment change counter (offset 24-27)
            f.seek(24)
            old_counter = struct.unpack('>I', f.read(4))[0]
            f.seek(24)
            f.write(struct.pack('>I', old_counter + 1))


def extract_records(db_path):
    """Extract all records from all user tables as list of dicts."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    
    if not tables:
        conn.close()
        return []
    
    records = []
    for table in tables:
        # Get column info
        col_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = [c[1] for c in col_info]  # Column names are in position 1
        
        # Get all rows
        cursor = conn.execute(f"SELECT * FROM {table}")
        for row in cursor:
            rec = {}
            for i, (col, val) in enumerate(zip(cols, row)):
                # Handle binary data
                if isinstance(val, (bytes, bytearray)):
                    val = val.hex() if len(val) > 8 else int.from_bytes(val, 'little', signed=True)
                rec[col] = val
            records.append(rec)
    
    conn.close()
    return records


def reconstruct_from_wal_only(wal_info, out_path):
    """Reconstruct a database from WAL frames when no base DB exists."""
    page_size = wal_info['page_size']
    max_page = max(f['page_num'] for f in wal_info['frames'])
    
    # Create empty database file with correct size
    with open(out_path, 'wb') as f:
        f.write(b'\x00' * (max_page * page_size))
    
    # Apply all pages
    with open(out_path, 'r+b') as f:
        for frame in wal_info['frames']:
            pg = frame['page_num']
            if pg < 1:
                continue
            offset = (pg - 1) * page_size
            f.seek(offset)
            f.write(frame['page_data'])


def recover(db_path, wal_path, output_path, min_records=1):
    """Main recovery function.
    
    Args:
        db_path: Path to SQLite database (may not exist for WAL-only recovery)
        wal_path: Path to WAL file (possibly encoded/corrupted)
        output_path: Path to write recovered JSON
        min_records: Minimum expected records for success validation
    """
    print(f"Recovering from {db_path} + {wal_path}")
    
    # Read WAL
    with open(wal_path, 'rb') as f:
        raw_wal = f.read()
    
    print(f"WAL size: {len(raw_wal)} bytes")
    
    # Step 1: Detect encoding type
    decoded_wal, encoding_type = detect_encoding_type(raw_wal)
    
    if encoding_type == 'none':
        print("WAL appears to be valid (correct magic)")
        key = b'\x00'
    elif encoding_type in ('base64', 'byte_swap', 'bitwise_not'):
        print(f"Detected encoding: {encoding_type}")
        key = b'\x00'  # Already decoded
    else:
        # Step 2: Determine page size
        if os.path.exists(db_path):
            expected_ps = read_db_page_size(db_path)
            print(f"Expected page size from DB: {expected_ps}")
        else:
            # Try common page sizes
            print("Base DB not found, trying common page sizes...")
            expected_ps = None
            for ps in [4096, 8192, 16384, 32768, 1024, 512]:
                key_test, key_info = derive_xor_key(raw_wal, ps)
                if key_test:
                    expected_ps = ps
                    print(f"Found valid page size: {ps}")
                    break
            if not expected_ps:
                raise RuntimeError("Could not determine page size")
        
        # Step 3: Derive XOR key
        print(f"WAL magic invalid, diagnosing XOR encoding...")
        key, key_info = derive_xor_key(raw_wal, expected_ps)
        if not key:
            raise RuntimeError("Could not derive XOR key from WAL")
        
        print(f"Derived XOR key: {key.hex()}")
        decoded_wal = xor_decode(raw_wal, key)
    
    # Determine page size for parsing
    if os.path.exists(db_path):
        expected_ps = read_db_page_size(db_path)
    else:
        expected_ps = struct.unpack('>I', decoded_wal[8:12])[0]
    
    # Parse WAL structure
    wal_info = parse_wal_frames(decoded_wal, expected_ps)
    if not wal_info:
        raise RuntimeError("Failed to parse WAL frames")
    
    print(f"Parsed {len(wal_info['frames'])} frames")
    
    # Recompute checksums (for potential Approach B)
    wal_info = recompute_checksums(wal_info)
    
    # Save original DB for safety (if it exists)
    if os.path.exists(db_path):
        original_db_backup = db_path + '.original_backup'
        shutil.copy2(db_path, original_db_backup)
    else:
        original_db_backup = None
    
    # Try Approach A (RECOMMENDED): Direct page application
    print("\nAttempting Approach A: Direct page application...")
    
    if os.path.exists(db_path):
        fixed_db = db_path + '.fixed'
        apply_pages_directly(db_path, wal_info, fixed_db)
        
        approach_a_success = False
        try:
            records = extract_records(fixed_db)
            if len(records) >= min_records:
                print(f"✓ Approach A successful: {len(records)} records")
                approach_a_success = True
                shutil.move(fixed_db, db_path)
            else:
                raise Exception(f"Only {len(records)} records (expected at least {min_records})")
        except Exception as e:
            print(f"✗ Approach A failed: {e}")
    else:
        # No base DB - reconstruct from WAL pages only
        print("No base DB, reconstructing from WAL pages...")
        fixed_db = db_path + '.reconstructed'
        reconstruct_from_wal_only(wal_info, fixed_db)
        
        approach_a_success = False
        try:
            records = extract_records(fixed_db)
            if len(records) >= min_records:
                print(f"✓ Reconstruction successful: {len(records)} records")
                approach_a_success = True
                shutil.move(fixed_db, db_path)
            else:
                raise Exception(f"Only {len(records)} records")
        except Exception as e:
            print(f"✗ Reconstruction failed: {e}")
    
    if not approach_a_success:
        if original_db_backup:
            shutil.copy2(original_db_backup, db_path)
        
        print("\nAttempting Approach B: Fix WAL for SQLite consumption...")
        write_fixed_wal(wal_info, wal_path)
        
        try:
            records = extract_records(db_path)
            if len(records) >= min_records:
                print(f"✓ Approach B successful: {len(records)} records")
            else:
                raise Exception(f"Only {len(records)} records")
        except Exception as e2:
            raise RuntimeError(f"Both recovery approaches failed: {e2}")
    
    # Clean up backup
    if original_db_backup and os.path.exists(original_db_backup):
        os.remove(original_db_backup)
    
    # Sort records by id
    records.sort(key=lambda r: r.get('id', 0))
    
    # Write JSON output
    with open(output_path, 'w') as f:
        json.dump(records, f, indent=2)
    
    print(f"\n✓ Recovered {len(records)} records → {output_path}")
    return records


if __name__ == '__main__':
    if len(sys.argv) >= 4:
        db_path = sys.argv[1]
        wal_path = sys.argv[2]
        output_path = sys.argv[3]
        min_records = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    else:
        # Default paths for v01 task
        db_path = '/app/main.db'
        wal_path = '/app/main.db-wal'
        output_path = '/app/recovered.json'
        min_records = 1
    
    recover(db_path, wal_path, output_path, min_records)

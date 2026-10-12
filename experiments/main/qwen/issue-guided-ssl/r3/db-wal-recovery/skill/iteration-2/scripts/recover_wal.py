#!/usr/bin/env python3
"""
SQLite WAL Recovery Script

Implements the critical "copy → diagnose → decode → open" workflow for recovering
data from encoded/corrupted SQLite WAL files.

Usage:
    python recover_wal.py <db_path> <wal_path> <output_json>

This script:
1. Copies original files to backups (preserves encoded data)
2. Diagnoses the encoding method (XOR, inversion, base64, byte-swap, etc.)
3. Decodes the WAL file
4. Validates frame checksums
5. Opens the database with the decoded WAL (or manually applies frames)
6. Extracts all data to JSON
"""

import struct
import shutil
import sqlite3
import json
import os
import sys
import base64


# ──────────────────────────────────────────────
# WAL Checksum Algorithm
# ──────────────────────────────────────────────

def wal_checksum(data, s1=0, s2=0, big_endian=True):
    """
    Compute WAL checksum over data (must be multiple of 8 bytes).
    
    The checksum byte order must match the platform/magic combination.
    Try both byte orders if unsure.
    
    Args:
        data: bytes to checksum (must be multiple of 8 bytes)
        s1, s2: initial checksum values (from previous frame or header)
        big_endian: if True, read data as big-endian u32; if False, little-endian
    
    Returns:
        (s1, s2) tuple of checksum values
    """
    fmt = '>I' if big_endian else '<I'
    for i in range(0, len(data), 8):
        x0 = struct.unpack(fmt, data[i:i+4])[0]
        x1 = struct.unpack(fmt, data[i+4:i+8])[0]
        s1 = (s1 + x0 + s2) & 0xFFFFFFFF
        s2 = (s2 + s1 + x1) & 0xFFFFFFFF
    return s1, s2


def detect_checksum_byteorder(decoded_wal):
    """
    Detect which byte order is used for WAL checksums.
    Returns True for big-endian, False for little-endian.
    Raises ValueError if neither works.
    """
    header_data = decoded_wal[0:24]
    stored_s1 = struct.unpack('>I', decoded_wal[24:28])[0]
    stored_s2 = struct.unpack('>I', decoded_wal[28:32])[0]
    
    for big_endian in [True, False]:
        s1, s2 = wal_checksum(header_data, big_endian=big_endian)
        if s1 == stored_s1 and s2 == stored_s2:
            return big_endian
    
    raise ValueError("Cannot determine checksum byte order - neither BE nor LE validates header")


# ──────────────────────────────────────────────
# Encoding Diagnosis
# ──────────────────────────────────────────────

def diagnose_xor_key(wal_data):
    """Diagnose single-byte XOR encoding by checking WAL magic and version."""
    WAL_MAGICS = [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]
    
    for key in range(1, 256):  # Skip key=0 (no encoding)
        decoded_magic = bytes([wal_data[i] ^ key for i in range(4)])
        if decoded_magic not in WAL_MAGICS:
            continue
        
        # Verify version field
        version_bytes = bytes([wal_data[i] ^ key for i in range(4, 8)])
        version = struct.unpack('>I', version_bytes)[0]
        if version == 3007000:
            # Additional check: page size should be a power of 2 (512-65536)
            ps_bytes = bytes([wal_data[i] ^ key for i in range(8, 12)])
            page_size = struct.unpack('>I', ps_bytes)[0]
            if page_size in [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]:
                return key
    
    return None


def diagnose_inversion(wal_data):
    """Diagnose bitwise inversion encoding."""
    WAL_MAGICS = [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]
    
    inverted = bytes([~b & 0xFF for b in wal_data[:4]])
    if inverted in WAL_MAGICS:
        version_bytes = bytes([~wal_data[i] & 0xFF for i in range(4, 8)])
        version = struct.unpack('>I', version_bytes)[0]
        if version == 3007000:
            return True
    return False


def diagnose_base64(wal_data):
    """Diagnose base64 encoding."""
    try:
        decoded = base64.b64decode(wal_data[:200])
        if decoded[:4] in [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]:
            version = struct.unpack('>I', decoded[4:8])[0]
            if version == 3007000:
                return True
    except Exception:
        pass
    return False


def diagnose_byte_swap(wal_data):
    """
    Diagnose byte-swap encoding.
    Try various swap patterns:
    - Reverse all bytes
    - Swap adjacent byte pairs
    - Swap within 4-byte words (reverse each u32)
    """
    WAL_MAGICS = [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]
    
    # Try reversing each 4-byte word
    swapped = bytearray()
    for i in range(0, min(len(wal_data), 32), 4):
        swapped.extend(wal_data[i:i+4][::-1])
    if swapped[:4] in WAL_MAGICS:
        version = struct.unpack('>I', swapped[4:8])[0]
        if version == 3007000:
            return 'u32_reverse'
    
    # Try swapping adjacent bytes
    swapped = bytearray()
    for i in range(0, min(len(wal_data), 32), 2):
        swapped.extend(wal_data[i:i+2][::-1])
    if swapped[:4] in WAL_MAGICS:
        version = struct.unpack('>I', swapped[4:8])[0]
        if version == 3007000:
            return 'pair_swap'
    
    return None


def decode_wal(wal_path):
    """
    Diagnose and decode the WAL file.
    Returns the decoded WAL data as a bytearray.
    """
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    
    print(f"WAL file size: {len(wal_data)} bytes")
    
    # Check if already valid
    WAL_MAGICS = [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]
    if wal_data[:4] in WAL_MAGICS:
        version = struct.unpack('>I', wal_data[4:8])[0]
        if version == 3007000:
            print("WAL file appears to be valid (no encoding detected)")
            return bytearray(wal_data)
    
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
        decoded = bytearray(base64.b64decode(wal_data))
        return decoded
    
    # Try byte-swap encoding
    swap_type = diagnose_byte_swap(wal_data)
    if swap_type == 'u32_reverse':
        print("Detected byte-swap encoding (u32 reverse)")
        decoded = bytearray()
        for i in range(0, len(wal_data), 4):
            decoded.extend(wal_data[i:i+4][::-1])
        return decoded
    elif swap_type == 'pair_swap':
        print("Detected byte-swap encoding (pair swap)")
        decoded = bytearray()
        for i in range(0, len(wal_data), 2):
            decoded.extend(wal_data[i:i+2][::-1])
        return decoded
    
    raise ValueError("Could not diagnose WAL encoding method")


# ──────────────────────────────────────────────
# WAL Structure Verification
# ──────────────────────────────────────────────

def verify_decoded_wal(decoded_wal):
    """Verify the decoded WAL structure and validate checksums."""
    WAL_MAGICS = [bytes.fromhex('377f0682'), bytes.fromhex('377f0683')]
    
    # Check magic
    magic = decoded_wal[:4]
    if magic not in WAL_MAGICS:
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
    remainder = (len(decoded_wal) - 32) % frame_size
    frame_count = (len(decoded_wal) - 32) // frame_size
    print(f"Frame count: {frame_count}")
    
    if remainder != 0:
        print(f"WARNING: {remainder} trailing bytes after last frame")
    
    # Detect checksum byte order
    try:
        cksum_be = detect_checksum_byteorder(decoded_wal)
        print(f"Checksum byte order: {'big-endian' if cksum_be else 'little-endian'}")
    except ValueError:
        print("WARNING: Header checksum does not validate with either byte order")
        print("  This may indicate structural damage beyond encoding")
        cksum_be = True  # Default to big-endian
    
    # Validate frame checksums
    hdr_s1 = struct.unpack('>I', decoded_wal[24:28])[0]
    hdr_s2 = struct.unpack('>I', decoded_wal[28:32])[0]
    salt1 = decoded_wal[16:24]
    
    valid_frames = 0
    for i in range(frame_count):
        offset = 32 + i * frame_size
        frame_hdr = decoded_wal[offset:offset+24]
        page_data = decoded_wal[offset+24:offset+24+page_size]
        
        page_num = struct.unpack('>I', frame_hdr[0:4])[0]
        frame_salt = frame_hdr[8:16]
        frame_s1 = struct.unpack('>I', frame_hdr[16:20])[0]
        frame_s2 = struct.unpack('>I', frame_hdr[20:24])[0]
        
        # Check salt match
        if frame_salt != salt1:
            print(f"  Frame {i}: SALT MISMATCH (page {page_num})")
            continue
        
        # Compute checksum
        if i == 0:
            prev_s1, prev_s2 = hdr_s1, hdr_s2
        else:
            prev_offset = 32 + (i-1) * frame_size
            prev_hdr = decoded_wal[prev_offset:prev_offset+24]
            prev_s1 = struct.unpack('>I', prev_hdr[16:20])[0]
            prev_s2 = struct.unpack('>I', prev_hdr[20:24])[0]
        
        check_data = frame_hdr[0:8] + page_data
        calc_s1, calc_s2 = wal_checksum(check_data, prev_s1, prev_s2, cksum_be)
        
        if calc_s1 == frame_s1 and calc_s2 == frame_s2:
            valid_frames += 1
        else:
            print(f"  Frame {i}: CHECKSUM MISMATCH (page {page_num})")
    
    print(f"Valid frames: {valid_frames}/{frame_count}")
    
    return page_size, frame_count, cksum_be, valid_frames


# ──────────────────────────────────────────────
# Data Extraction
# ──────────────────────────────────────────────

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


def manual_apply_frames(db_path, decoded_wal, page_size, frame_count, cksum_be, output_path):
    """
    Manually apply WAL frames to database pages when SQLite cannot consume the WAL.
    This is the fallback for deeper recovery scenarios.
    """
    print("\n[Manual Frame Application] SQLite cannot consume WAL directly")
    
    # Read database pages
    with open(db_path, 'rb') as f:
        db_data = f.read()
    
    db_page_size = struct.unpack('>H', db_data[16:18])[0]
    if db_page_size == 1:
        db_page_size = 65536
    
    if db_page_size != page_size:
        print(f"WARNING: DB page size ({db_page_size}) != WAL page size ({page_size})")
    
    # Build page map
    db_pages = {}
    num_db_pages = len(db_data) // db_page_size
    for p in range(1, num_db_pages + 1):
        offset = (p - 1) * db_page_size
        db_pages[p] = bytearray(db_data[offset:offset + db_page_size])
    
    # Parse and apply WAL frames
    hdr_s1 = struct.unpack('>I', decoded_wal[24:28])[0]
    hdr_s2 = struct.unpack('>I', decoded_wal[28:32])[0]
    salt1 = decoded_wal[16:24]
    frame_size = 24 + page_size
    
    applied = 0
    for i in range(frame_count):
        offset = 32 + i * frame_size
        frame_hdr = decoded_wal[offset:offset+24]
        page_data = decoded_wal[offset+24:offset+24+page_size]
        
        page_num = struct.unpack('>I', frame_hdr[0:4])[0]
        frame_salt = frame_hdr[8:16]
        frame_s1 = struct.unpack('>I', frame_hdr[16:20])[0]
        frame_s2 = struct.unpack('>I', frame_hdr[20:24])[0]
        
        # Validate salt
        if frame_salt != salt1:
            print(f"  Skipping frame {i}: salt mismatch")
            continue
        
        # Validate checksum
        if i == 0:
            prev_s1, prev_s2 = hdr_s1, hdr_s2
        else:
            prev_offset = 32 + (i-1) * frame_size
            prev_hdr = decoded_wal[prev_offset:prev_offset+24]
            prev_s1 = struct.unpack('>I', prev_hdr[16:20])[0]
            prev_s2 = struct.unpack('>I', prev_hdr[20:24])[0]
        
        check_data = frame_hdr[0:8] + page_data
        calc_s1, calc_s2 = wal_checksum(check_data, prev_s1, prev_s2, cksum_be)
        
        if calc_s1 != frame_s1 or calc_s2 != frame_s2:
            print(f"  Skipping frame {i}: checksum mismatch (page {page_num})")
            continue
        
        # Apply frame
        db_pages[page_num] = bytearray(page_data)
        applied += 1
        print(f"  Applied frame {i}: page {page_num}")
    
    print(f"Applied {applied}/{frame_count} frames")
    
    # Write reconstructed database
    working_db = db_path + '.working'
    with open(working_db, 'wb') as f:
        max_page = max(db_pages.keys())
        for p in range(1, max_page + 1):
            if p in db_pages:
                f.write(db_pages[p])
            else:
                f.write(b'\x00' * db_page_size)
    
    # Extract data from reconstructed database
    return extract_data(working_db, output_path)


# ──────────────────────────────────────────────
# Main Recovery Workflow
# ──────────────────────────────────────────────

def recover_wal(db_path, wal_path, output_path):
    """
    Main recovery workflow: copy → diagnose → decode → validate → open → extract
    Falls back to manual frame application if SQLite cannot consume the WAL.
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
    
    # Step 4: Verify decoded structure and checksums
    print("\n[Step 4] Verifying decoded WAL structure...")
    page_size, frame_count, cksum_be, valid_frames = verify_decoded_wal(decoded_wal)
    
    # Step 5: Write decoded WAL and try SQLite first
    print("\n[Step 5] Writing decoded WAL and attempting SQLite recovery...")
    
    # Remove stale SHM file
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    with open(wal_path, 'wb') as f:
        f.write(decoded_wal)
    print(f"  Decoded WAL written to {wal_path}")
    
    # Try extracting via SQLite
    try:
        rows = extract_data(db_path, output_path)
        
        # Check if we got all expected data
        # If valid_frames == frame_count, SQLite should have all data
        if valid_frames == frame_count:
            print("\n" + "=" * 60)
            print("Recovery complete!")
            print("=" * 60)
            return rows
        else:
            print(f"\n  SQLite returned {len(rows)} rows but only {valid_frames}/{frame_count} frames valid")
            print("  Attempting manual frame application...")
    except Exception as e:
        print(f"\n  SQLite extraction failed: {e}")
        print("  Attempting manual frame application...")
    
    # Step 6: Fallback - manual frame application
    # Restore the original DB (before SQLite may have modified it)
    shutil.copy2(db_backup, db_path)
    
    rows = manual_apply_frames(db_path, decoded_wal, page_size, frame_count, cksum_be, output_path)
    
    print("\n" + "=" * 60)
    print("Recovery complete (via manual frame application)!")
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
        import traceback
        traceback.print_exc()
        sys.exit(1)

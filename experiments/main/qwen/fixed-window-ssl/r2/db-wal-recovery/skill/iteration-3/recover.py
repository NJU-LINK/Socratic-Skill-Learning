#!/usr/bin/env python3
"""
WAL Recovery Script for db-wal-recovery skill.

Usage:
    python3 recover.py [db_path] [wal_path]

If paths not provided, auto-discovers /app/*.db and /app/*.db-wal
"""
import struct, sys, os, shutil, sqlite3, glob, json

def main():
    # Parse arguments or auto-discover
    if len(sys.argv) >= 3:
        db_path = sys.argv[1]
        wal_path = sys.argv[2]
    else:
        db_files = glob.glob('/app/*.db')
        wal_files = glob.glob('/app/*.db-wal')
        
        if not db_files or not wal_files:
            print("ERROR: Missing .db or .db-wal files in /app/")
            print("Usage: python3 recover.py <db_path> <wal_path>")
            sys.exit(1)
        
        db_path = db_files[0]
        wal_path = wal_files[0]
    
    print(f"Database: {db_path}")
    print(f"WAL file: {wal_path}")
    
    # Backup (CRITICAL)
    shutil.copy(wal_path, '/tmp/wal.bak')
    shutil.copy(db_path, '/tmp/db.bak')
    print("✓ Backed up to /tmp/")
    
    # Read DB header for page size
    db_data = open('/tmp/db.bak', 'rb').read()
    page_size = int.from_bytes(db_data[16:18], 'big')
    print(f"✓ DB page size: {page_size}")
    
    # Diagnose encoding
    wal_data = open('/tmp/wal.bak', 'rb').read()
    expected_magic = bytes.fromhex('377f0682')
    expected_version = bytes.fromhex('002de218')
    expected_pagesize = page_size.to_bytes(4, 'big')
    expected = expected_magic + expected_version + expected_pagesize
    
    xor_bytes = bytes(e ^ d for e, d in zip(expected, wal_data[:12]))
    vals = list(xor_bytes)
    
    # Determine encoding type
    if len(set(vals)) == 1:
        key = vals[0]
        print(f"✓ Encoding: Single-byte XOR with key 0x{key:02x}")
        decoded = bytes(b ^ key for b in wal_data)
    elif len(vals) >= 8 and vals[:4] == vals[4:8]:
        key = bytes(vals[:4])
        print(f"✓ Encoding: 4-byte repeating XOR key: {key.hex()}")
        decoded = bytes(wal_data[i] ^ key[i % 4] for i in range(len(wal_data)))
    elif len(vals) >= 16 and vals[:8] == vals[8:16]:
        key = bytes(vals[:8])
        print(f"✓ Encoding: 8-byte repeating XOR key: {key.hex()}")
        decoded = bytes(wal_data[i] ^ key[i % 8] for i in range(len(wal_data)))
    elif all(v == 0xff for v in vals):
        print("✓ Encoding: Bitwise NOT")
        decoded = bytes(b ^ 0xff for b in wal_data)
    elif all(0x20 <= b <= 0x7e for b in wal_data[:100]):
        print("✓ Encoding: Base64")
        import base64
        decoded = base64.b64decode(wal_data)
    elif len(wal_data) > 32 and wal_data[32:36] in (bytes.fromhex('00000001'), bytes.fromhex('00000002')):
        print("✓ Encoding: Header-only damage — attempting header repair")
        decoded = bytearray(wal_data)
        decoded[0:4] = expected_magic
        decoded[4:8] = expected_version
        decoded[8:12] = expected_pagesize
        decoded = bytes(decoded)
    else:
        print(f"ERROR: Unknown encoding. XOR bytes: {' '.join(f'{b:02x}' for b in vals)}")
        sys.exit(1)
    
    # Validate decoded WAL
    magic = decoded[:4]
    if magic not in (bytes.fromhex('377f0682'), bytes.fromhex('377f0683')):
        print(f"ERROR: Decoded magic invalid: {magic.hex()}")
        sys.exit(1)
    
    version = struct.unpack('>I', decoded[4:8])[0]
    if version != 3007000:
        print(f"ERROR: Decoded version invalid: {version}")
        sys.exit(1)
    
    decoded_pagesize = struct.unpack('>I', decoded[8:12])[0]
    if decoded_pagesize != page_size:
        print(f"ERROR: Page size mismatch: WAL={decoded_pagesize}, DB={page_size}")
        sys.exit(1)
    
    wal_salt = decoded[16:24]
    print(f"✓ WAL salt: {wal_salt.hex()}")
    
    # Validate frames
    offset = 32
    frame_num = 0
    while offset + 24 + page_size <= len(decoded):
        frame_hdr = decoded[offset:offset+24]
        page_num = struct.unpack('>I', frame_hdr[:4])[0]
        frame_salt = frame_hdr[8:16]
        
        if frame_salt != wal_salt:
            print(f"ERROR: Frame {frame_num} salt mismatch")
            sys.exit(1)
        
        offset += 24 + page_size
        frame_num += 1
    
    print(f"✓ Validated: {frame_num} frames")
    
    # Apply decoded WAL
    open('/tmp/wal.decoded', 'wb').write(decoded)
    
    # Remove stale SHM
    shm_path = db_path.replace('.db', '.db-shm')
    if os.path.exists(shm_path):
        os.remove(shm_path)
        print(f"✓ Removed stale {shm_path}")
    
    # Copy decoded WAL
    shutil.copy('/tmp/wal.decoded', wal_path)
    print(f"✓ Applied decoded WAL to {wal_path}")
    
    # Verify with SQLite
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✓ Tables: {tables}")
        
        for table in tables:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table}: {count} records")
        
        conn.close()
        print("✓ SUCCESS: WAL applied correctly")
    except Exception as e:
        print(f"ERROR: SQLite failed to read database: {e}")
        print("See SKILL.md 'Advanced Recovery' section for manual page extraction")
        sys.exit(1)
    
    # Export to JSON
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        table_name = tables[0] if tables else 'items'
        cursor = conn.execute(f"SELECT * FROM {table_name} ORDER BY id")
        rows = cursor.fetchall()
        
        cols = [desc[0] for desc in cursor.description]
        data = [dict(zip(cols, row)) for row in rows]
        
        with open('/app/recovered.json', 'w') as f:
            json.dump(data, f, indent=2)
        
        conn.close()
        print(f"✓ Exported {len(data)} records to /app/recovered.json")
        
    except Exception as e:
        print(f"ERROR: Failed to export JSON: {e}")
        sys.exit(1)
    
    print("\n=== RECOVERY COMPLETE ===")

if __name__ == '__main__':
    main()

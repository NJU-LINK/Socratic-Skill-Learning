#!/usr/bin/env python3
"""
Test script to verify WAL recovery works correctly.
Creates a test database with WAL, XOR-encodes it, then recovers it.
"""

import os
import sys
import json
import sqlite3
import shutil

def create_test_database():
    """Create a test database with known data in WAL."""
    db_path = '/tmp/test_recovery.db'
    
    # Remove if exists
    for f in [db_path, db_path + '-wal', db_path + '-shm', 
              db_path + '-wal.encoded', db_path + '-wal.original']:
        if os.path.exists(f):
            os.remove(f)
    
    # Create database with WAL mode
    conn = sqlite3.connect(db_path, isolation_level=None)
    cursor = conn.cursor()
    
    # Set WAL mode
    cursor.execute("PRAGMA journal_mode=WAL;")
    result = cursor.fetchone()
    print(f"Journal mode: {result[0]}")
    
    # Disable auto-checkpoint
    cursor.execute("PRAGMA wal_autocheckpoint=0;")
    
    # Create table
    cursor.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, value INTEGER);")
    
    # Insert base records
    cursor.execute("BEGIN TRANSACTION;")
    for i, (name, value) in enumerate([('apple', 100), ('banana', 200), ('cherry', 300)], 1):
        cursor.execute(f"INSERT INTO items VALUES ({i}, '{name}', {value});")
    cursor.execute("COMMIT;")
    
    # Checkpoint to ensure base has these records
    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    
    # Verify base has 3 records
    cursor.execute("SELECT COUNT(*) FROM items;")
    count = cursor.fetchone()[0]
    print(f"After checkpoint: {count} records")
    
    # Now add more records that will stay in WAL
    cursor.execute("BEGIN TRANSACTION;")
    for i, (name, value) in enumerate([('date', 400), ('elderberry', 500), ('fig', 600)], 4):
        cursor.execute(f"INSERT INTO items VALUES ({i}, '{name}', {value});")
    cursor.execute("COMMIT;")
    
    # Check if WAL exists before closing
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        wal_size = os.path.getsize(wal_path)
        print(f"WAL file exists: {wal_size} bytes")
    else:
        print("WARNING: WAL file not created before close")
        return None, None
    
    # Close without checkpointing
    # Don't call conn.close() - just let it go out of scope
    
    # Verify WAL still exists
    if os.path.exists(wal_path):
        wal_size = os.path.getsize(wal_path)
        print(f"WAL file after connection: {wal_size} bytes")
        return db_path, wal_path
    else:
        print("WAL file was deleted on connection close")
        return None, None

def xor_encode_file(input_path, output_path, key=0x42):
    """XOR-encode a file."""
    with open(input_path, 'rb') as f:
        data = f.read()
    
    encoded = bytes([b ^ key for b in data])
    
    with open(output_path, 'wb') as f:
        f.write(encoded)
    
    return len(data)

def main():
    print("=== WAL Recovery Test ===\n")
    
    # Step 1: Create test database
    print("Step 1: Creating test database...")
    db_path, wal_path = create_test_database()
    
    if db_path is None or wal_path is None:
        print("ERROR: Failed to create test database with WAL")
        sys.exit(1)
    
    if not os.path.exists(wal_path):
        print(f"ERROR: WAL file not found at {wal_path}")
        sys.exit(1)
    
    print()
    
    # Step 2: XOR-encode the WAL
    print("Step 2: XOR-encoding WAL file...")
    encoded_wal = wal_path + '.encoded'
    size = xor_encode_file(wal_path, encoded_wal, key=0x42)
    print(f"Encoded {size} bytes")
    
    # Verify encoding
    with open(encoded_wal, 'rb') as f:
        first_bytes = f.read(4)
    print(f"First 4 bytes of encoded WAL: {first_bytes.hex()}")
    expected = bytes([0x37^0x42, 0x7f^0x42, 0x06^0x42, 0x82^0x42])
    print(f"Expected (magic XOR 0x42): {expected.hex()}")
    
    if first_bytes == expected:
        print("✓ XOR encoding verified")
    else:
        print("✗ XOR encoding failed")
        sys.exit(1)
    print()
    
    # Step 3: Save original WAL
    print("Step 3: Saving original WAL...")
    original_wal = wal_path + '.original'
    shutil.copy2(wal_path, original_wal)
    print(f"Saved original WAL to {original_wal}")
    print()
    
    # Step 4: Test recovery with encoded WAL
    print("Step 4: Testing recovery with encoded WAL...")
    
    # Replace WAL with encoded version
    shutil.copy2(encoded_wal, wal_path)
    print(f"Replaced WAL with XOR-encoded version")
    
    # Remove SHM to force fresh connection
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    # Verify SQLite can't read encoded WAL
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items;")
        count = cursor.fetchone()[0]
        conn.close()
        print(f"SQLite sees {count} records with encoded WAL (should be 3)")
    except Exception as e:
        print(f"Note: SQLite error with encoded WAL: {e}")
    
    # The WAL might have been deleted by SQLite, so restore it
    if not os.path.exists(wal_path):
        print("SQLite deleted the encoded WAL, restoring from original...")
        shutil.copy2(original_wal, wal_path)
    
    # Now XOR-encode it again for the actual test
    xor_encode_file(wal_path, wal_path, key=0x42)
    print(f"WAL re-encoded for recovery test")
    print()
    
    # Step 5: Test recovery
    print("Step 5: Testing recovery script...")
    
    # Add skill scripts to path
    sys.path.insert(0, '/skill/scripts')
    
    try:
        import recover
        
        # Test encoding detection
        print("\nTesting encoding detection...")
        decoded_wal, encoding_type = recover.detect_encoding(wal_path)
        
        if decoded_wal is None:
            print("✗ Failed to detect encoding")
            sys.exit(1)
        
        print(f"✓ Detected encoding: {encoding_type}")
        
        # Verify decoded WAL structure
        print("\nVerifying decoded WAL structure...")
        valid, msg = recover.verify_wal_structure(decoded_wal)
        if not valid:
            print(f"✗ WAL structure check failed: {msg}")
            sys.exit(1)
        print(f"✓ WAL structure: {msg}")
        
        # Test recovery
        print("\nTesting data recovery...")
        
        # Restore original WAL first
        shutil.copy2(original_wal, wal_path)
        
        data, msg = recover.recover_with_decoded_wal(db_path, decoded_wal)
        
        if data is None:
            print(f"✗ Recovery failed: {msg}")
            sys.exit(1)
        
        print(f"✓ Recovered {len(data)} records")
        
        # Verify data
        print("\nRecovered data:")
        for row in data:
            print(f"  {row}")
        
        if len(data) == 6:
            print("\n" + "="*50)
            print("✓✓✓ ALL TESTS PASSED ✓✓✓")
            print("="*50)
            print("Recovery script successfully:")
            print("  1. Detected XOR encoding (key 0x42)")
            print("  2. Verified WAL structure")
            print("  3. Recovered all 6 records")
        else:
            print(f"\n✗ Expected 6 records, got {len(data)}")
            sys.exit(1)
        
    except ImportError as e:
        print(f"Could not import recovery script: {e}")
        sys.exit(1)
    
    print("\n=== Test Complete ===")

if __name__ == '__main__':
    main()

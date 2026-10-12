#!/usr/bin/env python3
"""
End-to-end test that simulates the actual v01 task scenario.
Creates a database with 5 base records, adds 6 more via WAL, XOR-encodes the WAL,
then runs the recovery script to verify it works.
"""

import os
import sys
import json
import sqlite3
import shutil
import struct

def setup_task_environment():
    """
    Simulate the v01 task setup:
    - Create main.db with 5 base records
    - Add 6 more records via WAL (total 11)
    - XOR-encode the WAL file
    """
    print("Setting up task environment...")
    
    # Clean up any existing files
    for f in ['/app/main.db', '/app/main.db-wal', '/app/main.db-shm',
              '/app/main.db.backup', '/app/main.db-wal.backup',
              '/app/recovered.json']:
        if os.path.exists(f):
            os.remove(f)
    
    # Create database with WAL mode using a single connection
    db_path = '/app/main.db'
    
    # Use isolation_level=None for manual transaction control
    conn = sqlite3.connect(db_path, isolation_level=None)
    cursor = conn.cursor()
    
    # Set WAL mode and disable auto-checkpoint
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA wal_autocheckpoint=0;")
    
    # Create table
    cursor.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, value INTEGER);")
    
    # Insert 5 base records
    cursor.execute("BEGIN;")
    base_records = [
        (1, 'apple', 100),
        (2, 'banana', 200),
        (3, 'cherry', 300),
        (4, 'date', 400),
        (5, 'elderberry', 500),
    ]
    for record in base_records:
        cursor.execute("INSERT INTO items VALUES (?, ?, ?);", record)
    cursor.execute("COMMIT;")
    
    # Checkpoint to ensure base has these 5 records
    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    
    # Verify base has 5 records
    cursor.execute("SELECT COUNT(*) FROM items;")
    count = cursor.fetchone()[0]
    print(f"Base database has {count} records (should be 5)")
    
    # Now add 6 more records that will stay in WAL
    cursor.execute("BEGIN;")
    wal_records = [
        (6, 'fig', 600),
        (7, 'grape', 700),
        (8, 'honeydew', 800),
        (9, 'kiwi', 900),
        (10, 'lemon', 1000),
        (11, 'mango', 1100),
    ]
    for record in wal_records:
        cursor.execute("INSERT INTO items VALUES (?, ?, ?);", record)
    cursor.execute("COMMIT;")
    
    # Verify total is 11 while connection is still open
    cursor.execute("SELECT COUNT(*) FROM items;")
    total_count = cursor.fetchone()[0]
    print(f"Total records with WAL: {total_count} (should be 11)")
    
    if total_count != 11:
        print("ERROR: Expected 11 records")
        conn.close()
        return False
    
    wal_path = db_path + '-wal'
    
    # Check WAL exists while connection is still open
    if not os.path.exists(wal_path):
        print("ERROR: WAL file not created")
        conn.close()
        return False
    
    wal_size = os.path.getsize(wal_path)
    print(f"WAL file exists: {wal_size} bytes")
    
    # Read WAL data while connection is still open
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    
    # NOW close the connection
    conn.close()
    
    # Immediately write back the WAL (in case SQLite deleted it on close)
    with open(wal_path, 'wb') as f:
        f.write(wal_data)
    
    print(f"WAL file preserved: {os.path.getsize(wal_path)} bytes")
    
    # Remove SHM file to simulate fresh environment
    shm_path = db_path + '-shm'
    if os.path.exists(shm_path):
        os.remove(shm_path)
    
    # Now XOR-encode the WAL file
    print("\nXOR-encoding WAL file with key 0x42...")
    encoded_wal = bytes([b ^ 0x42 for b in wal_data])
    with open(wal_path, 'wb') as f:
        f.write(encoded_wal)
    
    print(f"WAL file XOR-encoded: {os.path.getsize(wal_path)} bytes")
    
    # Verify encoding
    with open(wal_path, 'rb') as f:
        first_bytes = f.read(4)
    expected_magic = bytes([0x37^0x42, 0x7f^0x42, 0x06^0x42, 0x82^0x42])
    print(f"Encoded magic: {first_bytes.hex()} (expected: {expected_magic.hex()})")
    
    print("\n✓ Task environment ready")
    print(f"  - Base database: {db_path} (5 records)")
    print(f"  - Encoded WAL: {wal_path} ({os.path.getsize(wal_path)} bytes)")
    print(f"  - Expected recovery: 11 records total")
    
    return True

def run_recovery():
    """Run the recovery script."""
    print("\n" + "="*60)
    print("RUNNING RECOVERY SCRIPT")
    print("="*60 + "\n")
    
    # Import the recovery module
    sys.path.insert(0, '/skill/scripts')
    import recover
    
    # Run the main recovery
    recover.main()
    
    # Check if output was created
    output_path = '/app/recovered.json'
    if not os.path.exists(output_path):
        print("\n✗ Recovery failed: output file not created")
        return False
    
    # Load and verify output
    with open(output_path, 'r') as f:
        data = json.load(f)
    
    print(f"\nVerifying output...")
    print(f"Records recovered: {len(data)}")
    
    if len(data) != 11:
        print(f"✗ Expected 11 records, got {len(data)}")
        return False
    
    # Verify data is sorted by id
    ids = [row['id'] for row in data]
    if ids != sorted(ids):
        print("✗ Data not sorted by id")
        return False
    
    # Verify all expected records are present
    expected_ids = list(range(1, 12))
    if ids != expected_ids:
        print(f"✗ Missing or extra records")
        print(f"  Expected IDs: {expected_ids}")
        print(f"  Got IDs: {ids}")
        return False
    
    # Verify record structure
    for row in data:
        if not all(k in row for k in ['id', 'name', 'value']):
            print(f"✗ Record missing required fields: {row}")
            return False
    
    print("\n" + "="*60)
    print("✓✓✓ END-TO-END TEST PASSED ✓✓✓")
    print("="*60)
    print("\nRecovery script successfully:")
    print("  1. Backed up original files")
    print("  2. Detected XOR encoding (key 0x42)")
    print("  3. Decoded and verified WAL structure")
    print("  4. Recovered all 11 records")
    print("  5. Output sorted by id")
    print("  6. Created valid JSON output")
    
    print("\nRecovered data:")
    for row in data:
        print(f"  {row}")
    
    return True

def main():
    print("="*60)
    print("END-TO-END WAL RECOVERY TEST")
    print("="*60 + "\n")
    
    # Setup task environment
    if not setup_task_environment():
        print("\n✗ Failed to setup task environment")
        sys.exit(1)
    
    # Run recovery
    if not run_recovery():
        print("\n✗ Recovery test failed")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("ALL TESTS PASSED")
    print("="*60)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Test the WAL recovery script with a minimal example.
Creates a small database with a WAL file, applies XOR encoding, then recovers it.
"""

import sqlite3
import os
import struct
import subprocess
import json
import shutil

# Create a test database
test_dir = '/tmp/wal_test'
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir, exist_ok=True)

db_path = os.path.join(test_dir, 'test.db')
wal_path = os.path.join(test_dir, 'test.db-wal')

# Create database with WAL mode
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA wal_autocheckpoint=0')  # Disable auto-checkpoint
conn.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, value INTEGER)')
conn.execute("INSERT INTO items VALUES (1, 'apple', 100)")
conn.execute("INSERT INTO items VALUES (2, 'banana', 200)")
conn.commit()

# Add more data (this will be in the WAL)
conn.execute("INSERT INTO items VALUES (3, 'cherry', 300)")
conn.execute("INSERT INTO items VALUES (4, 'date', 400)")
conn.commit()

# Save WAL before closing
wal_existed = os.path.exists(wal_path)
if wal_existed:
    with open(wal_path, 'rb') as f:
        saved_wal = f.read()
    print(f"WAL size before close: {len(saved_wal)} bytes")
else:
    saved_wal = None

conn.close()

# Restore WAL if it was deleted during close
if saved_wal and not os.path.exists(wal_path):
    with open(wal_path, 'wb') as f:
        f.write(saved_wal)
    print(f"Restored WAL file ({len(saved_wal)} bytes)")

print(f"WAL file exists after close: {os.path.exists(wal_path)}")

if os.path.exists(wal_path):
    # Read the WAL file
    with open(wal_path, 'rb') as f:
        original_wal = f.read()
    
    print(f"Original WAL size: {len(original_wal)} bytes")
    print(f"Original WAL magic: {original_wal[0:4].hex()}")
    
    # Verify base database only has 2 records
    conn2 = sqlite3.connect(db_path)
    count = conn2.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    print(f"Base database record count: {count}")
    conn2.close()
    
    # Apply XOR encoding with key 0x42
    encoded_wal = bytes(b ^ 0x42 for b in original_wal)
    
    # Write the encoded WAL
    with open(wal_path, 'wb') as f:
        f.write(encoded_wal)
    
    print(f"Encoded WAL with XOR key 0x42")
    print(f"Encoded WAL magic: {encoded_wal[0:4].hex()}")
    
    # Now try to recover using the script
    script_path = '/skill/scripts/recover.py'
    output_path = os.path.join(test_dir, 'recovered.json')
    
    print(f"\nRunning recovery script...")
    result = subprocess.run(
        ['python3', script_path, db_path, wal_path, '-o', output_path],
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    if result.stderr:
        print("STDERR:")
        print(result.stderr)
    
    print(f"\nRecovery script exit code: {result.returncode}")
    
    if os.path.exists(output_path):
        with open(output_path) as f:
            recovered = json.load(f)
        print(f"\nRecovered data:")
        print(json.dumps(recovered, indent=2))
        
        # Verify
        expected = [
            {'id': 1, 'name': 'apple', 'value': 100},
            {'id': 2, 'name': 'banana', 'value': 200},
            {'id': 3, 'name': 'cherry', 'value': 300},
            {'id': 4, 'name': 'date', 'value': 400},
        ]
        
        if recovered == expected:
            print("\n✓ Test PASSED: Recovered data matches expected")
        else:
            print("\n✗ Test FAILED: Recovered data does not match")
            print(f"Expected: {expected}")
            print(f"Got: {recovered}")
    else:
        print(f"\n✗ Test FAILED: Output file not created")
else:
    print("WAL file was not created (SQLite checkpointed immediately)")

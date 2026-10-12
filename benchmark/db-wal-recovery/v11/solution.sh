#!/bin/bash
set -e

python3 << 'PYEOF'
import struct, json, os, subprocess, sqlite3

print("=== Step 1: Read encrypted WAL (before sqlite3 touches it) ===")
with open('/app/main.db-wal', 'rb') as f:
    encrypted = f.read()
print(f"Read {len(encrypted)} bytes of encrypted WAL")

print("\n=== Step 2: Extract AES key from database schema ===")
conn = sqlite3.connect('/app/main.db')
view_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='view'").fetchone()[0]
key_hex = view_sql.split('key ')[1].strip()
print(f"Found key: {key_hex}")
conn.close()

print("\n=== Step 3: Decrypt WAL with AES-128-ECB ===")
result = subprocess.run(
    ['openssl', 'enc', '-d', '-aes-128-ecb', '-K', key_hex],
    input=encrypted, capture_output=True, timeout=30
)
if result.returncode != 0:
    raise RuntimeError(
        f"openssl failed rc={result.returncode} stderr={result.stderr.decode()}"
    )
with open('/tmp/wal_decrypted', 'wb') as f:
    f.write(result.stdout)
print(f"Decrypted {len(encrypted)} bytes -> {len(result.stdout)} bytes")

print("\n=== Step 4: Parse decrypted WAL ===")
with open('/tmp/wal_decrypted', 'rb') as f:
    wal = f.read()

page_size = struct.unpack('>I', wal[8:12])[0]
frame_size = 24 + page_size
print(f"Page size: {page_size}")
print(f"WAL size: {len(wal)} bytes")

real_frames = []
pos = 32
while pos + frame_size <= len(wal):
    pgno = struct.unpack('>I', wal[pos:pos+4])[0]
    commit_size = struct.unpack('>I', wal[pos+4:pos+8])[0]
    body = wal[pos+24:pos+frame_size]
    is_all_zeros = all(b == 0 for b in body)
    if pgno == 0 and commit_size == 0 and is_all_zeros:
        print(f"  Removing fake checkpoint frame at offset {pos}")
    else:
        real_frames.append((pgno, body))
        print(f"  Real frame: page={pgno}, commit_size={commit_size}")
    pos += frame_size

print(f"\nTotal real frames: {len(real_frames)}")

print("\n=== Step 5: Apply page data to database ===")
with open('/app/main.db', 'rb') as f:
    db = bytearray(f.read())

for pgno, body in real_frames:
    offset = (pgno - 1) * page_size
    print(f"  Applying page {pgno} at offset {offset}")
    db[offset:offset+len(body)] = body

with open('/app/main.db', 'wb') as f:
    f.write(db)
db_size = len(db)

print("\n=== Step 6: Remove stale WAL files ===")
for p in ['/app/main.db-wal', '/app/main.db-shm']:
    if os.path.exists(p):
        os.remove(p)
        print(f"  Removed {p}")

print("\n=== Step 7: Verify recovered database ===")
conn2 = sqlite3.connect('/app/main.db')
inventory = conn2.execute('SELECT id, name, price FROM inventory ORDER BY id').fetchall()
print(f"  Inventory ({len(inventory)} records):")
for r in inventory:
    print(f"    id={r[0]}: {r[1]} = {r[2]}")

views = conn2.execute('SELECT * FROM expensive_items ORDER BY id').fetchall()
print(f"\n  Expensive items view ({len(views)} records):")
for r in views:
    print(f"    id={r[0]}: {r[1]} = {r[2]}")
conn2.close()

print("\n=== Step 8: Export to JSON ===")
data = [{"id": r[0], "name": r[1], "price": r[2]} for r in inventory]
with open('/app/recovered.json', 'w') as f:
    json.dump(data, f, indent=2)
print(f"  Written {len(data)} records to /app/recovered.json")
PYEOF

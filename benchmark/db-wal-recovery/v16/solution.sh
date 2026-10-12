#!/bin/bash
set -e

cd /app

python3 << 'PYEOF'
import struct
import json
import sqlite3
import os
import shutil

PAGE_SIZE = 4096

def byte_swap(data):
    result = bytearray(data)
    for i in range(0, len(result) - 1, 2):
        result[i], result[i+1] = result[i+1], result[i]
    return bytes(result)

for wal in ['main.db-wal', 'main.db-wal.extra']:
    with open(f'/app/{wal}', 'rb') as f:
        data = f.read()
    with open(f'/tmp/{wal}', 'wb') as f:
        f.write(byte_swap(data))

os.chdir('/tmp')
shutil.copy2('/app/main.db', '/tmp/main.db')

def apply_wal(wal_path, db_path):
    with open(wal_path, 'rb') as f:
        wal_data = f.read()
    with open(db_path, 'rb') as f:
        db_data = bytearray(f.read())

    offset = 32
    while offset + 24 + PAGE_SIZE <= len(wal_data):
        pgno = struct.unpack_from('>I', wal_data, offset)[0]
        page_data = wal_data[offset + 24 : offset + 24 + PAGE_SIZE]

        page_off = (pgno - 1) * PAGE_SIZE
        needed = page_off + PAGE_SIZE
        if needed > len(db_data):
            db_data.extend(b'\x00' * (needed - len(db_data)))
        db_data[page_off : page_off + PAGE_SIZE] = page_data

        offset += 24 + PAGE_SIZE

    with open(db_path, 'wb') as f:
        f.write(db_data)

apply_wal('/tmp/main.db-wal.extra', '/tmp/main.db')
apply_wal('/tmp/main.db-wal', '/tmp/main.db')

conn = sqlite3.connect('/tmp/main.db')
cursor = conn.execute('SELECT id, name, value FROM items ORDER BY id')
rows = cursor.fetchall()
conn.close()

data = [{"id": r[0], "name": r[1], "value": r[2]} for r in rows]
with open('/app/recovered.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f'Recovered {len(data)} records')
for r in data:
    print(f'  id={r["id"]}: {r["name"]} = {r["value"]}')
PYEOF

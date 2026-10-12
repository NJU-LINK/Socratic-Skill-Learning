#!/bin/bash
set -e

python3 << 'PYEOF'
import struct, os, json, sqlite3, shutil

WAL_PATH = '/app/main.db-wal'
DB_PATH = '/app/main.db'
OUTPUT_PATH = '/app/recovered.json'

shutil.copy(DB_PATH, DB_PATH + '.bak')

with open(WAL_PATH, 'rb') as f:
    wal = bytearray(f.read())

WAL_HDR_SIZE = 32
FRAME_HDR_SIZE = 24
PAGE_SIZE = struct.unpack('>I', wal[8:12])[0]

salt1 = struct.unpack('>I', bytes(wal[WAL_HDR_SIZE+8:WAL_HDR_SIZE+12]))[0]
salt2 = struct.unpack('>I', bytes(wal[WAL_HDR_SIZE+12:WAL_HDR_SIZE+16]))[0]

wal[0:4] = b'\x37\x7f\x06\x82'
wal[12:16] = struct.pack('>I', 1)
wal[16:20] = struct.pack('>I', salt1)
wal[20:24] = struct.pack('>I', salt2)

with open(WAL_PATH, 'wb') as f:
    f.write(wal)

frames = []
offset = WAL_HDR_SIZE
while offset + FRAME_HDR_SIZE + PAGE_SIZE <= len(wal):
    page_num = struct.unpack('>I', wal[offset:offset+4])[0]
    db_size = struct.unpack('>I', wal[offset+4:offset+8])[0]
    page_data = wal[offset + FRAME_HDR_SIZE : offset + FRAME_HDR_SIZE + PAGE_SIZE]
    frames.append((page_num, db_size, page_data))
    offset += FRAME_HDR_SIZE + PAGE_SIZE

with open(DB_PATH, 'rb') as f:
    db = bytearray(f.read())

for page_num, db_size, page_data in frames:
    page_offset = (page_num - 1) * PAGE_SIZE
    if page_offset + PAGE_SIZE > len(db):
        db.extend(b'\x00' * (page_offset + PAGE_SIZE - len(db)))
    db[page_offset:page_offset + PAGE_SIZE] = page_data
    if db_size > 0:
        db[28:32] = struct.pack('>I', db_size)

change_counter = struct.unpack('>I', bytes(db[24:28]))[0]
change_counter += 1
db[24:28] = struct.pack('>I', change_counter)

with open(DB_PATH, 'wb') as f:
    f.write(db)

conn = sqlite3.connect(DB_PATH)
conn.execute('PRAGMA journal_mode=DELETE;')
conn.row_factory = sqlite3.Row

tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for t in tables:
    name = t['name']
    rows = conn.execute(f'SELECT * FROM [{name}]').fetchall()
    print(f'Table {name}: {len(rows)} rows')
    for r in rows:
        print(f'  {dict(r)}')

rows = conn.execute('SELECT id, name, department, salary FROM employees ORDER BY id').fetchall()
employees = [{'id': r['id'], 'name': r['name'], 'department': r['department'], 'salary': r['salary']} for r in rows]

with open(OUTPUT_PATH, 'w') as f:
    json.dump(employees, f, indent=2)

print(f'\nWritten {len(employees)} employee records to {OUTPUT_PATH}')

conn.close()
PYEOF

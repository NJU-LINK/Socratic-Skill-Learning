#!/bin/bash
set -e

WORKDIR="${1:-/app}"

python3 - "$WORKDIR" << 'PYEOF'
import struct, sqlite3, json, base64, sys

WORKDIR = sys.argv[1]

WAL_PATH = f'{WORKDIR}/main.db-wal'
DB_PATH = f'{WORKDIR}/main.db'
OUTPUT_PATH = '/app/recovered.json'

with open(WAL_PATH, 'rb') as f:
    wal = f.read()
with open(DB_PATH, 'rb') as f:
    db = bytearray(f.read())

page_size = struct.unpack('>H', db[16:18])[0]
frame_size = 24 + page_size
wal_data = wal[32:]
num_frames = len(wal_data) // frame_size

pages = {}
for i in range(num_frames):
    offset = i * frame_size
    pgno = struct.unpack('>I', wal_data[offset:offset+4])[0]
    body = wal_data[offset+24:offset+frame_size]
    if pgno >= 1:
        pages[pgno] = body

for pgno, body in pages.items():
    page_offset = (pgno - 1) * page_size
    if page_offset + len(body) <= len(db):
        db[page_offset:page_offset+len(body)] = body

with open('/tmp/recovered.db', 'wb') as f:
    f.write(db)

conn = sqlite3.connect('/tmp/recovered.db')
cursor = conn.execute('SELECT id, name, price, data FROM items ORDER BY id')
rows = []
for row in cursor.fetchall():
    data_b64 = base64.b64encode(row[3]).decode('ascii') if row[3] else None
    rows.append({"id": row[0], "name": row[1], "price": row[2], "data": data_b64})
conn.close()

with open(OUTPUT_PATH, 'w') as f:
    json.dump(rows, f, indent=2)

print(f"Recovered {len(rows)} records to {OUTPUT_PATH}")
PYEOF

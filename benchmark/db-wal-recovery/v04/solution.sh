#!/bin/bash
set -e

python3 << 'PYEOF'
import struct
import sqlite3
import json

WAL_PATH = '/app/main.db-wal'
DB_PATH = '/tmp/recovered.db'
OUTPUT_PATH = '/app/recovered.json'

with open(WAL_PATH, 'rb') as f:
    data = bytearray(f.read())

for i in range(len(data)):
    data[i] ^= 0xFF

page_size = struct.unpack('>I', data[8:12])[0]
n_frames = (len(data) - 32) // (24 + page_size)

pages = {}
for i in range(n_frames):
    off = 32 + i * (24 + page_size)
    pgno = struct.unpack('>I', data[off:off+4])[0]
    pages[pgno] = bytes(data[off+24:off+24+page_size])

max_pgno = max(pages.keys())

with open(DB_PATH, 'wb') as f:
    for pgno in range(1, max_pgno + 1):
        if pgno in pages:
            f.write(pages[pgno])
        else:
            f.write(b'\x00' * page_size)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT id, name, value FROM items ORDER BY id")
rows = [dict(row) for row in cursor.fetchall()]
conn.close()

with open(OUTPUT_PATH, 'w') as f:
    json.dump(rows, f, indent=2)

print(f"Recovered {len(rows)} records to {OUTPUT_PATH}")
PYEOF

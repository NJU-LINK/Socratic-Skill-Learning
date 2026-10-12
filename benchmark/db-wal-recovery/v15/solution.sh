#!/bin/bash
set -e

cd /app

openssl enc -d -aes-256-cbc -in main.db-wal -out /tmp/decrypted.wal -pass pass:secret123

python3 << 'PYEOF'
import struct
import json
import sqlite3

PAGE_SIZE = 4096

with open('/tmp/decrypted.wal', 'rb') as f:
    wal_data = f.read()

with open('main.db', 'rb') as f:
    db_data = bytearray(f.read())

def get_row_ids(body, btree_off=0):
    if len(body) < btree_off + 8:
        return []
    if body[btree_off] != 0x0D:
        return []
    num_cells = struct.unpack_from('>H', body, btree_off + 3)[0]
    row_ids = []
    for i in range(num_cells):
        ptr = struct.unpack_from('>H', body, btree_off + 8 + i * 2)[0]
        pos = ptr
        while body[pos] & 0x80:
            pos += 1
        pos += 1
        row_id = 0
        shift = 0
        while True:
            byte = body[pos]
            row_id |= (byte & 0x7f) << shift
            shift += 7
            pos += 1
            if not (byte & 0x80):
                break
        row_ids.append(row_id)
    return row_ids

num_pages = len(db_data) // PAGE_SIZE
page_row_map = {}
for pg in range(1, num_pages + 1):
    off = (pg - 1) * PAGE_SIZE
    body = bytes(db_data[off : off + PAGE_SIZE])
    btree_off = 100 if pg == 1 else 0
    rids = get_row_ids(body, btree_off)
    if rids:
        page_row_map[pg] = set(rids)

offset = 32
while offset + 24 <= len(wal_data):
    pgno, ncommit = struct.unpack_from('>II', wal_data, offset)
    if offset + 24 + PAGE_SIZE > len(wal_data):
        break
    body = wal_data[offset + 24 : offset + 24 + PAGE_SIZE]
    if pgno == 0:
        if body[:16] == b'SQLite format 3\0':
            pgno = 1
        elif body[0] in (0x0D, 0x05, 0x0A, 0x02):
            frame_rids = get_row_ids(body, 0)
            best_page = None
            best_overlap = -1
            frame_set = set(frame_rids)
            for p, existing_rids in page_row_map.items():
                overlap = len(frame_set & existing_rids)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_page = p
            if best_page is not None:
                pgno = best_page
            else:
                pgno = num_pages + 1
    page_off = (pgno - 1) * PAGE_SIZE
    needed = page_off + PAGE_SIZE
    if needed > len(db_data):
        db_data.extend(b'\x00' * (needed - len(db_data)))
    db_data[page_off : page_off + PAGE_SIZE] = body
    offset += 24 + PAGE_SIZE

with open('main.db', 'wb') as f:
    f.write(db_data)

conn = sqlite3.connect('main.db')
cursor = conn.execute('SELECT id, name, value FROM items ORDER BY id')
rows = cursor.fetchall()
conn.close()

data = [{'id': r[0], 'name': r[1], 'value': r[2]} for r in rows]
with open('/app/recovered.json', 'w') as f:
    json.dump(data, f, indent=2)

print(f'Recovered {len(data)} records')
for r in data:
    print(f'  id={r["id"]}: {r["name"]} = {r["value"]}')
PYEOF

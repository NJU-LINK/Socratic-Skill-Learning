#!/bin/bash
set -e

echo "=== Step 1: Un-swap WAL bytes ==="
python3 << 'PYEOF'
import struct

with open("/app/main.db-wal", "rb") as f:
    data = f.read()

unswapped = bytearray(len(data))
for i in range(0, len(data) - 1, 2):
    unswapped[i] = data[i+1]
    unswapped[i+1] = data[i]

with open("/app/main.db-wal", "wb") as f:
    f.write(unswapped)

print("Byte-swapped WAL un-swapped successfully")
with open("/app/main.db-wal", "rb") as f:
    hdr = f.read(32)
print(f"Magic: {hdr[0]:02x}{hdr[1]:02x}{hdr[2]:02x}{hdr[3]:02x}")
PYEOF

echo ""
echo "=== Step 2: Analyze and fix WAL ==="
python3 << 'PYEOF'
import struct, os, shutil

page_size = 4096
frame_header_size = 24
frame_size = frame_header_size + page_size

with open("/app/main.db-wal", "rb") as f:
    wal = f.read()

with open("/app/main.db", "rb") as f:
    db = f.read()

db_page_size = struct.unpack('>H', db[16:18])[0]
num_pages = len(db) // db_page_size
num_frames = (len(wal) - 32) // frame_size

print(f"Database: {num_pages} pages of {db_page_size} bytes")
print(f"WAL: {num_frames} frames")

frames = []
for i in range(num_frames):
    offset = 32 + i * frame_size
    pgno = struct.unpack('>I', wal[offset:offset+4])[0]
    db_size = struct.unpack('>I', wal[offset+4:offset+8])[0]
    body = wal[offset + frame_header_size:offset + frame_size]

    if pgno < 1 or pgno > num_pages:
        if body[:15] == b'SQLite format 3':
            correct = 1
        else:
            correct = 2
        print(f"Frame {i}: corrupted page {pgno} -> corrected to page {correct}")
        pgno = correct

    frames.append({
        'pgno': pgno,
        'db_size': db_size,
        'body': body
    })

shutil.copy("/app/main.db", "/tmp/recovered_main.db")
for frm in frames:
    offset = (frm['pgno'] - 1) * page_size
    with open("/tmp/recovered_main.db", "r+b") as f:
        f.seek(offset)
        f.write(frm['body'])

shutil.move("/tmp/recovered_main.db", "/app/main.db")
os.remove("/app/main.db-wal")
print("Pages applied successfully; WAL removed to prevent stale replay")
PYEOF

echo ""
echo "=== Step 3: Extract all records ==="
python3 << 'PYEOF'
import sqlite3, json

conn = sqlite3.connect("/app/main.db")
data = [{"id": r[0], "name": r[1], "value": r[2]}
        for r in conn.execute("SELECT id, name, value FROM items ORDER BY id")]
conn.close()

with open("/app/recovered.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Recovered {len(data)} records:")
for r in data:
    print(f"  id={r['id']}: {r['name']} = {r['value']}")
PYEOF

echo ""
echo "=== Done! Output written to /app/recovered.json ==="

#!/bin/bash
set -e

echo "=== Step 1: Decode base64-encoded WAL ==="
python3 << 'PYEOF'
import base64, struct, json, sqlite3, os

PAGE_SIZE = 4096
WAL_HEADER_SIZE = 32
FRAME_HEADER_SIZE = 24

with open("/app/main.db-wal.encoded", "rb") as f:
    encoded = f.read()
decoded = base64.b64decode(encoded)

print(f"Decoded WAL: {len(decoded)} bytes")

offset = WAL_HEADER_SIZE
frames = []
while offset + FRAME_HEADER_SIZE <= len(decoded):
    page_num = struct.unpack_from(">I", decoded, offset)[0]
    db_size = struct.unpack_from(">I", decoded, offset + 4)[0]
    data_offset = offset + FRAME_HEADER_SIZE
    page_data = decoded[data_offset:data_offset + PAGE_SIZE]
    if len(page_data) < PAGE_SIZE:
        break
    frames.append((page_num, db_size, page_data))
    offset = data_offset + PAGE_SIZE

print(f"Found {len(frames)} frames: pages={[f[0] for f in frames]}")

with open("/app/main.db", "r+b") as f:
    for page_num, db_size, page_data in frames:
        f.seek((page_num - 1) * PAGE_SIZE)
        f.write(page_data)
        print(f"  Applied page {page_num}")

conn = sqlite3.connect("/app/main.db")
conn.row_factory = sqlite3.Row

result = {}
for table in ["users", "products", "orders"]:
    cursor = conn.execute(f"SELECT * FROM {table} ORDER BY id")
    rows = []
    for row in cursor.fetchall():
        rows.append(dict(row))
    result[table] = rows
    print(f"  {table}: {len(rows)} records")

conn.close()

with open("/app/recovered.json", "w") as f:
    json.dump(result, f, indent=2)

print("Written /app/recovered.json")
PYEOF

echo ""
echo "=== Done ==="

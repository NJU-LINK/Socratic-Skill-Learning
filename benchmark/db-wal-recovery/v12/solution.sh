#!/bin/bash
set -e

python3 << 'PYEOF'
import json, os, subprocess, struct

print("=== Step 1: Read encrypted WAL ===")
with open('/app/main.db-wal.encrypted', 'rb') as f:
    encrypted = f.read()
print(f"Read {len(encrypted)} bytes")

print("=== Step 2: Decrypt with bitwise NOT ===")
decoded = bytearray([~b & 0xff for b in encrypted])

page_size = struct.unpack('>I', decoded[8:12])[0]
print(f"Page size: {page_size}")

print("=== Step 3: Identify and fix corrupted frame page numbers ===")
frame_size = 24 + page_size
frame_count = (len(decoded) - 32) // frame_size
print(f"Found {frame_count} frames")

for i in range(frame_count):
    offset = 32 + i * frame_size
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    db_size = struct.unpack('>I', decoded[offset+4:offset+8])[0]
    valid_range = range(1, 7)
    if pgno not in valid_range:
        print(f"  Frame {i}: corrupted pgno={pgno} (0x{pgno:08x}), db_size={db_size}")
    else:
        print(f"  Frame {i}: valid pgno={pgno}, db_size={db_size}")

# Determine correct page numbers by analyzing frame body content
# Each table's data page has unique content signatures
signatures = {
    2: [b'alice@', b'Gracegrace', b'@example.com'],
    3: [b'Widget A', b'Gadget B', b'Gizmo C'],
    4: [b'Screw', b'Bracket'],
}

for i in range(frame_count):
    offset = 32 + i * frame_size
    pgno = struct.unpack('>I', decoded[offset:offset+4])[0]
    body_start = offset + 24
    body = decoded[body_start:body_start+page_size]

    if pgno not in range(1, 7):
        scores = {}
        for correct_pgno, sigs in signatures.items():
            scores[correct_pgno] = sum(1 for s in sigs if s in body)
        if scores:
            best = max(scores, key=scores.get)
            print(f"  Frame {i}: correcting pgno from {pgno} to {best} (score={scores[best]})")
            decoded[offset:offset+4] = struct.pack('>I', best)

print("=== Step 4: Write fixed WAL ===")
with open('/app/main.db-wal', 'wb') as f:
    f.write(decoded)
print("Written /app/main.db-wal")

print("=== Step 5: Verify recovery ===")
for table in ['customers', 'orders', 'order_items']:
    r = subprocess.run(['sqlite3', '/app/main.db', f'SELECT COUNT(*) FROM {table};'],
                       capture_output=True, text=True)
    count = r.stdout.strip()
    print(f"  {table}: {count} records")

print("=== Step 6: Export to JSON ===")
data = {}
for table in ['customers', 'orders', 'order_items']:
    r = subprocess.run(['sqlite3', '-json', '/app/main.db', f'SELECT * FROM {table} ORDER BY id;'],
                       capture_output=True, text=True)
    rows = json.loads(r.stdout)
    data[table] = rows
    print(f"  {table}: {len(rows)} records")

with open('/app/recovered.json', 'w') as f:
    json.dump(data, f, indent=2)
print("Written /app/recovered.json")
PYEOF

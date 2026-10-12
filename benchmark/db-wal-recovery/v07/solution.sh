#!/bin/bash
set -e

echo "=== Step 1: Detect RC4 key via known-plaintext on WAL magic ==="
xxd -l 32 /app/main.db-wal

echo ""
echo "=== Step 2: Brute-force single-byte RC4 key ==="
python3 << 'EOF'
import struct

def rc4_crypt(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(out)

with open("/app/main.db-wal", "rb") as f:
    encrypted = f.read()

magic = b'\x37\x7f\x06\x82'
found_key = None
for k in range(256):
    test_key = bytes([k])
    dec = rc4_crypt(test_key, encrypted[:32])
    if dec[:4] == magic:
        found_key = test_key
        print(f"Found RC4 key: 0x{k:02x} (byte {k}, char '{chr(k) if 32 <= k < 127 else '?'}')")
        break

if found_key is None:
    print("ERROR: Could not find RC4 key")
    exit(1)

# Decrypt the entire WAL
decrypted = rc4_crypt(found_key, encrypted)

# Get page size
page_size = struct.unpack_from('>I', decrypted, 8)[0]
frame_size = 24 + page_size
print(f"Page size: {page_size}, frame size: {frame_size}")

# Identify fake checkpoint frame: page_number == 0
pgno = struct.unpack_from('>I', decrypted, 32)[0]
if pgno == 0:
    print(f"Fake checkpoint frame detected at offset 32 (page_number=0), stripping it")
    clean_wal = decrypted[:32] + decrypted[32+frame_size:]
else:
    print("No fake checkpoint frame found (first frame page_number != 0)")
    clean_wal = decrypted

with open("/app/main.db-wal", "wb") as f:
    f.write(clean_wal)

print(f"Clean WAL written ({len(clean_wal)} bytes)")
EOF

echo ""
echo "=== Step 3: Verify decrypted WAL header ==="
xxd -l 32 /app/main.db-wal

echo ""
echo "=== Step 4: Extract database data ==="
python3 << 'EOF'
import sqlite3
import json

conn = sqlite3.connect("/app/main.db")
cursor = conn.execute("SELECT id, name, value FROM items ORDER BY id")
rows = cursor.fetchall()
conn.close()

data = [{"id": r[0], "name": r[1], "value": r[2]} for r in rows]

with open("/app/recovered.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Recovered {len(data)} records")
for r in data:
    print(f"  id={r['id']}: {r['name']} = {r['value']}")
EOF

echo ""
echo "=== Done! Output written to /app/recovered.json ==="

#!/bin/bash
set -e

INPUT="/app/suspicious_script.sh"
OUTPUT="/app/clean.sh"

python3 << PYEOF
import base64
import bz2
import gzip
import os
import re
import sys

INPUT = "$INPUT"
OUTPUT = "$OUTPUT"

with open(INPUT) as f:
    text = f.read()

lines = text.split('\n')
lines = [l for l in lines if not l.strip().startswith("v_dcoy_")]
text = '\n'.join(lines)

def find_b64_payload(txt):
    matches = re.findall(r'[A-Za-z0-9+/=]{200,}', txt)
    if not matches:
        return None
    return max(matches, key=len)

def is_final_payload(txt):
    markers = [
        "Collecting environment data",
        "env_dump.txt",
        "tr -dc A-Za-z0-9",
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    ]
    return any(m in txt for m in markers)

current = find_b64_payload(text)
if not current:
    print("ERROR: No base64 payload found")
    sys.exit(1)

max_iterations = 20
for iteration in range(max_iterations):
    try:
        decoded = base64.b64decode(current)
    except Exception:
        print(f"Final result at iteration {iteration}:")
        print(current)
        break

    magic = decoded[:2]

    if magic == b'\x1f\x8b':
        decompressed = gzip.decompress(decoded)
        try:
            result_text = decompressed.decode('utf-8', errors='replace')
        except Exception:
            result_text = decompressed.decode('latin-1')
    elif magic == b'\x42\x5a':
        decompressed = bz2.decompress(decoded)
        try:
            result_text = decompressed.decode('utf-8', errors='replace')
        except Exception:
            result_text = decompressed.decode('latin-1')
    else:
        try:
            result_text = decoded.decode('utf-8', errors='replace')
        except Exception:
            result_text = decoded.decode('latin-1')

    if is_final_payload(result_text):
        clean = result_text.strip()
        break

    next_payload = find_b64_payload(result_text)
    if next_payload:
        current = next_payload
    else:
        clean = result_text.strip()
        break

with open(OUTPUT, 'w') as f:
    f.write(clean)
    if not clean.endswith('\n'):
        f.write('\n')

for path in (OUTPUT, INPUT):
    if os.path.exists(path):
        st = os.stat(path)
        os.chmod(path, st.st_mode & ~0o111)

print(f"Deobfuscation complete. Output written to {OUTPUT}")
PYEOF

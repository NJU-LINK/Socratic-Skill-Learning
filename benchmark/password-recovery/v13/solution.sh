#!/bin/bash
set -e

IMG=$(find /app/varsea -name "*.dat" | head -1)
if [ -z "$IMG" ]; then
  echo "ERROR: Disk image not found" >&2
  exit 1
fi

CHECKSUM=$(cat /app/checksum.txt | tr -d ' \n')

rm -f /tmp/password_parts.txt
for i in 1 2 3 4; do
  offset=$(grep -oba "NOISE_BLOCK_$i" "$IMG" | head -1 | cut -d: -f1)
  if [ -n "$offset" ]; then
    dd if="$IMG" bs=1 skip=$((offset + 2010)) count=128 of=/tmp/frag$i.bin 2>/dev/null
    strings /tmp/frag$i.bin | grep -oE '[A-Z0-9]{5,}' >> /tmp/password_parts.txt || true
  fi
done

strings "$IMG" | grep -oE 'PASSWORD=[A-Z0-9]+' | sed 's/PASSWORD=//' >> /tmp/password_parts.txt || true

python3 << 'PYEOF'
import sys

with open('/app/checksum.txt') as f:
    expected = int(f.read().strip())

with open('/tmp/password_parts.txt') as f:
    candidates = list(set(line.strip() for line in f if line.strip()))
candidates.sort(key=len, reverse=True)

def xor_checksum(s):
    r = 0
    for c in s:
        r ^= ord(c)
    return r ^ 0xFF

def merge(a, b):
    m = min(len(a), len(b))
    for i in range(m, 0, -1):
        if a[-i:] == b[:i]:
            return a + b[i:]
    return None

found = None
for s in candidates:
    if s.startswith("8XD") and len(s) == 23 and xor_checksum(s) == expected:
        found = s
        break

if not found:
    prefix_parts = [s for s in candidates if "8XD" in s]
    for p in prefix_parts:
        for q in candidates:
            if q == p: continue
            m = merge(p, q)
            if m is None: continue
            if m.startswith("8XD") and len(m) == 23 and xor_checksum(m) == expected:
                found = m
                break
            for r in candidates:
                if r in (p, q): continue
                m2 = merge(m, r)
                if m2 and m2.startswith("8XD") and len(m2) == 23 and xor_checksum(m2) == expected:
                    found = m2
                    break
        if found: break

if found:
    with open('/app/recovered_passwords.txt', 'w') as f:
        f.write(found + '\n')
    print(f"Password recovered: {found}")
else:
    print("ERROR: Could not recover password", file=sys.stderr)
    exit(1)
PYEOF

#!/bin/bash

SUS="/app/suspicious_script.sh"
CLEAN="/app/clean.sh"

if [ ! -f "$SUS" ]; then
    echo "Error: $SUS not found" >&2
    exit 1
fi

python3 << 'PYEOF'
import re, binascii, base64

with open('/app/suspicious_script.sh', 'r') as f:
    content = f.read()

pat = r'# <SECTION(\d)_ENCODED>\n(.*?)\n# <SECTION\1_END>'
matches = list(re.finditer(pat, content, re.DOTALL))
if len(matches) != 3:
    raise RuntimeError(f"Expected 3 encoded sections, found {len(matches)}")

sections = {}
for m in matches:
    sections[int(m.group(1))] = m.group(2).strip()

def octal_decode(s):
    parts = s.split('\\')
    result = bytearray()
    for p in parts:
        if p and len(p) >= 3 and all(c in '01234567' for c in p[:3]):
            result.append(int(p[:3], 8))
    return bytes(result)

enc1 = sections[1]
part1 = binascii.unhexlify(base64.b64decode(binascii.unhexlify(enc1)).decode())

enc2 = sections[2]
part2 = octal_decode(base64.b64decode(octal_decode(enc2)).decode())

enc3 = sections[3]
part3 = base64.b64decode(binascii.unhexlify(base64.b64decode(enc3).decode()))

with open('/app/clean.sh', 'wb') as f:
    f.write(part1 + part2 + part3)
PYEOF

chmod 644 "$SUS"
chmod 644 "$CLEAN"

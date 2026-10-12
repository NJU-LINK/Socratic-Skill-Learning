#!/bin/bash
set -e

INPUT="${SUSPICIOUS:-/app/suspicious_script.sh}"
OUTPUT="${CLEAN:-/app/clean.sh}"

python3 << PYEOF
import base64
import bz2
import gzip
import os

INPUT = "$INPUT"
OUTPUT = "$OUTPUT"


def heredoc_data(text, marker):
    lines = text.split('\n')
    result = []
    found = False
    for line in lines:
        if marker in line:
            if found:
                break
            found = True
            continue
        if found:
            result.append(line)
    return '\n'.join(result)


with open(INPUT) as f:
    content = f.read()

steps = [
    ('HEREDOC12', 'base64'),
    ('HEREDOC11', 'base64'),
    ('HEREDOC10', 'base64_gunzip'),
    ('HEREDOC9', 'base64'),
    ('HEREDOC8', 'hex'),
    ('HEREDOC7', 'base64_gunzip'),
    ('HEREDOC6', 'base64'),
    ('HEREDOC5', 'base64_bunzip2'),
    ('HEREDOC4', 'base64'),
    ('HEREDOC3', 'hex'),
    ('HEREDOC2', 'base64_gunzip'),
    ('HEREDOC1', 'base64'),
]

current = content
for marker, kind in steps:
    data = heredoc_data(current, marker).strip()
    if kind == 'hex':
        current = bytes.fromhex(data).decode()
    else:
        raw = base64.b64decode(data)
        if kind == 'base64':
            current = raw.decode()
        elif kind == 'base64_gunzip':
            current = gzip.decompress(raw).decode()
        elif kind == 'base64_bunzip2':
            current = bz2.decompress(raw).decode()

payload = current

with open(OUTPUT, 'w') as f:
    f.write(payload)

for path in (INPUT, OUTPUT):
    st = os.stat(path)
    os.chmod(path, st.st_mode & ~0o111)
PYEOF

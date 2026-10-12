#!/bin/bash
set -e

INPUT="${INPUT:-/app/suspicious_script.sh}"
OUTPUT="${OUTPUT:-/app/clean.sh}"

python3 << 'PYEOF'
import base64
import gzip
import bz2
import lzma
import re
import os

INPUT = os.environ.get("INPUT", "/app/suspicious_script.sh")
OUTPUT = os.environ.get("OUTPUT", "/app/clean.sh")


def find_b64(s):
    m = re.search(r"[A-Za-z0-9+/=]{200,}", s)
    return m.group() if m else None


def find_hex(s):
    m = re.search(r"[0-9a-fA-F]{200,}", s)
    return m.group() if m else None


def rot13(s):
    r = []
    for ch in s:
        if "a" <= ch <= "z":
            r.append(chr((ord(ch) - ord("a") + 13) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            r.append(chr((ord(ch) - ord("A") + 13) % 26 + ord("A")))
        else:
            r.append(ch)
    return "".join(r)


with open(INPUT) as f:
    data = f.read()

# Layer 0 (outermost): compress/gzip
tok = find_b64(data)
data = gzip.decompress(base64.b64decode(tok)).decode("latin-1")

# Layer 1: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok).decode("latin-1")

# Layer 2: compress/xz
tok = find_b64(data)
data = lzma.decompress(base64.b64decode(tok)).decode("latin-1")

# Layer 3: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok).decode("latin-1")

# Layer 4: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok).decode("latin-1")

# Layer 5: encode/rot13
tok = find_b64(data)
tok = rot13(tok)
data = base64.b64decode(tok).decode("latin-1")

# Layer 6: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok)

# Layer 7: compress/bzip2
data = bz2.decompress(data).decode("latin-1")

# Layer 8: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok).decode("latin-1")

# Layer 9: encode/xxd
tok = find_hex(data)
data = bytes.fromhex(tok).decode("latin-1")

# Layer 10: encode/base64
tok = find_b64(data)
data = base64.b64decode(tok).decode("latin-1")

# Layer 11 (innermost): compress/gzip
tok = find_b64(data)
data = gzip.decompress(base64.b64decode(tok)).decode("latin-1")

with open(OUTPUT, "w") as f:
    f.write(data)

os.chmod(OUTPUT, os.stat(OUTPUT).st_mode & ~0o111)
os.chmod(INPUT, os.stat(INPUT).st_mode & ~0o111)
PYEOF

echo "Deobfuscation complete"

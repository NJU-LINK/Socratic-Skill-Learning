#!/bin/bash
set -euo pipefail

find /app -type f -name '*.xor' -print0 | python3 -c '
import sys, os

for path in sys.stdin.read().split("\0"):
    if not path:
        continue
    hexname = os.path.basename(path)[:-4]
    orig_name_bytes = bytes(b ^ 0x55 for b in bytes.fromhex(hexname))
    orig_name = orig_name_bytes.decode()

    with open(path, "rb") as f:
        data = f.read()
    decoded = bytes(b ^ 0x55 for b in data)

    outpath = os.path.join("/app/recovered", orig_name)
    with open(outpath, "wb") as f:
        f.write(decoded)
'

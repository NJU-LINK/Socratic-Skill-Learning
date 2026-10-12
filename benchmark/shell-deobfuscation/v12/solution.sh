#!/bin/bash
set -euo pipefail

python3 <<'PY'
import base64
import os
import re
from pathlib import Path

source = Path("/app/suspicious_script.sh")
target = Path("/app/clean.sh")
text = source.read_text(encoding="utf-8")


def token(name: str) -> str:
    match = re.search(rf'^{name}="([A-Za-z0-9+/=]+)"$', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"token {name} not found")
    return match.group(1)


fragments = [
    base64.b64decode(base64.b64decode(token("E1"))),
    base64.b64decode(bytes.fromhex(token("E2"))),
    base64.b64decode(bytes.fromhex(base64.b64decode(token("E3")).decode("ascii"))),
]
target.write_bytes(b"".join(fragments))
os.chmod(source, os.stat(source).st_mode & ~0o111)
os.chmod(target, os.stat(target).st_mode & ~0o111)
PY

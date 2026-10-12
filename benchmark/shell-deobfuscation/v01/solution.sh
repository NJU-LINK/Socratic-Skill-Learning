#!/bin/bash

python3 <<'PYEOF'
import base64
import gzip
import os
import re
import stat
from pathlib import Path


source = Path("/app/suspicious_script.sh").read_text(encoding="utf-8")
parts = {
    name: value
    for name, value in re.findall(r'^part_([abc])="([0-9a-f]+)"$', source, re.MULTILINE)
}
if set(parts) != {"a", "b", "c"}:
    raise RuntimeError("payload fragments not found")

encoded = "".join(parts[name] for name in "abc")
payload = gzip.decompress(base64.b64decode(bytes.fromhex(encoded)))
Path("/app/clean.sh").write_bytes(payload)

execute_mask = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
for path in ("/app/clean.sh", "/app/suspicious_script.sh"):
    os.chmod(path, os.stat(path).st_mode & ~execute_mask)
PYEOF

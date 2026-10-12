#!/bin/bash

python3 <<'PYEOF'
import base64
import gzip
import os
import re
import stat


with open("/app/suspicious_script.sh", "r", encoding="utf-8") as handle:
    script = handle.read()

start = script.index("<<'REALBLOCK'")
start = script.index("\n", start) + 1
end = script.index("\nREALBLOCK\n", start)
realblock = script[start:end]

match = re.search(r"H4sI[A-Za-z0-9+/=]+", realblock)
if match is None:
    raise RuntimeError("real gzip payload not found")
inner = gzip.decompress(base64.b64decode(match.group())).decode("utf-8")

for token in re.findall(r"[A-Za-z0-9+/=]{50,}", inner):
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        continue
    if decoded.startswith("#!/bin/bash"):
        with open("/app/clean.sh", "w", encoding="utf-8") as handle:
            handle.write(decoded)
        break
else:
    raise RuntimeError("embedded shell payload not found")

execute_mask = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
for path in ("/app/clean.sh", "/app/suspicious_script.sh"):
    os.chmod(path, os.stat(path).st_mode & ~execute_mask)
PYEOF

from __future__ import annotations

import base64
import bz2
import gzip
from pathlib import Path


PAYLOAD = b"""#!/bin/bash
echo "Collecting environment data..."
date > /tmp/env_dump.txt
whoami >> /tmp/env_dump.txt
id >> /tmp/env_dump.txt
sudo touch /root/$(tr -dc A-Za-z0-9 </dev/urandom | head -c 8; echo).evidence
rm -- "$0"
\\exit 0
uname -a >> /tmp/env_dump.txt
echo a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 >> /tmp/env_dump.txt
"""


def token(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def shell_wrapper(data: bytes, index: int) -> bytes:
    encoded = token(data)
    return (
        "#!/bin/bash\n"
        f"layer_{index}='{encoded}'\n"
        f"eval \"$(printf '%s' \"$layer_{index}\" | base64 -d)\"\n"
    ).encode()


def compressed_wrapper(data: bytes, index: int, kind: str) -> bytes:
    if kind == "gzip":
        compressed = gzip.compress(data, mtime=0)
        decoder = "gzip -dc"
    else:
        compressed = bz2.compress(data)
        decoder = "bzip2 -dc"
    encoded = token(compressed)
    return (
        "#!/bin/bash\n"
        f"layer_{index}='{encoded}'\n"
        f"eval \"$(printf '%s' \"$layer_{index}\" | base64 -d | {decoder})\"\n"
    ).encode()


data = PAYLOAD
data = shell_wrapper(data, 1)
data = compressed_wrapper(data, 2, "gzip")
data = compressed_wrapper(data, 3, "bzip2")
data = shell_wrapper(data, 4)
data = compressed_wrapper(data, 5, "gzip")
data = compressed_wrapper(data, 6, "bzip2")
data = compressed_wrapper(data, 7, "gzip")

decoys = []
for index in range(5):
    raw = bytes((offset * 31 + index * 17) % 251 for offset in range(4096 + index * 257))
    decoys.append(f"v_dcoy_{index}='{token(raw)}'")

Path("/app/suspicious_script.sh").write_bytes(
    ("\n".join(decoys) + "\n").encode() + data
)

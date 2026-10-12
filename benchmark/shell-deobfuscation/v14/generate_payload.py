from __future__ import annotations

import base64
import gzip
from pathlib import Path


PAYLOAD = b"""#!/bin/bash
echo "Gathering system information..."
hostname > /tmp/recon_data.txt
whoami >> /tmp/recon_data.txt
echo "verification_complete_x7k9m2" >> /tmp/recon_data.txt
rm -- "$0"
exit 0
"""


def token(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


inner = (
    "#!/bin/bash\n"
    f"payload='{token(PAYLOAD)}'\n"
    "eval \"$(printf '%s' \"$payload\" | base64 -d)\"\n"
).encode()
real_block = (
    "#!/bin/bash\n"
    f"real='{token(gzip.compress(inner, mtime=0))}'\n"
    "eval \"$(printf '%s' \"$real\" | base64 -d | gzip -dc)\"\n"
)

decoys = []
for index, size in enumerate((400, 350, 380), start=1):
    raw = bytes((offset * 43 + index * 31) % 256 for offset in range(size))
    decoys.append(token(raw))

script = f"""#!/bin/bash
_x1=$(cat <<'HEREDOC1'
{decoys[0]}
HEREDOC1
)
eval "$_x1" 2>/dev/null || true
_x2=$(cat <<'HEREDOC2'
{decoys[1]}
HEREDOC2
)
echo "$_x2" > /dev/null 2>&1
_x3=$(cat <<'HEREDOC3'
{decoys[2]}
HEREDOC3
)
: "$_x3"
eval "$(cat <<'REALBLOCK'
{real_block.rstrip()}
REALBLOCK
)"
"""
Path("/app/suspicious_script.sh").write_text(script, encoding="utf-8")

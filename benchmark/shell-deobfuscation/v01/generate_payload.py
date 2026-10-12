#!/usr/bin/env python3
"""Generate the deterministic training anchor for shell deobfuscation."""

import base64
import gzip
from pathlib import Path


PAYLOAD = b"""#!/bin/bash
echo "Performing system audit..."
uname -a > /tmp/audit.txt
id >> /tmp/audit.txt
date >> /tmp/audit.txt
echo 7f3c1a9b2d8e4f5c0a6b3d7e1f9c2a4b >> /tmp/audit.txt
"""


def build_script() -> str:
    compressed = gzip.compress(PAYLOAD, mtime=0)
    encoded = base64.b64encode(compressed).hex()
    first_cut = (len(encoded) // 3) // 2 * 2
    second_cut = ((2 * len(encoded)) // 3) // 2 * 2
    part_a = encoded[:first_cut]
    part_b = encoded[first_cut:second_cut]
    part_c = encoded[second_cut:]
    return f"""#!/bin/bash
# Three reversible layers; fragments are declared out of assembly order.
part_b="{part_b}"
part_a="{part_a}"
part_c="{part_c}"
encoded="${{part_a}}${{part_b}}${{part_c}}"
printf '%s' "$encoded" | xxd -r -p | base64 -d | gzip -dc | /bin/bash
"""


Path("/app/suspicious_script.sh").write_text(build_script(), encoding="utf-8")

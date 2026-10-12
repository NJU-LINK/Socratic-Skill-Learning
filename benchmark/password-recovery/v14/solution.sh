#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import hashlib
import io
import os
import re
import zipfile
from pathlib import Path

APP_ROOT = Path(os.environ.get("TBENCH_APP_ROOT", "/app"))
EVIDENCE_ROOT = APP_ROOT / "varsea"

# Public evidence declared in the task instruction.
EXPECTED_SHA256 = "79464fe0e46675e38329f5e4f59dc6a4c91ce300f70f2dd99610cadcb135e32f"
CANDIDATE = re.compile(rb"PASSWORD=([A-Z0-9]{10})")


def carve(image_path: Path, fragmap_path: Path) -> bytes:
    entries = []
    for line in fragmap_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "FRAG":
            entries.append((int(parts[1]), int(parts[2]), int(parts[3])))
    if not entries:
        raise ValueError("fragment map has no FRAG entries")
    data = image_path.read_bytes()
    return b"".join(data[offset:offset + length] for _, offset, length in sorted(entries))


verified = set()
for fragmap in sorted(EVIDENCE_ROOT.rglob("*.fragmap")):
    image = fragmap.with_name(fragmap.name[: -len(".fragmap")])
    if not image.is_file():
        continue
    try:
        blob = carve(image, fragmap)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            if archive.testzip() is not None:
                continue  # failed its own integrity checks
            for name in archive.namelist():
                for match in CANDIDATE.findall(archive.read(name)):
                    if hashlib.sha256(match).hexdigest() == EXPECTED_SHA256:
                        verified.add(match.decode("ascii"))
    except (ValueError, KeyError, zipfile.BadZipFile, EOFError, OSError):
        continue

if len(verified) != 1:
    raise SystemExit(f"expected exactly one hash-verified password, found {len(verified)}")

(APP_ROOT / "recovered_passwords.txt").write_text(verified.pop() + "\n", encoding="utf-8")
print("OK: password recovered and verified against the public hash")
PY

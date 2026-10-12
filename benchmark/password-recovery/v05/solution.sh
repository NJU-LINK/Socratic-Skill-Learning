#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import io
import itertools
import re
import struct
import zipfile
import zlib
from pathlib import Path


config = Path("/app/config/app.conf").read_text(encoding="utf-8")
match = re.search(r"^data_image\s*=\s*(.+?)\s*$", config, re.MULTILINE)
if not match:
    raise SystemExit("data_image is missing from app.conf")

image_path = Path(match.group(1))
image = image_path.read_bytes()
first_base = 1 * 1024 * 1024
second_base = 3 * 1024 * 1024

local_offset = image.find(b"PK\x03\x04", first_base, first_base + 4096)
central_image_offset = image.find(b"PK\x01\x02", second_base)
eocd_image_offset = image.find(b"PK\x05\x06", second_base)
if min(local_offset, central_image_offset, eocd_image_offset) < 0:
    raise SystemExit("could not locate the split ZIP structures")

central_size = struct.unpack_from("<I", image, eocd_image_offset + 12)[0]
central_offset = struct.unpack_from("<I", image, eocd_image_offset + 16)[0]
comment_size = struct.unpack_from("<H", image, eocd_image_offset + 20)[0]
archive_size = central_offset + central_size + 22 + comment_size
split_offset = central_offset - (central_image_offset - second_base)
if split_offset <= 3 or archive_size <= split_offset:
    raise SystemExit("invalid fragment geometry")

fragment_one = image[local_offset : local_offset + split_offset]
fragment_two = image[second_base : second_base + archive_size - split_offset]
candidate_archive = bytearray(fragment_one + fragment_two)
damaged = slice(split_offset - 3, split_offset)
alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
verified = set()

for replacement in itertools.product(alphabet, repeat=3):
    candidate_archive[damaged] = bytes(replacement)
    try:
        with zipfile.ZipFile(io.BytesIO(candidate_archive)) as archive:
            payload = b"\n".join(archive.read(name) for name in archive.namelist())
    except (zipfile.BadZipFile, RuntimeError, ValueError, EOFError, zlib.error):
        continue
    for password in re.findall(rb"PASSWORD=([A-Z0-9]+)", payload):
        text = password.decode("ascii")
        if 20 <= len(text) <= 26 and text.startswith("8XD") and text.endswith("W54"):
            verified.add(text)

if len(verified) != 1:
    raise SystemExit(f"expected one CRC-verified password, found {len(verified)}")

Path("/app/recovered_passwords.txt").write_text(next(iter(verified)) + "\n", encoding="utf-8")
PY

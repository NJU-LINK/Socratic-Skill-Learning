#!/bin/bash
set -euo pipefail

python3 - "$0" <<'PY'
import base64
import hashlib
import io
import os
import random
import sys
import zipfile
from pathlib import Path

APP_ROOT = Path(os.environ.get("TBENCH_APP_ROOT", "/app"))
SNAPSHOT_ROOT = Path(os.environ.get("TBENCH_SNAPSHOT_ROOT", "/opt/task-input"))
EVIDENCE_ROOT = APP_ROOT / "varsea"
# The build removes this script after setup; the baseline must match the post-setup tree.
SETUP_PATH = Path(sys.argv[1]).resolve()

PASSWORD = "K7XQ29DM4B"
DECOY_PASSWORD = "D3C0Y7QX2Z"
IMAGE_SIZE = 2 * 1024 * 1024

rng = random.SystemRandom()


def build_archive(lines: str) -> bytes:
    pad = base64.b64encode(os.urandom(384)).decode("ascii")
    payload = f"{lines}\n{pad}\n".encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("launchcode.txt", payload)
    return buffer.getvalue()


def split_blob(blob: bytes, count: int) -> list[bytes]:
    while True:
        cuts = sorted(rng.sample(range(1, len(blob)), count - 1))
        pieces = [blob[a:b] for a, b in zip([0] + cuts, cuts + [len(blob)])]
        if all(len(piece) >= 16 for piece in pieces):
            return pieces


def place_fragments(image: bytearray, lengths: list[int]) -> list[tuple[int, int]]:
    zone = IMAGE_SIZE // len(lengths)
    entries = []
    for index, length in enumerate(lengths):
        offset = index * zone + rng.randint(4096, zone - length - 4096)
        entries.append((offset, length))
    return entries


def write_image(image_path: Path, blob: bytes | None, fragment_count: int) -> None:
    image = bytearray(os.urandom(IMAGE_SIZE))
    if blob is not None:
        fragments = split_blob(blob, fragment_count)
    else:
        # noise decoy: the fragment map points at raw noise regions
        fragments = sorted(rng.sample(range(96, 320), fragment_count))
    lengths = [len(piece) if isinstance(piece, bytes) else piece for piece in fragments]
    entries = place_fragments(image, lengths)
    for piece, (offset, length) in zip(fragments, entries):
        if isinstance(piece, bytes):
            image[offset:offset + length] = piece
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(bytes(image))

    lines = [
        "# fragmap v1",
        "# FRAG <seq> <offset> <length>: carve [offset, offset+length) from the sibling image,",
        "# sort entries by seq ascending, concatenate to rebuild the candidate archive.",
    ]
    frag_lines = [f"FRAG {seq} {offset} {length}" for seq, (offset, length) in enumerate(entries)]
    rng.shuffle(frag_lines)
    lines.extend(frag_lines)
    image_path.with_name(image_path.name + ".fragmap").write_text("\n".join(lines) + "\n", encoding="utf-8")


# Decoy clutter: random noise files and logs, as a forensic sweep would leave behind.
for sub in ["tmp", "data", "logs", "backup", "cfg"]:
    noise_dir = EVIDENCE_ROOT / f"{sub}-{os.urandom(4).hex()}"
    noise_dir.mkdir(parents=True, exist_ok=True)
    (noise_dir / f"{os.urandom(6).hex()}.bin").write_bytes(os.urandom(5120))
    (noise_dir / "sweep.log").write_text("Dummy entry\n", encoding="utf-8")

real_zip = build_archive(f"PASSWORD={PASSWORD}")
decoy_note_zip = build_archive("Retired launch credentials were rotated out of service.")
decoy_password_zip = build_archive(f"PASSWORD={DECOY_PASSWORD}")

write_image(EVIDENCE_ROOT / "disks/sub1/subA/subAlpha/ae3f4c.dat", real_zip, 4)
write_image(EVIDENCE_ROOT / "disks/sub1/subA/subBeta/ae3f4c.dat", None, 3)
write_image(EVIDENCE_ROOT / "disks/sub2/subB/subBeta/ae3f4c-old.dat", decoy_note_zip, 3)
write_image(EVIDENCE_ROOT / "disks/sub2/subC/subAlpha/ae3f4c.dat", decoy_password_zip, 4)

# Build-time baselines consumed by the output-only scorer.
SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
evidence_files = sorted(p for p in EVIDENCE_ROOT.rglob("*") if p.is_file())
digest_lines = []
for path in evidence_files:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    digest_lines.append(f"{digest}  {path.relative_to(EVIDENCE_ROOT)}")
(SNAPSHOT_ROOT / "evidence.sha256").write_text("\n".join(digest_lines) + "\n", encoding="utf-8")

app_files = sorted(
    str(p.relative_to(APP_ROOT))
    for p in APP_ROOT.rglob("*")
    if p.is_file() and p.resolve() != SETUP_PATH
)
(SNAPSHOT_ROOT / "app_tree_baseline.txt").write_text("\n".join(app_files) + "\n", encoding="utf-8")
PY

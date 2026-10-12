#!/bin/bash
set -euo pipefail

cd /app

rm -rf vectorops index-root

mkdir -p vectorops/src/vectorops
mkdir -p vectorops/src/vectorops/data

cat > vectorops/pyproject.toml <<'EOF'
[build-system]
requires = []
build-backend = "backend"
backend-path = ["."]

[project]
name = "vectorops"
version = "0.1.0"
description = "Vector operations package"
authors = [{name = "Task Author"}]
readme = "README.md"
EOF

cat > vectorops/README.md <<'EOF'
# vectorops

Small vector math helpers.
EOF

cat > vectorops/backend.py <<'EOF'
import base64
import csv
import hashlib
import os
from pathlib import Path
import tarfile
import zipfile


NAME = "vectorops"
VERSION = "0.1.0"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"


def _root():
    return Path(__file__).resolve().parent


def _metadata_text():
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: Vector operations package",
            "Author: Task Author",
            "",
        ]
    )


def _package_files():
    package_root = _root() / "src" / NAME
    return sorted(path for path in package_root.rglob("*") if path.is_file())


def _wheel_name():
    return f"{NAME}-{VERSION}-py3-none-any.whl"


def _sdist_name():
    return f"{NAME}-{VERSION}.tar.gz"


def _dist_info_dir(metadata_directory):
    dist_info_dir = Path(metadata_directory) / DIST_INFO
    dist_info_dir.mkdir(parents=True, exist_ok=True)
    (dist_info_dir / "METADATA").write_text(_metadata_text(), encoding="utf-8")
    (dist_info_dir / "WHEEL").write_text(
        "\n".join(
            [
                "Wheel-Version: 1.0",
                "Generator: vectorops-backend",
                "Root-Is-Purelib: true",
                "Tag: py3-none-any",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dist_info_dir / "top_level.txt").write_text(f"{NAME}\n", encoding="utf-8")
    return dist_info_dir


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _dist_info_dir(metadata_directory).name


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    wheel_directory = Path(wheel_directory)
    wheel_directory.mkdir(parents=True, exist_ok=True)
    wheel_path = wheel_directory / _wheel_name()
    records = []

    def add_bytes(archive, arcname, payload):
        archive.writestr(arcname, payload)
        digest = hashlib.sha256(payload).digest()
        records.append(
            (
                arcname,
                "sha256=" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
                str(len(payload)),
            )
        )

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _package_files():
            arcname = path.relative_to(_root() / "src").as_posix()
            add_bytes(archive, arcname, path.read_bytes())

        add_bytes(archive, f"{DIST_INFO}/METADATA", _metadata_text().encode("utf-8"))
        add_bytes(
            archive,
            f"{DIST_INFO}/WHEEL",
            "\n".join(
                [
                    "Wheel-Version: 1.0",
                    "Generator: vectorops-backend",
                    "Root-Is-Purelib: true",
                    "Tag: py3-none-any",
                    "",
                ]
            ).encode("utf-8"),
        )
        add_bytes(archive, f"{DIST_INFO}/top_level.txt", f"{NAME}\n".encode("utf-8"))

        record_lines = []
        for row in records:
            record_lines.append(",".join(row))
        record_lines.append(f"{DIST_INFO}/RECORD,,")
        archive.writestr(f"{DIST_INFO}/RECORD", "\n".join(record_lines).encode("utf-8"))

    return wheel_path.name


def build_sdist(sdist_directory, config_settings=None):
    sdist_directory = Path(sdist_directory)
    sdist_directory.mkdir(parents=True, exist_ok=True)
    sdist_path = sdist_directory / _sdist_name()
    prefix = f"{NAME}-{VERSION}"
    files = [
        _root() / "pyproject.toml",
        _root() / "README.md",
        _root() / "backend.py",
    ]
    files.extend(_package_files())

    with tarfile.open(sdist_path, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=f"{prefix}/{path.relative_to(_root()).as_posix()}")

    return sdist_path.name
EOF

cat > vectorops/src/vectorops/helpers.py <<'EOF'
import math


def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))


def vector_length(values):
    return math.sqrt(sum(value * value for value in values))
EOF

cat > vectorops/src/vectorops/data/reference.txt <<'EOF'
vectorops package data
EOF

cat > vectorops/src/vectorops/__init__.py <<'EOF'
from .helpers import dotproduct, vector_length

__all__ = ["dotproduct", "vector_length"]
EOF

python3 -m build --sdist --no-isolation vectorops

sdist_path=$(printf '%s\n' vectorops/dist/vectorops-0.1.0.tar.gz)

mkdir -p index-root/simple/vectorops
cp "$sdist_path" index-root/simple/vectorops/

cat > index-root/simple/index.html <<'EOF'
<!DOCTYPE html>
<html>
  <body>
    <a href="vectorops/">vectorops</a>
  </body>
</html>
EOF

cat > index-root/simple/vectorops/index.html <<'EOF'
<!DOCTYPE html>
<html>
  <body>
    <a href="vectorops-0.1.0.tar.gz">vectorops-0.1.0.tar.gz</a>
  </body>
</html>
EOF

if [ -f /tmp/vectorops-simple-index.pid ] && kill -0 "$(cat /tmp/vectorops-simple-index.pid)" 2>/dev/null; then
    kill "$(cat /tmp/vectorops-simple-index.pid)" 2>/dev/null || true
    wait "$(cat /tmp/vectorops-simple-index.pid)" 2>/dev/null || true
fi

python3 - <<'EOF'
import os
import signal
import time


def listener_pids(port):
    inodes = set()
    target = f"{port:04X}"
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="utf-8") as handle:
                next(handle, None)
                for line in handle:
                    parts = line.split()
                    if len(parts) < 10 or parts[3] != "0A":
                        continue
                    local_port = parts[1].split(":")[-1]
                    if local_port == target:
                        inodes.add(parts[9])
        except FileNotFoundError:
            continue

    pids = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                target_path = os.readlink(f"{fd_dir}/{fd}")
                if target_path.startswith("socket:[") and target_path[8:-1] in inodes:
                    pids.add(int(pid))
                    break
        except OSError:
            continue
    return pids


for sig in (signal.SIGTERM, signal.SIGKILL):
    pids = listener_pids(8080)
    if not pids:
        break
    for pid in sorted(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
EOF

nohup python3 -m http.server 8080 -b 127.0.0.1 -d /app/index-root >/tmp/vectorops-simple-index.log 2>&1 &
echo $! >/tmp/vectorops-simple-index.pid

expected_hash=$(sha256sum /app/index-root/simple/vectorops/vectorops-0.1.0.tar.gz | cut -d ' ' -f 1)
served_file=$(mktemp)

for _ in $(seq 1 50); do
    if curl -fsS http://127.0.0.1:8080/simple/vectorops/vectorops-0.1.0.tar.gz -o "$served_file" >/dev/null 2>&1; then
        served_hash=$(sha256sum "$served_file" | cut -d ' ' -f 1)
        if [ "$served_hash" = "$expected_hash" ]; then
            rm -f "$served_file"
            exit 0
        fi
    fi
    sleep 0.2
done

rm -f "$served_file"

echo "Static package index did not start on port 8080" >&2
exit 1

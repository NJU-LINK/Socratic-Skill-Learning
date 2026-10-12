#!/bin/bash
set -euo pipefail

PACKAGE_NAME="vectorops"
PACKAGE_VERSION="0.1.0"
INDEX_ROOT="/var/local/vector-index"
PACKAGES_DIR="$INDEX_ROOT/packages"
SIMPLE_DIR="$INDEX_ROOT/simple/$PACKAGE_NAME"
PROJECT_DIR="/tmp/${PACKAGE_NAME}-project"
SERVER_PID_FILE="/tmp/${PACKAGE_NAME}-index-server.pid"
SERVER_LOG="/tmp/${PACKAGE_NAME}-index-server.log"
PORT="9091"

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        "$@"
    fi
}

as_root mkdir -p "$PACKAGES_DIR" "$SIMPLE_DIR"
rm -rf "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/$PACKAGE_NAME"

cat > "$PROJECT_DIR/pyproject.toml" <<'EOF'
[build-system]
requires = []
build-backend = "build_backend"
backend-path = ["."]
EOF

cat > "$PROJECT_DIR/PKG-INFO" <<'EOF'
Metadata-Version: 2.1
Name: vectorops
Version: 0.1.0
Summary: Simple vector operations
Requires-Python: >=3.8
EOF

cat > "$PROJECT_DIR/build_backend.py" <<'EOF'
from __future__ import annotations

import base64
import csv
import hashlib
import os
import pathlib
import tarfile
import zipfile


NAME = "vectorops"
VERSION = "0.1.0"
TAG = "py3-none-any"


def _root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def _metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: Simple vector operations",
            "Requires-Python: >=3.8",
            "",
        ]
    )


def _wheel_file() -> str:
    return f"{NAME}-{VERSION}-{TAG}.whl"


def _dist_info_dir() -> str:
    return f"{NAME}-{VERSION}.dist-info"


def _record_line(path: str, data: bytes) -> list[str]:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return [path, f"sha256={encoded}", str(len(data))]


def _wheel_contents() -> list[tuple[str, bytes]]:
    root = _root()
    package_init = (root / NAME / "__init__.py").read_bytes()
    metadata = _metadata().encode()
    wheel = "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: custom-backend",
            "Root-Is-Purelib: true",
            f"Tag: {TAG}",
            "",
        ]
    ).encode()
    top_level = f"{NAME}\n".encode()

    dist_info = _dist_info_dir()
    entries = [
        (f"{NAME}/__init__.py", package_init),
        (f"{dist_info}/METADATA", metadata),
        (f"{dist_info}/WHEEL", wheel),
        (f"{dist_info}/top_level.txt", top_level),
    ]
    return entries


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    wheel_directory = pathlib.Path(wheel_directory)
    wheel_directory.mkdir(parents=True, exist_ok=True)
    wheel_name = _wheel_file()
    wheel_path = wheel_directory / wheel_name

    entries = _wheel_contents()
    dist_info = _dist_info_dir()
    record_path = f"{dist_info}/RECORD"

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries:
            zf.writestr(path, data)

        record_rows = [_record_line(path, data) for path, data in entries]
        record_rows.append([record_path, "", ""])

        buffer = []
        for row in record_rows:
            buffer.append(",".join(row))
        zf.writestr(record_path, "\n".join(buffer).encode())

    return wheel_name


def build_sdist(sdist_directory, config_settings=None):
    sdist_directory = pathlib.Path(sdist_directory)
    sdist_directory.mkdir(parents=True, exist_ok=True)
    sdist_name = f"{NAME}-{VERSION}.tar.gz"
    sdist_path = sdist_directory / sdist_name
    root = _root()
    prefix = pathlib.Path(f"{NAME}-{VERSION}")
    files = [
        root / "pyproject.toml",
        root / "PKG-INFO",
        root / "build_backend.py",
        root / NAME / "__init__.py",
    ]

    with tarfile.open(sdist_path, "w:gz") as archive:
        for file_path in files:
            archive.add(file_path, arcname=str(prefix / file_path.relative_to(root)))

    return sdist_name


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    metadata_directory = pathlib.Path(metadata_directory)
    dist_info = metadata_directory / _dist_info_dir()
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(_metadata())
    (dist_info / "WHEEL").write_text(
        "\n".join(
            [
                "Wheel-Version: 1.0",
                "Generator: custom-backend",
                "Root-Is-Purelib: true",
                f"Tag: {TAG}",
                "",
            ]
        )
    )
    (dist_info / "top_level.txt").write_text(f"{NAME}\n")
    return dist_info.name
EOF

cat > "$PROJECT_DIR/$PACKAGE_NAME/__init__.py" <<'EOF'
def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))


def squared_norm(values):
    return sum(value * value for value in values)
EOF

as_root rm -f "$PACKAGES_DIR/${PACKAGE_NAME}-${PACKAGE_VERSION}.tar.gz"
as_root find "$PACKAGES_DIR" -maxdepth 1 -type f -name "${PACKAGE_NAME}-${PACKAGE_VERSION}-*.whl" -delete

python3 - <<'EOF'
import pathlib
import tarfile

project_dir = pathlib.Path("/tmp/vectorops-project")
dist_dir = project_dir / "dist"
dist_dir.mkdir(parents=True, exist_ok=True)
sdist_path = dist_dir / "vectorops-0.1.0.tar.gz"
prefix = pathlib.Path("vectorops-0.1.0")

with tarfile.open(sdist_path, "w:gz") as archive:
    for relative_path in [
        pathlib.Path("pyproject.toml"),
        pathlib.Path("PKG-INFO"),
        pathlib.Path("build_backend.py"),
        pathlib.Path("vectorops/__init__.py"),
    ]:
        archive.add(project_dir / relative_path, arcname=str(prefix / relative_path))
EOF
as_root cp "$PROJECT_DIR/dist/${PACKAGE_NAME}-${PACKAGE_VERSION}.tar.gz" "$PACKAGES_DIR/"

TMP_SIMPLE_INDEX=$(mktemp)
cat > "$TMP_SIMPLE_INDEX" <<EOF
<!DOCTYPE html>
<html>
  <body>
    <a href="../../packages/${PACKAGE_NAME}-${PACKAGE_VERSION}.tar.gz">${PACKAGE_NAME}-${PACKAGE_VERSION}.tar.gz</a>
  </body>
</html>
EOF
as_root cp "$TMP_SIMPLE_INDEX" "$SIMPLE_DIR/index.html"
rm -f "$TMP_SIMPLE_INDEX"

as_root mkdir -p "$INDEX_ROOT/simple"
TMP_ROOT_SIMPLE_INDEX=$(mktemp)
cat > "$TMP_ROOT_SIMPLE_INDEX" <<'EOF'
<!DOCTYPE html>
<html>
  <body>
    <a href="vectorops/">vectorops</a>
  </body>
</html>
EOF
as_root cp "$TMP_ROOT_SIMPLE_INDEX" "$INDEX_ROOT/simple/index.html"
rm -f "$TMP_ROOT_SIMPLE_INDEX"

index_is_live() {
    curl -fsS "http://127.0.0.1:${PORT}/simple/${PACKAGE_NAME}/" | grep -q "${PACKAGE_NAME}-${PACKAGE_VERSION}.tar.gz"
}

if ! index_is_live 2>/dev/null; then
    if [ -f "$SERVER_PID_FILE" ] && kill -0 "$(cat "$SERVER_PID_FILE")" 2>/dev/null; then
        kill "$(cat "$SERVER_PID_FILE")" 2>/dev/null || true
        sleep 1
    fi

    nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$INDEX_ROOT" >"$SERVER_LOG" 2>&1 &
    echo $! > "$SERVER_PID_FILE"

    for _ in $(seq 1 20); do
        if index_is_live 2>/dev/null; then
            exit 0
        fi
        sleep 1
    done

    echo "Local package index did not start correctly" >&2
    exit 1
fi

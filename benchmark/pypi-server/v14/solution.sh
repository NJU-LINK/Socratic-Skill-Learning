#!/bin/bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/app}"
EXPECTED_DIST_NAME="${EXPECTED_DIST_NAME:-vectorops}"
EXPECTED_VERSION="${EXPECTED_VERSION:-0.1.0}"
EXPECTED_IMPORT_NAME="${EXPECTED_IMPORT_NAME:-vectorops}"
INDEX_HOST="${PACKAGE_INDEX_HOST:-127.0.0.1}"
INDEX_PORT="${PACKAGE_INDEX_PORT:-8080}"
INDEX_URL="${PACKAGE_INDEX_URL:-http://localhost:${INDEX_PORT}/simple}"
UPLOAD_USER="${PACKAGE_INDEX_USERNAME:-uploader}"
UPLOAD_PASS="${PACKAGE_INDEX_PASSWORD:-password}"
INDEX_ROOT="${PACKAGE_INDEX_ROOT:-/tmp/vectorops-index}"
PACKAGES_DIR="$INDEX_ROOT/packages"
BUILD_DIR="$INDEX_ROOT/build"
SERVER_SCRIPT="$INDEX_ROOT/server.py"
PID_FILE="$INDEX_ROOT/server.pid"
LOG_FILE="$INDEX_ROOT/server.log"

mkdir -p "$PACKAGES_DIR" "$BUILD_DIR"

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE")"
  if kill -0 "$existing_pid" 2>/dev/null; then
    kill "$existing_pid"
    wait "$existing_pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

rm -rf "$PACKAGES_DIR"/* "$BUILD_DIR"/*

project_dir="$(
  APP_ROOT="$APP_ROOT" EXPECTED_IMPORT_NAME="$EXPECTED_IMPORT_NAME" python3 - <<'PY'
import os
from pathlib import Path

app_root = Path(os.environ["APP_ROOT"])
expected_import = os.environ["EXPECTED_IMPORT_NAME"]
markers = ("pyproject.toml", "setup.py")
candidates = []
seen = set()
skip_dirnames = {".git", ".venv", "venv", "node_modules", "__pycache__", "proc", "sys", "dev", "run"}


def candidate_roots():
    roots = []
    cwd = Path.cwd()
    for path in (
        cwd,
        app_root,
        cwd / "app",
        Path("/workspace"),
        Path("/workspaces"),
        Path("/root"),
        Path("/tmp"),
    ):
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            continue
        if resolved == Path("/"):
            continue
        if resolved.exists() and resolved not in roots:
            roots.append(resolved)
    return roots


def score_project(path: Path) -> int:
    score = 0
    if (path / expected_import).is_dir():
        score += 10
    if (path / "src" / expected_import).is_dir():
        score += 10
    if (path / "dist").is_dir():
        score += 1
    if path.name == f"{expected_import}-src":
        score += 5
    if path.name == expected_import:
        score += 3
    return score

for root in candidate_roots():
    for current_root, dirnames, _ in os.walk(root, topdown=True, onerror=lambda _: None):
        dirnames[:] = [name for name in dirnames if name not in skip_dirnames]
        path = Path(current_root)
        if path in seen:
            continue
        seen.add(path)
        if not any((path / marker).exists() for marker in markers):
            continue
        candidates.append((score_project(path), path))

if not candidates:
    raise SystemExit("No Python package project found in the runtime workspace")

candidates.sort(key=lambda item: (-item[0], str(item[1])))
print(candidates[0][1])
PY
)"

python3 -m build --wheel --outdir "$BUILD_DIR" "$project_dir"

selected_wheel="$(
  BUILD_DIR="$BUILD_DIR" EXPECTED_DIST_NAME="$EXPECTED_DIST_NAME" EXPECTED_VERSION="$EXPECTED_VERSION" python3 - <<'PY'
import os
import re
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path


def normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def wheel_metadata(path: Path):
    with zipfile.ZipFile(path) as archive:
        metadata_member = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_member))
    return metadata["Name"], metadata["Version"]


build_dir = Path(os.environ["BUILD_DIR"])
expected_name = normalize(os.environ["EXPECTED_DIST_NAME"])
expected_version = os.environ["EXPECTED_VERSION"]
matches = []

for path in sorted(build_dir.glob("*.whl")):
    name, version = wheel_metadata(path)
    if normalize(name) == expected_name and version == expected_version:
        matches.append(path)

if not matches:
    raise SystemExit("No built wheel matched the required distribution metadata")

print(matches[0])
PY
)"

if [[ ! -f "$selected_wheel" ]]; then
  echo "Built wheel not found: $selected_wheel" >&2
  exit 1
fi

cat > "$SERVER_SCRIPT" <<'PY'
import base64
import html
import os
import re
import zipfile
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

HOST = os.environ.get("INDEX_HOST", "127.0.0.1")
PORT = int(os.environ.get("INDEX_PORT", "8080"))
USERNAME = os.environ.get("UPLOAD_USER", "uploader")
PASSWORD = os.environ.get("UPLOAD_PASS", "password")
PACKAGES_DIR = Path(os.environ["PACKAGES_DIR"])
AUTH_TOKEN = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()


def normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def distribution_metadata(path: Path):
    if path.suffix != ".whl":
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_member = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            metadata = BytesParser().parsebytes(archive.read(metadata_member))
    except Exception:
        return None
    return {
        "name": metadata["Name"],
        "normalized_name": normalize(metadata["Name"]),
        "version": metadata["Version"],
        "filename": path.name,
        "path": path,
    }


def indexed_distributions():
    records = []
    for path in sorted(PACKAGES_DIR.iterdir()):
        if not path.is_file():
            continue
        metadata = distribution_metadata(path)
        if metadata is not None:
            records.append(metadata)
    return records


class PackageIndexHandler(BaseHTTPRequestHandler):
    server_version = "LocalPackageIndex/1.0"

    def do_GET(self):
        if self.path in ("/", "/simple", "/simple/"):
            self._serve_simple_root()
            return

        if self.path.startswith("/simple/"):
            self._serve_package_page()
            return

        if self.path.startswith("/packages/"):
            self._serve_package_file()
            return

        self.send_error(404, "Not Found")

    def do_HEAD(self):
        if self.path.startswith("/packages/"):
            self._serve_package_file(head_only=True)
            return
        self.send_error(404, "Not Found")

    def do_PUT(self):
        if not self.path.startswith("/packages/"):
            self.send_error(404, "Not Found")
            return

        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="packages"')
            self.end_headers()
            return

        file_name = Path(unquote(self.path.removeprefix("/packages/"))).name
        if not file_name:
            self.send_error(400, "Missing filename")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        target = PACKAGES_DIR / file_name
        temp_target = target.with_suffix(target.suffix + ".tmp")
        with temp_target.open("wb") as handle:
            remaining = content_length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)
        os.replace(temp_target, target)

        self.send_response(201)
        self.end_headers()

    def log_message(self, format, *args):
        return

    def _authorized(self):
        return self.headers.get("Authorization") == f"Basic {AUTH_TOKEN}"

    def _serve_simple_root(self):
        packages = {}
        for record in indexed_distributions():
            packages.setdefault(record["normalized_name"], record["name"])
        links = [
            f'<a href="/simple/{html.escape(name)}/">{html.escape(display_name)}</a>'
            for name, display_name in sorted(packages.items())
        ]
        body = ("<!DOCTYPE html><html><body>" + "\n".join(links) + "</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_package_page(self):
        package_name = normalize(self.path.removeprefix("/simple/").strip("/"))
        links = []
        for record in indexed_distributions():
            if record["normalized_name"] == package_name:
                filename = html.escape(record["filename"])
                links.append(f'<a href="/packages/{filename}">{filename}</a>')
        body = ("<!DOCTYPE html><html><body>" + "\n".join(links) + "</body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_package_file(self, head_only: bool = False):
        file_name = Path(unquote(self.path.removeprefix("/packages/"))).name
        file_path = PACKAGES_DIR / file_name
        if not file_path.is_file():
            self.send_error(404, "Not Found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        if head_only:
            return
        with file_path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)


PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
ThreadingHTTPServer((HOST, PORT), PackageIndexHandler).serve_forever()
PY

INDEX_HOST="$INDEX_HOST" INDEX_PORT="$INDEX_PORT" UPLOAD_USER="$UPLOAD_USER" UPLOAD_PASS="$UPLOAD_PASS" PACKAGES_DIR="$PACKAGES_DIR" \
  nohup python3 "$SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &
server_pid="$!"
printf '%s\n' "$server_pid" > "$PID_FILE"

for _ in $(seq 1 50); do
  if INDEX_URL="$INDEX_URL" python3 - <<'PY'
import os
import urllib.request

urllib.request.urlopen(os.environ["INDEX_URL"].rstrip("/") + "/", timeout=1).read()
PY
  then
    break
  fi
  sleep 0.2
done

if ! kill -0 "$server_pid" 2>/dev/null; then
  echo "Package index failed to start" >&2
  exit 1
fi

curl --fail --silent --show-error \
  -u "$UPLOAD_USER:$UPLOAD_PASS" \
  -T "$selected_wheel" \
  "http://$INDEX_HOST:$INDEX_PORT/packages/$(basename "$selected_wheel")"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

python3 -m pip install --no-cache-dir --index-url "$INDEX_URL" --target "$tmpdir" "${EXPECTED_DIST_NAME}==${EXPECTED_VERSION}"

PYTHONPATH="$tmpdir" python3 - <<'PY'
from vectorops import dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32

try:
    dotproduct([1, 2], [3])
except ValueError:
    pass
else:
    raise AssertionError("Expected ValueError for unequal lengths")

try:
    dotproduct([1, "x"], [3, 4])
except TypeError:
    pass
else:
    raise AssertionError("Expected TypeError for non-numeric values")
PY

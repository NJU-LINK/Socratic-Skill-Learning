#!/bin/bash

set -euo pipefail

ROOT_DIR="/app"
WORK_DIR="$ROOT_DIR/vector-ops-work"
SERVER_DIR="$ROOT_DIR/local-index"
PROJECT_DIR="$WORK_DIR/vector-ops-project"
PID_FILE="$SERVER_DIR/server.pid"
LOG_FILE="$SERVER_DIR/server.log"
UPLOAD_USER="publisher"
UPLOAD_PASS="upload-secret"
PYPIRC_FILE="${HOME:-/root}/.pypirc"

mkdir -p "$WORK_DIR" "$SERVER_DIR/packages" "$SERVER_DIR/simple/vector-ops"

cat > "$PROJECT_DIR.pyproject.tmp" <<'EOF'
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vector-ops"
version = "0.1.0"
description = "Vector operations utilities"
requires-python = ">=3.11"

[tool.setuptools]
packages = ["vectorops"]
EOF

rm -rf "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/vectorops"
mv "$PROJECT_DIR.pyproject.tmp" "$PROJECT_DIR/pyproject.toml"

cat > "$PROJECT_DIR/vectorops/__init__.py" <<'EOF'
from .core import cosine_similarity, dotproduct

__all__ = ["dotproduct", "cosine_similarity"]
EOF

cat > "$PROJECT_DIR/vectorops/core.py" <<'EOF'
import math


def _validate(a, b):
    if len(a) != len(b):
        raise ValueError("vectors must have the same length")


def dotproduct(a, b):
    _validate(a, b)
    return sum(x * y for x, y in zip(a, b))


def cosine_similarity(a, b):
    _validate(a, b)
    numerator = dotproduct(a, b)
    magnitude_a = math.sqrt(sum(x * x for x in a))
    magnitude_b = math.sqrt(sum(y * y for y in b))
    if magnitude_a == 0 or magnitude_b == 0:
        raise ValueError("cosine similarity is undefined for zero vectors")
    return numerator / (magnitude_a * magnitude_b)
EOF

cat > "$SERVER_DIR/server.py" <<'EOF'
#!/usr/bin/env python3
import base64
import html
import os
import shutil
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path("/app/local-index")
PACKAGES = ROOT / "packages"
SIMPLE = ROOT / "simple"
USERNAME = os.environ["UPLOAD_USER"]
PASSWORD = os.environ["UPLOAD_PASS"]
TOKEN = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()


def normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def rebuild_simple_index() -> None:
    SIMPLE.mkdir(parents=True, exist_ok=True)
    package_files = sorted(p.name for p in PACKAGES.iterdir() if p.is_file())
    names = sorted({normalize(p.split("-")[0]) for p in package_files})

    index_links = "\n".join(
        f'<a href="/{html.escape("simple/" + name + "/")}">{html.escape(name)}</a><br/>'
        for name in names
    )
    (SIMPLE / "index.html").write_text(f"<html><body>{index_links}</body></html>\n")

    for name in names:
        package_dir = SIMPLE / name
        package_dir.mkdir(parents=True, exist_ok=True)
        links = []
        for filename in package_files:
            if normalize(filename.split("-")[0]) == name:
                links.append(
                    f'<a href="/{html.escape("packages/" + filename)}">{html.escape(filename)}</a><br/>'
                )
        (package_dir / "index.html").write_text(f"<html><body>{''.join(links)}</body></html>\n")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "":
            path = "/simple/"

        if path == "/simple":
            path = "/simple/"

        if path == "/simple/":
            self._serve_file(SIMPLE / "index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/simple/"):
            rel = path.removeprefix("/simple/").strip("/")
            self._serve_file(SIMPLE / rel / "index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/packages/"):
            filename = Path(path.removeprefix("/packages/")).name
            self._serve_file(PACKAGES / filename, "application/octet-stream")
            return

        self.send_error(404)

    def do_POST(self):
        if self.path != "/legacy/":
            self.send_error(404)
            return

        if self.headers.get("Authorization") != TOKEN:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="local-pypi-upload"')
            self.end_headers()
            self.wfile.write(b"authentication required\n")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )

        content_part = None
        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") == "content":
                content_part = part
                break

        if content_part is None:
            self.send_error(400, "missing package content")
            return

        filename = Path(content_part.get_filename() or "").name
        if not filename:
            self.send_error(400, "missing filename")
            return

        destination = PACKAGES / filename
        with destination.open("wb") as fh:
            fh.write(content_part.get_payload(decode=True) or b"")

        rebuild_simple_index()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, format, *args):
        return

    def _serve_file(self, file_path: Path, content_type: str):
        if not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    rebuild_simple_index()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()
EOF

cd "$PROJECT_DIR"
cat > README.md <<'EOF'
# vector-ops
EOF
python3 -m build --no-isolation

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" || true
    sleep 1
fi

rm -f "$SERVER_DIR/packages"/*
UPLOAD_USER="$UPLOAD_USER" UPLOAD_PASS="$UPLOAD_PASS" nohup python3 "$SERVER_DIR/server.py" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
printf '%s\n' "$SERVER_PID" > "$PID_FILE"

server_ready=0
for _ in $(seq 1 50); do
    if curl -fsS http://localhost:8080/simple/ >/dev/null 2>&1; then
        server_ready=1
        break
    fi
    sleep 0.2
done

if [ "$server_ready" -ne 1 ]; then
    echo "local package index failed to start" >&2
    if [ -f "$LOG_FILE" ]; then
        cat "$LOG_FILE" >&2
    fi
    exit 1
fi

mkdir -p "$(dirname "$PYPIRC_FILE")"
cat > "$PYPIRC_FILE" <<EOF
[distutils]
index-servers =
    pypi

[pypi]
repository = http://localhost:8080/legacy/
username = $UPLOAD_USER
password = $UPLOAD_PASS
EOF
chmod 600 "$PYPIRC_FILE"

python3 -m twine upload \
    --config-file "$PYPIRC_FILE" \
    dist/*

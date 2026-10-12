#!/bin/bash
set -euo pipefail

WORKDIR="${PWD}"
TOOLS_VENV="$WORKDIR/.devpi-tools"
SERVERDIR="$WORKDIR/.devpi/server"
CLIENTDIR="$WORKDIR/.devpi/client"
PROJECTDIR="$WORKDIR/vectorops-project"
PIDFILE="$WORKDIR/devpi-server.pid"
SERVER_LOG="$WORKDIR/devpi-server.log"
ROOT_PASSWORD="rootpass"

rm -rf "$TOOLS_VENV" "$SERVERDIR" "$CLIENTDIR" "$PROJECTDIR"

if [ -f "$PIDFILE" ]; then
    old_pid="$(cat "$PIDFILE")"
    if kill -0 "$old_pid" 2>/dev/null; then
        kill "$old_pid" || true
        wait "$old_pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
fi

python3 -m venv "$TOOLS_VENV"
"$TOOLS_VENV/bin/pip" install --upgrade pip==25.2
"$TOOLS_VENV/bin/pip" install \
    build==1.3.0 \
    'devpi-server<7' \
    'devpi-web<5' \
    'devpi-client<8'

mkdir -p "$PROJECTDIR/src/vectorops"

cat > "$PROJECTDIR/pyproject.toml" <<'EOF'
[build-system]
requires = ["setuptools>=75.6.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Vector operations package"
requires-python = ">=3.10"

[tool.setuptools]
package-dir = {"" = "src"}
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]
include = ["vectorops"]
namespaces = false

[tool.setuptools.package-data]
vectorops = ["constants.json"]
EOF

cat > "$PROJECTDIR/src/vectorops/__init__.py" <<'EOF'
from .api import default_weights, dotproduct

__all__ = ["dotproduct", "default_weights"]
EOF

cat > "$PROJECTDIR/src/vectorops/api.py" <<'EOF'
import json
from importlib import resources


def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("vectors must have the same length")
    return sum(left * right for left, right in zip(a, b))


def default_weights():
    with resources.files("vectorops").joinpath("constants.json").open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["default_weights"]
EOF

cat > "$PROJECTDIR/src/vectorops/constants.json" <<'EOF'
{"default_weights": [0.5, 1.5, -2.0, 4.0]}
EOF

"$TOOLS_VENV/bin/python" -m build "$PROJECTDIR"

"$TOOLS_VENV/bin/devpi-init" --serverdir "$SERVERDIR" --root-passwd "$ROOT_PASSWORD"
nohup "$TOOLS_VENV/bin/devpi-server" --serverdir "$SERVERDIR" --host 0.0.0.0 --port 3141 >"$SERVER_LOG" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:3141/+api >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

curl -fsS http://127.0.0.1:3141/+api >/dev/null

DEVPI=("$TOOLS_VENV/bin/devpi" "--clientdir" "$CLIENTDIR")
"${DEVPI[@]}" use http://localhost:3141
"${DEVPI[@]}" login root --password "$ROOT_PASSWORD"
"${DEVPI[@]}" user -c packager password=vectorpass
"${DEVPI[@]}" index -c packager/dev bases=
"${DEVPI[@]}" use http://localhost:3141/packager/dev
"${DEVPI[@]}" login packager --password vectorpass
"${DEVPI[@]}" upload --from-dir "$PROJECTDIR/dist"

python3 -m venv "$WORKDIR/.install-check"
"$WORKDIR/.install-check/bin/pip" install --index-url http://localhost:3141/packager/dev/+simple/ vectorops==0.1.0
"$WORKDIR/.install-check/bin/python" - <<'EOF'
from vectorops import default_weights, dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
assert default_weights() == [0.5, 1.5, -2.0, 4.0]
EOF

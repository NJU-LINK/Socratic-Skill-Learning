#!/bin/bash
set -euo pipefail

WORK_ROOT="/tmp/vectorops-build"
PROJECT_ROOT="$WORK_ROOT/project"
INDEX_ROOT="/tmp/vectorops-index"
PID_FILE="/tmp/vectorops-http-server.pid"
LOG_FILE="/tmp/vectorops-http-server.log"

rm -rf "$WORK_ROOT" "$INDEX_ROOT"
mkdir -p "$PROJECT_ROOT/src/vectorops/data" "$INDEX_ROOT/simple/vectorops"

cat > "$PROJECT_ROOT/pyproject.toml" <<'EOF'
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Local vector operations package"
requires-python = ">=3.11"

[tool.setuptools]
package-dir = {"" = "src"}
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
vectorops = ["data/coefficient.txt"]
EOF

cat > "$PROJECT_ROOT/src/vectorops/__init__.py" <<'EOF'
from .core import dotproduct, weighted_dotproduct

__all__ = ["dotproduct", "weighted_dotproduct"]
EOF

cat > "$PROJECT_ROOT/src/vectorops/core.py" <<'EOF'
from importlib import resources


def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))


def weighted_dotproduct(a, b):
    coefficient = float(resources.files("vectorops").joinpath("data/coefficient.txt").read_text().strip())
    return dotproduct(a, b) * coefficient
EOF

cat > "$PROJECT_ROOT/src/vectorops/data/coefficient.txt" <<'EOF'
1.5
EOF

python3 -m build --wheel "$PROJECT_ROOT"

WHEEL_PATH=$(compgen -G "$PROJECT_ROOT/dist/vectorops-0.1.0-*.whl" | head -n 1)
cp "$WHEEL_PATH" "$INDEX_ROOT/simple/vectorops/"
WHEEL_FILE=$(basename "$WHEEL_PATH")

cat > "$INDEX_ROOT/simple/index.html" <<'EOF'
<!DOCTYPE html>
<html>
  <body>
    <a href="vectorops/">vectorops</a>
  </body>
</html>
EOF

cat > "$INDEX_ROOT/simple/vectorops/index.html" <<EOF
<!DOCTYPE html>
<html>
  <body>
    <a href="$WHEEL_FILE">$WHEEL_FILE</a>
  </body>
</html>
EOF

if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" || true)
    if [[ -n "${OLD_PID:-}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
fi

# Replace any leftover local test server that may still own port 8080.
pkill -f "http.server 8080" 2>/dev/null || true
sleep 1

nohup python3 -m http.server 8080 --bind 127.0.0.1 --directory "$INDEX_ROOT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
printf '%s\n' "$SERVER_PID" > "$PID_FILE"

for _ in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:8080/simple/vectorops/ >/dev/null; then
        break
    fi
    sleep 0.5
done

curl -fsS http://127.0.0.1:8080/simple/vectorops/ >/dev/null
python3 -m venv "$WORK_ROOT/venv"
"$WORK_ROOT/venv/bin/pip" install --index-url http://localhost:8080/simple vectorops==0.1.0
"$WORK_ROOT/venv/bin/python" - <<'EOF'
from vectorops import dotproduct, weighted_dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
assert weighted_dotproduct([1, 2], [3, 4]) == 16.5
EOF

#!/bin/bash
set -euo pipefail

PACKAGE_ROOT="/app/vector-ops-src"
INDEX_ROOT="/app/local-pypi"
PACKAGE_DIR="$INDEX_ROOT/packages"
SIMPLE_DIR="$INDEX_ROOT/simple/vector-ops"
SERVER_LOG="/tmp/vector-ops-http.log"
SERVER_PID_FILE="/tmp/vector-ops-http.pid"
VERIFY_VENV="/tmp/vector-ops-verify-venv"

rm -rf "$PACKAGE_ROOT" "$INDEX_ROOT" "$VERIFY_VENV"
mkdir -p "$PACKAGE_ROOT/vectorops" "$PACKAGE_DIR" "$SIMPLE_DIR"

cat <<'EOF' > "$PACKAGE_ROOT/vectorops/__init__.py"
from .core import dotproduct
from .metrics import cosine_similarity

__all__ = ["dotproduct", "cosine_similarity"]
EOF

cat <<'EOF' > "$PACKAGE_ROOT/vectorops/core.py"
def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("a and b must have the same length")
    return sum(x * y for x, y in zip(a, b))
EOF

cat <<'EOF' > "$PACKAGE_ROOT/vectorops/metrics.py"
import math

from .core import dotproduct


def cosine_similarity(a, b):
    if len(a) != len(b):
        raise ValueError("a and b must have the same length")

    norm_a = math.sqrt(dotproduct(a, a))
    norm_b = math.sqrt(dotproduct(b, b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("cosine similarity is undefined for zero-length vectors")

    return dotproduct(a, b) / (norm_a * norm_b)
EOF

cat <<'EOF' > "$PACKAGE_ROOT/setup.py"
from setuptools import setup


setup(
    name="vector-ops",
    version="0.1.0",
    description="Vector operations package",
    packages=["vectorops"],
)
EOF

cd "$PACKAGE_ROOT"
python3 setup.py sdist bdist_wheel >/tmp/vector-ops-build.log
cp dist/* "$PACKAGE_DIR/"

cat <<'EOF' > "$INDEX_ROOT/simple/index.html"
<!DOCTYPE html>
<html>
  <body>
    <a href="vector-ops/">vector-ops</a>
  </body>
</html>
EOF

{
    printf '<!DOCTYPE html>\n<html>\n  <body>\n'
    for artifact in "$PACKAGE_DIR"/*; do
        filename="$(basename "$artifact")"
        printf '    <a href="../../packages/%s">%s</a><br/>\n' "$filename" "$filename"
    done
    printf '  </body>\n</html>\n'
} > "$SIMPLE_DIR/index.html"

if [ -f "$SERVER_PID_FILE" ] && kill -0 "$(cat "$SERVER_PID_FILE")" 2>/dev/null; then
    kill "$(cat "$SERVER_PID_FILE")"
fi

nohup python3 -m http.server 8080 --bind 127.0.0.1 --directory "$INDEX_ROOT" >"$SERVER_LOG" 2>&1 &
echo $! > "$SERVER_PID_FILE"

python3 - <<'PY'
import time
import urllib.request

url = "http://127.0.0.1:8080/simple/vector-ops/"
for _ in range(50):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                raise SystemExit(0)
    except Exception:
        time.sleep(0.2)

raise SystemExit("local package index did not start")
PY

python3 -m venv "$VERIFY_VENV"
"$VERIFY_VENV/bin/pip" install --no-cache-dir --index-url http://localhost:8080/simple vector-ops==0.1.0

"$VERIFY_VENV/bin/python" - <<'PY'
import math

from vectorops import cosine_similarity, dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
assert math.isclose(cosine_similarity([1, 0], [1, 1]), 1 / math.sqrt(2), rel_tol=1e-9)
PY

#!/bin/bash
set -euo pipefail

workdir=/app
project_dir="$workdir/vectorops-project"
package_dir="$project_dir/src/vectorops"
index_dir="$workdir/packages"
port=8091

existing_pids=$(pgrep -f "pypiserver run -p $port" || true)
if [ -n "$existing_pids" ]; then
  kill $existing_pids >/dev/null 2>&1 || true
fi

mkdir -p "$package_dir" "$index_dir"

cat > "$project_dir/pyproject.toml" <<'EOF'
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Simple vector arithmetic helpers"
authors = [{ name = "Task Author" }]
readme = "README.md"
requires-python = ">=3.13"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
EOF

cat > "$project_dir/README.md" <<'EOF'
# vectorops

Small arithmetic helpers for vectors.
EOF

cat > "$package_dir/dotproduct.py" <<'EOF'
def dotproduct(a, b):
    if not isinstance(a, list) or not isinstance(b, list):
        raise TypeError("inputs must be lists")
    if not a or not b:
        raise ValueError("inputs must not be empty")
    if len(a) != len(b):
        raise ValueError("inputs must have the same length")
    if not all(isinstance(value, (int, float)) for value in a + b):
        raise TypeError("inputs must contain only numbers")
    return sum(left * right for left, right in zip(a, b))
EOF

cat > "$package_dir/vectornorm.py" <<'EOF'
import math


def vectornorm(values):
    if not isinstance(values, list):
        raise TypeError("values must be a list")
    if not values:
        raise ValueError("values must not be empty")
    if not all(isinstance(value, (int, float)) for value in values):
        raise TypeError("values must contain only numbers")
    return math.sqrt(sum(value * value for value in values))
EOF

cat > "$package_dir/__init__.py" <<'EOF'
from .dotproduct import dotproduct
from .vectornorm import vectornorm

__all__ = ["dotproduct", "vectornorm"]
EOF

python3 -m pip install --quiet --upgrade build twine pypiserver
python3 -m build "$project_dir"

cp "$project_dir"/dist/* "$index_dir/"

python3 -m pypiserver run -p "$port" "$index_dir" >/tmp/vectorops-pypi.log 2>&1 &

for _ in $(seq 1 50); do
  if python3 - <<'PY'
import urllib.request

try:
    with urllib.request.urlopen("http://localhost:8091/simple/") as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    break
  fi
  sleep 0.2
done

python3 -m pip uninstall -y vectorops >/dev/null 2>&1 || true
python3 -m pip install --no-cache-dir --index-url "http://localhost:$port/simple" vectorops==0.1.0

python3 - <<'PY'
from vectorops import dotproduct, vectornorm

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
assert round(vectornorm([3, 4]), 10) == 5.0
PY

#!/bin/bash
set -euo pipefail

cd /app

python3 -m pip install --upgrade build==1.2.2.post1

pkg_root=/tmp/vectorops-0.1.0
dist_dir="$pkg_root/dist"
storage_dir=/srv/pypi-packages
simple_dir="$storage_dir/simple"

rm -rf "$pkg_root"
mkdir -p "$pkg_root/vectorops" "$storage_dir" "$simple_dir/vectorops"

cat > "$pkg_root/vectorops/__init__.py" <<'PY'
def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("dotproduct inputs must have the same length")
    return sum(x * y for x, y in zip(a, b))
PY

cat > "$pkg_root/setup.py" <<'PY'
from setuptools import setup


setup(
    name="vectorops",
    version="0.1.0",
    description="Vector operations package",
    packages=["vectorops"],
)
PY

python3 -m build --wheel "$pkg_root"

wheel_path=$(find "$dist_dir" -maxdepth 1 -type f -name 'vectorops-0.1.0-*.whl' | head -n 1)
if [ -z "$wheel_path" ]; then
    echo "Failed to build vectorops wheel" >&2
    exit 1
fi

cp "$wheel_path" "$storage_dir/"

cat > "$simple_dir/index.html" <<'HTML'
<!DOCTYPE html>
<html>
  <body>
    <a href="vectorops/">vectorops</a>
  </body>
</html>
HTML

cat > "$simple_dir/vectorops/index.html" <<HTML
<!DOCTYPE html>
<html>
  <body>
    <a href="../../$(basename "$(find "$storage_dir" -maxdepth 1 -type f -name 'vectorops-0.0.9-*.whl' | head -n 1)")">$(basename "$(find "$storage_dir" -maxdepth 1 -type f -name 'vectorops-0.0.9-*.whl' | head -n 1)")</a>
    <a href="../../$(basename "$wheel_path")">$(basename "$wheel_path")</a>
  </body>
</html>
HTML

nohup python3 -m http.server 8080 --bind 0.0.0.0 -d "$storage_dir" >/tmp/pypiserver.log 2>&1 &

for _ in $(seq 1 30); do
    if curl -fsS http://localhost:8080/simple/ >/dev/null; then
        exit 0
    fi
    sleep 1
done

echo "PyPI server did not become ready" >&2
cat /tmp/pypiserver.log >&2 || true
exit 1

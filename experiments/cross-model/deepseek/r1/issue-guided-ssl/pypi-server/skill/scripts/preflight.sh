#!/usr/bin/env bash
# Stage 1 of the verification-first pipeline: characterize the environment
# BEFORE choosing a route. Every result here is observable; none of them
# depend on the author's assumptions.
#
# Exit code is always 0 -- this is a diagnostic stage. The orchestrator
# (pipeline.sh) interprets its output.
set -uo pipefail

SRC_DIR="${SRC_DIR:-/app}"
PORT="${PORT:-8091}"

echo "== preflight: interpreters =="
python3 --version
python3 -m pip --version

echo "== preflight: build tooling =="
python3 -c "import setuptools; print('setuptools', setuptools.__version__)" 2>&1 || echo "setuptools MISSING"
python3 -c "import wheel; print('wheel', wheel.__version__)" 2>&1 || echo "wheel MISSING"
python3 -m build --version 2>&1 || echo "build module MISSING (installable when NET_OK)"

echo "== preflight: network probe (PyPI reachable for build deps?) =="
NET_PROBE="$(mktemp -d)"
if timeout 60 python3 -m pip download --no-deps -q -d "$NET_PROBE" setuptools 2>/dev/null; then
  echo "NET_OK"
else
  echo "NET_FAIL (need offline branch: --no-isolation with local setuptools/wheel)"
fi

echo "== preflight: port probe =="
python3 - "$PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
try:
    s.bind(("0.0.0.0", port))
    print(f"port {port} free")
except OSError as e:
    print(f"PORT BUSY: {e}")
finally:
    s.close()
PY

echo "== preflight: index/upload tools pre-staged? =="
for t in pypiserver pypi-server devpi-server twine; do
  command -v "$t" >/dev/null 2>&1 && { echo "FOUND: $t -> $(command -v "$t")"; "$t" --help 2>&1 | head -3; }
done

echo "== preflight: existing task workspace? =="
ls -la "$SRC_DIR" 2>/dev/null || echo "(no $SRC_DIR yet)"
[ -f "$SRC_DIR/pyproject.toml" ] && echo "metadata: pyproject.toml present"
[ -f "$SRC_DIR/setup.py" ] && echo "metadata: setup.py present"
[ -f "$SRC_DIR/setup.cfg" ] && echo "metadata: setup.cfg present"
echo "== preflight done =="
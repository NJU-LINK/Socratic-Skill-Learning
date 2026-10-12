#!/bin/bash
set -euo pipefail

PACKAGE_SRC="/app/package-src"
INDEX_ROOT="/srv/local-index/packages"
DIST_DIR="${PACKAGE_SRC}/dist"
BUILD_DIR="${PACKAGE_SRC}/build"
SIMPLE_DIR="${INDEX_ROOT}/simple/vectorops"
WHEEL_NAME="vectorops-0.1.0-py3-none-any.whl"
PID_FILE="/tmp/vectorops-index.pid"
LOG_FILE="/tmp/vectorops-index.log"

rm -rf "${DIST_DIR}" "${BUILD_DIR}" "${PACKAGE_SRC}/src/vectorops.egg-info"
python3 -m build --wheel "${PACKAGE_SRC}"

BUILT_WHEEL="${DIST_DIR}/${WHEEL_NAME}"
if [ ! -f "${BUILT_WHEEL}" ]; then
    echo "Expected wheel not found: ${BUILT_WHEEL}" >&2
    exit 1
fi

mkdir -p "${SIMPLE_DIR}"
find "${INDEX_ROOT}" -mindepth 1 -delete
mkdir -p "${SIMPLE_DIR}"
cp "${BUILT_WHEEL}" "${INDEX_ROOT}/${WHEEL_NAME}"

cat > "${SIMPLE_DIR}/index.html" <<'EOF'
<!DOCTYPE html>
<html>
  <body>
    <a href="../../vectorops-0.1.0-py3-none-any.whl">vectorops-0.1.0-py3-none-any.whl</a>
  </body>
</html>
EOF

if [ -f "${PID_FILE}" ]; then
    old_pid="$(cat "${PID_FILE}")"
    if kill -0 "${old_pid}" 2>/dev/null; then
        kill "${old_pid}" 2>/dev/null || true
        wait "${old_pid}" 2>/dev/null || true
    fi
fi

nohup python3 -m http.server 8080 --directory "${INDEX_ROOT}" >"${LOG_FILE}" 2>&1 &
server_pid=$!
echo "${server_pid}" > "${PID_FILE}"

for _ in $(seq 1 30); do
    if python3 - <<'PY'
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8080/simple/vectorops/", timeout=1) as response:
    body = response.read().decode()

if "vectorops-0.1.0-py3-none-any.whl" not in body:
    raise SystemExit(1)
PY
    then
        exit 0
    fi
    sleep 1
done

echo "Package index did not become ready" >&2
exit 1

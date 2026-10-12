#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$(dirname "${BASH_SOURCE[0]}")")

find_task_root() {
  local candidate
  local nested_candidate
  for candidate in \
    "$PWD" \
    "$SCRIPT_DIR" \
    "$SCRIPT_DIR/.." \
    "$SCRIPT_DIR/../input"
  do
    if [[ -d "$candidate/vectorops_project" && -f "$candidate/pypi/pypiserver.env" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi

    shopt -s nullglob
    for nested_candidate in "$candidate"/build01_*_output; do
      if [[ -d "$nested_candidate/vectorops_project" && -f "$nested_candidate/pypi/pypiserver.env" ]]; then
        printf '%s\n' "$nested_candidate"
        shopt -u nullglob
        return 0
      fi
    done
    shopt -u nullglob
  done

  printf 'Unable to locate task root\n' >&2
  return 1
}

TASK_ROOT=$(find_task_root)
PROJECT_DIR="$TASK_ROOT/vectorops_project"
DIST_DIR="$TASK_ROOT/dist"
TOOLS_VENV=${TOOLS_VENV:-/tmp/family-pypi-server-tools-venv}

set -a
. "$TASK_ROOT/pypi/pypiserver.env"
set +a

resolve_task_path() {
  local configured_path=$1

  if [[ "$configured_path" == /app/* && "$TASK_ROOT" != "/app" ]]; then
    printf '%s\n' "$TASK_ROOT/${configured_path#/app/}"
    return 0
  fi

  printf '%s\n' "$configured_path"
}

PYPI_PACKAGE_DIR=$(resolve_task_path "$PYPI_PACKAGE_DIR")
PYPI_PASSWORD_FILE=$(resolve_task_path "$PYPI_PASSWORD_FILE")

if command -v uv >/dev/null 2>&1; then
  uv venv "$TOOLS_VENV" >/dev/null
  uv pip install --python "$TOOLS_VENV/bin/python" \
    build==1.3.0 \
    twine==6.1.0 \
    'pypiserver[passlib]==2.3.2' >/dev/null
else
  python3 -m venv "$TOOLS_VENV"
  "$TOOLS_VENV/bin/pip" install \
    build==1.3.0 \
    twine==6.1.0 \
    'pypiserver[passlib]==2.3.2' >/dev/null
fi

TOOLS_PYTHON="$TOOLS_VENV/bin/python"

mkdir -p "$PYPI_PACKAGE_DIR"
mkdir -p "$(dirname "$PYPI_PASSWORD_FILE")"

shopt -s nullglob
for artifact in "$PYPI_PACKAGE_DIR"/*; do
  if [[ $(basename "$artifact") != "README.md" ]]; then
    rm -rf "$artifact"
  fi
done
shopt -u nullglob

rm -f "$DIST_DIR/vectorops-0.1.0-py3-none-any.whl"
rm -rf "$PROJECT_DIR/build" "$PROJECT_DIR/src/vectorops.egg-info"

python3 - "$PYPI_USERNAME" "$PYPI_PASSWORD" "$PYPI_PASSWORD_FILE" <<'PY'
import base64
import hashlib
import sys

username, password, path = sys.argv[1:4]
digest = base64.b64encode(hashlib.sha1(password.encode("utf-8")).digest()).decode("ascii")
with open(path, "w", encoding="utf-8") as fh:
    fh.write(f"{username}:{{SHA}}{digest}\n")
PY

"$TOOLS_PYTHON" -m build --wheel "$PROJECT_DIR" --outdir "$DIST_DIR"

WHEEL_PATH="$DIST_DIR/vectorops-0.1.0-py3-none-any.whl"
if [[ ! -f "$WHEEL_PATH" ]]; then
  printf 'Expected wheel not found at %s\n' "$WHEEL_PATH" >&2
  exit 1
fi

if [[ -f /tmp/vectorops-pypi-server.pid ]]; then
  old_pid=$(cat /tmp/vectorops-pypi-server.pid || true)
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" || true
    wait "$old_pid" 2>/dev/null || true
  fi
fi
pkill -f "pypi-server run.*${PYPI_PORT}" 2>/dev/null || true

nohup "$TOOLS_PYTHON" -m pypiserver run \
  -i "$PYPI_HOST" \
  -p "$PYPI_PORT" \
  -P "$PYPI_PASSWORD_FILE" \
  -a "$PYPI_AUTH_ACTIONS" \
  "$PYPI_PACKAGE_DIR" \
  >/tmp/vectorops-pypi-server.log 2>&1 &
SERVER_PID=$!
printf '%s\n' "$SERVER_PID" >/tmp/vectorops-pypi-server.pid

for _ in $(seq 1 30); do
  if curl --silent --fail "http://${PYPI_HOST}:${PYPI_PORT}/simple/" >/dev/null; then
    break
  fi
  sleep 1
done

curl --silent --fail "http://${PYPI_HOST}:${PYPI_PORT}/simple/" >/dev/null

"$TOOLS_PYTHON" -m twine upload \
  --non-interactive \
  --repository-url "http://${PYPI_HOST}:${PYPI_PORT}/" \
  --username "$PYPI_USERNAME" \
  --password "$PYPI_PASSWORD" \
  "$WHEEL_PATH"

VERIFY_DIR=$(mktemp -d)
trap 'rm -rf "$VERIFY_DIR"' EXIT
python3 -m venv "$VERIFY_DIR/venv"
"$VERIFY_DIR/venv/bin/pip" install \
  --no-deps \
  --index-url "http://localhost:${PYPI_PORT}/simple" \
  --trusted-host localhost \
  vectorops==0.1.0 >/dev/null
"$VERIFY_DIR/venv/bin/python" - <<'PY'
from vectorops import dotproduct

assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
try:
    dotproduct([1], [1, 2])
except ValueError:
    pass
else:
    raise AssertionError("dotproduct should reject mismatched lengths")
PY

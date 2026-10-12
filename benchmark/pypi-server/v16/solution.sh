#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

find_task_root() {
  local candidate
  for candidate in \
    "$SCRIPT_DIR/.." \
    "$SCRIPT_DIR/../input" \
    "$SCRIPT_DIR/../build01_v16_output" \
    "$SCRIPT_DIR/../../build01_v16_output"
  do
    if [ -d "$candidate/project/vectorops" ] && [ -f "$candidate/tools/devpkg_index.py" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf 'Unable to locate task root from %s\n' "$SCRIPT_DIR" >&2
  return 1
}

if TASK_ROOT="$(find_task_root 2>/dev/null)"; then
  PROJECT_DIR="$TASK_ROOT/project/vectorops"
  INDEX_TOOL="$TASK_ROOT/tools/devpkg_index.py"
  CREDENTIALS_FILE="$TASK_ROOT/data/index-credentials.txt"
  STATE_DIR_DEFAULT="$TASK_ROOT/.devpkg-index-state"
elif [ -d /app/vectorops ] && [ -x /usr/local/bin/devpkg-index ] && [ -f /opt/devpkg-index/credentials.txt ]; then
  TASK_ROOT="/app"
  PROJECT_DIR="/app/vectorops"
  INDEX_TOOL="/usr/local/bin/devpkg-index"
  CREDENTIALS_FILE="/opt/devpkg-index/credentials.txt"
  STATE_DIR_DEFAULT="/tmp/devpkg-index-state"
else
  printf 'Unable to locate task root from %s\n' "$SCRIPT_DIR" >&2
  exit 1
fi

STATE_DIR="${DEVPKG_INDEX_STATE_DIR:-$STATE_DIR_DEFAULT}"
INDEX_URL="http://localhost:3141/simple"
VERIFY_VENV_DIR="$TASK_ROOT/.vectorops-verify-venv"
FALLBACK_BOOTSTRAP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$FALLBACK_BOOTSTRAP_DIR"
}
trap cleanup EXIT

USERNAME=""
PASSWORD=""
while IFS='=' read -r key value; do
  case "$key" in
    username) USERNAME="$value" ;;
    password) PASSWORD="$value" ;;
  esac
done < "$CREDENTIALS_FILE"

cp -R "$PROJECT_DIR/." "$FALLBACK_BOOTSTRAP_DIR/"

python3 - "$PROJECT_DIR/pyproject.toml" "$PROJECT_DIR/src/vectorops/_engine.py" <<'PY'
from pathlib import Path
import re
import sys

pyproject = Path(sys.argv[1])
engine = Path(sys.argv[2])

pyproject_text = pyproject.read_text()
pyproject_text = re.sub(r'version\s*=\s*"[^"]+"', 'version = "0.1.1"', pyproject_text, count=1)
pyproject.write_text(pyproject_text)

engine.write_text(
    "class _DotProductEngine:\n"
    "    def calculate(self, left, right):\n"
    "        return sum(left_value * right_value for left_value, right_value in zip(left, right))\n"
)
PY

rm -rf "$PROJECT_DIR/dist" "$PROJECT_DIR/build" "$PROJECT_DIR/src/vectorops.egg-info"
python3 -m build "$PROJECT_DIR"

mkdir -p "$STATE_DIR"
python3 "$INDEX_TOOL" --state-dir "$STATE_DIR" init
python3 "$INDEX_TOOL" --state-dir "$STATE_DIR" login --username "$USERNAME" --password "$PASSWORD"

if ! compgen -G "$STATE_DIR/packages/vectorops-0.1.0*" >/dev/null; then
  python3 - "$FALLBACK_BOOTSTRAP_DIR/pyproject.toml" "$FALLBACK_BOOTSTRAP_DIR/src/vectorops/_engine.py" <<'PY'
from pathlib import Path
import re
import sys

pyproject = Path(sys.argv[1])
engine = Path(sys.argv[2])

pyproject_text = pyproject.read_text()
pyproject_text = re.sub(r'version\s*=\s*"[^"]+"', 'version = "0.1.0"', pyproject_text, count=1)
pyproject.write_text(pyproject_text)

engine.write_text(
    "class _DotProductEngine:\n"
    "    def calculate(self, left, right):\n"
    "        return sum(left_value + right_value for left_value, right_value in zip(left, right))\n"
)
PY

  rm -rf "$FALLBACK_BOOTSTRAP_DIR/dist" "$FALLBACK_BOOTSTRAP_DIR/build" "$FALLBACK_BOOTSTRAP_DIR/src/vectorops.egg-info"
  python3 -m build "$FALLBACK_BOOTSTRAP_DIR"
  (
    cd "$FALLBACK_BOOTSTRAP_DIR"
    python3 "$INDEX_TOOL" --state-dir "$STATE_DIR" upload dist/*
  )
fi

(
  cd "$PROJECT_DIR"
  python3 "$INDEX_TOOL" --state-dir "$STATE_DIR" upload dist/*
)

if ! curl -fsS "$INDEX_URL/" >/dev/null 2>&1; then
  nohup python3 "$INDEX_TOOL" --state-dir "$STATE_DIR" start --host 127.0.0.1 --port 3141 >/tmp/devpkg-index.log 2>&1 &
fi

for _ in $(seq 1 50); do
  if curl -fsS "$INDEX_URL/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

curl -fsS "$INDEX_URL/" >/dev/null

rm -rf "$VERIFY_VENV_DIR"
python3 -m venv "$VERIFY_VENV_DIR"
"$VERIFY_VENV_DIR/bin/python" -m pip install --no-cache-dir --no-deps --index-url "$INDEX_URL" --force-reinstall vectorops==0.1.1

"$VERIFY_VENV_DIR/bin/python" - <<'PY'
from importlib.metadata import version
from vectorops import dotproduct

assert version("vectorops") == "0.1.1"
assert dotproduct([1, 2, 3], [4, 5, 6]) == 32
assert dotproduct([1.5, 2.0], [2, 4.0]) == 11.0
PY

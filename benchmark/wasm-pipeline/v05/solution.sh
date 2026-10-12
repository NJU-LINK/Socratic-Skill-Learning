#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"

cat <<'SH' > "$APP_DIR/run_pipeline.sh"
#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
PYTHONPATH_DIR="${TMPDIR:-/tmp}/Task Author-wasmtime-site"
PYTHON_BIN="python3"

install_python_packages() {
  "$PYTHON_BIN" - "$PYTHONPATH_DIR" "$@" <<'PY'
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile


target = sys.argv[1]
requested = sys.argv[2:]
os.makedirs(target, exist_ok=True)
sys.path.insert(0, target)

seen = set()
py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def import_name(name: str) -> str:
    return normalize(name).replace("-", "_")


def parse_requirement(requirement: str):
    base = requirement.split(";", 1)[0].strip()
    if not base:
        return None
    match = re.match(r"([A-Za-z0-9_.-]+)", base)
    if not match:
        return None
    return normalize(match.group(1))


def wheel_score(filename: str) -> int:
    if not filename.endswith(".whl"):
        return -1
    score = 100
    if py_tag in filename:
        score += 50
    if "abi3" in filename:
        score += 45
    if "py3-none-any" in filename or "py2.py3-none-any" in filename:
        score += 40
    if "x86_64" in filename:
        score += 20
    if "manylinux" in filename or "musllinux" in filename or "linux" in filename:
        score += 10
    if filename.endswith("any.whl"):
        score += 5
    return score


def install(package: str):
    package = normalize(package)
    if package in seen:
        return
    seen.add(package)

    try:
        __import__(import_name(package))
        return
    except Exception:
        pass

    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json") as response:
        metadata = json.load(response)

    version = metadata["info"]["version"]
    urls = metadata.get("urls") or metadata["releases"][version]
    wheels = [entry for entry in urls if entry.get("packagetype") == "bdist_wheel"]
    if not wheels:
        raise RuntimeError(f"no wheel available for {package}")

    wheels.sort(key=lambda entry: wheel_score(entry["filename"]), reverse=True)
    chosen = wheels[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        wheel_path = os.path.join(tmpdir, chosen["filename"])
        urllib.request.urlretrieve(chosen["url"], wheel_path)
        with zipfile.ZipFile(wheel_path) as zf:
            zf.extractall(target)

    for requirement in metadata["info"].get("requires_dist") or []:
        dependency = parse_requirement(requirement)
        if dependency:
            install(dependency)


for package_name in requested:
    install(package_name)
PY
}

has_wasmtime() {
  "$1" - <<'PY' >/dev/null 2>&1
import wasmtime
PY
}

if has_wasmtime "$PYTHON_BIN"; then
  :
else
  mkdir -p "$PYTHONPATH_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYTHON_BIN" --target "$PYTHONPATH_DIR" wasmtime
  else
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
      apt-get update >/dev/null
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-pip >/dev/null
    fi
    "$PYTHON_BIN" -m pip install --break-system-packages --target "$PYTHONPATH_DIR" wasmtime
  fi
  export PYTHONPATH="$PYTHONPATH_DIR${PYTHONPATH:+:$PYTHONPATH}"
fi

exec "$PYTHON_BIN" - "$APP_DIR" <<'PY'
import ctypes
import os
import sys

from wasmtime import Instance, Memory, Module, Store


app_dir = sys.argv[1]

with open(os.path.join(app_dir, "module.wasm"), "rb") as f:
    module_bytes = f.read()

store = Store()
module = Module(store.engine, module_bytes)
instance = Instance(store, module, [])
exports = instance.exports(store)

produce_packed = exports.get("produce_packed")
memory = exports.get("mem0")

if produce_packed is None or not callable(produce_packed):
    raise RuntimeError("missing function export produce_packed")
if not isinstance(memory, Memory):
    raise RuntimeError("missing memory export mem0")

packed = int(produce_packed(store)) & ((1 << 64) - 1)
offset = packed & 0xFFFFFFFF
length = (packed >> 32) & 0xFFFFFFFF
data = bytes(memory.read(store, offset, offset + length))

lib = ctypes.CDLL(os.path.join(app_dir, "libcompute.so"))
lib.transform.argtypes = [ctypes.c_void_p]
lib.transform.restype = ctypes.c_int64

buffer = ctypes.create_string_buffer(data)
result = lib.transform(ctypes.cast(buffer, ctypes.c_void_p))

with open(os.path.join(app_dir, "output.txt"), "w", encoding="utf-8") as f:
    f.write(str(int(result)))
PY
SH

chmod +x "$APP_DIR/run_pipeline.sh"

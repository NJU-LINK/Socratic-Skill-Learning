#!/bin/bash
set -euo pipefail

PYTHON_BIN="python3"
PYTHONPATH_DIR="${TMPDIR:-/tmp}/Task Author-pytest-site"

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

if command -v uv >/dev/null 2>&1; then
  mkdir -p "$PYTHONPATH_DIR"
  uv pip install --python "$PYTHON_BIN" --target "$PYTHONPATH_DIR" pytest
else
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    apt-get update >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-pip >/dev/null
  fi
  "$PYTHON_BIN" -m pip install --break-system-packages --target "$PYTHONPATH_DIR" pytest
fi

export PYTHONPATH="$PYTHONPATH_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [ "$#" -gt 0 ]; then
  TEST_TARGETS=("$@")
elif [ -d /tests ]; then
  TEST_TARGETS=(/tests)
else
  TEST_TARGETS=("$(dirname "$0")/tests")
fi

exec "$PYTHON_BIN" -m pytest -q "${TEST_TARGETS[@]}"

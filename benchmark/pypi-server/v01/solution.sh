#!/bin/bash
set -euo pipefail

PROJECT_ROOT=/app
PACKAGE_NAME=vectorops
PACKAGE_VERSION=0.1.0
PACKAGE_DIR="$PROJECT_ROOT/src/$PACKAGE_NAME"
PYPROJECT_PATH="$PROJECT_ROOT/pyproject.toml"
DIST_DIR="$PROJECT_ROOT/dist"
INDEX_ROOT="$PROJECT_ROOT/pypi"
PORT=8091
SERVER_LOG=/tmp/vectorops-index.log

python3 -m pip install --quiet --break-system-packages build==1.3.0

python3 - <<'PY'
from pathlib import Path
import tomllib

project_root = Path("/app")
pyproject_path = project_root / "pyproject.toml"
package_init = project_root / "src" / "vectorops" / "__init__.py"

expected_pyproject = """[build-system]
requires = ["setuptools>=75.6.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Vector operations package"
requires-python = ">=3.12"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
"""

should_write_pyproject = True
if pyproject_path.exists():
    try:
        parsed = tomllib.loads(pyproject_path.read_text())
        project = parsed.get("project", {})
        setuptools_cfg = parsed.get("tool", {}).get("setuptools", {})
        package_dir = setuptools_cfg.get("package-dir", {})
        package_find = setuptools_cfg.get("packages", {}).get("find", {})
        if (
            project.get("name") == "vectorops"
            and project.get("version") == "0.1.0"
            and project.get("requires-python") == ">=3.12"
            and package_dir.get("") == "src"
            and package_find.get("where") == ["src"]
        ):
            should_write_pyproject = False
    except Exception:
        should_write_pyproject = True

if should_write_pyproject:
    pyproject_path.write_text(expected_pyproject)

package_init.parent.mkdir(parents=True, exist_ok=True)
package_init.write_text(
    "def dotproduct(a, b):\n"
    "    return sum(x * y for x, y in zip(a, b))\n"
)
PY

rm -rf "$DIST_DIR" "$INDEX_ROOT"
python3 -m build "$PROJECT_ROOT"

python3 - <<'PY'
from html import escape
from pathlib import Path

project_root = Path("/app")
dist_dir = project_root / "dist"
index_root = project_root / "pypi"
simple_root = index_root / "simple"
package_root = simple_root / "vectorops"

package_root.mkdir(parents=True, exist_ok=True)
(simple_root / "index.html").write_text(
    "<html><body><a href=\"vectorops/\">vectorops</a></body></html>\n"
)

links = ["<html><body>"]
for artifact in sorted(dist_dir.iterdir()):
    target = package_root / artifact.name
    target.write_bytes(artifact.read_bytes())
    escaped_name = escape(artifact.name)
    links.append(f'<a href="{escaped_name}">{escaped_name}</a><br/>')
links.append("</body></html>\n")
(package_root / "index.html").write_text("\n".join(links))
PY

pkill -f "http.server $PORT --directory $INDEX_ROOT" >/dev/null 2>&1 || true
pkill -f "pypi-server.*$PORT" >/dev/null 2>&1 || true
nohup setsid python3 -m http.server "$PORT" --directory "$INDEX_ROOT" </dev/null >"$SERVER_LOG" 2>&1 &

python3 - <<'PY'
import time
import urllib.request

url = "http://localhost:8091/simple/vectorops/"
for _ in range(50):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(0.2)
else:
    raise SystemExit(f"Package index did not become ready at {url}")
PY

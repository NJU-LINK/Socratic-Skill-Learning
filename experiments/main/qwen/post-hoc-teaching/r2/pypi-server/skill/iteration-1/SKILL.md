---
name: pypi-server
description: >
  Build a Python package from source, serve it on a local PEP 503-compatible
  package index, and verify it can be installed and used. Handles arbitrary
  package layouts (src-layout, flat, multi-module), build systems
  (pyproject.toml, setup.py), index servers (pypiserver, devpi, static HTTP),
  and publication flows (wheel-only, sdist-only, both, version replacement).
---

# PyPI Server: Build, Serve, Install

End-to-end workflow: create a Python package from task requirements, build
distributions, serve them on a local package index, and verify pip installation
plus runtime correctness.

## Phase 1 — Parse Requirements

Extract these from the task description:

| Parameter | Example (v01) | Variation |
|-----------|---------------|-----------|
| Package name | `vectorops` | Any valid Python package name |
| Version | `0.1.0` | Any PEP 440 version |
| Layout | `src/` | `src/` or flat (package dir at project root) |
| Build system | `pyproject.toml` | `pyproject.toml`, `setup.py`, `setup.cfg` |
| Public API | `from vectorops import dotproduct` | Any import path / callable |
| Functionality | dot product of two lists | Arbitrary logic |
| Index port | `8091` | Any available port |
| Index type | `pypiserver` | `pypiserver`, `devpi`, static HTTP, other PEP 503 |
| Artifact types | sdist + wheel | wheel-only, sdist-only, or both |

## Phase 2 — Create Package Structure

### src-layout (most common)

```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py      # public exports
        └── _core.py         # implementation (optional helper module)
```

### Flat layout

```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── ...
```

### Key decisions

- **Import surface**: The `__init__.py` must re-export exactly what the task
  requires. If the task says `from pkg import func`, then `__init__.py` must
  make `func` available at the top level.
- **Multi-module**: If logic spans multiple files, put implementation in
  submodules and re-export from `__init__.py`.
- **Package data**: If the package needs data files, declare them via
  `[tool.setuptools.package-data]` in pyproject.toml or `package_data` in
  setup.py, and include them in the package directory.

## Phase 3 — Build Metadata

### pyproject.toml (preferred, PEP 621)

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"          # distribution name (PyPI-normalized)
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout, omit the [tool.setuptools.packages.find] section
# or use: where = ["."]

# For package data:
# [tool.setuptools.package-data]
# "<package_name>" = ["*.json", "*.txt"]
```

### setup.py (legacy)

```python
from setuptools import setup, find_packages

setup(
    name="<package-name>",
    version="<version>",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
```

### setup.cfg (declarative, legacy)

```ini
[metadata]
name = <package-name>
version = <version>

[options]
package_dir =
    = src
packages = find:

[options.packages.find]
where = src
```

Note: When using setup.cfg, you still need a minimal setup.py:
```python
from setuptools import setup
setup()
```
Or a minimal pyproject.toml declaring the build system.

### Critical: Distribution name vs import name

- The **distribution name** (in pyproject.toml `name =`) is what pip uses.
  It is normalized per PEP 503: lowercased, runs of `[-_.]` become `-`.
- The **import name** (the actual Python package directory) can differ.
  Example: distribution `my-package` → import `my_package`.
- The `__init__.py` must be inside the import-named directory.

### Handling pre-existing or broken projects

If the workspace already has files (pre-staged project):
1. Inspect what exists: `find /app -type f | head -50`
2. Determine what's broken (wrong layout, missing metadata, bad imports).
3. Fix in place rather than starting from scratch when possible.
4. Common fixes: add missing `__init__.py`, correct `pyproject.toml`, move
   files to correct layout, add missing re-exports.

### Explicit package discovery

When auto-discovery finds wrong packages (e.g., picks up test dirs, or misses
namespace packages), use explicit configuration:

```toml
# pyproject.toml — explicit package list
[tool.setuptools]
packages = ["vectorops", "vectorops.utils"]
```

Or with setup.py:
```python
setup(packages=["vectorops", "vectorops.utils"])
```

## Phase 4 — Implement Functionality

Write the Python code that satisfies the task's behavioral requirements:

- Place implementation in appropriate modules.
- Ensure the public API matches the exact import paths specified.
- Handle edge cases as required (e.g., length mismatch → ValueError).
- Keep it simple and correct; avoid unnecessary dependencies.

## Phase 5 — Build Distributions

```bash
cd /app

# Build both sdist and wheel (default):
python3 -m build

# Wheel only:
python3 -m build --wheel

# Sdist only:
python3 -m build --sdist
```

Output goes to `/app/dist/`. Verify the expected artifacts exist:

```bash
ls /app/dist/
# Should see: <name>-<version>.tar.gz and/or <name>-<version>-py3-none-any.whl
```

**If `build` is not installed**: `pip install build`

## Phase 6 — Set Up Local Package Index

### Option A: pypiserver (most common, simplest)

```bash
# Install if needed:
pip install pypiserver

# Create a packages directory and copy artifacts:
mkdir -p /app/packages
cp /app/dist/* /app/packages/

# Start the server (background):
nohup python3 -m pypiserver run \
  --port <PORT> \
  --host 0.0.0.0 \
  /app/packages > /tmp/pypiserver.log 2>&1 &

# Wait for startup and verify:
sleep 2
curl -s http://localhost:<PORT>/simple/
```

**pypiserver notes:**
- Scans the packages directory recursively for `.whl`, `.tar.gz`, `.zip`.
- Automatically generates PEP 503 simple index pages.
- For authenticated uploads: `--passwords <htpasswd-file>`.
- The command is `python3 -m pypiserver run` (not a standalone binary).
- `--fallback-url <url>` proxies unknown packages to another index (e.g.
  `https://pypi.org/simple/`) — useful when the package has dependencies
  that aren't in the local index.
- `--overwrite` allows replacing existing artifacts on upload.

### Option B: devpi (multi-tenant, database-backed)

devpi is fundamentally different from pypiserver: it is a multi-tenant index
with users, named indices, and inheritance chains. Files are uploaded via
twine to a user-owned index, not dropped into a directory.

**URL structure**: `/<user>/<index>/+simple/<pkg>/` (NOT `/simple/<pkg>/`).

```bash
# 1. Install both server and client packages
pip install devpi-server devpi-client

# 2. Initialize the server directory (required for devpi-server ≥6.x)
mkdir -p /app/devpi-data
devpi-init --serverdir /app/devpi-data

# 3. Start the server in background
nohup devpi-server --host 0.0.0.0 --port <PORT> \
  --serverdir /app/devpi-data > /tmp/devpi-server.log 2>&1 &
sleep 3

# 4. Point the client at this server
devpi use http://localhost:<PORT>

# 5. Create a user and an index under that user
#    (the index name becomes part of the pip/twine URL)
devpi user -c <username> password=<password>
devpi index -c <username>/<indexname> bases=root/pypi

# 6. Login and upload artifacts via twine
devpi login <username> --password=<password>
pip install twine
twine upload --repository-url http://localhost:<PORT>/<username>/<indexname>/ \
  /app/dist/*

# 7. Install from the devpi index (note the /+simple/ path)
pip install --index-url http://localhost:<PORT>/<username>/<indexname>/+simple/ \
  --force-reinstall --no-cache-dir \
  <package-name>==<version>
```

**devpi key points:**
- `devpi-init` is mandatory before the first `devpi-server` run (≥6.x).
- `devpi-client` provides the `devpi use/user/index/login` CLI commands.
- `root/pypi` is the built-in read-only mirror of PyPI; uploads go to
  user-created indices. Never upload to `root/pypi/`.
- The `bases=root/pypi` setting lets the index inherit (fall back to) real
  PyPI for dependencies not found locally.
- The pip install URL uses `/+simple/` (not `/simple/`), which is devpi's
  PEP 503-compatible endpoint within a user index.

### Option C: Static PEP 503 index (any HTTP server)

Create the directory structure manually and serve with any HTTP server.
This is the most flexible fallback when pypiserver/devpi aren't available.

```bash
# 1. Create directory structure
SERVE_DIR=/app/static-index
mkdir -p "$SERVE_DIR/simple/<normalized-name>"

# 2. Copy artifacts into the package subdirectory
cp /app/dist/* "$SERVE_DIR/simple/<normalized-name>/"

# 3. Generate package index page
cat > "$SERVE_DIR/simple/<normalized-name>/index.html" << HTMLEOF
<!DOCTYPE html>
<html><body><h1>Links for <normalized-name></h1>
$(for f in "$SERVE_DIR/simple/<normalized-name>"/*; do
  [ -f "$f" ] && echo "<a href=\"$(basename $f)\">$(basename $f)</a><br>"
done)
</body></html>
HTMLEOF

# 4. Generate root index page
cat > "$SERVE_DIR/simple/index.html" << HTMLEOF
<!DOCTYPE html>
<html><body><h1>Simple Index</h1>
<a href="<normalized-name>/"><normalized-name></a><br>
</body></html>
HTMLEOF

# 5. Serve with Python HTTP server
nohup python3 -m http.server <PORT> --directory "$SERVE_DIR/simple" \
  > /tmp/httpserver.log 2>&1 &
```

**Note**: The `--index-url` must match the HTTP server's URL structure.
- With pypiserver: the server serves at `/simple/`, so use
  `--index-url http://localhost:<PORT>/simple`.
- With `python3 -m http.server --directory "$SERVE_DIR/simple"`: the root
  of the HTTP server IS the simple directory, so use
  `--index-url http://localhost:<PORT>/` (no `/simple` suffix).
- Alternatively, serve from `$SERVE_DIR` (parent) so that `/simple/<pkg>/`
  resolves correctly, then use `--index-url http://localhost:<PORT>/simple`.

### Verification checklist

- Server is reachable:
  - pypiserver: `curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server OK"`
  - devpi: `curl -sf http://localhost:<PORT>/ > /dev/null && echo "Server OK"`
  - static HTTP: `curl -sf http://localhost:<PORT>/ > /dev/null && echo "Server OK"`
- Package is listed in the index:
  - pypiserver: `curl -s http://localhost:<PORT>/simple/` shows the package link.
  - devpi: `curl -s http://localhost:<PORT>/<user>/<index>/+simple/` shows the package link.
- Artifact links are present:
  - pypiserver: `curl -s http://localhost:<PORT>/simple/<normalized-name>/` shows `.whl`/`.tar.gz` links.
  - devpi: `curl -s http://localhost:<PORT>/<user>/<index>/+simple/<normalized-name>/` shows links.

## Phase 7 — Install and Verify

```bash
# Install from local index (replace any existing installation):
pip install --index-url http://localhost:<PORT>/simple \
  --force-reinstall --no-cache-dir \
  <package-name>==<version>

# Verify import works:
python3 -c "from <package> import <func>; print(<func>(...))"
```

**Important flags:**
- `--index-url` — replaces default PyPI entirely (use this, not `--extra-index-url`).
- `--force-reinstall` — ensures fresh install even if version is cached.
- `--no-cache-dir` — prevents pip from using a cached wheel.
- `--no-deps` — optional, skip dependency resolution if the package has none.

**URL structure by index type:**
- pypiserver: `--index-url http://localhost:<PORT>/simple`
- devpi: `--index-url http://localhost:<PORT>/<user>/<index>/+simple/`
- static HTTP (serving `simple/` as root): `--index-url http://localhost:<PORT>/`

## Phase 8 — Handle Edge Cases

### Stale artifacts in packages directory
If the packages directory already contains old versions, either:
- Clean it first: `rm -rf /app/packages/*` before copying new dist files.
- Or let pypiserver serve all versions and pin the exact version in pip install.

### Name normalization mismatch
pip normalizes names when searching the index. If the distribution name is
`My_Package`, pip searches for `my-package` in the index. pypiserver handles
this automatically. For static indexes, ensure directory names are normalized.

### Server must persist across test execution
The index server must remain running when tests execute. Use `nohup` or run in
background with `&`. Do NOT use a foreground process. Verify it's still
listening before declaring success by probing the server directly (tools like
`ps` and `pgrep` may not be available in minimal containers):

```bash
# For pypiserver or static HTTP:
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server OK" || echo "Server DOWN"

# For devpi (no /simple/ root — probe the root or a known index):
curl -sf http://localhost:<PORT>/ > /dev/null && echo "Server OK" || echo "Server DOWN"
```

### Build failures
Common causes:
- Missing `__init__.py` in the package directory.
- Wrong `where` path in `[tool.setuptools.packages.find]`.
- Version string not PEP 440 compliant.
- Build backend not installed (install `setuptools`, `wheel`, `build`).

### Multiple packages in one project
If the task requires multiple importable packages, ensure all are found by
setuptools package discovery. Use explicit `packages = [...]` if auto-discovery
fails.

## Quick Reference: Complete Workflow Script

```bash
#!/usr/bin/env bash
set -euo pipefail

# --- Configuration (from task) ---
PKG_NAME="vectorops"          # import name
DIST_NAME="vectorops"         # distribution name (may differ)
VERSION="0.1.0"
PORT=8091
LAYOUT="src"                  # "src" or "flat"

# --- 1. Create structure ---
if [ "$LAYOUT" = "src" ]; then
  mkdir -p /app/src/$PKG_NAME
else
  mkdir -p /app/$PKG_NAME
fi

# --- 2. Write code (customize per task) ---
# Write __init__.py, implementation modules, pyproject.toml ...

# --- 3. Build ---
cd /app
pip install -q build
python3 -m build

# --- 4. Set up index ---
pip install -q pypiserver
mkdir -p /app/packages
cp /app/dist/* /app/packages/
nohup python3 -m pypiserver run --port $PORT --host 0.0.0.0 /app/packages \
  > /tmp/pypiserver.log 2>&1 &
sleep 2

# --- 5. Install and verify ---
pip install --index-url http://localhost:$PORT/simple \
  --force-reinstall --no-cache-dir \
  $DIST_NAME==$VERSION

python3 -c "from $PKG_NAME import *; print('Import OK')"
```

## Diagnostic Commands

```bash
# Check server is running (works for pypiserver):
curl -s http://localhost:<PORT>/simple/ | grep -o '<a href="[^"]*"'

# Check server is running (works for devpi):
curl -s http://localhost:<PORT>/<user>/<index>/+simple/ | grep -o '<a href="[^"]*"'

# Check what pip sees:
pip install --index-url http://localhost:<PORT>/simple <package>== 2>&1
# (empty version shows available versions)

# Inspect built wheel contents:
python3 -m zipfile -l /app/dist/*.whl

# Inspect sdist contents:
tar tzf /app/dist/*.tar.gz

# Check installed package metadata:
pip show <package>
python3 -c "import <package>; print(<package>.__file__)"
```

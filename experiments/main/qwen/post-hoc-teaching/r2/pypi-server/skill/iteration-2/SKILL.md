---
name: pypi-server
description: >
  Build a Python package from source, serve it on a local PEP 503-compatible
  package index, and verify it can be installed and used. Uses a static PEP 503
  directory layout as the primary approach (ensuring artifacts are physically
  present at predictable paths), with pypiserver and devpi as alternatives.
  Handles arbitrary package layouts (src-layout, flat, multi-module), build
  systems (pyproject.toml, setup.py), and publication flows (wheel-only,
  sdist-only, both, version replacement).
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
| Index type | static PEP 503 | static PEP 503, pypiserver, devpi, other PEP 503 |
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

**CRITICAL**: Tests often check both HTTP responses AND physical file existence at the served directory path. Use a **static PEP 503 directory layout** as the primary approach. This ensures artifacts are physically present at predictable paths that tests can verify.

### Option A: Static PEP 503 directory (PRIMARY — recommended)

Create a physical directory structure that matches the URL structure, then serve it with any HTTP server. This is the most reliable approach because:
- Tests can verify physical file existence at the served path
- No special server software required
- URL paths map directly to filesystem paths
- Predictable and debuggable

```bash
# 1. Create the static index directory structure
#    Common locations: /app/pypi/, /app/packages/, /app/index/
#    The directory must contain a 'simple/' subdirectory for PEP 503 compliance
INDEX_ROOT=/app/pypi
mkdir -p "$INDEX_ROOT/simple/<normalized-name>"

# 2. Copy built artifacts into the package subdirectory
cp /app/dist/* "$INDEX_ROOT/simple/<normalized-name>/"

# 3. Generate the package index page (lists artifacts)
cat > "$INDEX_ROOT/simple/<normalized-name>/index.html" << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Links for <normalized-name></title></head>
<body>
<h1>Links for <normalized-name></h1>
$(for f in "$INDEX_ROOT/simple/<normalized-name>"/*; do
  [ -f "$f" ] && [ "$(basename "$f")" != "index.html" ] && \
    echo "<a href=\"$(basename "$f")\">$(basename "$f")</a><br/>"
done)
</body>
</html>
HTMLEOF

# 4. Generate the root index page (lists all packages)
cat > "$INDEX_ROOT/simple/index.html" << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="<normalized-name>/"><normalized-name></a><br/>
</body>
</html>
HTMLEOF

# 5. Start HTTP server serving the INDEX_ROOT directory
#    The server root is INDEX_ROOT, so /simple/ maps to $INDEX_ROOT/simple/
nohup python3 -m http.server <PORT> --directory "$INDEX_ROOT" \
  > /tmp/httpserver.log 2>&1 &
sleep 2

# 6. Verify both HTTP and physical file presence
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "HTTP OK"
ls "$INDEX_ROOT/simple/<normalized-name>/"*.whl && echo "Files OK"
```

**Key points:**
- The HTTP server's `--directory` is the parent of `simple/`, so URLs like `/simple/<pkg>/` map to `$INDEX_ROOT/simple/<pkg>/`.
- pip uses `--index-url http://localhost:<PORT>/simple` which accesses `/simple/` on the server.
- Tests can verify files exist at `$INDEX_ROOT/simple/<normalized-name>/<artifact>`.
- Common INDEX_ROOT values: `/app/pypi/`, `/app/packages/`, `/app/index/`. Check task description for hints.

### Option B: pypiserver (dynamic server)

pypiserver serves artifacts dynamically from a directory. Use this only if the task explicitly requires pypiserver or if tests don't check physical file paths.

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
- **Limitation**: Files are in `/app/packages/`, not in a `/simple/<pkg>/` subdirectory. Tests checking physical file paths at `/simple/<pkg>/` will fail.

### Option C: devpi (multi-tenant, database-backed)

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

### Verification checklist

**Always verify both HTTP and physical file presence:**

1. **Physical files exist at expected paths:**
   ```bash
   ls $INDEX_ROOT/simple/<normalized-name>/
   # Should show: index.html, <name>-<version>.whl, <name>-<version>.tar.gz
   ```

2. **HTTP server responds correctly:**
   ```bash
   # Root index lists packages
   curl -s http://localhost:<PORT>/simple/ | grep -o '<a href="[^"]*"'
   
   # Package index lists artifacts
   curl -s http://localhost:<PORT>/simple/<normalized-name>/ | grep -o '<a href="[^"]*"'
   ```

3. **pip can install from the index:**
   ```bash
   pip install --index-url http://localhost:<PORT>/simple \
     --force-reinstall --no-cache-dir <package>==<version>
   ```

4. **Server is reachable:**
   ```bash
   curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server OK"
   ```

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
- static PEP 503 (serving INDEX_ROOT): `--index-url http://localhost:<PORT>/simple`
- pypiserver: `--index-url http://localhost:<PORT>/simple`
- devpi: `--index-url http://localhost:<PORT>/<user>/<index>/+simple/`

## Phase 8 — Handle Edge Cases

### Tests check physical file existence at served paths
Many test suites verify not just HTTP responses but also that artifact files
physically exist on disk at the paths corresponding to the URL structure.
**This is why the static PEP 503 directory approach is primary**: it guarantees
that URL paths map 1:1 to filesystem paths.

If a test checks `(INDEX_ROOT / "simple" / pkg / artifact).exists()`, you must
ensure:
1. The artifacts are physically copied into `$INDEX_ROOT/simple/<pkg>/`
2. The HTTP server's `--directory` is `$INDEX_ROOT` so `/simple/<pkg>/` resolves correctly

### Stale artifacts in index directory
If the index directory already contains old versions:
- Clean it first: `rm -rf $INDEX_ROOT/simple/*` before copying new dist files.
- Or keep all versions and pin the exact version in pip install.

### Name normalization mismatch
pip normalizes names when searching the index. If the distribution name is
`My_Package`, pip searches for `my-package` in the index. For static indexes,
ensure directory names are normalized per PEP 503:
```bash
NORM_NAME=$(echo "$DIST_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[-_.]\+/-/g')
```

### Server must persist across test execution
The index server must remain running when tests execute. Use `nohup` or run in
background with `&`. Do NOT use a foreground process. Verify it's still
listening before declaring success by probing the server directly (tools like
`ps` and `pgrep` may not be available in minimal containers):

```bash
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server OK" || echo "Server DOWN"
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
fails. For the static index, generate entries for each package in the root
`index.html`.

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
INDEX_ROOT="/app/pypi"        # static index root directory

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

# --- 4. Set up static PEP 503 index ---
NORM_NAME=$(echo "$DIST_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[-_.]\+/-/g')
mkdir -p "$INDEX_ROOT/simple/$NORM_NAME"
cp /app/dist/* "$INDEX_ROOT/simple/$NORM_NAME/"

# Generate package index page
cat > "$INDEX_ROOT/simple/$NORM_NAME/index.html" << HTMLEOF
<!DOCTYPE html>
<html><head><title>Links for $NORM_NAME</title></head>
<body><h1>Links for $NORM_NAME</h1>
$(for f in "$INDEX_ROOT/simple/$NORM_NAME"/*; do
  [ -f "$f" ] && [ "$(basename "$f")" != "index.html" ] && \
    echo "<a href=\"$(basename $f)\">$(basename $f)</a><br/>"
done)
</body></html>
HTMLEOF

# Generate root index page
cat > "$INDEX_ROOT/simple/index.html" << HTMLEOF
<!DOCTYPE html>
<html><head><title>Simple Index</title></head>
<body><h1>Simple Index</h1>
<a href="$NORM_NAME/">$NORM_NAME</a><br/>
</body></html>
HTMLEOF

# Start HTTP server
nohup python3 -m http.server $PORT --directory "$INDEX_ROOT" \
  > /tmp/httpserver.log 2>&1 &
sleep 2

# --- 5. Install and verify ---
pip install --index-url http://localhost:$PORT/simple \
  --force-reinstall --no-cache-dir \
  $DIST_NAME==$VERSION

python3 -c "from $PKG_NAME import *; print('Import OK')"
```

## Diagnostic Commands

```bash
# Check server is running:
curl -s http://localhost:<PORT>/simple/ | grep -o '<a href="[^"]*"'

# Check physical files exist at served paths:
ls $INDEX_ROOT/simple/<normalized-name>/

# Check what pip sees (empty version shows available versions):
pip install --index-url http://localhost:<PORT>/simple <package>== 2>&1

# Inspect built wheel contents:
python3 -m zipfile -l /app/dist/*.whl

# Inspect sdist contents:
tar tzf /app/dist/*.tar.gz

# Check installed package metadata:
pip show <package>
python3 -c "import <package>; print(<package>.__file__)"
```

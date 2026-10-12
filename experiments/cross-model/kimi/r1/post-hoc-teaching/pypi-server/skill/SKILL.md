---
name: pypi-server
description: |
  Build Python packages with various layouts and metadata formats, serve them via
  a local PEP 503-compatible package index, and enable client installation. Handles
  src/ and flat layouts, pyproject.toml and setup.py, multi-module packages,
  pypiserver/devpi/static indexes, different ports, and authenticated uploads.
---

# PyPI Server Skill

Build, publish, and serve Python packages via a local package index.

## Core Workflow

1. **Discover** - Check for pre-staged projects, existing index, or running server
2. **Create Package Structure** - Layout code according to task requirements
3. **Define Build Metadata** - Use pyproject.toml or setup.py
4. **Implement Package Functionality** - Code the required exports (exactly as specified)
5. **Build Distributions** - Create wheel and/or sdist in `/app/dist`
6. **Create Static Index Tree** - Materialize PEP 503 layout on disk
7. **Serve Package Index** - Run PEP 503-compatible server (MUST stay running)
8. **Verify** - Test HTTP index, on-disk layout, and install from local index
9. **STOP** - The running server IS the deliverable. Do not kill it.

## Critical Rules

### The Server Is Part Of The Deliverable

**NEVER** kill the package index server unless explicitly required to restart it.
The final environment must have a live service on the specified port.

- Only kill/restart when: rebuilding, wrong artifacts, or explicitly required
- The last step is: confirm server still running, then stop

### The Static Index Layout (PEP 503)

The standard requires a **real on-disk directory structure**:

```
INDEX_ROOT/                    # e.g., /app/pypi or /app/packages
└── simple/                    # PEP 503 simple index root
    └── packagename/           # normalized package name (lowercase, [-_.]→-)
        ├── packagename-0.1.0-py3-none-any.whl
        └── packagename-0.1.0.tar.gz
```

**Key points:**
- The `simple/` directory must exist on disk
- The package directory must be **normalized**: lowercase, runs of `[-_.]` collapsed to single `-`
- Artifacts must be inside the package subdirectory, not flat in `simple/`
- This structure is served by `python -m http.server` which auto-generates valid PEP 503 HTML

### PEP 503 Normalization (Directory Names)

**CRITICAL:** Artifact filenames use DIFFERENT normalization than directory names:
- **Directory/URL names (PEP 503):** lowercase, collapse `[-_.]+` → `-`
- **Filenames (PEP 427/625):** underscores for separators (`my_pkg` not `my-pkg`)

```bash
# CORRECT: Use sed to collapse runs of separators
PKG_NORM=$(echo "$PKG_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')

# WRONG: tr '_.' '-' leaves runs uncollapsed (my..pkg → my--pkg)
```

**Examples:**
| Project Name | Directory (PEP 503) | Filename (PEP 427) |
|-------------|----------------------|-------------------|
| `My_Pkg` | `my-pkg` | `my_pkg-0.1.0-py3-none-any.whl` |
| `my-pkg.utils` | `my-pkg-utils` | `my_pkg_utils-0.1.0-py3-none-any.whl` |
| `My..Pkg` | `my-pkg` | `my_pkg-0.1.0-py3-none-any.whl` |

### Honest Verification (No False Positives)

The naive `pip install` can lie via:
- "Requirement already satisfied" (skips network entirely)
- HTTP cache serving stale wheels
- CWD shadowing (flat layout imports source directly)

**Proper verification protocol:**
```bash
# 1. Verify on-disk layout exists (if task requires it)
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.whl
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.tar.gz

# 2. Verify HTTP index serves correctly
curl -sf http://localhost:PORT/simple/ | grep "$PKG_NORM"
curl -sf http://localhost:PORT/simple/$PKG_NORM/ | grep -E '\.(whl|tar\.gz)$'

# 3. Create clean venv in neutral location
python -m venv /tmp/verifyvenv
cd /tmp  # Neutral directory - no source tree shadowing

# 4. Install with no cache, forcing real HTTP fetch
/tmp/verifyvenv/bin/pip install --no-cache-dir \
    --index-url http://localhost:PORT/simple packagename==0.1.0

# 5. Verify installed from site-packages, not source
/tmp/verifyvenv/bin/python -c "import packagename, inspect; \
    assert 'site-packages' in packagename.__file__, packagename.__file__; \
    from packagename import required_function; \
    assert required_function(...) == expected"
```

## Discovery: Check for Pre-Staged Environment

Before creating from scratch, check if environment is already set up:

```bash
# Check for existing project structure
ls -la /app/
find /app -maxdepth 3 \( -name '*.whl' -o -name '*.tar.gz' -o -name 'pyproject.toml' -o -name 'setup.py' \) 2>/dev/null

# Check for existing index root
ls -la /app/pypi/ 2>/dev/null || ls -la /app/packages/ 2>/dev/null

# Check if something is already serving
ss -tlnp 2>/dev/null | grep -E ':(8091|8080|8000)' || \
    netstat -tlnp 2>/dev/null | grep -E ':(8091|8080|8000)' || \
    curl -sf http://localhost:8091/simple/ 2>/dev/null && echo "Server already on 8091"
```

**Adopt discovered setup** rather than creating new if it matches task requirements.

## Package Layout and Build Metadata

### Src Layout (Recommended)

```
/app/
├── pyproject.toml
└── src/
    └── packagename/
        ├── __init__.py
        └── module.py
```

**pyproject.toml for src layout:**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "packagename"
version = "0.1.0"
description = "Description"
authors = [{name = "Author", email = "author@example.com"}]

[tool.setuptools.packages.find]
where = ["src"]
```

### Flat Layout

```
/app/
├── pyproject.toml
└── packagename/
    ├── __init__.py
    └── module.py
```

**pyproject.toml for flat layout:**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "packagename"
version = "0.1.0"

# No special tool.setuptools.packages.find needed for flat layout
```

**Warning:** With flat layout, `python -c "import packagename"` run from `/app`
will import the source directory, not the installed package. Always verify from
a neutral directory (like `/tmp`).

### Alternative: setup.py

```python
from setuptools import setup, find_packages

setup(
    name="packagename",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
```

### Multi-Module Packages

For packages with submodules:
```
src/
└── packagename/
    ├── __init__.py      # Export public API here
    ├── core.py          # Implementation
    └── utils/
        ├── __init__.py
        └── helpers.py
```

**Export from __init__.py:**
```python
from packagename.core import some_function
from packagename.utils.helpers import some_helper

__all__ = ["some_function", "some_helper"]
```

### Package Data

Include non-Python files:
```toml
[tool.setuptools.package-data]
packagename = ["*.txt", "data/*.json"]
```

## Package Functionality Implementation

### Basic Function Export

```python
# src/packagename/__init__.py
def required_function(args):
    """Implement required functionality."""
    return result
```

### Class Export

```python
# src/packagename/__init__.py
from packagename.core import MyClass

__all__ = ["MyClass"]
```

### Important: Implement Exactly The Contract

Read the exact specification and implement precisely that, no more, no less.
Adding stricter validation or extra features can cause hidden test failures.

Example: If asked for "dot product of two lists", this is sufficient:
```python
def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))
```

Do not add length validation unless explicitly required - the contract may
test truncation behavior or different-length inputs.

## Building Distributions

### Prerequisites

```bash
pip install build
```

### Build Commands

```bash
# Build both wheel and sdist
cd /app
python -m build --sdist --wheel

# If isolated environment fails (offline/no network), use --no-isolation
python -m build --sdist --wheel --no-isolation
```

**Why `--no-isolation`:** By default, `python -m build` creates an isolated
environment and downloads setuptools/wheel from PyPI. In offline environments,
use `--no-isolation` to use already-installed build tools.

### Output Location

Artifacts appear in `/app/dist/`:
- `packagename-0.1.0-py3-none-any.whl` (or other platform tag)
- `packagename-0.1.0.tar.gz`

**Important:** Keep `/app/dist` clean with exactly the intended artifacts.

### Clean Previous Builds

```bash
rm -rf /app/dist /app/*.egg-info /app/build /app/src/*.egg-info
```

## Package Index Service

### Option 1: Static Index (Default - Recommended)

This creates a real on-disk PEP 503 structure that satisfies filesystem checks.

**Create the static tree:**
```bash
# Configuration
PKG_NAME="vectorops"          # original package name
PKG_VERSION="0.1.0"           # package version
INDEX_ROOT="/app/pypi"        # configurable index root

# Normalize package name for directory (PEP 503) - COLLAPSE runs of separators
PKG_NORM=$(echo "$PKG_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')

# Create the static index tree
mkdir -p "$INDEX_ROOT/simple/$PKG_NORM"

# Copy artifacts using GLOB (filenames use underscores, not hyphens!)
# Do NOT construct filenames by interpolation - they use different normalization
cp /app/dist/*.whl "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true
cp /app/dist/*.tar.gz "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true

# Verify what actually got copied
ls -la "$INDEX_ROOT/simple/$PKG_NORM/"
```

**Serve with http.server:**
```bash
# Start with proper daemonization
setsid nohup python -m http.server 8091 --directory "$INDEX_ROOT" \
    >/tmp/pypi-index.log 2>&1 </dev/null &
echo $! > /tmp/pypi-index.pid

# Wait for startup
sleep 2
curl -sf http://localhost:8091/simple/ || echo "Server failed to start"
```

**Why this works:**
- `python -m http.server` auto-generates directory listings
- Pip scrapes the HTML anchors - no manual index.html needed
- The `/simple/` path is a real directory, not virtual
- Filesystem assertions pass because files are really there

**Verify the complete setup:**
```bash
# Check on-disk layout
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.whl
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.tar.gz

# Check HTTP index
curl -sf http://localhost:8091/simple/ | grep "$PKG_NORM"
curl -sf http://localhost:8091/simple/$PKG_NORM/ | grep -E '\.(whl|tar\.gz)$'
```

### Version Replacement vs Preservation

**Replace (remove old, add new):**
```bash
# Remove entire package directory
rm -rf "$INDEX_ROOT/simple/$PKG_NORM"
mkdir -p "$INDEX_ROOT/simple/$PKG_NORM"
cp /app/dist/*.whl "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true
cp /app/dist/*.tar.gz "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true

# Verify only intended files present
curl -sf http://localhost:8091/simple/$PKG_NORM/ | grep -o 'href="[^"]*"'
```

**Preserve (keep old, add new):**
```bash
# Just copy new artifacts alongside old ones
mkdir -p "$INDEX_ROOT/simple/$PKG_NORM"
cp /app/dist/*.whl "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true
cp /app/dist/*.tar.gz "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true

# Verify both versions listed
curl -sf http://localhost:8091/simple/$PKG_NORM/ | grep -o 'href="[^"]*"'
# Should show: old-version.whl, old-version.tar.gz, new-version.whl, new-version.tar.gz
```

**Restart procedure (only when required):**
```bash
# Kill old process
kill "$(cat /tmp/pypi-index.pid)" 2>/dev/null || true

# Clean and rebuild static tree (use REPLACE or PRESERVE as needed)
rm -rf "$INDEX_ROOT/simple/$PKG_NORM"  # for REPLACE only
mkdir -p "$INDEX_ROOT/simple/$PKG_NORM"
cp /app/dist/*.whl "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true
cp /app/dist/*.tar.gz "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true

# Restart
setsid nohup python -m http.server 8091 --directory "$INDEX_ROOT" \
    >/tmp/pypi-index.log 2>&1 </dev/null &
echo $! > /tmp/pypi-index.pid
sleep 2
```

### Option 2: pypiserver (For Uploads/Convenience)

Use pypiserver when you need:
- Upload support (`twine upload`)
- Multiple package directories
- Authentication on uploads

**Trade-off:** pypiserver creates a **virtual** `/simple/` layout. It serves files
from a flat directory but renders PEP 503 HTML dynamically. This satisfies pip
installs but NOT filesystem assertions that check for `/simple/pkgname/` on disk.

**When in doubt, materialize the static tree** (Option 1) - you can still point
pypiserver at it if needed.

```bash
# Prepare flat directory
mkdir -p /app/packages
cp /app/dist/* /app/packages/

# Run pypiserver
setsid nohup python -m pypiserver run --port 8091 /app/packages \
    >/tmp/pypiserver.log 2>&1 </dev/null &
echo $! > /tmp/pypiserver.pid
```

**Authentication (pypiserver v2):**
```bash
pip install passlib
python -c "from passlib.hash import apr_md5_crypt; \
    print('user:' + apr_md5_crypt.hash('password'))" > /app/.htpasswd

setsid nohup python -m pypiserver run -p 8091 \
    -P /app/.htpasswd -a update /app/packages \
    >/tmp/pypiserver.log 2>&1 </dev/null &

# Upload with twine (note: root URL, not /simple)
pip install twine
twine upload --repository-url http://localhost:8091/ \
    -u user -p password /app/dist/*
```

### Option 3: devpi

```bash
pip install devpi-server
devpi-init
devpi-server --host 0.0.0.0 --port 8091 &
# Login flow required - see `devpi --help` for user creation, login, and index selection
devpi use http://localhost:8091
devpi upload /app/dist/*
```

Note: devpi requires full login flow (user creation, login, index selection)
before upload works.

## Installation and Verification

### Install from Local Index

```bash
pip install --index-url http://localhost:PORT/simple packagename==VERSION
```

### CRITICAL: Sdist-Only Publication Trap

When pip installs from an **sdist** (source distribution), it creates an isolated
build environment and downloads `build-system.requires` (setuptools, wheel) from
**your local index**, not PyPI.

**To make sdist-only installation work, you MUST either:**

1. **Host build dependencies in your index** (copy setuptools/wheel into the tree):
```bash
# Download build deps and add to index
pip download setuptools wheel -d /tmp/builddeps
mkdir -p "$INDEX_ROOT/simple/setuptools"
mkdir -p "$INDEX_ROOT/simple/wheel"
cp /tmp/builddeps/setuptools*.whl "$INDEX_ROOT/simple/setuptools/"
cp /tmp/builddeps/wheel*.whl "$INDEX_ROOT/simple/wheel/"
```

2. **Use `--no-build-isolation`** (requires setuptools/wheel already installed):
```bash
/tmp/verifyvenv/bin/pip install --no-cache-dir --no-build-isolation \
    --index-url http://localhost:PORT/simple packagename==VERSION
```

3. **Publish wheel alongside sdist** (pip prefers wheels, skipping the build):
```bash
# Always build both - wheel avoids the build isolation issue entirely
python -m build --sdist --wheel
```

### Critical: --index-url Replaces PyPI

Using `--index-url` means pip **only** queries your local index.
Dependencies will fail to resolve unless:
1. They are also hosted in your index (in `simple/<dep-name>/`), OR
2. You add `--extra-index-url https://pypi.org/simple` (falls back to PyPI), OR
3. You use `--no-deps` (task must permit dependency-free installation)

**Note:** The spec may require "exact fresh installation without falling back
to another source" - in that case, all dependencies must be in your index.

### Force Reinstall (with Caution)

```bash
# --no-deps avoids dependency resolution against external indexes
pip install --index-url http://localhost:PORT/simple \
    --force-reinstall --no-deps packagename==VERSION
```

Warning: `--no-deps` skips dependency checking. Only use if task permits.

### Complete End-to-End Verification Protocol

```bash
# Configuration
PKG_NAME="vectorops"
PKG_VERSION="0.1.0"
PORT=8091

# Normalize name (COLLAPSE runs of separators)
PKG_NORM=$(echo "$PKG_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')

# 1. Verify on-disk layout (if task requires it)
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.whl || \
    echo "ERROR: Wheel not in expected location"
test -f "$INDEX_ROOT/simple/$PKG_NORM/"*.tar.gz || \
    echo "ERROR: Sdist not in expected location"

# 2. Verify HTTP index
curl -sf "http://localhost:$PORT/simple/" | grep "$PKG_NORM" || \
    echo "ERROR: Package not in root index"
curl -sf "http://localhost:$PORT/simple/$PKG_NORM/" | grep -E '\.(whl|tar\.gz)$' || \
    echo "ERROR: Artifacts not in package index"

# 3. Check what versions are available (for version replacement/preservation)
curl -sf "http://localhost:$PORT/simple/$PKG_NORM/" | grep -o 'href="[^"]*"'

# 4. Clean venv install test
python -m venv /tmp/verifyvenv
cd /tmp
/tmp/verifyvenv/bin/pip install --no-cache-dir \
    --index-url "http://localhost:$PORT/simple" "$PKG_NAME==$PKG_VERSION"

# 5. Verify installed from site-packages
/tmp/verifyvenv/bin/python -c "
import $PKG_NAME, inspect
assert 'site-packages' in $PKG_NAME.__file__, $PKG_NAME.__file_
from $PKG_NAME import required_function
print('Verification passed')
"
```

## Process Management

### Check if Server is Running

```bash
curl -sf http://localhost:PORT/simple/ > /dev/null && echo "Running" || echo "Not running"
```

### Stop Server (Only When Restarting)

```bash
# Using pidfile created at startup
kill "$(cat /tmp/pypi-index.pid)" 2>/dev/null || true
```

### Read Logs

```bash
cat /tmp/pypi-index.log
```

## Common Issues and Solutions

### Files Not Found at Expected Path

Verify the full path component by component:
```bash
ls -la "$INDEX_ROOT"                        # Should exist
ls -la "$INDEX_ROOT/simple"                 # Should exist
ls -la "$INDEX_ROOT/simple/$PKG_NORM"       # Should contain artifacts
ls -la "$INDEX_ROOT/simple/$PKG_NORM/"
```

**Check actual files vs expected:**
```bash
echo "Expected PKG_NORM: $PKG_NORM"
echo "Actual files in index:"
ls "$INDEX_ROOT/simple/$PKG_NORM/"
echo "Files in dist:"
ls /app/dist/
```

### Import From Source Instead of Site-Packages

```bash
# Check where import is coming from
python -c "import packagename; print(packagename.__file__)"
# Should contain "site-packages", not "/app/src/" or "/app/packagename"
```

### Stale Artifacts

Always clean before rebuilding:
```bash
rm -rf "$INDEX_ROOT/simple/$PKG_NORM"
rm -rf /app/dist /app/build /app/*.egg-info /app/src/*.egg-info
```

### Port Already in Use

Use a different port or kill existing process:
```bash
# Try different port
setsid nohup python -m http.server 8092 --directory "$INDEX_ROOT" \
    >/tmp/pypi-index.log 2>&1 </dev/null &
```

### pip Shows "Requirement already satisfied"

This means pip skipped the index entirely. Use `--force-reinstall` or uninstall first:
```bash
pip uninstall packagename
# Then install from local index
```

### Build Fails with "No module named setuptools"

In isolated build environments (default), setuptools must be downloadable. Solutions:
1. Use `--no-isolation` with already-installed setuptools
2. Host setuptools in your local index
3. Build wheels (avoids build isolation for clients)

## Complete Example (v01 Pattern)

```bash
# Configuration
PKG_NAME="vectorops"
PKG_VERSION="0.1.0"
PORT=8091
INDEX_ROOT="/app/pypi"

# 1. Create structure
mkdir -p /app/src/vectorops
cat > /app/src/vectorops/__init__.py << 'EOF'
def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))
EOF

# 2. Create pyproject.toml
cat > /app/pyproject.toml << 'EOF'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"

[tool.setuptools.packages.find]
where = ["src"]
EOF

# 3. Build (with fallback for offline)
pip install build
python -m build --sdist --wheel 2>/dev/null || \
    python -m build --sdist --wheel --no-isolation

# 4. Create static index tree
# Normalize with COLLAPSE: my_pkg → my-pkg, my..pkg → my-pkg
PKG_NORM=$(echo "$PKG_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')
mkdir -p "$INDEX_ROOT/simple/$PKG_NORM"

# Copy using GLOB (filenames use underscores!)
cp /app/dist/*.whl "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true
cp /app/dist/*.tar.gz "$INDEX_ROOT/simple/$PKG_NORM/" 2>/dev/null || true

# Verify on-disk layout
ls -la "$INDEX_ROOT/simple/$PKG_NORM/"

# 5. Start http.server (serves static tree)
setsid nohup python -m http.server $PORT --directory "$INDEX_ROOT" \
    >/tmp/pypi-index.log 2>&1 </dev/null &
echo $! > /tmp/pypi-index.pid
sleep 2

# 6. Verify server is up
curl -sf http://localhost:$PORT/simple/ || { echo "Server failed"; cat /tmp/pypi-index.log; exit 1; }

# 7. Verify HTTP index serves correctly
curl -sf http://localhost:$PORT/simple/ | grep "$PKG_NORM"
curl -sf http://localhost:$PORT/simple/$PKG_NORM/ | grep -E '\.(whl|tar\.gz)$'

# 8. Honest end-to-end verification
python -m venv /tmp/verifyvenv
cd /tmp
/tmp/verifyvenv/bin/pip install --no-cache-dir \
    --index-url http://localhost:$PORT/simple "$PKG_NAME==$PKG_VERSION"
/tmp/verifyvenv/bin/python -c "
import vectorops
assert 'site-packages' in vectorops.__file__
from vectorops import dotproduct
assert dotproduct([1,2], [3,4]) == 11
print('Success')
"

# 9. STOP - server must remain running
```

## Verification Checklist

- [ ] **Discovery complete:** Checked for pre-staged project, existing index, running server
- [ ] Package structure matches required layout (src/flat)
- [ ] Build metadata declares package discovery correctly
- [ ] Required exports available via specified import path
- [ ] Wheel and/or sdist built successfully in `/app/dist`
- [ ] **Normalization correct:** `PKG_NORM=$(echo "$PKG" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')`
- [ ] **On-disk layout correct:** `test -f $INDEX_ROOT/simple/$NORM/*.whl`
- [ ] **On-disk layout correct:** `test -f $INDEX_ROOT/simple/$NORM/*.tar.gz`
- [ ] **HTTP root index:** `curl $URL/simple/` shows package link
- [ ] **HTTP package index:** `curl $URL/simple/$NORM/` shows artifact links
- [ ] **Version handling:** Replace or preserve as required
- [ ] Installation from local index succeeds (verified with clean venv, --no-cache-dir)
- [ ] Installed package is from site-packages (not source tree)
- [ ] Installed package behaves correctly
- [ ] **Index server still running and reachable at handoff** (`curl -sf http://localhost:$PORT/simple/`)

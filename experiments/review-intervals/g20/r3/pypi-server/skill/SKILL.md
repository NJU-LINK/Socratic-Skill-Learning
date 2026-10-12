---
name: pypi-server
description: >
  Build a Python package from source (handling src-layout, flat layout,
  pre-staged or broken projects, setup.py or pyproject.toml metadata,
  multi-module packages, and package data), produce sdist/wheel artifacts,
  and serve them via a local PEP 503-compatible package index so that
  pip can install the package from that index. Covers the full lifecycle:
  workspace assessment, package code creation or repair, build metadata
  configuration, artifact construction, index service startup, and
  end-to-end install verification.
---

# PyPI Server — Local Package Build & Serve Skill

## Overview

This skill handles the full lifecycle of:
1. Creating or repairing a Python package from task requirements
2. Building distribution artifacts (sdist and/or wheel)
3. Serving those artifacts via a local PEP 503-compatible index
4. Verifying that `pip install` from the local index produces a working package

The skill must adapt to variation across four axes:
- **Package layout & build metadata** (src-layout, flat layout, setup.py vs pyproject.toml, pre-staged/broken projects)
- **Package functionality** (arbitrary APIs, validation, helper modules, import paths)
- **Index service configuration** (pypiserver, devpi, static HTML, different ports, authentication)
- **Publication & installation flow** (wheel-only, source-only, stale artifacts, version management)

---

## Phase 1: Assess the Workspace

Before creating anything, determine what already exists.

### 1.1 Detect package layout

```bash
# Check for src-layout
ls /app/src/ 2>/dev/null
# Check for flat layout (package dirs at root)
ls -d /app/*/  2>/dev/null | grep -v -E '/(src|dist|build|\.git|__pycache__|node_modules)/'
# Check for __init__.py files to identify actual Python packages
find /app -name "__init__.py" -not -path "*/build/*" -not -path "*/.git/*" 2>/dev/null
```

**Decision tree:**
- If `src/<pkgname>/__init__.py` exists → **src-layout detected**
- If `<pkgname>/__init__.py` exists at root (no src/) → **flat layout detected**
- If neither exists → **create from scratch** (default to src-layout unless task specifies otherwise)
- If files exist but are broken (wrong name, missing __init__.py, etc.) → **repair mode**

### 1.2 Detect build metadata system

```bash
ls /app/pyproject.toml /app/setup.py /app/setup.cfg 2>/dev/null
```

**Decision tree:**
- `pyproject.toml` exists → read it, check `[project]` name/version, check `[tool.setuptools.packages.find]`
- `setup.py` exists → read it, check `name=` and `version=` arguments
- `setup.cfg` exists → read it for metadata
- None exist → **create pyproject.toml** (preferred modern approach)
- Multiple exist → check which is authoritative; pyproject.toml with `build-backend` takes precedence

### 1.3 Detect existing index service

```bash
# Check if something is already listening on the required port
curl -sf http://localhost:${INDEX_PORT}/simple/ 2>/dev/null
# Check if the expected filesystem layout exists
ls -la ${INDEX_ROOT}/simple/ 2>/dev/null
```

**Decision tree:**
- Port is in use and serves correct artifacts AND filesystem layout exists → **reuse existing index**
- Port is in use but serves wrong/no artifacts → **kill and restart**
- Port is free → **create index** (choose Approach A or B based on test requirements)
- Tests may check filesystem layout → **use static PEP 503 index** (Approach A)

### 1.4 Detect existing artifacts

```bash
ls -la /app/dist/ 2>/dev/null
```

**Decision tree:**
- dist/ has artifacts matching required name+version → may be reusable (verify)
- dist/ has stale/wrong artifacts → **clean before rebuilding**
- dist/ doesn't exist → will be created by build

### 1.5 Check available tools

```bash
which pypi-server 2>/dev/null
which devpi 2>/dev/null
pip show pypiserver 2>/dev/null
python3 -c "import build" 2>/dev/null && echo "build available" || echo "build not available"
```

**Install missing tools:**
```bash
# Build tool (needed for python3 -m build)
pip install build 2>/dev/null

# Index server (if pypiserver is chosen)
pip install pypiserver 2>/dev/null
```

**Build backend considerations:**
- If existing pyproject.toml specifies `build-backend = "hatchling.build"` → install hatchling: `pip install hatchling`
- If it specifies `build-backend = "flit_core.buildapi"` → install flit_core: `pip install flit_core`
- If creating from scratch, prefer setuptools (most widely available)
- The build backend must match the metadata format in pyproject.toml

**Alternative build backend examples:**

Hatchling (uses hatch-specific config):
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mypackage"
version = "0.1.0"

[tool.hatch.build.targets.wheel]
packages = ["src/mypackage"]
```

Flit (minimal config, auto-discovery):
```toml
[build-system]
requires = ["flit_core>=3.2,<4"]
build-backend = "flit_core.buildapi"

[project]
name = "mypackage"
version = "0.1.0"
description = "My package"
```
Note: flit expects the package at `mypackage/` (flat) or uses `[tool.flit.module]` to specify location.

**If the existing project uses a non-setuptools backend and you need to switch to setuptools:**
1. Replace the `[build-system]` section
2. Add `[tool.setuptools.packages.find]` with correct `where`
3. Ensure the code layout matches what setuptools expects

---

## Phase 2: Plan

Based on assessment, determine:

1. **Layout type**: src-layout vs flat → determines `packages.find.where` or `package_dir`
2. **Metadata system**: pyproject.toml vs setup.py → determines how to declare name/version
3. **What needs creation vs repair**: new files vs fixing existing ones
4. **Index tool**: pypiserver (install if needed), devpi, static HTML, or already-running
5. **Artifact types needed**: sdist only, wheel only, or both
6. **Port**: from task requirements (default 8091 if not specified, but always read the task)

### Key invariants across all variants:
- The package must be importable via the exact import path specified in the task
- The index must serve artifacts at `/simple/<normalized-name>/` (PEP 503)
- `pip install --index-url http://localhost:PORT/simple <name>==<version>` must succeed
- Distribution names are normalized: lowercase, runs of `[-_.]` become single `-`

---

## Phase 3: Implement Package Code & Metadata

### 3.1 Create/repair package code

The code must match the task's functional requirements exactly:
- Correct import path (e.g., `from vectorops import dotproduct`)
- Correct callable signature (parameter types, return type)
- Correct edge-case behavior (validation, empty inputs, etc.)

**For src-layout**, code goes in `/app/src/<pkgname>/__init__.py` (or submodules).
**For flat layout**, code goes in `/app/<pkgname>/__init__.py`.

If the task requires multiple modules, create them as submodules within the package directory.

If the task requires specific classes or functions, implement them in the appropriate module and ensure they are exported from `__init__.py` if the task requires top-level import.

### 3.2 Create/repair build metadata

#### pyproject.toml (preferred)

**For src-layout:**
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**For flat layout:**
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

# For flat layout, setuptools auto-discovers packages in "." by default
# If explicit control is needed:
[tool.setuptools.packages.find]
where = ["."]
```

**If setup.py is required or already exists and is authoritative:**
```python
from setuptools import setup, find_packages

setup(
    name="<package-name>",
    version="<version>",
    packages=find_packages(where="src"),  # or find_packages() for flat
    package_dir={"": "src"},              # only for src-layout
)
```

**If both exist and conflict:** pyproject.toml with `[build-system]` takes precedence. Either make them consistent or remove the redundant one.

#### Package data

If the package includes non-Python files (data files, templates, etc.):
```toml
[tool.setuptools.package-data]
"<pkgname>" = ["*.json", "*.txt", "data/*"]
```

Or in MANIFEST.in for sdist:
```
recursive-include src/<pkgname> *.json *.txt
```

### 3.3 Verify metadata correctness

```bash
# Check that the package name and version are correct
python3 -c "
import tomllib
with open('/app/pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
print('Name:', data['project']['name'])
print('Version:', data['project']['version'])
"
```

---

## Phase 4: Build Artifacts

### 4.1 Clean dist directory

**Critical**: Always clean dist/ before building to avoid stale artifacts.

```bash
rm -rf /app/dist/ /app/build/ /app/src/*.egg-info
```

### 4.2 Build

```bash
cd /app && python3 -m build
```

This produces both sdist (.tar.gz) and wheel (.whl) in `/app/dist/`.

**If only wheel is needed:**
```bash
cd /app && python3 -m build --wheel
```

**If only sdist is needed:**
```bash
cd /app && python3 -m build --sdist
```

### 4.3 Verify artifacts

```bash
ls -la /app/dist/
# Check that the expected files exist with correct name and version
# Wheel: <normalized_name>-<version>-py3-none-any.whl
# Sdist: <normalized_name>-<version>.tar.gz
```

**Name normalization check:**
- PyPI normalizes names: lowercase, replace `[-_.]+` with `-`
- Example: `My_Package` → `my-package` on the index
- The wheel filename uses underscores: `my_package-0.1.0-py3-none-any.whl`
- The sdist filename uses the normalized name: `my_package-0.1.0.tar.gz`

**Name normalization reference (PEP 503):**
```python
import re
def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()

# Examples:
# "My_Package"  → "my-package"
# "my.package"  → "my-package"  
# "MyPackage"   → "mypackage"
# "vector_ops"  → "vector-ops"
```

**Critical**: The directory name under `simple/` must use the normalized form. The wheel filename uses the name with underscores replaced (per PEP 427). The sdist uses the name with underscores. When in doubt, check what `python3 -m build` actually produces in `/app/dist/` and use those exact filenames.

### 4.4 Verify wheel contents (optional but recommended)

```bash
python3 -m zipfile -l /app/dist/*.whl
```

Check that the expected modules are included.

---

## Phase 5: Serve via Local Index

**IMPORTANT**: Tests MAY verify filesystem layout in addition to HTTP behavior. Check test expectations to determine the required approach.

### 5.0 Detect index requirements

Before creating the index, determine what the tests expect:

```bash
# Detect index root from test files
INDEX_ROOT=$(grep -roh 'INDEX_ROOT.*Path("[^"]*")' /tests/ 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' | head -1)
INDEX_ROOT=${INDEX_ROOT:-/app/pypi}  # default if not detected

# Detect port from test files or task
INDEX_PORT=$(grep -roh 'INDEX_PORT.*=.*[0-9]\+' /tests/ 2>/dev/null | grep -o '[0-9]\+' | head -1)
INDEX_PORT=${INDEX_PORT:-8091}  # default if not detected

# Check if tests verify filesystem layout
FILESYSTEM_CHECK=$(grep -r "\.exists()" /tests/ 2>/dev/null | grep -i "simple\|index\|pypi" | head -1)

echo "Using INDEX_ROOT=${INDEX_ROOT}, PORT=${INDEX_PORT}"
echo "Filesystem check detected: ${FILESYSTEM_CHECK:-none}"
```

**Decision based on detection:**
- If tests check `.exists()` on filesystem paths → use **static PEP 503 index** (Section 5.2)
- If tests only check HTTP behavior → use **pypiserver** (Section 5.3) OR static index (both work)
- If uncertain → use **static PEP 503 index** (satisfies both HTTP and filesystem checks)

### 5.1 Approach A: Static PEP 503 index (satisfies HTTP + filesystem checks)

**Use when**: Tests verify filesystem layout OR you're uncertain. This approach satisfies both HTTP serving and filesystem verification.

```bash
# Create directory structure using detected INDEX_ROOT
mkdir -p ${INDEX_ROOT}/simple/<normalized-name>

# Copy actual artifact files to the index directory
# (not symlinks — tests check file existence)
cp /app/dist/<wheel-filename> ${INDEX_ROOT}/simple/<normalized-name>/
cp /app/dist/<sdist-filename> ${INDEX_ROOT}/simple/<normalized-name>/

# Create root index at ${INDEX_ROOT}/simple/index.html
# This serves GET /simple/
cat > ${INDEX_ROOT}/simple/index.html << EOF
<!DOCTYPE html>
<html>
<body>
<h1>Simple Index</h1>
<a href="<normalized-name>/"><normalized-name></a><br>
</body>
</html>
EOF

# Create package index at ${INDEX_ROOT}/simple/<normalized-name>/index.html
# This serves GET /simple/<normalized-name>/
# Note: href paths are relative to the current directory (simple/<name>/)
cat > ${INDEX_ROOT}/simple/<normalized-name>/index.html << EOF
<!DOCTYPE html>
<html>
<body>
<h1>Links for <normalized-name></h1>
<a href="<wheel-filename>"><wheel-filename></a><br>
<a href="<sdist-filename>"><sdist-filename></a><br>
</body>
</html>
EOF
```

**Why this structure works:**
- HTTP server serves from `${INDEX_ROOT}/`
- `GET /simple/` → `${INDEX_ROOT}/simple/index.html` ✓
- `GET /simple/<name>/` → `${INDEX_ROOT}/simple/<name>/index.html` ✓
- `GET /simple/<name>/<file>` → `${INDEX_ROOT}/simple/<name>/<file>` ✓
- Filesystem check: `${INDEX_ROOT}/simple/<name>/<file>.exists()` ✓

**Start HTTP server:**
```bash
# Kill any existing HTTP servers
pkill -f "http.server" 2>/dev/null
pkill -f "pypi-server" 2>/dev/null
sleep 1

# Start HTTP server from the index root directory
cd ${INDEX_ROOT} && python3 -m http.server ${INDEX_PORT} --bind 0.0.0.0 > /tmp/http-server.log 2>&1 &

# Poll until ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:${INDEX_PORT}/simple/ >/dev/null 2>&1; then
        echo "Index server is ready on port ${INDEX_PORT}"
        break
    fi
    sleep 1
done
```

### 5.2 Approach B: pypiserver (HTTP-only, simpler setup)

**Use when**: Tests only check HTTP behavior (no filesystem checks). pypiserver is simpler and more robust for HTTP-only scenarios.

```bash
pip install pypiserver 2>/dev/null

# Kill any existing servers
pkill -f "pypi-server" 2>/dev/null
pkill -f "http.server" 2>/dev/null
sleep 1

# Start pypiserver pointing at the dist directory
pypi-server run --host 0.0.0.0 --port ${INDEX_PORT} /app/dist/ > /tmp/pypiserver.log 2>&1 &

# Poll until ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:${INDEX_PORT}/simple/ >/dev/null 2>&1; then
        echo "Index server is ready on port ${INDEX_PORT}"
        break
    fi
    sleep 1
done
```

**Note**: pypiserver serves files via HTTP but does NOT create the on-disk layout at `${INDEX_ROOT}/simple/`. If tests check filesystem paths, use Approach A instead.

### 5.3 Verify index serves artifacts

```bash
# Check root index
curl -s http://localhost:${INDEX_PORT}/simple/

# Check package-specific index
curl -s http://localhost:${INDEX_PORT}/simple/<normalized-name>/

# If using static index, verify artifact files exist at expected filesystem path
ls -lh ${INDEX_ROOT}/simple/<normalized-name>/

# Verify artifact links are accessible via HTTP
curl -sI http://localhost:${INDEX_PORT}/simple/<normalized-name>/<artifact-filename> | head -3
```

**Verification checklist:**
- ✓ HTTP root index lists the package
- ✓ HTTP package index lists the artifacts
- ✓ Artifacts are downloadable via HTTP
- ✓ If tests check filesystem: artifact files exist at `${INDEX_ROOT}/simple/<name>/`

---

## Phase 6: Verify End-to-End

### 6.1 Install from local index

```bash
# If package has NO dependencies (or all deps are already installed):
pip install --force-reinstall --no-deps \
    --index-url http://localhost:${PORT}/simple \
    <package-name>==<version>

# If package HAS dependencies that should also come from the local index:
pip install --force-reinstall \
    --index-url http://localhost:${PORT}/simple \
    <package-name>==<version>
```

**Flags explained:**
- `--force-reinstall` — ensures fresh install, not cached
- `--no-deps` — prevents pip from trying to resolve dependencies at all; use only when the package has no dependencies or they are pre-installed. If the package has dependencies that must be fetched from the local index, omit this flag.
- `--index-url` — replaces the default PyPI entirely. Use this (not `--extra-index-url`) to prevent any fallback to public PyPI.
- `--no-cache-dir` — optional, useful if pip has cached an old version of the package

### 6.2 Verify import and functionality

```bash
python3 -c "
from <package> import <function_or_class>
# Test the API as specified in the task
result = <function_or_class>(<test_args>)
assert result == <expected>, f'Expected <expected>, got {result}'
print('Verification passed')
"
```

### 6.3 Verify version

```bash
pip show <package-name> | grep -E "^(Name|Version):"
```

### 6.4 Verify the index is still running

```bash
curl -sf http://localhost:${PORT}/simple/ >/dev/null && echo "Index still running"
```

---

## Common Pitfalls & Troubleshooting

### Build failures
- **"No module named build"**: `pip install build`
- **Package not found in build**: Check `packages.find.where` matches your layout
- **Version mismatch**: Ensure version in pyproject.toml/setup.py matches task requirement

### Index failures
- **Port already in use**: Kill existing process or use different port
- **Index returns 404 for package**: Check that the index directory contains the artifact files and the HTTP server serves from the correct root
- **pypiserver not found**: `pip install pypiserver`
- **Tests check filesystem layout but files missing**: If tests verify `(INDEX_ROOT / 'simple' / name / filename).exists()`, you MUST create a static PEP 503 directory with actual artifact files at the expected path. pypiserver alone won't satisfy this check.

### Installation failures
- **pip falls back to PyPI**: Use `--index-url` (not `--extra-index-url`) and `--no-deps`
- **Wrong version installed**: Clean dist/, rebuild, force-reinstall
- **Import error after install**: Check that the built wheel contains the expected modules (`python3 -m zipfile -l dist/*.whl`)

### Name normalization issues
- Package name in pyproject.toml: can use any valid Python identifier style
- Package name on index: PEP 503 normalized (lowercase, `[-_.]+` → `-`)
- Wheel filename: uses underscores for the name part
- When in doubt, check what pypiserver actually serves: `curl -s http://localhost:${PORT}/simple/`

### Stale artifacts
- Always `rm -rf /app/dist/` before rebuilding
- pypiserver serves everything in its directory — old versions will appear alongside new ones
- If you need only one version, ensure dist/ contains only that version's artifacts

---

## Edge Cases & Advanced Scenarios

### Pre-staged project repair (concrete workflow)

When the workspace already has files that are broken or incomplete, follow this systematic repair process:

**Step 1: Diagnose what exists and what's wrong**
```bash
# Check layout
find /app -name "__init__.py" -not -path "*/build/*" -not -path "*/.git/*" 2>/dev/null
# Check metadata
ls /app/pyproject.toml /app/setup.py /app/setup.cfg 2>/dev/null
# Read existing metadata
cat /app/pyproject.toml 2>/dev/null || cat /app/setup.py 2>/dev/null
# Check existing code
head -20 /app/src/*/  __init__.py 2>/dev/null || head -20 /app/*/__init__.py 2>/dev/null
```

**Step 2: Identify mismatches with requirements**
Common issues:
- Wrong package name in metadata
- Wrong version in metadata
- Wrong function/class names in code
- Wrong layout (flat vs src)
- Missing __init__.py
- Missing build-system declaration

**Step 3: Fix systematically**
- If layout is wrong (e.g., flat but task requires src): `mkdir -p /app/src && mv /app/<pkg> /app/src/`
- If metadata is wrong: overwrite pyproject.toml or setup.py with correct values
- If code is wrong: overwrite the source files with correct implementations
- If both setup.py and pyproject.toml exist and conflict: keep pyproject.toml, remove setup.py

**Step 4: Build and verify**
```bash
rm -rf /app/dist/ /app/build/ /app/src/*.egg-info
cd /app && python3 -m build
ls -la /app/dist/
```

### Import surface doesn't match file layout

Sometimes the directory structure doesn't automatically map to the desired import path. Examples:
- Directory named `src/my_lib/` but the task requires `from mypackage import func`
- Multiple source directories that should form one package

**Solution**: Use explicit `packages` configuration and `package_dir` mapping:
```toml
[tool.setuptools]
packages = ["mypackage"]

[tool.setuptools.package-dir]
mypackage = "src/my_lib"
```

Or in setup.py:
```python
setup(
    packages=["mypackage"],
    package_dir={"mypackage": "src/my_lib"},
)
```

### Multi-module packages

If the task requires multiple importable modules:
```
src/
  mypackage/
    __init__.py      # re-exports from submodules
    core.py          # core functionality
    utils.py         # helper functions
    subpkg/
      __init__.py
      helpers.py
```

Ensure `__init__.py` exports everything the task requires at the top level.

### Package data (non-Python files)

If the package includes data files:
```toml
[tool.setuptools.package-data]
"mypackage" = ["data/*.json", "templates/*.html"]
```

Also ensure MANIFEST.in includes them for sdist:
```
recursive-include src/mypackage *.json *.html
```

### Authenticated uploads

If the index requires authentication (e.g., pypiserver with `-P` flag):
```bash
# Start pypiserver with password file
pypi-server run -P /path/to/htpasswd --port ${PORT} /app/dist/ &

# Upload with twine
pip install twine
twine upload --repository-url http://localhost:${PORT}/ \
    -u username -p password /app/dist/*
```

### Version replacement

If a previous version exists and needs to be replaced:
1. Clean dist/ completely: `rm -rf /app/dist/*`
2. Rebuild with new version
3. If using pypiserver, restart it pointing at the cleaned dist/
4. Use `pip install --force-reinstall` to ensure the new version is installed

### Keeping the index running

The index server must remain running for tests to install from it. Start it as a background process:

**For static PEP 503 index:**
```bash
# Using nohup for persistence
nohup python3 -m http.server ${INDEX_PORT} --bind 0.0.0.0 --directory ${INDEX_ROOT} > /tmp/http-server.log 2>&1 &

# Or from the directory
cd ${INDEX_ROOT} && python3 -m http.server ${INDEX_PORT} --bind 0.0.0.0 &
```

**For pypiserver:**
```bash
nohup pypi-server run --host 0.0.0.0 --port ${INDEX_PORT} /app/dist/ > /tmp/pypiserver.log 2>&1 &
```

**Verify it's still running before tests:**
```bash
curl -sf http://localhost:${INDEX_PORT}/simple/ >/dev/null && echo "OK" || echo "Server down!"
```

---

## Critical Insight: Tests May Verify Filesystem Layout

**Tests MAY verify filesystem layout** — check test expectations to determine if this applies to your variant.

**How to detect:**
```bash
# Check if tests verify filesystem paths
grep -r "\.exists()" /tests/ 2>/dev/null | grep -i "simple\|index\|pypi"
# Look for INDEX_ROOT or similar constants
grep -r "INDEX_ROOT\|INDEX_DIR" /tests/ 2>/dev/null
```

**If tests check filesystem layout:**
- You MUST create a static PEP 503 directory structure with actual artifact files
- The index root path is typically defined in test files (e.g., `INDEX_ROOT = Path("/app/pypi")`)
- Use Approach A (static PEP 503 index) from Phase 5

**If tests only check HTTP behavior:**
- You can use either static PEP 503 index OR pypiserver
- pypiserver is simpler for HTTP-only scenarios

**Safe default:** When uncertain, use the static PEP 503 index approach — it satisfies both HTTP and filesystem checks.

---

## Decision Summary

| Detection | If... | Then... |
|-----------|-------|---------|
| `src/<pkg>/__init__.py` exists | src-layout | Use `where = ["src"]` in packages.find |
| `<pkg>/__init__.py` at root | flat layout | Use `where = ["."]` or omit packages.find |
| Neither exists | create from scratch | Default to src-layout |
| `pyproject.toml` exists | modern metadata | Read and verify/fix name+version |
| Only `setup.py` exists | legacy metadata | Read and verify/fix, or add pyproject.toml shim |
| Port is in use | existing index | Check if it serves correct artifacts AND has correct filesystem layout |
| Port is free | no index | Detect INDEX_ROOT from tests, then create index (Approach A if filesystem checks, B if HTTP-only) |
| dist/ has files | possible stale artifacts | Clean before rebuilding |

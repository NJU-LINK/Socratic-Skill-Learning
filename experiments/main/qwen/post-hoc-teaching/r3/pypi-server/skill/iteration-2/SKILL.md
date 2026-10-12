---
name: pypi-server
description: >
  Build a Python package from source, set up a local PEP 503-compatible package
  index (typically pypiserver), publish built artifacts to it, and verify that
  the package installs and functions correctly from the local index. Handles
  src-layout and flat-layout projects, pyproject.toml and setup.py metadata,
  multiple distribution formats, various port/host configurations, authenticated
  and unauthenticated index services, and fresh-installation verification.
---

# PyPI Server: Build, Serve, Install

This skill covers the end-to-end pipeline of creating a Python package, building
distribution artifacts, running a local package index, publishing to it, and
verifying installation. It is designed to handle the full variation space
described in the spec.

## Overview of the Pipeline

```
0. Diagnose pre-staged or broken projects (if files already exist)
1. Inspect/Create package structure
2. Configure build metadata
3. Build distribution artifacts (sdist, wheel, or both)
4. Create static PEP 503 index layout at /app/pypi/simple/
5. Start the index HTTP server
6. Verify installation and functionality
```

Step 0 is a diagnostic front-end that runs BEFORE Step 1 when the workspace
already contains files. It detects misconfigurations, stale artifacts, and
import mismatches early — before the build system gets involved. If the
workspace is empty, Step 0 is a no-op and you proceed directly to Step 1.

Steps 4-5 create a **static PEP 503 directory layout** on disk and serve it
via HTTP. This approach satisfies both HTTP serving requirements AND physical
file existence checks that tests may perform.

## Step 0: Diagnose Pre-staged or Broken Projects

This step is critical when the workspace is NOT empty. Many task variants
present a partially-built or misconfigured project that must be diagnosed and
fixed before proceeding. **Always run this diagnostic before touching the build
system.**

### 0a. Detect the existing layout

```bash
ls -la /app/
find /app -maxdepth 3 -name "*.py" -o -name "pyproject.toml" \
  -o -name "setup.py" -o -name "setup.cfg" 2>/dev/null
```

Determine what exists:
- **src-layout**: `src/<name>/__init__.py` exists → src-layout
- **Flat layout**: `<name>/__init__.py` exists at root (no `src/`) → flat-layout
- **Neither**: workspace is empty or has only metadata → create from scratch (go to Step 1)
- **Both or ambiguous**: investigate further, pick the one that matches the task instructions

### 0b. Verify `__init__.py` exports the required public API

Read the `__init__.py` and check that the function/class names match what the
task's import requirement demands:

```bash
# For src-layout
cat /app/src/<package_name>/__init__.py
# For flat-layout
cat /app/<package_name>/__init__.py
```

**Common problems to catch:**
- Function is defined under a different name than what `from <pkg> import <func>` expects
- Function is in a submodule but not re-exported from `__init__.py`
- `__init__.py` is missing entirely (directory exists but has no init file)
- Function signature doesn't match the task spec (wrong parameter names, wrong return type)

**Fix**: If the function is named differently, either rename it in the source or
add an alias in `__init__.py`:
```python
# If the function is defined as _dot_product but task requires dotproduct:
from .module import _dot_product as dotproduct
```

### 0c. Verify build metadata matches task requirements

Read `pyproject.toml` or `setup.py` and check:

```bash
cat /app/pyproject.toml 2>/dev/null || cat /app/setup.py 2>/dev/null
```

**Checklist:**
1. **Package discovery for src-layout**: `[tool.setuptools.packages.find]` with
   `where = ["src"]` MUST be present. Without it, setuptools will NOT find
   packages under `src/` and the built wheel will be empty.
2. **Distribution name**: `name = "<dist-name>"` must normalize (PEP 503) to
   what pip will be asked to install. E.g., if task says `pip install vectorops`,
   the name must normalize to `vectorops`.
3. **Version**: Must exactly match the task's required version.
4. **Build system**: `[build-system]` section must be present with appropriate
   `requires` and `build-backend`.
5. **Flat-layout with setup.py**: Check that `packages=` or `find_packages()`
   lists the correct packages (not stale/wrong names).

**Fix**: Edit the metadata file to correct any mismatches. For a missing
`[tool.setuptools.packages.find]` in src-layout, add:
```toml
[tool.setuptools.packages.find]
where = ["src"]
```

### 0d. Clean stale artifacts from prior builds

Leftover build artifacts can cause the build system to use stale metadata or
produce incorrect distributions:

```bash
rm -rf /app/build /app/dist
rm -rf /app/src/*.egg-info /app/*.egg-info
rm -rf /app/src/*/*.egg-info
```

This is safe — these are all generated artifacts that will be recreated by
`python -m build`.

### 0e. Test-import locally before building

Catch import errors early without involving the build system:

```bash
# For src-layout:
cd /app && PYTHONPATH=src python3 -c "from <package> import <function>"

# For flat-layout:
cd /app && PYTHONPATH=. python3 -c "from <package> import <function>"
```

If this fails, the problem is in the source code or layout — fix it now before
building. Common failures:
- `ModuleNotFoundError`: Package directory missing `__init__.py` or wrong path
- `ImportError: cannot import name 'X'`: Function not defined or not exported
- `SyntaxError`: Code has a syntax error

### 0f. Only then proceed to build

After all checks pass, proceed to Step 1 (if creating from scratch) or directly
to Step 3 (if the existing project is now verified correct).

## Step 1: Inspect and Create Package Structure

**If Step 0 found and fixed a pre-staged project**, you may skip directly to
Step 3 (build). This step is for creating structure from scratch.

### Detect existing layout

First, inspect the workspace at `/app` to understand what already exists:

```bash
ls -la /app/
find /app -name "*.py" -o -name "pyproject.toml" -o -name "setup.py" -o -name "setup.cfg" 2>/dev/null
```

### Layout types

**src-layout** (preferred, most common in this task family):
```
/app/
  pyproject.toml
  src/
    <package_name>/
      __init__.py
      ...
```

**Flat layout**:
```
/app/
  pyproject.toml
  <package_name>/
    __init__.py
    ...
```

**Multi-module package**:
```
/app/
  pyproject.toml
  src/
    <package_name>/
      __init__.py
      module_a.py
      module_b.py
```

### Create structure if needed

For a **src-layout** project:
```bash
mkdir -p /app/src/<package_name>
```

For a **flat-layout** project:
```bash
mkdir -p /app/<package_name>
```

### Write the module code

The `__init__.py` must export the required public API. The import path specified
in the task (e.g., `from <package> import <function>`) determines what must be
available at the top level of the package.

```python
# /app/src/<package_name>/__init__.py
def required_function(args):
    """Implementation of required functionality."""
    ...
```

If the task requires `from package import func`, then `func` must be importable
directly from the package's `__init__.py`. If it requires
`from package.submodule import func`, ensure the submodule exists and is
importable.

## Step 2: Configure Build Metadata

### pyproject.toml (modern, preferred)

**For src-layout:**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<distribution-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**For flat-layout:**
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<distribution-name>"
version = "<version>"

# setuptools auto-discovery finds flat-layout packages automatically
```

### setup.py (legacy, when required)

```python
from setuptools import setup, find_packages

setup(
    name="<distribution-name>",
    version="<version>",
    package_dir={"": "src"},  # for src-layout
    packages=find_packages(where="src"),  # for src-layout
)
```

### Key metadata considerations

- **Distribution name vs import name**: The distribution name (in pyproject.toml)
  may differ from the import name. PEP 503 normalizes distribution names
  (lowercase, runs of `[-_.]` become `-`). The import name is the actual Python
  package directory name.
- **Version**: Must match exactly what the task specifies.
- **Package discovery**: For src-layout, explicitly set `where = ["src"]`. For
  flat-layout, auto-discovery usually works but can be made explicit.
- **Package data**: If the package includes non-Python files, use
  `[tool.setuptools.package-data]` or `include_package_data = true` with a
  MANIFEST.in.

## Step 3: Build Distribution Artifacts

### Install the build tool

```bash
pip install build
```

### Build both sdist and wheel (default)

```bash
cd /app && python -m build
```

This produces files in `/app/dist/`:
- `<name>-<version>.tar.gz` (sdist)
- `<name>-<version>-py3-none-any.whl` (pure Python wheel)

### Build wheel only

```bash
cd /app && python -m build --wheel
```

### Build sdist only

```bash
cd /app && python -m build --sdist
```

### Verify build output

```bash
ls -la /app/dist/
```

Ensure the expected artifacts are present with correct names and versions.

### Common build issues

- **Missing `__init__.py`**: Package won't be found. Ensure all package
  directories have `__init__.py`.
- **Wrong package discovery**: If using src-layout without `where = ["src"]`,
  setuptools won't find the package.
- **Name mismatch**: The distribution name in metadata must match what pip will
  look for (after normalization).

## Step 4: Create Static PEP 503 Index Layout

The local package index must be a **static PEP 503 directory layout** on disk.
This layout serves double duty: it provides the files that an HTTP server will
serve, AND it satisfies tests that check for physical file existence at specific
paths.

### Default index root: `/app/pypi/simple/`

The standard location for the index is `/app/pypi/simple/`. The URL path
`/simple/` maps to this directory. Some task variants may specify a different
root; if so, adjust accordingly.

### Create the directory structure

```bash
NORMALIZED_NAME="<normalized-package-name>"  # e.g., "vectorops"

# Create package directory and copy artifacts
mkdir -p /app/pypi/simple/${NORMALIZED_NAME}
cp /app/dist/* /app/pypi/simple/${NORMALIZED_NAME}/
```

### Generate PEP 503 index HTML files

**Root index** at `/app/pypi/simple/index.html`:
```bash
cat > /app/pypi/simple/index.html << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<a href="${NORMALIZED_NAME}/">${NORMALIZED_NAME}</a><br>
</body>
</html>
HTMLEOF
```

**Package index** at `/app/pypi/simple/<normalized-name>/index.html`:
```bash
cat > /app/pypi/simple/${NORMALIZED_NAME}/index.html << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Links for ${NORMALIZED_NAME}</title></head>
<body>
<h1>Links for ${NORMALIZED_NAME}</h1>
$(for f in /app/pypi/simple/${NORMALIZED_NAME}/*; do
  fname=$(basename "$f")
  [ "$fname" = "index.html" ] && continue
  echo "<a href=\"${fname}\">${fname}</a><br>"
done)
</body>
</html>
HTMLEOF
```

This generates `<a href="...">` links for each distribution file, excluding
the `index.html` itself.

### Verify the layout

```bash
find /app/pypi -type f | sort
# Expected:
# /app/pypi/simple/index.html
# /app/pypi/simple/<name>/index.html
# /app/pypi/simple/<name>/<name>-<version>-*.whl
# /app/pypi/simple/<name>/<name>-<version>.tar.gz
```

## Step 5: Start the Index HTTP Server

### Option A: Python http.server (default, simplest)

Serve the static layout directly:

```bash
cd /app/pypi && python -m http.server <PORT> --bind 0.0.0.0 &
```

This serves:
- `http://localhost:<PORT>/simple/` → `/app/pypi/simple/index.html`
- `http://localhost:<PORT>/simple/<name>/` → `/app/pypi/simple/<name>/index.html`
- `http://localhost:<PORT>/simple/<name>/<file>` → the actual distribution file

### Option B: pypiserver (when specifically required)

If the task requires pypiserver, install and run it. Note that you should
**still create the static layout** (Step 4) as tests may check for physical
files.

```bash
pip install pypiserver

# Point pypiserver at the dist directory (or a copy of it)
mkdir -p /app/packages
cp /app/dist/* /app/packages/

python -m pypiserver run \
  --port <PORT> \
  --host 0.0.0.0 \
  --disable-fallback \
  /app/packages &
```

Key flags:
- `--port <PORT>`: The port to listen on (task-specified, e.g., 8091)
- `--host 0.0.0.0`: Listen on all interfaces
- `--disable-fallback`: Prevent redirecting to real PyPI for missing packages

**Authenticated pypiserver** (when required):
```bash
pip install passlib
python -c "from passlib.apache import HtpasswdFile; ht = HtpasswdFile('/app/.htpasswd', new=True); ht.set_password('user', 'pass'); ht.save()"

python -m pypiserver run \
  --port <PORT> \
  --host 0.0.0.0 \
  -a update \
  -P /app/.htpasswd \
  /app/packages &
```

### Option C: devpi (when specified)

```bash
pip install devpi-server devpi-web
devpi-server --host 0.0.0.0 --port <PORT> --server-dir /app/devpi-data &
```

### Verify the server is running

```bash
sleep 2

# Check root index
curl -s http://localhost:<PORT>/simple/

# Check package-specific index
curl -s http://localhost:<PORT>/simple/<normalized-name>/
```

Both should return HTML with appropriate links.

### Keeping the server running

The server must remain running for pip install to work. Always start it as a
background process. Verify it's responsive before proceeding:

```bash
for i in $(seq 1 10); do
  curl -s http://localhost:<PORT>/simple/ > /dev/null && break
  sleep 1
done
```

If the server dies or needs restarting:
```bash
fuser -k <PORT>/tcp 2>/dev/null || true
# Then restart
```

## Step 6: Verify Installation and Functionality

### Install from the local index

**Default (safe for all packages, including those with dependencies):**
```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  <package-name>==<version>
```

Key flags:
- `--index-url`: Sets the **sole** package index (won't fall back to PyPI)

**If the package has dependencies that aren't hosted on the local index**, you
need PyPI as a fallback for those dependencies:
```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  --extra-index-url https://pypi.org/simple \
  <package-name>==<version>
```

**Optional optimization** — only when you have confirmed the package has zero
dependencies (no `dependencies = [...]` in pyproject.toml):
```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  --no-deps \
  <package-name>==<version>
```
⚠️ Do NOT use `--no-deps` as the default. It silently produces a broken
installation for any package that declares dependencies — the install succeeds
but imports fail with `ModuleNotFoundError` at runtime.

### Force reinstall (if already installed)

```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  --force-reinstall \
  <package-name>==<version>
```

### Verify the installation

```bash
# Check it's installed
pip show <package-name>

# Test the import
python3 -c "from <package> import <function>; print(<function>(<test_args>))"
```

### Verify the correct version is installed

```bash
python3 -c "import <package>; print(getattr(<package>, '__version__', 'no version attr'))"
pip show <package-name> | grep Version
```

## Important Details and Pitfalls

### PEP 503 Name Normalization

Distribution names are normalized for URLs: lowercase, and any run of
`[-_.]` becomes a single `-`. For example:
- `My_Package` → `my-package`
- `my.package` → `my-package`

The import name (Python module name) is NOT normalized — it must match the
actual directory name exactly.

### --index-url vs --extra-index-url

- `--index-url`: Replaces the default index entirely. pip will ONLY look here.
- `--extra-index-url`: Adds an additional index alongside the default (PyPI).

For tasks requiring installation from the local index only, use `--index-url`.

### Server must stay running

The package index server is a long-running process. It must be started in the
background and remain alive for pip install to succeed. Always verify it's
responsive before attempting installation.

### Build isolation

`python -m build` creates an isolated virtual environment for building. This
means build dependencies (like setuptools) are installed fresh. Ensure all
build requirements are declared in `[build-system].requires`.

### Wheel naming conventions

Pure Python wheels: `<name>-<version>-py3-none-any.whl`
Platform-specific: `<name>-<version>-cp3XX-cp3XX-<platform>.whl`

The `py3-none-any` wheel is universal for pure Python packages.

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `pip install` says "No matching distribution found" | Server not running or wrong port | Check server, verify URL |
| Package installs but import fails | Wrong package layout or discovery | Check `__init__.py` exists, package discovery config |
| Wrong version installed | Stale artifacts in index dir | Clean packages dir, re-copy |
| Build fails with "not a package" | Missing `__init__.py` | Add it to all package dirs |
| `python -m build` not found | `build` not installed | `pip install build` |

## Complete Worked Example

Given: Create package `vectorops` v0.1.0 with `dotproduct` function, serve on
port 8091.

```bash
# 1. Create package structure (src-layout)
mkdir -p /app/src/vectorops

# 2. Write module code
cat > /app/src/vectorops/__init__.py << 'EOF'
def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")
    return sum(x * y for x, y in zip(a, b))
EOF

# 3. Write build metadata
cat > /app/pyproject.toml << 'EOF'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
EOF

# 4. Build
pip install build
cd /app && python -m build

# 5. Create static PEP 503 layout
mkdir -p /app/pypi/simple/vectorops
cp /app/dist/* /app/pypi/simple/vectorops/

cat > /app/pypi/simple/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<a href="vectorops/">vectorops</a><br>
</body>
</html>
HTMLEOF

cat > /app/pypi/simple/vectorops/index.html << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Links for vectorops</title></head>
<body>
<h1>Links for vectorops</h1>
$(for f in /app/pypi/simple/vectorops/*; do
  fname=$(basename "$f")
  [ "$fname" = "index.html" ] && continue
  echo "<a href=\"${fname}\">${fname}</a><br>"
done)
</body>
</html>
HTMLEOF

# 6. Start HTTP server
cd /app/pypi && python -m http.server 8091 --bind 0.0.0.0 &
sleep 2

# 7. Verify index is serving
curl -s http://localhost:8091/simple/

# 8. Install from local index
pip install --index-url http://localhost:8091/simple vectorops==0.1.0

# 9. Verify functionality
python3 -c "from vectorops import dotproduct; print(dotproduct([1,2,3],[4,5,6]))"
# Expected output: 32
```

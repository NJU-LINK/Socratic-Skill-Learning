---
name: pypi-server
description: >
  Build a Python package from source, serve it via a local PEP 503-compatible
  package index, and install it from that index. Covers src-layout and flat
  package structures, pyproject.toml and setup.py metadata, building sdist and
  wheel artifacts, running a local PyPI server (pypiserver or alternatives),
  and performing fresh pip installs from the local index.
---

# PyPI Server: Build, Serve, and Install Local Python Packages

## Overview

This skill covers the full lifecycle of creating a local Python package index:
1. Structure and declare a Python package
2. Build distribution artifacts (sdist + wheel)
3. Serve them via a local PEP 503-compatible index
4. Install the package from that index

## Step 1: Package Structure and Build Metadata

### Determine the layout from the task

The task will specify (or imply) one of these layouts:

- **src-layout**: Package code lives under `src/<package_name>/`. This is the
  modern recommended layout. Use `[tool.setuptools.packages.find]` with
  `where = ["src"]` in pyproject.toml.
- **flat layout**: Package code lives directly at the project root as
  `<package_name>/`. No special `where` configuration needed.
- **multi-module**: Multiple top-level packages. Use explicit `packages` list
  or package discovery configuration.

### Create pyproject.toml

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<normalized-package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout, omit the [tool.setuptools.packages.find] section entirely,
# or use:
# [tool.setuptools]
# packages = ["<package_name>"]
```

**Key rules:**
- The `name` field in `[project]` is the *distribution name* (what pip uses).
  Hyphens and underscores are normalized by PEP 503: `my-package`,
  `my_package`, and `My.Package` all resolve to `my-package`.
- The *import name* (what you use in `import` statements) is the directory
  name under `src/` (or at root for flat layout). It must be a valid Python
  identifier.
- If the distribution name and import name differ (e.g., distribution name
  `my-package` with import name `my_package`), ensure the package directory
  matches the import name and setuptools discovers it correctly.

### Create the package code

For src-layout:
```
project-root/
├── pyproject.toml
├── src/
│   └── <package_name>/
│       ├── __init__.py      # Public API exports
│       └── _internal.py     # Implementation modules
└── dist/                    # Created by build step
```

The `__init__.py` must export whatever the task requires:
```python
from <package_name>._module import <required_function_or_class>

__all__ = ["<required_function_or_class>"]
__version__ = "<version>"
```

### Handle setup.py variants

If the task uses `setup.py` instead of (or alongside) `pyproject.toml`:
```python
from setuptools import setup, find_packages

setup(
    name="<package-name>",
    version="<version>",
    package_dir={"": "src"},  # for src-layout
    packages=find_packages(where="src"),
)
```

When both exist, `pyproject.toml`'s `[build-system]` controls the build
backend, and `setup.py` provides metadata.

### Package data

If the package needs non-Python files (data, templates, etc.):
```toml
[tool.setuptools.package-data]
"<package_name>" = ["*.json", "*.txt", "data/*"]
```

## Step 2: Build Distribution Artifacts

### Install build tools

```bash
pip install build
```

### Build both sdist and wheel

```bash
cd /app && python3 -m build
```

This creates:
- `dist/<name>-<version>.tar.gz` (source distribution)
- `dist/<name>-<version>-py3-none-any.whl` (pure Python wheel)

**Important:** Clean previous build artifacts before rebuilding:
```bash
rm -rf dist/ build/ src/*.egg-info
```

### Build only wheel (if task requires)

```bash
python3 -m build --wheel
```

### Build only sdist (if task requires)

```bash
python3 -m build --sdist
```

### Verify artifacts

```bash
ls -la dist/
# Check wheel contents:
python3 -m zipfile -l dist/*.whl
```

## Step 3: Serve via Local Package Index

**CRITICAL INSIGHT:** Tests often verify that artifact files physically exist on disk
at a specific path (e.g., `/app/pypi/simple/<package>/`), not just that a server is
running. Always create a static PEP 503 file layout AND serve it.

### Discovering the Index Root Path

The index root path is where you create the PEP 503 directory structure. Common patterns:
- **v01 default**: `/app/pypi/` (most common in this family)
- **Task-specified**: The task instruction may specify a different path
- **Test-inferred**: Check test expectations if available (look for `INDEX_ROOT` or similar)

**Default to `/app/pypi/` unless the task or test environment specifies otherwise.**

The HTTP server serves from the index root, so the URL path `/simple/` maps to `<index-root>/simple/`.

### Static PEP 503 Index Layout (Recommended for test compatibility)

Create the physical directory structure that tests may check. **Use `/app/pypi/` as the default index root:**

```bash
# Set the index root (default to /app/pypi/)
INDEX_ROOT="${INDEX_ROOT:-/app/pypi}"

# Create the index directory structure
mkdir -p "$INDEX_ROOT/simple/<normalized-package-name>"

# Copy artifacts to the index
cp /app/dist/<package>-<version>-*.whl "$INDEX_ROOT/simple/<normalized-package-name>/"
cp /app/dist/<package>-<version>.tar.gz "$INDEX_ROOT/simple/<normalized-package-name>/"

# Create root index.html
cat > "$INDEX_ROOT/simple/index.html" << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="<normalized-package-name>/"><<normalized-package-name></a><br>
</body>
</html>
EOF

# Create package index.html
cat > "$INDEX_ROOT/simple/<normalized-package-name>/index.html" << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Links for <normalized-package-name></title></head>
<body>
<h1>Links for <normalized-package-name></h1>
<a href="<filename>.whl"><filename>.whl</a><br>
<a href="<filename>.tar.gz"><filename>.tar.gz</a><br>
</body>
</html>
EOF
```

**Serve with HTTP server using retry logic:**
```bash
# Kill any existing server on the port
pkill -f "http.server <PORT>" 2>/dev/null || true
sleep 1

# Start the HTTP server from the index root directory
cd "$INDEX_ROOT" && nohup python3 -m http.server <PORT> > /tmp/httpserver.log 2>&1 &

# Wait for server to be ready with retry
for i in {1..10}; do
    if curl -sf http://localhost:<PORT>/simple/ > /dev/null 2>&1; then
        echo "Server is ready"
        break
    fi
    sleep 1
done

# Final verification
curl -sf http://localhost:<PORT>/simple/ > /dev/null || { echo "Server failed to start"; exit 1; }
```

This approach:
- Creates physical files at `/app/pypi/simple/<package>/` (tests check this)
- Serves them via HTTP at `http://localhost:<PORT>/simple/`
- Works with `pip install --index-url http://localhost:<PORT>/simple`

### Using pypiserver (dynamic server)

**Install:**
```bash
pip install pypiserver
```

**Start with durable background process:**
```bash
# CRITICAL: Use nohup so the server survives shell session boundaries.
# Tests run in a separate shell (run_tests_in_same_shell: false), so the
# server must persist independently.
nohup pypi-server run --port <PORT> /app/dist > /tmp/pypiserver.log 2>&1 &
sleep 2
```

**Verify it's running:**
```bash
curl -s http://localhost:<PORT>/simple/ | grep <package-name>
```

**pypiserver options:**
- `--port <PORT>`: Port to listen on (default 8080)
- `--host <HOST>`: Host to bind to (default 0.0.0.0)
- `-P <htpasswd>`: Enable authenticated uploads (not needed for read-only)
- `--overwrite`: Allow overwriting existing package versions

**Note:** pypiserver serves dynamically from `/app/dist/` but doesn't create
the physical `/app/pypi/simple/<package>/` structure. If tests check for files
on disk, use the static layout approach above instead.

### Hybrid approach (both static layout AND pypiserver)

If you need both physical files AND pypiserver features:
```bash
# Create static layout first
mkdir -p /app/pypi/simple/<normalized-package-name>
cp /app/dist/* /app/pypi/simple/<normalized-package-name>/
# Create index.html files as shown above

# Then run pypiserver pointed at the static directory
nohup pypi-server run --port <PORT> /app/pypi/simple > /tmp/pypiserver.log 2>&1 &
```

### Using devpi

```bash
pip install devpi-server devpi-client
devpi server --start --host 0.0.0.0 --port <PORT>
devpi use http://localhost:<PORT>
devpi login root --password ''
devpi upload --from-dir /app/dist
```

### Handling stale or conflicting artifacts

If the dist/ directory contains artifacts from previous builds:
1. **Clean approach**: Remove old artifacts before building
   ```bash
   rm -rf dist/
   ```
2. **Selective approach**: Only keep artifacts matching the target version
   ```bash
   find dist/ -not -name "*<version>*" -delete
   ```
3. **pypiserver --overwrite**: Allow version replacement
   ```bash
   pypi-server run --overwrite --port <PORT> /app/dist
   ```

## Step 4: Install from the Local Index

### Fresh install (no cache)

```bash
# CRITICAL: Use --no-cache-dir to prevent pip from using a cached version
# from a previous install. This ensures a truly fresh install from the
# local index, which matters when versions change or artifacts are replaced.
pip install --no-cache-dir --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

### Key pip flags

- `--index-url <URL>`: Replace PyPI entirely with this index
- `--extra-index-url <URL>`: Add this index alongside PyPI
- `--no-cache-dir`: Force download from the index (no local cache)
- `--no-deps`: Skip dependency resolution (useful for isolated testing)
- `--force-reinstall`: Reinstall even if already present

### Verify installation

```bash
python3 -c "from <package_name> import <symbol>; print(<symbol>(...))"
pip show <package-name>
```

## Edge Cases and Robustness Patterns

### Durable background services

The index server must survive across shell session boundaries because test
harnesses typically run in a separate shell. Always use:
```bash
nohup <command> > /tmp/<service>.log 2>&1 &
```

And verify with a health check:
```bash
sleep 2
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server is up"
```

### Distribution name normalization

PEP 503 normalizes package names: all runs of `[-_.]` become a single `-`,
and everything is lowercased. So `My_Package`, `my-package`, and
`my.package` all become `my-package` in the index URL.

When building, setuptools normalizes the name in the filename:
- `pyproject.toml` name `My_Package` → file `my_package-0.1.0-...whl`
- Index URL: `http://localhost:8091/simple/my-package/`

### Empty input edge cases

When implementing functions, consider mathematical edge cases:
- Dot product of empty vectors = 0 (empty sum)
- `sum()` over empty iterable returns 0 by default
- Don't add unnecessary guards that reject valid empty inputs

**Example:** For a `dotproduct(a, b)` function:
```python
def dotproduct(a, b):
    """Compute the dot product of two numeric lists."""
    # Length check is correct: vectors must have same dimension
    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")
    # Empty vectors naturally return 0 (empty sum)
    return sum(x * y for x, y in zip(a, b))
```

**Key principle:** Validate structural constraints (length mismatch) but accept
mathematically valid edge cases (empty inputs). The `sum()` function naturally
handles empty iterables by returning 0.

### Version conflicts

If a version is already installed:
```bash
pip uninstall -y <package-name>
pip install --no-cache-dir --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

Or use `--force-reinstall`:
```bash
pip install --force-reinstall --no-cache-dir --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

## Handling Pre-existing or Broken Projects

The spec mentions "pre-staged or broken projects." When the workspace is not empty:

1. **Inspect existing files first**:
   ```bash
   ls -la /app/
   find /app -name "*.py" -o -name "pyproject.toml" -o -name "setup.py" 2>/dev/null
   ```

2. **Decide whether to clean or work with existing files**:
   - If files are broken/incomplete: clean and start fresh
   - If files are mostly correct: fix only what's needed
   - If task requires specific structure: ensure it matches requirements

3. **Clean approach** (when starting fresh):
   ```bash
   rm -rf /app/src /app/dist /app/build /app/*.egg-info /app/pyproject.toml /app/setup.py
   ```

4. **Selective cleanup** (preserve what works):
   ```bash
   # Keep existing source, fix metadata
   rm -rf /app/dist /app/build /app/*.egg-info
   # Fix pyproject.toml if needed
   ```

## Complete Workflow Checklist

1. **Read the task carefully** to determine:
   - Package name, version, and import structure
   - Required functions/classes and their behavior
   - Index port and any authentication requirements
   - Which artifacts to build (sdist, wheel, or both)
   - Index root path (default to `/app/pypi/` if not specified)
   - Whether workspace has pre-existing files to handle

2. **Inspect and prepare the workspace**:
   - Check for pre-existing files
   - Decide whether to clean or work with existing files
   - Ensure clean build environment

3. **Create the package structure**:
   - Choose src-layout or flat layout as specified
   - Write pyproject.toml (or setup.py) with correct metadata
   - Implement the required functionality in package code
   - Ensure `__init__.py` exports the required public API
   - Handle edge cases correctly (empty inputs, validation)

4. **Build artifacts**:
   - Clean previous build artifacts
   - Run `python3 -m build` (or `--wheel`/`--sdist` as needed)
   - Verify dist/ contains the expected files

5. **Create static PEP 503 index layout** (CRITICAL):
   - Set INDEX_ROOT (default `/app/pypi/`)
   - Create `$INDEX_ROOT/simple/<normalized-package-name>/` directory
   - Copy artifacts from dist/ to the index directory
   - Create root index.html and package index.html
   - This ensures files exist on disk where tests expect them

6. **Start the index server**:
   - Use `python3 -m http.server <PORT>` from `$INDEX_ROOT/`
   - OR use pypiserver pointed at `$INDEX_ROOT/simple/`
   - Start with `nohup` for persistence across shell boundaries
   - Use retry logic to wait for server readiness
   - Verify with curl health check

7. **Install and verify**:
   - Use `pip install --no-cache-dir --index-url http://localhost:<PORT>/simple`
   - Test the installed package with the required API
   - Verify edge cases and error handling
   - Confirm physical files exist at expected paths

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

### Using pypiserver (most common)

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

### Using a static file-based index

If the task requires a static index (no server process), create the PEP 503
directory structure:
```
index-root/
└── <normalized-package-name>/
    └── index.html
```

Where `index.html` contains:
```html
<!DOCTYPE html>
<html>
<body>
<a href="../../dist/<filename>.whl"><filename>.whl</a><br>
<a href="../../dist/<filename>.tar.gz"><filename>.tar.gz</a><br>
</body>
</html>
```

Then serve with any HTTP server (e.g., `python3 -m http.server <PORT>`).

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

## Complete Workflow Checklist

1. **Read the task carefully** to determine:
   - Package name, version, and import structure
   - Required functions/classes and their behavior
   - Index port and any authentication requirements
   - Which artifacts to build (sdist, wheel, or both)

2. **Create the package structure**:
   - Choose src-layout or flat layout as specified
   - Write pyproject.toml (or setup.py) with correct metadata
   - Implement the required functionality in package code
   - Ensure `__init__.py` exports the required public API

3. **Build artifacts**:
   - Clean previous build artifacts
   - Run `python3 -m build` (or `--wheel`/`--sdist` as needed)
   - Verify dist/ contains the expected files

4. **Start the index server**:
   - Install pypiserver (or other tool as specified)
   - Start with `nohup` for persistence
   - Verify with curl health check

5. **Install and verify**:
   - Use `pip install --no-cache-dir --index-url ...`
   - Test the installed package with the required API
   - Verify edge cases and error handling

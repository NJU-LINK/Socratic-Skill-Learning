---
name: pypi-server
description: >
  Build, publish, and verify Python packages via a local PyPI-compatible index.
  Covers src-layout and flat-layout packaging with setuptools, pyproject.toml
  build metadata, explicit package discovery, sdist/wheel building, local index
  service (pypiserver or alternatives), and end-to-end install verification.
---

# PyPI Server — Local Package Build, Publish, and Verification

## Overview

This skill handles the full chain: **source → build → serve → install → verify**
for Python packages using a local PEP 503-compatible package index. It applies to
any variant where a Python package must be built, hosted on a local index, and
installed by a client.

## Decision Framework

Before executing, determine these variant-specific parameters from the task:

| Parameter | How to Determine | Common Variants |
|-----------|-----------------|-----------------|
| Package name | Task specification | Any valid Python package name |
| Version | Task specification | Semver strings |
| Layout | Task says "src/" or implies flat | `src/` layout vs flat layout |
| Build metadata file | Task says `pyproject.toml` or `setup.py` | PEP 621 pyproject.toml vs legacy setup.py |
| Package discovery | Layout + task hints | Auto-discovery, explicit `where`, explicit `packages` list |
| Build artifacts | Task says "wheel", "sdist", or "both" | `--wheel`, `--sdist`, or both |
| Index tool | Task names a tool or port | pypiserver, devpi, static file server |
| Index port | Task specification | Any available port |
| API surface | Task specification | Functions, classes, re-exports |

## Step 1: Create Package Structure

### src/ Layout (Preferred for new projects)

```
project_root/
  pyproject.toml
  src/
    <package_name>/
      __init__.py
      [submodule.py ...]
```

**Why src/ layout:** Python cannot accidentally import the package from the
project root during development. Import only works after installation, catching
packaging errors early.

### Flat Layout

```
project_root/
  pyproject.toml
  <package_name>/
    __init__.py
```

**When to use:** Legacy projects, simple single-package projects, or when the
task explicitly requires it.

### Multi-module Package

```
project_root/
  pyproject.toml
  src/
    <package_name>/
      __init__.py       # Re-exports public API
      core.py           # Core logic
      utils.py          # Helper functions
```

The `__init__.py` controls the public import surface:
```python
# __init__.py — re-export public API
from .core import main_function
from .utils import helper_function
```

## Step 2: Write Build Metadata

### pyproject.toml with src/ layout (MOST COMMON FAILURE POINT)

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**CRITICAL:** The `[tool.setuptools.packages.find]` section with `where = ["src"]`
is essential for src/ layout. Without it, setuptools auto-discovery searches the
project root and will either:
- Find `src` itself as a package (wrong)
- Find unrelated directories like `tests/` or `scripts/`
- Miss the actual package entirely

### pyproject.toml with flat layout

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"

# Auto-discovery works for flat layout (packages at root)
# But explicit is still safer:
[tool.setuptools.packages.find]
where = ["."]
```

### Explicit package listing (when discovery fails)

```toml
[tool.setuptools]
packages = ["vectorops", "vectorops.submodule"]

[tool.setuptools.package-dir]
"" = "src"
```

### setup.py variant (legacy)

```python
from setuptools import setup, find_packages

setup(
    name="<package-name>",
    version="<version>",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)
```

### Including package data (non-Python files)

```toml
[tool.setuptools.package-data]
"<package-name>" = ["data/*.json", "templates/*.html"]
```

## Step 3: Build the Package

### Install the build frontend

```bash
pip install build
```

### Build both sdist and wheel

```bash
python3 -m build <project_root>
```

Output goes to `<project_root>/dist/`:
- `<name>-<version>.tar.gz` (sdist)
- `<name>-<version>-py3-none-any.whl` (pure Python wheel)
- `<name>-<version>-cp3XX-cp3XX-<platform>.whl` (platform-specific wheel)

### Build only wheel

```bash
python3 -m build --wheel <project_root>
```

### Build only sdist

```bash
python3 -m build --sdist <project_root>
```

### Verify wheel contents (MANDATORY after build)

```bash
python3 -m zipfile -l dist/<name>-<version>-py3-none-any.whl
```

**Expected contents for a correct src/ layout build:**
- `<package_name>/__init__.py` (and other modules)
- `<name>-<version>.dist-info/METADATA`
- `<name>-<version>.dist-info/WHEEL`
- `<name>-<version>.dist-info/RECORD`

**Failure indicators:**
- Wheel contains `src/` as a directory → package discovery misconfigured
- Wheel contains no `.py` files → package not found at all
- Wheel contains wrong package name → name mismatch in pyproject.toml
- Wheel contains `tests/` or other non-package dirs → over-broad discovery

## Step 4: Start Local Package Index

### pypiserver (Recommended — simple, PEP 503 compliant)

```bash
pip install pypiserver
pypi-server run -p <port> <dist_directory> &
```

**Key points:**
- Must stay running (background with `&` or process manager)
- Points at directory containing built artifacts
- Implements PEP 503 Simple Repository API
- No authentication by default (add `-P .htpasswd` for auth)
- Verify it's serving: `curl http://localhost:<port>/simple/`

### pypiserver with authentication

```bash
# Create password file
pip install passlib
htpasswd -sc .htpasswd <username>

# Start with auth
pypi-server run -p <port> -P .htpasswd <dist_directory> &

# Upload with auth
twine upload --repository-url http://localhost:<port>/ -u <username> -p <password> dist/*
```

### devpi (Full-featured, with caching)

```bash
pip install devpi-server devpi-client
devpi-server --start --host 0.0.0.0 --port <port>
devpi use http://localhost:<port>/root/pypi
devpi login root --password ''
devpi use root/local
twine upload --repository-url http://localhost:<port>/root/local/ dist/*
```

### Static file server (Read-only index)

For a static PEP 503 index, the directory structure must be:
```
<root>/
  simple/
    index.html                    # Lists all packages
    <normalized-name>/
      index.html                  # Lists versions with download links
  packages/
    <name>-<version>.tar.gz
    <name>-<version>-py3-none-any.whl
```

Serve with any HTTP server (nginx, `python3 -m http.server`).

### Distribution name normalization

PEP 503 normalizes names: `My-Package` → `my-package`, `my_package` → `my-package`.
pypiserver handles this automatically. For static indexes, normalize manually.

## Step 5: Install from Local Index

### Basic installation

```bash
pip install --index-url http://localhost:<port>/simple <package-name>==<version>
```

### Prevent fallback to public PyPI

```bash
pip install --index-url http://localhost:<port>/simple --no-deps <package-name>==<version>
```

`--no-deps` prevents pip from trying to resolve dependencies from public PyPI.
Only use when the package has no dependencies or all deps are already installed.

### Force reinstall (replace existing version)

```bash
pip install --index-url http://localhost:<port>/simple --force-reinstall <package-name>==<version>
```

### Install from local directory (alternative to index)

```bash
pip install --no-index --find-links <dist_directory> <package-name>==<version>
```

## Step 6: Verify Installation

### Import verification

```bash
python3 -c "from <package> import <function>; print(<function>(<test_args>))"
```

### Functional verification

Test the specific API the task requires:
1. Import path matches task specification exactly
2. Function signature matches (argument types, return type)
3. Edge cases work (empty inputs, single elements, boundary values)
4. Error handling matches requirements (if any)

### Installation source verification

```bash
pip show <package-name>
# Check that the location points to site-packages, not the project directory
```

## Failure Mode Checklist

| Stage | Common Failure | Diagnosis | Fix |
|-------|---------------|-----------|-----|
| Source layout | Package not under `src/` | `ls src/<pkg>/` shows nothing | Create correct directory structure |
| Build metadata | Auto-discovery finds wrong packages | Wheel contains wrong files | Add `[tool.setuptools.packages.find] where = ["src"]` |
| Build metadata | setup.py + pyproject.toml conflict | Build error or wrong metadata | Use one or the other consistently |
| Build | Empty or wrong wheel | `zipfile -l` shows no `.py` files | Fix package discovery configuration |
| Build | Version mismatch | Wrong filename in dist/ | Check `version` in pyproject.toml |
| Index server | Server not running | `curl` connection refused | Start server, check port |
| Index server | Wrong directory | `/simple/` shows no packages | Point server at `dist/` directory |
| Install | pip falls back to PyPI.org | Download URL shows pypi.org | Use `--index-url` (not `--extra-index-url`) |
| Install | Version not found | "No matching distribution" | Check version string, check server has artifact |
| Runtime | Import fails after install | `ModuleNotFoundError` | Check wheel contained the package; reinstall |
| Runtime | Wrong function behavior | Incorrect results | Check implementation logic |

## Troubleshooting Procedures

### "No matching distribution found"

1. Verify server is running: `curl http://localhost:<port>/simple/`
2. Check artifact exists: `ls <dist_dir>/`
3. Check name normalization: `curl http://localhost:<port>/simple/<normalized-name>/`
4. Try `--verbose` flag on pip for detailed resolution info

### Wheel contains wrong files

1. Check pyproject.toml package discovery section
2. For src/ layout: must have `[tool.setuptools.packages.find] where = ["src"]`
3. For flat layout: packages should be at project root
4. Clean build artifacts: `rm -rf build/ dist/ *.egg-info src/*.egg-info`
5. Rebuild and re-inspect

### Import works in project dir but not after install

This indicates flat layout masking a packaging error. The src/ layout prevents
this by making local imports impossible without installation.

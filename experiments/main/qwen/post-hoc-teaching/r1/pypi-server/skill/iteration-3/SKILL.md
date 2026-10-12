---
name: pypi-server
description: >
  Build a Python package from source, serve it via a local PyPI-compatible
  package index, and verify pip-installable behavior. Covers src-layout and
  flat-layout projects, pyproject.toml and setup.py metadata, pypiserver
  and devpi indexes, wheel/sdist publication, dependency resolution strategies,
  and end-to-end install verification.
---

# PyPI Server: Local Package Build, Index, and Install

## Overview

This skill creates a Python package from specification, builds distribution
artifacts, serves them from a local PEP 503-compatible index, and verifies the
package installs and behaves correctly. The four phases are:

1. **Package authoring** — create source tree and build metadata
2. **Build** — produce wheel and/or sdist artifacts
3. **Index service** — start a local package index serving the artifacts
4. **Install & verify** — pip install from the local index and test behavior

## Phase 1: Package Authoring

### 1.1 Determine the Layout

Read the task specification to determine:
- **Package name** (the import name and distribution name)
- **Version** string
- **Layout**: `src/` layout (code under `src/<pkg>/`) vs flat layout (code under `<pkg>/`)
- **Module structure**: single module, multi-module, subpackages
- **Public API**: what symbols must be importable from the top-level package

### 1.2 Handle Pre-existing Projects

If the workspace already contains files (pre-staged or broken projects):
- **Check before creating**: Use `ls` or `test -f` to detect existing files
- **Overwrite when needed**: If files exist but are incorrect, overwrite them with correct content
- **Don't assume empty workspace**: The task may provide a starting point (possibly broken)

```bash
# Example: check if pyproject.toml exists and is valid
if [ -f /app/pyproject.toml ]; then
  echo "pyproject.toml exists, checking content..."
  # Validate or overwrite as needed
fi
```

### 1.3 Create the Source Tree

**For src-layout** (most common; preferred when specified):
```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py      # re-exports public API
        └── _core.py         # implementation (optional helper)
```

**For flat layout**:
```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── ...
```

**Important**: The import name (Python module name) may differ from the distribution name (package name in pyproject.toml). For example:
- Distribution name: `vector-ops` (hyphens, used in pyproject.toml and pip)
- Import name: `vector_ops` (underscores, used in Python `import` statements)
- PEP 503 directory: `vector-ops` (normalized with hyphens)

### 1.4 Implement the Functionality

Implement all required functions/classes in the package modules. The `__init__.py`
must re-export the public API so that the specified import paths work. For example,
if the spec requires `from <pkg> import func`, then `__init__.py` must contain
`from <pkg>._core import func` or define `func` directly.

Key implementation principles:
- Match the exact function signatures specified (parameter names, types, defaults)
- Handle edge cases as specified (empty inputs, mismatched lengths, type validation)
- Use helper modules (`_core.py`, `_utils.py`) for implementation details to keep
  `__init__.py` clean
- Ensure numeric operations work with both `int` and `float` inputs

### 1.5 Write Build Metadata

**pyproject.toml** (modern, preferred):
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "<distribution-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout, omit the [tool.setuptools.packages.find] section
# or use where = ["."]
```

**setup.py** (legacy, when required):
```python
from setuptools import setup, find_packages

setup(
    name="<distribution-name>",
    version="<version>",
    package_dir={"": "src"},  # for src-layout
    packages=find_packages(where="src"),
)
```

**Critical metadata considerations:**
- The distribution name (in pyproject.toml) may differ from the import name;
  pip normalizes names (e.g., `my-package` → `my_package` for import)
- For src-layout, always specify `[tool.setuptools.packages.find] where = ["src"]`
- For multi-module packages, ensure all subpackages are discovered
- If the project has package data files, declare them explicitly

## Phase 2: Build Distribution Artifacts

### 2.1 Install Build Tools

```bash
pip install build
```

The `build` package is the standard PEP 517 build frontend. It creates an
isolated environment and invokes the configured backend.

### 2.2 Clean Before Build

Always remove stale build artifacts before building to avoid mixing old and new files:

```bash
# Remove old build artifacts
cd /app && rm -rf dist/ build/ src/*.egg-info
```

This prevents stale artifacts from being served alongside new ones.

### 2.3 Build Artifacts

```bash
cd /app && python -m build
```

This produces both a wheel (`.whl`) and source distribution (`.tar.gz`) in
`/app/dist/` by default.

**If only wheel is needed**: `python -m build --wheel`
**If only sdist is needed**: `python -m build --sdist`

### 2.4 Verify Build Output

```bash
ls /app/dist/
# Should show: <name>-<version>-py3-none-any.whl and <name>-<version>.tar.gz
```

**Troubleshooting build failures:**
- "standard file not found: should have one of README" — this is a warning, not an error; the build still succeeds
- "package not found" — check that `packages.find` `where` matches your layout
- "module not found" in wheel — verify `__init__.py` exists and files are in the right directory

### 2.5 Including Package Data (Non-Python Files)

If the package needs to include non-Python files (data files, configs, templates):

**In pyproject.toml**, add:
```toml
[tool.setuptools.package-data]
"<package_name>" = ["*.txt", "*.json", "*.yaml", "data/*"]
```

Or for all packages:
```toml
[tool.setuptools.package-data]
"*" = ["*.txt", "*.json", "*.yaml"]
```

**Verify data files are included:**
```bash
python -c "
import zipfile
with zipfile.ZipFile('/app/dist/<package>-<version>-py3-none-any.whl') as z:
    for name in sorted(z.namelist()):
        print(name)
"
```

Data files should appear in the wheel alongside Python modules.

## Phase 3: Local Package Index Service

### 3.1 Choose the Index Implementation

Based on the task specification:

| Requirement | Implementation |
|---|---|
| PEP 503 compatible, simple setup | `pypiserver` (recommended default) |
| Full-featured (auth, caching, proxy) | `devpi` |

**Note:** Do NOT use `python -m http.server` or other plain HTTP servers as
package indexes — they are not PEP 503 compliant and will fail with pip.
See Section 3.4 for details.

### 3.2 pypiserver Setup (Most Common)

**Install:**
```bash
pip install pypiserver
```

**Prepare the PEP 503 directory structure:**

Tests often verify BOTH HTTP serving AND filesystem existence. Create the standard
PEP 503 directory layout where artifacts are organized by normalized package name.

**Name normalization**: The PEP 503 directory name uses the **normalized distribution name**
(lowercase, hyphens replaced with hyphens, underscores replaced with hyphens):
```python
import re
# Distribution name from pyproject.toml: "vector-ops" or "vector_ops"
# PEP 503 normalized: "vector-ops"
normalized = re.sub(r'[-_.]+', '-', distribution_name).lower()
```

```bash
# Default location (adjust if task specifies a different INDEX_ROOT)
INDEX_ROOT=/app/pypi
# Use the PEP 503 normalized distribution name for the directory
PKG_DIR="$INDEX_ROOT/simple/<normalized-distribution-name>"
mkdir -p "$PKG_DIR"
cp /app/dist/* "$PKG_DIR/"
```

For example, for package `vectorops`:
```bash
mkdir -p /app/pypi/simple/vectorops
cp /app/dist/* /app/pypi/simple/vectorops/
```

For a package with distribution name `vector-ops`:
```bash
mkdir -p /app/pypi/simple/vector-ops
cp /app/dist/* /app/pypi/simple/vector-ops/
```

This creates:
```
/app/pypi/
└── simple/
    └── vectorops/
        ├── vectorops-0.1.0-py3-none-any.whl
        └── vectorops-0.1.0.tar.gz
```

**Start the server (with PID tracking):**
```bash
python -m pypiserver run --port <PORT> "$PKG_DIR" &>/tmp/pypiserver.log &
echo $! > /tmp/pypiserver.pid
```

For the vectorops example:
```bash
python -m pypiserver run --port 8091 /app/pypi/simple/vectorops &>/tmp/pypiserver.log &
echo $! > /tmp/pypiserver.pid
```

- The `run` subcommand starts the server
- `--port` sets the listening port (default 8080; use whatever the spec requires)
- The last argument is the directory containing `.whl` and `.tar.gz` files
- Run in background with `&`; always save `$!` to a PID file for later management
- `&>/tmp/pypiserver.log` captures both stdout and stderr for debugging

**Why PEP 503 directory structure?**
- Tests may check filesystem existence at `<INDEX_ROOT>/simple/<package>/`
- pypiserver serves from this directory, satisfying HTTP checks
- The same directory satisfies both filesystem and HTTP requirements
- If the task doesn't specify `INDEX_ROOT`, default to `/app/pypi`

**Verify the index is serving:**
```bash
curl -s http://localhost:<PORT>/simple/
# Should return HTML listing available packages
```

**Important notes:**
- `pypiserver` command may not be on PATH; use `python -m pypiserver` instead
- The server must remain running for pip install to work
- Use `--host 0.0.0.0` if access from outside localhost is needed
- For authenticated uploads, use `-P <password_file>` with htpasswd

### 3.3 Alternative: devpi (Full-Featured Index)

For tasks requiring authenticated uploads, caching from upstream PyPI, or
multi-project staging:
```bash
pip install devpi-server devpi-web
devpi-server --host 0.0.0.0 --port <PORT> --server-dir /app/devpi-data &
# Upload packages
devpi upload --from /app/dist --url http://localhost:<PORT>/root/pypi/
```

### 3.4 ⚠️ Do NOT Use `python -m http.server` as a Package Index

`python -m http.server` is **not** PEP 503 compliant and will silently fail
for pip installation. Specific problems:
- Directory listings lack the `#sha256=...` hash fragments pip expects
- URL encoding of package names may not match PEP 503 normalization rules
- pip may reject the index or fail to find packages with normalized names
  (e.g., `my-package` vs `my_package`)

**Always use pypiserver or devpi for any task requiring pip installation.**
A plain HTTP file server is only suitable for manual downloads or non-pip
clients.

### 3.5 Wait for Server Readiness

After starting the server, always verify it's accepting connections:
```bash
sleep 2
curl -s http://localhost:<PORT>/simple/ | grep -q "<package-name>" && echo "Index ready"
```

## Phase 4: Install and Verify

### 4.1 Install from Local Index

```bash
pip install --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

**Key flags:**
- `--index-url` replaces the default PyPI entirely (use when the local index is
  the only source)
- `--extra-index-url` adds the local index alongside PyPI (use when falling back
  to PyPI is acceptable)
- Always pin the exact version to ensure the local artifact is used
- Use `--no-deps` if dependency resolution from other sources is unwanted
- Use `--force-reinstall` to ensure a fresh install if a version was previously
  installed

### 4.2 Dependency Resolution — The `--index-url` Trap

**Critical:** `--index-url` and `--extra-index-url` are NOT interchangeable.
When you use `--index-url`, ALL dependency resolution goes through that single
index — including runtime dependencies and build-system requires.

**Failure scenario:**
- Package declares `dependencies = ["numpy"]` in pyproject.toml
- Test runs `pip install --index-url http://localhost:8091/simple mypackage==1.0`
- pip searches the local index for `numpy`, doesn't find it, and **fails**
- Even if numpy is already installed system-wide, pip may still try to
  re-resolve it and fail

**Decision tree for handling dependencies:**

| Situation | Solution |
|---|---|
| Package has zero dependencies (like v01) | `--index-url` works fine as-is |
| Test command is fixed as `--index-url` and package has deps | Pre-install deps system-wide, then use `--no-deps` alongside `--index-url` |
| Test command is fixed as `--index-url` and you control the package | Remove external dependencies from pyproject.toml if not required |
| You control the install command and deps exist | Use `--extra-index-url` (keeps PyPI as fallback for deps) |
| Package has build-system requires (e.g., Cython) | Build the wheel beforehand (avoids build-dep resolution at install time); use `--prefer-binary` |
| Local index must be sole source of truth | Host all dependency wheels in the same packages directory |

**Patterns:**
```bash
# Option A: --extra-index-url (local index + PyPI fallback)
pip install --extra-index-url http://localhost:<PORT>/simple mypackage==1.0

# Option B: --index-url with --no-deps (when deps are pre-installed)
pip install --index-url http://localhost:<PORT>/simple --no-deps mypackage==1.0

# Option C: --index-url with all deps hosted locally
# Copy dependency wheels into the same PEP 503 directory pypiserver serves from
cp /path/to/numpy-*.whl "$PKG_DIR/"
pip install --index-url http://localhost:<PORT>/simple mypackage==1.0

# Option D: Prefer binary to avoid build-dep resolution from index
pip install --index-url http://localhost:<PORT>/simple --prefer-binary mypackage==1.0
```

**Key rule:** If the task spec says `--index-url`, assume the local index must
be self-contained OR use `--no-deps`. If you have freedom to choose, prefer
`--extra-index-url` when the package has external dependencies.

### 4.3 Installation Troubleshooting

**If installation fails:**
- Check that the server is running: `curl http://localhost:<PORT>/simple/`
- Check that the distribution name matches (pip normalizes: `-` ↔ `_`)
- Check that the version in the filename matches the requested version
- Try `pip install -vvv` for verbose output to diagnose issues
- If it fails on a dependency not found, see Section 4.2 above

### 4.4 Verify Installation

```bash
# Check the package is installed
pip show <package-name>

# Test the required import paths
python -c "from <package> import <symbol>; print(<symbol>(<test_args>))"
```

### 4.5 Functional Verification

Test the installed package with representative inputs:
- Normal inputs that should succeed
- Edge cases specified in the requirements (empty lists, mismatched lengths, etc.)
- Both integer and float inputs if numeric operations are involved

## General Troubleshooting

### Distribution Name Normalization
PEP 503 normalizes package names: `My_Package`, `my-package`, and `my_package`
all refer to the same distribution. pip handles this automatically, but be aware
when manually checking URLs or filenames.

### Port Conflicts and Process Management

Minimal containers often lack `ps`, `pgrep`, `ss`, and `lsof`. Always manage
background processes using explicit PID tracking:

```bash
# Save PID immediately when backgrounding
python -m pypiserver run --port <PORT> /app/pypi/simple/<package> &>/tmp/pypiserver.log &
echo $! > /tmp/pypiserver.pid

# Check if process is alive (works without ps/pgrep)
kill -0 $(cat /tmp/pypiserver.pid) 2>/dev/null && echo "Server running" || echo "Server dead"

# Kill by saved PID
kill $(cat /tmp/pypiserver.pid) 2>/dev/null

# Find process by port using /proc (when ss/lsof unavailable)
PORT_HEX=$(printf '%04X' <PORT>)
for pid_dir in /proc/[0-9]*/; do
  pid_num=$(basename "$pid_dir")
  if grep -q ":${PORT_HEX}" /proc/$pid_num/net/tcp 2>/dev/null; then
    echo "Found process $pid_num on port <PORT>"
    kill $pid_num 2>/dev/null
  fi
done
```

**Key rule:** Always save `$!` to a file immediately after backgrounding any
server process. Use `kill -0 $PID` to check liveness. Never rely on `ps`,
`pgrep`, `ss`, or `lsof` — they are often absent in minimal containers.

### Stale Installs
If a previous version is installed, pip may refuse to reinstall:
```bash
pip uninstall -y <package-name>
pip install --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

### Build Isolation Issues
If `python -m build` fails due to missing build dependencies:
```bash
# The build tool creates an isolated venv; ensure the build backend is declared
# correctly in pyproject.toml [build-system] requires
```

## Checklist for Any Variant

1. ☐ Read spec: package name, version, layout, API, port, artifact types, **dependencies**, **INDEX_ROOT**
2. ☐ **Check for pre-existing files** — overwrite if broken or incorrect
3. ☐ Create directory structure matching the required layout
4. ☐ Implement all required functions/classes with correct signatures
5. ☐ Write `__init__.py` with correct re-exports for the required import paths
6. ☐ Write build metadata (pyproject.toml or setup.py) with correct package discovery
7. ☐ **Add package-data config if non-Python files are needed**
8. ☐ Install build tools (`pip install build`)
9. ☐ **Clean stale artifacts** (`rm -rf dist/ build/ src/*.egg-info`)
10. ☐ Build artifacts (`python -m build` or variant) — prefer wheel if deps exist
11. ☐ Verify dist/ contains expected files (and data files if applicable)
12. ☐ Install index server (`pip install pypiserver`)
13. ☐ **Create PEP 503 directory structure** at `<INDEX_ROOT>/simple/<normalized-dist-name>/` (default: `/app/pypi/simple/<package>/`)
14. ☐ Copy artifacts (and dependency wheels if needed) to that directory
15. ☐ Start index server pointing at the package directory; **save PID to file**
16. ☐ Verify index is serving the package (`curl /simple/`)
17. ☐ **Verify filesystem**: artifacts exist at `<INDEX_ROOT>/simple/<package>/<filename>`
18. ☐ Choose install strategy: `--index-url` vs `--extra-index-url` vs `--no-deps` (see §4.2)
19. ☐ Install package via pip from local index
20. ☐ Verify import paths work
21. ☐ Verify functional correctness with test inputs

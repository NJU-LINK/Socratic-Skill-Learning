---
name: pypi-server
description: >
  Build a Python package with correct layout and metadata, produce distribution
  artifacts (sdist and/or wheel), stand up a local PEP 503-compatible PyPI index
  (pypiserver), and make the package installable from that index. Covers src and
  flat layouts, pyproject.toml and setup.py build systems, arbitrary package
  names/versions/APIs, configurable index ports, and end-to-end verification.
---

# Local PyPI Package Build & Serve

## Overview

This skill creates a Python package, builds distribution artifacts, serves them
via a local PEP 503-compatible package index, and verifies end-to-end
installability. It generalises across package names, versions, layouts, build
backends, functionality requirements, index tools, and ports.

## Phase 0 — Environment Reconnaissance

Before writing any code, determine what already exists and what must change.

```bash
# 1. Inspect the workspace
ls -la /app/
find /app -maxdepth 4 -not -path '*/\.*' -not -path '*/__pycache__/*' | sort

# 2. Check available tooling
python3 --version
pip list 2>&1 | grep -iE 'setuptools|wheel|build|twine|pypiserver'
which pypi-server 2>/dev/null || echo "pypi-server not found"
```

**Decision rules from reconnaissance:**

| Observation | Action |
|---|---|
| `/app/src/<pkg>/` exists with code | Reuse the existing src-layout source tree |
| `/app/<pkg>/` exists (no `src/`) | Flat layout — adjust `packages.find` accordingly |
| `pyproject.toml` exists | Reuse or patch; verify `[build-system]`, `[project]`, and package discovery |
| `setup.py` exists (no pyproject.toml) | Legacy build — either keep setup.py or migrate to pyproject.toml |
| Neither exists | Create from scratch using the layout specified in the task |
| `build` package missing | `pip install build` |
| `pypiserver` / `pypi-server` missing | `pip install pypiserver` |
| `dist/` directory has artifacts | Verify they match the required package name + version; rebuild if stale |

## Phase 1 — Create / Repair the Package Source Tree

### 1A. Determine the target layout

Read the task specification carefully. Extract these variables:

| Variable | Example (v01) | How to find |
|---|---|---|
| `PKG_NAME` | `vectorops` | Task instruction, `pyproject.toml`, or directory name |
| `PKG_VERSION` | `0.1.0` | Task instruction or `[project] version` |
| `LAYOUT` | `src` | Presence of `src/` dir, or task instruction |
| `IMPORT_NAME` | `vectorops` | Usually matches `PKG_NAME`; check for explicit overrides |
| `FUNCTIONS` | `dotproduct` | Task instruction "must support `from X import Y`" |

### 1B. Src layout (most common for new projects)

```
/app/
  pyproject.toml
  src/
    <PKG_NAME>/
      __init__.py        # Public API surface
      <module>.py        # Implementation modules
```

The `__init__.py` is the **public API surface**. Every symbol the task requires
must be importable directly from the package:

```python
# src/<PKG_NAME>/__init__.py
"""<PKG_NAME> - <one-line description>."""

from .core import dotproduct   # example: re-export from implementation module

__all__ = ["dotproduct"]
```

### 1C. Flat layout

```
/app/
  pyproject.toml
  <PKG_NAME>/
    __init__.py
    <module>.py
```

For flat layout the `pyproject.toml` package discovery differs (see Phase 2).

### 1D. Implement the required functionality

Implement every function/class the task specifies. Follow these principles:

- **Match the exact signature** the task describes (parameter names, types, return type).
- **Handle obvious edge cases**: empty inputs, type mismatches, length mismatches —
  raise `ValueError` or `TypeError` as appropriate.
- **Keep helper code in private modules** (e.g., `core.py`, `_utils.py`) and
  re-export through `__init__.py`. This separates concerns and makes the public
  surface explicit.

Example implementation:

```python
# src/vectorops/core.py
def dotproduct(a, b):
    """Compute the dot product of two numeric sequences."""
    if len(a) != len(b):
        raise ValueError("Sequences must have equal length")
    return sum(x * y for x, y in zip(a, b))
```

## Phase 2 — Build Metadata (pyproject.toml)

### Standard pyproject.toml for src layout

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<PKG_NAME>"
version = "<PKG_VERSION>"
description = "<short description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

### Standard pyproject.toml for flat layout

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<PKG_NAME>"
version = "<PKG_VERSION>"
description = "<short description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["."]
```

### Critical rules

- **`name` must exactly match** what the task asks for. PyPI normalises names
  (lowercase, hyphens ↔ underscores), but the source-of-truth is the task text.
- **`version` must exactly match** the required version string.
- **`[tool.setuptools.packages.find]`** must point to the correct `where`:
  - `["src"]` for src layout
  - `["."]` for flat layout
- If the package name differs from the directory name, add an explicit mapping:
  ```toml
  [tool.setuptools.package-dir]
  "<IMPORT_NAME>" = "src/<DIRECTORY_NAME>"
  ```

### Fallback: setup.py (only if pyproject.toml is absent and task does not require it)

```python
from setuptools import setup, find_packages
setup(
    name="<PKG_NAME>",
    version="<PKG_VERSION>",
    packages=find_packages(where="src"),   # or find_packages() for flat
    package_dir={"": "src"},               # omit for flat layout
    python_requires=">=3.8",
)
```

## Phase 3 — Build Distribution Artifacts

### 3A. Ensure build tools are installed

```bash
pip install --quiet build wheel setuptools
```

### 3B. Clean stale artifacts

```bash
rm -rf /app/dist /app/build /app/src/*.egg-info /app/*.egg-info
```

**Why**: Old artifacts in `dist/` may have wrong versions or names. The local
index serves *everything* in the packages directory, so stale artifacts cause
confusion.

### 3C. Build

```bash
cd /app && python -m build
```

This produces both sdist (`.tar.gz`) and wheel (`.whl`) in `/app/dist/`.

If the task requests **only a wheel**:
```bash
python -m build --wheel
```

If the task requests **only an sdist**:
```bash
python -m build --sdist
```

### 3D. Verify artifacts

```bash
ls -la /app/dist/
# Expected: <pkg_name>-<version>.tar.gz and <pkg_name>-<version>-py3-none-any.whl
```

Check that the filename contains the exact version string required.

## Phase 4 — Local PyPI Index Server

### 4A. Install pypiserver

```bash
pip install --quiet pypiserver
```

The command-line entry point is `pypi-server` (not `pypiserver`).

### 4B. Determine port and index root

| Variable | Default | Source |
|---|---|---|
| `PORT` | `8091` | Task instruction |
| `INDEX_ROOT` | `/app/pypi` | Convention expected by test harness |
| `HOST` | `0.0.0.0` | Bind to all interfaces for accessibility |

**Critical convention**: The test harness typically defines `INDEX_ROOT = /app/pypi` and
asserts that built artifacts exist on the filesystem at
`/app/pypi/simple/<pkg_name>/<filename>`. The server must be started from the
`simple` directory, not directly from `dist`.

### 4C. Create the static PEP 503 index directory structure

```bash
mkdir -p /app/pypi/simple/<PKG_NAME>

# Symlink built artifacts from dist/ into the static index
for f in /app/dist/*; do
    ln -sf "$f" "/app/pypi/simple/<PKG_NAME>/$(basename $f)"
done
```

This creates:
```
/app/pypi/
  simple/
    <PKG_NAME>/
      <pkg>-<version>-py3-none-any.whl -> /app/dist/<pkg>-<version>-py3-none-any.whl
      <pkg>-<version>.tar.gz           -> /app/dist/<pkg>-<version>.tar.gz
```

**Why symlinks instead of copies**: Symlinks keep a single source of truth in
`dist/`, avoid wasting disk space, and ensure that if artifacts are rebuilt the
index automatically reflects the new files.

**Why serve from `simple/` and not `dist/`**: pypiserver's root index
(`/simple/`) maps subdirectories of its packages directory to package names.
By serving from `./pypi/simple/`, pypiserver discovers `<PKG_NAME>/` as a
package directory. Additionally, test harnesses commonly assert that files
exist at `INDEX_ROOT / "simple" / <pkg_name> / <filename>`, which only works
when the server's packages directory is rooted at `simple/`.

### 4D. Kill any existing server on the target port

```bash
# Kill existing pypi-server processes by PID
for pid_dir in /proc/[0-9]*/cmdline; do
    pid=$(echo "$pid_dir" | cut -d/ -f3)
    if grep -q "pypi-server" "$pid_dir" 2>/dev/null; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 1
```

### 4E. Start the server from the static index directory

```bash
cd /app
pypi-server run --host 0.0.0.0 --port <PORT> ./pypi/simple/ &
PYPID_PID=$!
echo "pypi-server started with PID $PYPID_PID"
sleep 2
```

**Important**: Serve from `./pypi/simple/`, NOT from `./dist/`. This ensures:
- The filesystem path `INDEX_ROOT / simple / <pkg> / <file>` resolves correctly
- pypiserver generates the correct PEP 503 HTML for the root and package indexes
- pip can install via `--index-url http://localhost:<PORT>/simple`

### 4F. Verify the server is responding

```bash
curl -s http://localhost:<PORT>/simple/
# Should list the package name in an HTML page with a link like "<pkg_name>/"

curl -s http://localhost:<PORT>/simple/<PKG_NAME>/
# Should list both .whl and .tar.gz with sha256 hashes
```

Verify filesystem assertions will pass:
```bash
python3 -c "
from pathlib import Path
root = Path('/app/pypi')
for f in Path('/app/dist').iterdir():
    p = root / 'simple' / '<PKG_NAME>' / f.name
    assert p.exists(), f'Missing: {p}'
    print(f'OK: {p}')
"
```

If the server is not responding:
1. Check if the port is already in use (another process)
2. Try a different port if the task allows it
3. Check if pypiserver installed correctly: `python -c "import pypiserver; print(pypiserver.__version__)"`

## Phase 5 — End-to-End Verification

This is the **self-verification** step. Run it before declaring the task complete.

### 5A. Uninstall any existing version

```bash
pip uninstall -y <PKG_NAME> 2>/dev/null
```

### 5B. Install from the local index

```bash
pip install --index-url http://localhost:<PORT>/simple <PKG_NAME>==<PKG_VERSION>
```

**Important flags:**
- `--index-url` (not `--extra-index-url`): ensures pip uses ONLY the local index
- `--trusted-host localhost`: may be needed on older pip versions, but modern
  pip (≥23) does not require it for `http://` URLs
- If pip falls back to PyPI despite `--index-url`, add `--no-deps` if the
  package has no dependencies, or investigate whether the local index is
  correctly serving the package

### 5C. Test the installed package

```python
python3 -c "
from <PKG_NAME> import <FUNCTION_NAME>
# Test basic functionality
result = <FUNCTION_NAME>(<test_args>)
print(f'Result: {result}')
assert result == <expected>, f'Expected <expected>, got {result}'
print('OK')
"
```

### 5D. Verify the server stays alive

The pypi-server must remain running after the task completes, because the test
harness may attempt installation **after** the agent finishes. Ensure:

- The server was started with `&` (background)
- The server process is still alive: `cat /proc/$PYPID_PID/cmdline 2>/dev/null`
- **Do not** kill the server at the end of the script

## Common Pitfalls & Debugging

### Package not found on local index

```bash
# Check what packages the server sees
curl -s http://localhost:<PORT>/simple/
curl -s http://localhost:<PORT>/simple/<PKG_NAME>/
```

If the package page is empty, the `dist/` directory may be wrong or empty.

### Import fails after installation

```bash
# Check what was installed
pip show <PKG_NAME>
# Check where it was installed
python3 -c "import <PKG_NAME>; print(<PKG_NAME>.__file__)"
```

Common causes:
- `__init__.py` missing from the package directory
- `[tool.setuptools.packages.find]` misconfigured (wrong `where`)
- Package name in pyproject.toml doesn't match import name

### Build fails

```bash
# Check build output carefully
python -m build 2>&1 | tail -20
```

Common causes:
- Missing `[build-system]` in pyproject.toml
- `setuptools` or `wheel` not installed
- Syntax error in source code

### Server won't start

Common causes:
- Port already in use
- `dist/` directory doesn't exist yet
- `pypi-server` binary not in PATH (try `python -m pypiserver`)

### Test expects files at `/app/pypi/simple/<pkg>/<filename>` but they don't exist

This is the **most common failure mode** when the index was started from `./dist/`
instead of `./pypi/simple/`. Symptoms:
- `pip install` and HTTP checks pass
- But `Path("/app/pypi/simple/<pkg>/<file>").exists()` returns `False`

Fix: Always create the static index structure and serve from `./pypi/simple/`.
```bash
mkdir -p /app/pypi/simple/<PKG_NAME>
for f in /app/dist/*; do
    ln -sf "$f" "/app/pypi/simple/<PKG_NAME>/$(basename $f)"
done
pypi-server run --host 0.0.0.0 --port <PORT> ./pypi/simple/ &
```

## Variant Handling Summary

| Dimension | Variants | Detection | Adaptation |
|---|---|---|---|
| **Layout** | src / flat / pre-existing | Directory inspection | Adjust `where` in packages.find |
| **Build system** | pyproject.toml / setup.py | File existence | Use appropriate config format |
| **Functionality** | Any Python API | Task instruction | Implement per spec, expose in `__init__.py` |
| **Index tool** | pypiserver (primary) | `which pypi-server` | Fall back to `python -m pypiserver` |
| **Index root** | `/app/pypi` (convention) | Test harness convention | Always create `/app/pypi/simple/<pkg>/` with symlinks |
| **Port** | Any port (default 8091) | Task instruction | Parameterise all commands |
| **Dist types** | sdist+wheel / wheel-only / sdist-only | Task instruction | Pass `--wheel`, `--sdist`, or nothing to `build` |
| **Version** | Any semver string | Task instruction | Use exact string in pyproject.toml and pip install |

## Quick Reference — Minimal Complete Sequence

```bash
# 0. Install tools
pip install --quiet build pypiserver

# 1. Create package (src layout example)
mkdir -p /app/src/<PKG_NAME>
# ... write __init__.py and implementation modules ...

# 2. Create pyproject.toml
cat > /app/pyproject.toml << 'PYEOF'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<PKG_NAME>"
version = "<PKG_VERSION>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
PYEOF

# 3. Build
cd /app && rm -rf dist build *.egg-info src/*.egg-info
python -m build

# 4. Set up static PEP 503 index and start server
mkdir -p /app/pypi/simple/<PKG_NAME>
for f in /app/dist/*; do
    ln -sf "$f" "/app/pypi/simple/<PKG_NAME>/$(basename $f)"
done
pypi-server run --host 0.0.0.0 --port <PORT> ./pypi/simple/ &
sleep 2

# 5. Verify
pip install --index-url http://localhost:<PORT>/simple <PKG_NAME>==<PKG_VERSION>
python3 -c "from <PKG_NAME> import <FUNC>; print(<FUNC>(<args>))"
```

Replace `<PKG_NAME>`, `<PKG_VERSION>`, `<PORT>`, `<FUNC>`, and `<args>` with
the values from the task specification.

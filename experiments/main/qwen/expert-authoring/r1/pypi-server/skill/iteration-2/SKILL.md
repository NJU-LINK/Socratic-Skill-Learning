---
name: pypi-server
description: >
  Create a Python package with correct layout and build metadata, build
  distribution artifacts (sdist and/or wheel), stand up a local PEP 503
  compatible package index with artifacts on disk in a simple/ directory,
  publish the artifacts to it, and verify that the package installs and
  functions correctly from the local index.
---

# PyPI Server: Local Package Build, Index, and Installation

## Overview

This skill covers the full lifecycle of a local Python package: authoring source
code, declaring build metadata, building distribution artifacts, running a local
PyPI-compatible index, publishing artifacts, and verifying end-to-end
installation and functionality.

## Phase 1 — Determine Package Parameters

Extract from the task instruction:

| Parameter | Default / Convention | How to find |
|-----------|---------------------|-------------|
| Package name | — | Explicitly stated or implied |
| Version | `0.1.0` | Explicitly stated or default |
| Layout | `src/` | "Use a src/ layout" or inspect existing tree |
| Build system | `pyproject.toml` | "Declare build metadata" or inspect existing files |
| Public API | — | "must support `from X import Y`" |
| Index port | `8091` | "on port NNNN" |
| Artifact types | sdist + wheel | "both a source distribution and a wheel" |
| INDEX_ROOT | `/app/pypi` | Test convention; the on-disk root of the index |

**Decision rule — layout:** If the task says "src/ layout", put code under
`<root>/src/<package_name>/`. If it says "flat layout", put code under
`<root>/<package_name>/`. If the layout is not specified but existing files are
present, match the existing structure.

## Phase 2 — Author Package Source

### 2.1 Create directory structure

For **src layout** (most common in modern tasks):

```
<root>/
  pyproject.toml
  src/
    <package_name>/
      __init__.py
      <module>.py       # optional, for larger packages
```

For **flat layout**:

```
<root>/
  pyproject.toml
  <package_name>/
    __init__.py
```

### 2.2 Implement functionality

- Implement all required functions/classes as specified in the task.
- Expose the public API through `__init__.py` so that the required import path
  works. If the task says `from <pkg> import <func>`, ensure `<func>` is
  importable from `<pkg>.__init__`.
- Add input validation and handle edge cases if specified.

**Self-check:** After writing code, verify the import works from the source tree:

```bash
cd <root>
PYTHONPATH=src python3 -c "from <pkg> import <func>; print(<func>(<test_args>))"
```

For flat layout, use `PYTHONPATH=.` instead.

### 2.3 Write build metadata

**Preferred: `pyproject.toml`** (use unless task specifies `setup.py`/`setup.cfg`):

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package_name>"
version = "<version>"
description = "<short description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]          # omit for flat layout
```

**If using `setup.py`:**

```python
from setuptools import setup, find_packages
setup(
    name="<package_name>",
    version="<version>",
    packages=find_packages(where="src"),   # or find_packages() for flat
    package_dir={"" : "src"},              # omit for flat
)
```

**Key rule:** `setuptools.packages.find` must discover the package. For src
layout, always set `where = ["src"]`. For flat layout, omit `where` or set it
to `["."]`.

## Phase 3 — Build Distribution Artifacts

### 3.1 Install build tool

```bash
pip install build
```

### 3.2 Build

```bash
cd <root>
python3 -m build
```

This produces artifacts in `<root>/dist/`:
- `<package_name>-<version>.tar.gz` (sdist)
- `<package_name>-<version>-py3-none-any.whl` (wheel, for pure-Python packages)

**Decision rule for artifact types:**
- Task says "both sdist and wheel" → `python3 -m build` (default builds both)
- Task says "wheel only" → `python3 -m build --wheel`
- Task says "sdist only" → `python3 -m build --sdist`

### 3.3 Verify artifacts exist

```bash
ls -la dist/
```

Expected: at least one `.whl` and/or `.tar.gz` file matching the package name
and version.

**Self-check — inspect wheel contents:**

```bash
python3 -m zipfile -l dist/<package_name>-<version>-*.whl
```

Verify the package modules are present and `__init__.py` is included.

## Phase 4 — Set Up Local Package Index

This is the critical phase. The index must satisfy **two constraints
simultaneously**:

1. **pip install works over HTTP** — pypiserver serves a PEP 503 simple index.
2. **Artifacts exist on disk** at the path the tests assert:
   `INDEX_ROOT/simple/<package_name>/<artifact_filename>`.

### 4.1 Install index server

```bash
pip install pypiserver
```

### 4.2 Create the on-disk index directory and copy artifacts

```bash
INDEX_ROOT="/app/pypi"
mkdir -p "${INDEX_ROOT}/simple/<package_name>"
cp <root>/dist/<package_name>-<version>-*.whl "${INDEX_ROOT}/simple/<package_name>/"
cp <root>/dist/<package_name>-<version>.tar.gz "${INDEX_ROOT}/simple/<package_name>/"
```

**Why:** Tests assert `(INDEX_ROOT / "simple" / "<pkg>" / "<artifact>").exists()`.
pypiserver discovers artifacts by scanning its root directory recursively, so
placing files under `simple/<pkg>/` and serving from `simple/` satisfies both
the HTTP protocol and the on-disk file check.

**Keep `/app/dist/` intact** — some tests also glob `DIST_DIR` for artifacts.

### 4.3 Start the index server

```bash
nohup pypi-server run -p <port> -P . -a . "${INDEX_ROOT}/simple" > /tmp/pypi-server.log 2>&1 &
sleep 2
```

Key flags:
- `-p <port>`: Listen on the required port
- `-P .`: Accept uploads from any host (use `.htpasswd` for auth if needed)
- `-a .`: Disable authentication for downloads
- Final argument: the **directory containing package subdirectories**

### 4.4 Verify the index is running

```bash
# Check the simple index page
curl -s http://localhost:<port>/simple/

# Check the package page lists both artifacts
curl -s http://localhost:<port>/simple/<package_name>/
```

Expected: HTML pages. The root lists the package name; the package page lists
links to the `.whl` and `.tar.gz` files.

**Troubleshooting:**
- If the page is empty, verify the dist directory path and that files were
  copied into `${INDEX_ROOT}/simple/<package_name>/`.
- If connection refused, check the port isn't already in use:
  `curl -sf http://localhost:<port>/simple/ > /dev/null && echo "running" || echo "not running"`

## Phase 5 — Install and Verify from Local Index

### 5.1 Install from local index

```bash
pip install --index-url http://localhost:<port>/simple <package_name>==<version>
```

**Important:** Use `--index-url` (replaces default PyPI) not `--extra-index-url`
(adds to default PyPI). The task typically requires the local index to be the
sole source.

If the task requires `--trusted-host`:

```bash
pip install --index-url http://localhost:<port>/simple --trusted-host localhost <package_name>==<version>
```

### 5.2 Verify installation

```bash
pip show <package_name>
```

Check that version and location are correct.

### 5.3 Verify functionality

```bash
python3 -c "from <package_name> import <func>; print(<func>(<test_args>))"
```

Run several test cases covering:
- Normal inputs (integers, floats, mixed)
- Edge cases specified in the task (empty lists, single elements, etc.)
- The exact import path specified in the task

## Phase 6 — End-to-End Self-Verification

Run this checklist before declaring completion. Use `curl` for checks because
`ps` and `ss` may not be available in minimal containers.

1. **Source layout matches requirement** — `find <root>/src -type f -name "*.py"`
2. **Build metadata is valid**:
   ```bash
   python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb')))"
   ```
3. **Distribution artifacts in /app/dist**:
   ```bash
   ls dist/*.whl dist/*.tar.gz
   ```
4. **Artifacts exist on disk at INDEX_ROOT**:
   ```bash
   ls "${INDEX_ROOT}/simple/<pkg>/"*.whl "${INDEX_ROOT}/simple/<pkg>/"*.tar.gz
   ```
5. **Index server responds**:
   ```bash
   curl -sf http://localhost:<port>/simple/ > /dev/null && echo "Index OK" || echo "Index FAILED"
   ```
6. **Package listed on index**:
   ```bash
   curl -s http://localhost:<port>/simple/<pkg>/
   ```
7. **Fresh install succeeds** — uninstall first, then reinstall:
   ```bash
   pip uninstall -y <package_name>
   pip install --index-url http://localhost:<port>/simple <package_name>==<version>
   ```
8. **Installed package imports correctly**:
   ```bash
   python3 -c "from <pkg> import <func>"
   ```
9. **Functionality is correct** — test with representative inputs
10. **Version matches** — `pip show <package_name> | grep Version`
11. **Index stays running** — verify with curl; use `nohup ... &` to persist

## Handling Variation

### Pre-existing or broken projects

If the workspace already has source files, inspect them first:

```bash
find /app -type f \( -name "*.py" -o -name "*.toml" -o -name "*.cfg" \)
```

Fix issues rather than starting from scratch. Common fixes:
- Missing `__init__.py` → create it
- Wrong `where` in pyproject.toml → correct the package discovery path
- Missing build-system table → add it
- Import not working from installed package → check package discovery and exports

### Multiple modules or sub-packages

If the task requires multiple modules or classes:
- Organize them within the package directory
- Export the public API in `__init__.py`:
  ```python
  from .module_a import func_a
  from .module_b import ClassB
  ```

### Authenticated index

If the task requires upload authentication:
- Create `.htpasswd` file with `htpasswd` or `pypiserver` utilities
- Start server with `-P <htpasswd_file>`
- Use `twine upload` with credentials to publish

### Version replacement

If the task requires replacing an existing version:
- Remove old artifacts from the dist directory **and** from
  `INDEX_ROOT/simple/<pkg>/` before building
- Ensure the version string is updated in metadata

### Different INDEX_ROOT paths

If tests or the task specify a different root (e.g. `/app/index`,
`/tmp/packages`), adjust the `INDEX_ROOT` variable in Phase 4 accordingly. The
critical invariant is:

```
<INDEX_ROOT>/simple/<package_name>/<artifact_filename>  must exist on disk
```

### Keeping the index alive

Always start the index as a background process and verify it responds before
the evaluation tests execute:

```bash
nohup pypi-server run -p <port> -P . -a . /app/pypi/simple > /tmp/pypi-server.log 2>&1 &
sleep 2
curl -sf http://localhost:<port>/simple/ > /dev/null && echo "Index OK" || echo "Index FAILED"
```

If the index must survive across multiple shell sessions, ensure it was started
with `nohup` (not just `&`), which protects it from SIGHUP when the parent
shell exits.

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Missing `__init__.py` | `ModuleNotFoundError` on import | Create `__init__.py` in package dir |
| Wrong `where` in pyproject.toml | Package not found during build | Set `where = ["src"]` for src layout |
| Serving from `/app/dist` instead of INDEX_ROOT | Tests pass for pip install but fail on-disk file assertions | Copy artifacts to `INDEX_ROOT/simple/<pkg>/` and serve from `INDEX_ROOT/simple` |
| Index not started in background | Server dies when shell exits | Use `nohup ... &` |
| `--extra-index-url` instead of `--index-url` | pip falls back to pypi.org | Use `--index-url` |
| Stale artifacts in dist/ | Wrong version installed | Clean dist/ and INDEX_ROOT before building |
| Port already in use | Server fails to start | `curl -sf http://localhost:<port>/simple/` to check; kill old process |
| Using `ps` or `ss` for verification | Command not found in minimal containers | Use `curl` to check index health |
| Package name normalization | `vector_ops` vs `vector-ops` | Use the exact name from the task; PEP 503 normalizes hyphens/underscores |
| Removing `/app/dist` after copying to index | Tests that glob DIST_DIR fail | Keep both locations populated |

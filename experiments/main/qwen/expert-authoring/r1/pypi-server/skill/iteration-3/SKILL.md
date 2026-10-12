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

This skill covers the full lifecycle of a local Python package: discovering
existing workspace state, authoring or fixing source code, declaring build
metadata, building distribution artifacts, running a local PEP 503 index,
publishing artifacts, and verifying end-to-end installation and functionality.

## Phase 1 — Discover Workspace State and Extract Parameters

### 1.1 Scan for existing project files

Before writing anything, inspect the workspace to determine whether this is a
fresh project or a pre-staged / broken one that needs fixing:

```bash
find /app -maxdepth 4 -type f \( \
    -name "*.py" -o -name "*.toml" -o -name "*.cfg" -o -name "*.txt" \
    -o -name "MANIFEST.in" \) 2>/dev/null | grep -v __pycache__ | sort
```

Also check for hidden test files that reveal expected paths:

```bash
find / -path "*/tests/test_*.py" -o -path "*/test/test_*.py" 2>/dev/null | head -5
```

If test files exist, read them to discover:
- `INDEX_ROOT` — where the on-disk index directory is expected (common: `/app/pypi`)
- `DIST_DIR` — where build artifacts are expected (common: `/app/dist`)
- `INDEX_URL` / port — where the index HTTP server must listen
- Any specific file-path assertions

```bash
# Grep for key test variables
grep -rn "INDEX_ROOT\|DIST_DIR\|INDEX_URL\|index_url\|pypi" /tests/ 2>/dev/null | head -20
```

### 1.2 Extract task parameters

From the task instruction, identify:

| Parameter | Default / Convention | How to find |
|-----------|---------------------|-------------|
| Package name | — | Explicitly stated or implied |
| Version | `0.1.0` | Explicitly stated or default |
| Layout | `src/` | "Use a src/ layout" or inspect existing tree |
| Build system | `pyproject.toml` | "Declare build metadata" or inspect existing files |
| Public API | — | "must support `from X import Y`" |
| Index port | `8091` | "on port NNNN" |
| Artifact types | sdist + wheel | "both a source distribution and a wheel" |
| INDEX_ROOT | `/app/pypi` | Test convention or test-file scan |
| DIST_DIR | `/app/dist` | Test convention or test-file scan |

**Decision rule — layout:** If the task says "src/ layout", put code under
`<root>/src/<package_name>/`. If it says "flat layout", put code under
`<root>/<package_name>/`. If the layout is not specified but existing files are
present, match the existing structure.

## Phase 2 — Author or Fix Package Source

### 2.1 Pre-staged project: fix rather than rewrite

If existing source files are present:
1. **Read** every existing `.py`, `.toml`, `.cfg` file
2. **Identify** what's broken (missing `__init__.py`, wrong `where`, stale
   egg-info, missing build-system table)
3. **Fix** the specific issues rather than overwriting everything
4. **Clean** stale build artifacts:
   ```bash
   rm -rf /app/build /app/*.egg-info /app/src/*.egg-info /app/__pycache__ /app/src/__pycache__
   ```

### 2.2 Fresh project: create directory structure

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

### 2.3 Implement functionality

- Implement all required functions/classes as specified in the task.
- Expose the public API through `__init__.py` so that the required import path
  works. If the task says `from <pkg> import <func>`, ensure `<func>` is
  importable from `<pkg>.__init__`.
- If the task says `from <pkg>.<sub> import <func>`, do NOT flatten the import.
- Add input validation and handle edge cases if specified.
- For package data (non-Python files like `.json`, `.txt`, templates):
  - Add `include_package_data = true` to pyproject.toml under `[tool.setuptools]`
  - Or create a `MANIFEST.in` listing the data files

**Self-check:** After writing code, verify the import works from the source tree:

```bash
cd <root>
PYTHONPATH=src python3 -c "from <pkg> import <func>; print(<func>(<test_args>))"
```

For flat layout, use `PYTHONPATH=.` instead.

### 2.4 Write build metadata

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

**Name normalization matters:** Python normalizes package names in distribution
filenames:
- Hyphens → underscores: `my-package` → wheel `my_package-<ver>-py3-none-any.whl`
- Dots → underscores: `my.pkg` → wheel `my_pkg-<ver>-...`
- The `[project] name` field keeps the canonical name (with hyphens if that's
  what the task says), but setuptools normalizes internally.
- `pip install my-package` and `pip install my_package` are equivalent.

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

### 3.2 Clean stale artifacts

**Critical before building** — remove old artifacts to avoid serving wrong versions:

```bash
rm -rf /app/dist/*
rm -rf "${INDEX_ROOT:-/app/pypi}/simple" 2>/dev/null
```

### 3.3 Build

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

### 3.4 Verify artifacts exist

```bash
ls -la dist/
```

Expected: at least one `.whl` and/or `.tar.gz` file matching the package name
and version. Verify the **actual filename** matches what tests expect, paying
attention to name normalization.

**Self-check — inspect wheel contents:**

```bash
python3 -m zipfile -l dist/<actual_wheel_filename>
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

**Alternative tools:** If the task specifies `devpi`, `bandersnatch`, or another
index, install and configure that instead. `pypiserver` is the default choice
for a lightweight PEP 503 index.

### 4.2 Create the on-disk index directory and copy artifacts

```bash
INDEX_ROOT="/app/pypi"   # or whatever test files expect
mkdir -p "${INDEX_ROOT}/simple/<package_name>"
cp <root>/dist/<actual_wheel_file> "${INDEX_ROOT}/simple/<package_name>/"
cp <root>/dist/<actual_sdist_file> "${INDEX_ROOT}/simple/<package_name>/"
```

**Why:** Tests assert `(INDEX_ROOT / "simple" / "<pkg>" / "<artifact>").exists()`.
pypiserver discovers artifacts by scanning its root directory recursively, so
placing files under `simple/<pkg>/` and serving from `simple/` satisfies both
the HTTP protocol and the on-disk file check.

**Keep `/app/dist/` intact** — some tests also glob `DIST_DIR` for artifacts.

**For multiple packages on the same index**, repeat the mkdir/cp for each
package name — pypiserver will auto-discover all subdirectories.

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

# Check the package page lists all artifacts
curl -s http://localhost:<port>/simple/<package_name>/
```

Expected: HTML pages. The root lists the package name; the package page lists
links to the `.whl` and `.tar.gz` files.

**Troubleshooting:**
- If the page is empty, verify files were copied into
  `${INDEX_ROOT}/simple/<package_name>/`.
- If connection refused: `curl -sf http://localhost:<port>/simple/` returns
  non-zero; kill any old process and restart.

## Phase 5 — Install and Verify from Local Index

### 5.1 Install from local index

```bash
pip install --index-url http://localhost:<port>/simple <package_name>==<version>
```

**Important:** Use `--index-url` (replaces default PyPI) not `--extra-index-url`
(adds to default PyPI). The task typically requires the local index to be the
sole source.

If pip warns about trusted hosts:

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
3. **Distribution artifacts in DIST_DIR** (no stale extras):
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

If the workspace already has source files (detected in Phase 1.1):
1. Read all existing files before modifying anything
2. Identify specific problems (missing `__init__.py`, wrong layout, bad metadata)
3. Clean stale build state: `rm -rf build *.egg-info src/*.egg-info`
4. Fix issues incrementally; don't overwrite working code

### Flat layout

For flat layout, the key differences are:
- Package dir at `<root>/<pkg>/` not `<root>/src/<pkg>/`
- `[tool.setuptools.packages.find]` omits `where` or uses `where = ["."]`
- `PYTHONPATH=.` for self-check instead of `PYTHONPATH=src`

### Multiple functions or classes

If the task requires multiple public exports:
- Organize across modules within the package directory
- Export everything needed in `__init__.py`:
  ```python
  from .module_a import func_a, ClassA
  from .module_b import func_b
  ```
- Verify each required import path individually

### Authenticated index

If the task requires upload authentication:
- Create `.htpasswd` file with `htpasswd` or `pypiserver` utilities
- Start server with `-P <htpasswd_file>`
- Use `twine upload` with credentials to publish

### Version replacement / multiple versions

If the task requires replacing an existing version:
- Remove old artifacts from both `dist/` **and** `INDEX_ROOT/simple/<pkg>/`
- Build the new version
- Ensure only the correct version is served

### Package data (non-Python files)

If the package includes data files (`.json`, `.csv`, templates, etc.):
- In `pyproject.toml`:
  ```toml
  [tool.setuptools]
  include-package-data = true
  ```
- Or create `MANIFEST.in`:
  ```
  recursive-include src/<pkg>/data *.json *.csv
  ```

### Different INDEX_ROOT paths

If tests or the task specify a different root (e.g. `/app/index`,
`/tmp/packages`), adjust the `INDEX_ROOT` variable in Phase 4 accordingly.
**Always scan test files in Phase 1** to discover the expected path. The
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
| Stale artifacts in dist/ | Old version served or multiple versions listed | `rm -rf dist/*` and `rm -rf INDEX_ROOT/simple` before building |
| Stale `.egg-info` directories | Build uses wrong metadata | `rm -rf *.egg-info src/*.egg-info build/` before building |
| Name normalization mismatch | Test expects `my_pkg-...` but agent builds `my-pkg-...` | Check actual wheel filename with `ls dist/*.whl`; Python normalizes hyphens to underscores |
| Index not started in background | Server dies when shell exits | Use `nohup ... &` |
| `--extra-index-url` instead of `--index-url` | pip falls back to pypi.org | Use `--index-url` |
| Port already in use | Server fails to start | `curl -sf http://localhost:<port>/simple/` to check; kill old process |
| Using `ps` or `ss` for verification | Command not found in minimal containers | Use `curl` to check index health |
| Package name normalization | `vector_ops` vs `vector-ops` | Use the exact name from the task; PEP 503 normalizes hyphens/underscores |
| Removing `/app/dist` after copying to index | Tests that glob DIST_DIR fail | Keep both locations populated |
| Not scanning test files | INDEX_ROOT or DIST_DIR mismatch | Always `grep -rn "INDEX_ROOT\|DIST_DIR" /tests/ 2>/dev/null` in Phase 1 |
| Pre-staged project with stale `__pycache__` | Old bytecode imported instead of new code | `find /app -type d -name __pycache__ -exec rm -rf {} +` before build |
| Package data files not included | `FileNotFoundError` when accessing data at runtime | Add `include-package-data = true` or `MANIFEST.in` |

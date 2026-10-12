---
name: pypi-server
description: >
  Create a Python package with correct layout and build metadata, build
  distribution artifacts (sdist and/or wheel), stand up a local PEP 503
  compatible package index, publish the artifacts to it, and verify that the
  package installs and functions correctly from the local index.
---

# PyPI Server: Local Package Build, Index, and Installation

## Overview

This skill covers the full lifecycle of a local Python package: authoring source
code, declaring build metadata, building distribution artifacts, running a local
PyPI-compatible index, publishing artifacts, and verifying end-to-end
installation and functionality.

## Phase 1 — Determine Package Parameters

Extract from the task instruction:

| Parameter | Example (v01) | How to find |
|-----------|---------------|-------------|
| Package name | `vectorops` | Explicitly stated or implied |
| Version | `0.1.0` | Explicitly stated or default |
| Layout | `src/` | "Use a src/ layout" or inspect existing tree |
| Build system | `pyproject.toml` | "Declare build metadata" or inspect existing files |
| Public API | `dotproduct(a, b)` | "must support `from X import Y`" |
| Index port | `8091` | "on port NNNN" |
| Artifact types | sdist + wheel | "both a source distribution and a wheel" |

**Decision rule:** If the task says "src/ layout", put code under
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

### 4.1 Install index server

```bash
pip install pypiserver
```

**Alternative tools:** If the task specifies `devpi`, `bandersnatch`, or another
index, install and configure that instead. `pypiserver` is the default choice
for a lightweight PEP 503 index.

### 4.2 Start the index server

```bash
pypi-server run -p <port> -P . -a . <root>/dist &
```

Key flags:
- `-p <port>`: Listen on the required port
- `-P .`: Allow uploads from any host (use `.htpasswd` file path for auth if needed)
- `-a .`: Disable authentication for downloads
- Final argument: directory containing distribution artifacts

**Run in background** using `&` or `nohup ... &` so the process persists.

### 4.3 Verify the index is running

```bash
# Check port is listening
ss -tlnp | grep <port>

# Check the simple index page
curl -s http://localhost:<port>/simple/ | head -20
```

Expected: HTML page listing the package name as a link.

### 4.4 Check package is listed

```bash
curl -s http://localhost:<port>/simple/<package_name>/
```

Expected: HTML page with links to the `.whl` and/or `.tar.gz` files.

**Troubleshooting:**
- If the page is empty, verify the dist directory path is correct.
- If connection refused, check the port isn't already in use: `ss -tlnp`.
- pypiserver discovers packages by scanning the directory; ensure files have
  standard naming (`<name>-<version>...`).

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

Run this checklist before declaring completion:

1. **Source layout matches requirement** — `find <root>/src -type f` or
   `find <root>/<pkg> -type f`
2. **Build metadata is valid** — `python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb')))"`
3. **Distribution artifacts exist** — `ls dist/*.whl dist/*.tar.gz`
4. **Index server is running** — `curl -s http://localhost:<port>/simple/`
5. **Package listed on index** — `curl -s http://localhost:<port>/simple/<pkg>/`
6. **Fresh install succeeds** — uninstall first, then reinstall:
   ```bash
   pip uninstall -y <package_name>
   pip install --index-url http://localhost:<port>/simple <package_name>==<version>
   ```
7. **Installed package imports correctly** — `python3 -c "from <pkg> import <func>"`
8. **Functionality is correct** — test with representative inputs
9. **Version matches** — `pip show <package_name> | grep Version`
10. **Index stays running** — it must remain active for the duration of testing;
    use `nohup` or `&` and verify with `ps aux | grep pypi-server`

## Handling Variation

### Pre-existing or broken projects

If the workspace already has source files, inspect them first:

```bash
find /app -type f -name "*.py" -o -name "*.toml" -o -name "*.cfg"
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
- Remove old artifacts from the dist directory before building
- Or use `--no-isolation` and ensure the version string is updated in metadata

### Keeping the index alive

Always start the index as a background process and verify it's still running
before the evaluation tests execute:

```bash
nohup pypi-server run -p <port> -P . -a . /app/dist > /tmp/pypi-server.log 2>&1 &
sleep 2
curl -sf http://localhost:<port>/simple/ > /dev/null && echo "Index OK" || echo "Index FAILED"
```

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Missing `__init__.py` | `ModuleNotFoundError` on import | Create `__init__.py` in package dir |
| Wrong `where` in pyproject.toml | Package not found during build | Set `where = ["src"]` for src layout |
| Index not started in background | Server dies when shell exits | Use `nohup ... &` |
| `--extra-index-url` instead of `--index-url` | pip falls back to pypi.org | Use `--index-url` |
| Stale artifacts in dist/ | Wrong version installed | Clean dist/ before building |
| Port already in use | Server fails to start | Check with `ss -tlnp`, kill old process |
| Package name normalization | `vector_ops` vs `vector-ops` | Use the exact name from the task; PEP 503 normalizes hyphens/underscores |

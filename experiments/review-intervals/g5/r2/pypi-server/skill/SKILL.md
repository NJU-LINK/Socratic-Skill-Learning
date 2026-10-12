---
name: pypi-server
description: >
  Build a Python package from source (handling src-layout, flat layout,
  pyproject.toml or setup.py metadata, explicit or auto-discovered packages),
  produce distribution artifacts (sdist, wheel, or both), and serve them via a
  local PEP 503-compatible package index (pypiserver, static directory index,
  or devpi) so that clients can install the exact built version with pip.
---

# PyPI Server — Local Package Build & Serve Skill

## Overview

This skill covers the full pipeline: **source project → build artifacts → local
index → pip-installable package**. Every step has variation points that depend
on the concrete task; the procedures below are decision trees, not fixed
recipes.

---

## Phase 1: Inspect & Prepare the Project

### 1.0 Determine the project root

The task instructions specify where the project lives. Set a variable:

```bash
PROJECT_DIR=<path-from-task-instructions>  # e.g., /app, /workspace, /home/user/project
cd $PROJECT_DIR
```

All subsequent paths are relative to `$PROJECT_DIR` unless absolute paths are given.

### 1.1 Determine the layout type

Examine the workspace to understand what exists and what's expected:

```bash
# Check for existing project structure
find $PROJECT_DIR -maxdepth 3 -name "*.py" -o -name "*.toml" -o -name "setup.py" -o -name "setup.cfg" | sort
```

**Decision tree:**

| Signal | Layout | Action |
|--------|--------|--------|
| `src/<pkg>/` directory exists or is required | **src-layout** | Set `where = ["src"]` in package discovery |
| `<pkg>/` at project root | **flat layout** | Default discovery works; no `where` needed |
| Only `setup.py` exists | Legacy metadata | May need `python setup.py sdist bdist_wheel` or migrate to pyproject.toml |
| `pyproject.toml` exists | Modern metadata | Use `python -m build` |
| Nothing exists | Greenfield | Create structure from scratch per task spec |

### 1.2 Build metadata configuration

#### For pyproject.toml (modern, preferred):

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
# ... other metadata as required

# CRITICAL for src-layout — without this, setuptools won't find packages in src/
[tool.setuptools.packages.find]
where = ["src"]
```

**Key invariants:**
- `name` must match the import name (after PEP 503 normalization: hyphens → underscores)
- `version` must be an exact string or dynamic reference
- For src-layout, `[tool.setuptools.packages.find]` with `where = ["src"]` is **mandatory** — auto-discovery looks in the project root by default

#### For setup.py (legacy):

```python
from setuptools import setup, find_packages

setup(
    name="<package-name>",
    version="<version>",
    package_dir={"": "src"},  # for src-layout
    packages=find_packages(where="src"),
)
```

### 1.3 Source code structure

**Public API surface**: The task specifies what must be importable. Create the
right `__init__.py` to expose the required symbols:

```python
# src/<pkg>/__init__.py
from <pkg>._core import <required_function>
__all__ = ["<required_function>"]
```

**Decision points:**
- If the task says `from <pkg> import <func>`, it must be in `__init__.py` (directly or via re-export)
- If logic spans multiple modules, organize them under the package directory
- Use `_` prefix for internal modules (convention, not enforced)
- Package data (non-Python files) requires explicit configuration:
  ```toml
  [tool.setuptools.package-data]
  "<pkg>" = ["data/*.json", "templates/*"]
  ```

---

## Phase 2: Build Distribution Artifacts

### 2.1 Install build tools

```bash
pip install build
# If using pypiserver:
pip install pypiserver
```

### 2.2 Clean previous artifacts

**Critical**: Always clean `dist/` before building to avoid stale artifacts
causing version conflicts or serving wrong files.

```bash
rm -rf $PROJECT_DIR/dist $PROJECT_DIR/build $PROJECT_DIR/src/*.egg-info
```

### 2.3 Build

```bash
cd $PROJECT_DIR && python3 -m build
```

This produces both sdist (`.tar.gz`) and wheel (`.whl`) in `$PROJECT_DIR/dist/`.

**Variations:**
- Wheel only: `python3 -m build --wheel`
- Sdist only: `python3 -m build --sdist`
- Legacy setup.py: `python3 setup.py sdist bdist_wheel`

### 2.4 Verify artifacts

```bash
ls $PROJECT_DIR/dist/
# Should show: <name>-<version>.tar.gz and <name>-<version>-py3-none-any.whl
```

**Name normalization**: Distribution names are normalized per PEP 503:
- Hyphens, underscores, and periods all become hyphens in the simple index
- Wheel filenames use underscores: `my_package-0.1.0-py3-none-any.whl`
- The simple index URL uses the normalized (lowercased, hyphenated) name

---

## Phase 2.5: Stage Artifacts into Index Directory

**Always stage artifacts** — you cannot know if tests will check filesystem layout, so do this by default.

### INDEX_ROOT selection:

The INDEX_ROOT path is **not specified in task instructions**. Use `$PROJECT_DIR/pypi` as a conventional default. If tests fail with filesystem path errors, you may need to adjust this location.

```bash
# Conventional default
INDEX_ROOT=$PROJECT_DIR/pypi

# Create PEP 503 directory structure
mkdir -p $INDEX_ROOT/simple/<normalized-package-name>

# Copy built artifacts from dist/ to the index directory
cp $PROJECT_DIR/dist/<package-name>-<version>-*.whl $INDEX_ROOT/simple/<normalized-package-name>/
cp $PROJECT_DIR/dist/<package-name>-<version>.tar.gz $INDEX_ROOT/simple/<normalized-package-name>/

# Verify staging
ls -la $INDEX_ROOT/simple/<normalized-package-name>/
```

**Why this matters:**
- pypiserver scans recursively, so serving from `$INDEX_ROOT/` finds artifacts in `simple/<pkg>/`
- HTTP endpoint: `http://localhost:<port>/simple/<package>/` serves the package index
- Filesystem check: `$INDEX_ROOT/simple/<package>/<artifact>` exists on disk
- Both HTTP and filesystem tests pass

**Important**: Create the directory structure **before** copying files. Parallel execution of mkdir and cp can cause race conditions.

---

## Phase 3: Start Local Package Index

### 3.1 Choose the index mechanism

| Requirement | Tool | Command |
|-------------|------|---------|
| Simple file-serving, no auth | pypiserver | `pypi-server run -p <port> <dist_dir>` |
| Static HTML index | manual | Generate PEP 503 HTML files |
| Full-featured with auth | devpi | `devpi-server --host 0.0.0.0 --port <port>` |
| Provided tool | per spec | Follow task instructions |

### 3.2 pypiserver (most common)

```bash
# Modern syntax (pypiserver >= 2.0):
# Serve from INDEX_ROOT (which contains simple/<package>/ structure)
# Redirect output to log file to keep shell clean
pypi-server run -p <port> $INDEX_ROOT/ > /tmp/pypi-server.log 2>&1 &

# Legacy syntax (still works but deprecated):
pypi-server -p <port> $INDEX_ROOT/ > /tmp/pypi-server.log 2>&1 &

# Alternative: If no staging was done, serve directly from dist/
# (Not recommended — filesystem tests may fail)
pypi-server run -p <port> $PROJECT_DIR/dist/ > /tmp/pypi-server.log 2>&1 &
```

**Key details:**
- The directory argument is scanned recursively for `.whl` and `.tar.gz` files
- The `/simple/` endpoint serves PEP 503-compatible index pages
- The `/packages/` endpoint serves the actual files
- Run in background with `&` so the shell remains usable
- Redirect output to a log file (e.g., `/tmp/pypi-server.log`) to keep shell clean
- Wait 1-2 seconds after starting before attempting to use it
- **Always point pypiserver at `$INDEX_ROOT/`** (not `dist/`) when you've staged artifacts
- If serving from `dist/` without staging, filesystem tests will likely fail

### 3.3 Verify the index is running

```bash
sleep 2
curl -s http://localhost:<port>/simple/
# Should show HTML with links to hosted packages
```

### 3.4 Static index alternative

If pypiserver is unavailable, create a PEP 503 directory structure manually:

```bash
mkdir -p $PROJECT_DIR/index/simple/<normalized-name>/
# Copy dist files to a served location
# Create index HTML:
cat > $PROJECT_DIR/index/simple/index.html << 'EOF'
<!DOCTYPE html>
<html><body>
<a href="<normalized-name>/"><normalized-name></a>
</body></html>
EOF

cat > $PROJECT_DIR/index/simple/<normalized-name>/index.html << 'EOF'
<!DOCTYPE html>
<html><body>
<a href="../../packages/<wheel-file>"><wheel-file></a><br>
<a href="../../packages/<sdist-file>"><sdist-file></a>
</body></html>
EOF
```

Then serve with any HTTP server: `python3 -m http.server <port> --directory $PROJECT_DIR/index`

---

## Phase 4: Install & Verify

### 4.1 Install from local index

```bash
pip install --no-cache-dir --index-url http://localhost:<port>/simple <package-name>==<version>
```

**Critical flags:**
- `--no-cache-dir`: Prevents pip from using a cached version from a previous
  attempt. Without this, pip might "succeed" using a stale cache even if the
  index is broken.
- `--index-url`: Replaces the default PyPI entirely. Use `--extra-index-url` if
  you need both local and public packages.

### 4.2 Verify installation

```bash
python3 -c "from <pkg> import <func>; print(<func>(<test_args>))"
```

### 4.3 Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No matching distribution found" | Index not running, wrong port, or artifacts not in served directory | Check `curl localhost:<port>/simple/`; verify dist/ contents |
| Import error after install | Package not found by setuptools during build | Check `[tool.setuptools.packages.find]` `where` setting; verify `__init__.py` exists |
| Wrong version installed | Stale cache or stale artifacts | `--no-cache-dir`; clean `dist/` before rebuild |
| "Could not find a version" | Package name mismatch (normalization) | Use normalized name (lowercase, hyphens) in pip install |
| Build fails with "no pyproject.toml" | Missing build config | Create pyproject.toml with `[build-system]` |
| sdist missing files | MANIFEST.in needed or package-data not configured | Add `[tool.setuptools.package-data]` or MANIFEST.in |
| pip refuses `http://` index URL | Some pip versions/configs enforce HTTPS by default | Add `--trusted-host localhost` to the pip install command |

---

## Diagnostic Checklist

When something goes wrong, work through this sequence:

1. **Can the index list the package?**
   ```bash
   curl http://localhost:<port>/simple/<package-name>/
   ```
   If empty → artifacts aren't in the served directory, or name normalization is wrong.

2. **Do artifacts exist on the filesystem in the expected location?**
   ```bash
   ls $INDEX_ROOT/simple/<package-name>/
   ```
   If empty or missing → staging phase was skipped or used wrong path.

3. **Does the wheel contain the right files?**
   ```bash
   python3 -m zipfile -l $PROJECT_DIR/dist/<wheel-file>
   ```
   If missing modules → package discovery misconfigured.

4. **Does the import work from the source tree?**
   ```bash
   cd $PROJECT_DIR && PYTHONPATH=src python3 -c "from <pkg> import <func>"
   ```
   If this fails → source code or `__init__.py` is wrong.

5. **Is the server process alive?**
   ```bash
   ps aux | grep pypi-server
   ```
   If dead → check logs, restart with output visible.

---

## Quick Reference: Common Case

For the typical scenario (src-layout, pyproject.toml, pypiserver):

```bash
# 1. Create project structure
PROJECT_DIR=/app  # or from task instructions
mkdir -p $PROJECT_DIR/src/<package-name>

# 2. Create pyproject.toml
cat > $PROJECT_DIR/pyproject.toml << 'EOF'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"

[tool.setuptools.packages.find]
where = ["src"]
EOF

# 3. Create source files
cat > $PROJECT_DIR/src/<package-name>/__init__.py << 'EOF'
from <package-name>._core import <function>
__all__ = ["<function>"]
EOF

cat > $PROJECT_DIR/src/<package-name>/_core.py << 'EOF'
def <function>(...):
    # implementation
    pass
EOF

# 4. Install tools and build
pip install build pypiserver -q
cd $PROJECT_DIR && python3 -m build

# 5. Stage artifacts
INDEX_ROOT=$PROJECT_DIR/pypi
mkdir -p $INDEX_ROOT/simple/<package-name>
cp $PROJECT_DIR/dist/<package-name>-<version>-*.whl $INDEX_ROOT/simple/<package-name>/
cp $PROJECT_DIR/dist/<package-name>-<version>.tar.gz $INDEX_ROOT/simple/<package-name>/

# 6. Start server
pypi-server run -p <port> $INDEX_ROOT/ > /tmp/pypi-server.log 2>&1 &
sleep 2

# 7. Install and verify
pip install --no-cache-dir --index-url http://localhost:<port>/simple <package-name>==<version>
python3 -c "from <package-name> import <function>; print(<function>(...))"
```

---

## Spec Axis Summary

| Axis | v01 Grounding | Expected Variation |
|------|---------------|-------------------|
| **package_layout_and_build_metadata** | src-layout, pyproject.toml, setuptools | Flat layout, setup.py, multi-module, package data, explicit package lists |
| **package_functionality_requirements** | `dotproduct(a, b)` over numeric lists | Multiple functions/classes, validation logic, helper modules, specific signatures |
| **package_index_service_configuration** | pypiserver on port 8091, artifacts staged at `/app/pypi/simple/vectorops/` | Static index, devpi, different ports, authenticated uploads, provided tools, different index root paths |
| **publication_and_installation_flow** | Both sdist+wheel, single version, staging to PEP 503 layout | Wheel-only, sdist-only, version replacement, stale artifact cleanup, normalized names, flat vs staged directory structure |

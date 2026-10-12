---
name: pypi-server
description: >
  Build a Python package from source, publish it to a local PEP 503-compatible
  package index, and verify installation. Handles src-layout and flat-layout
  projects, setuptools pyproject.toml or setup.py metadata, pypiserver or
  alternative index tools, and arbitrary package functionality requirements.
---

# Local PyPI Package Build & Serve Skill

## Overview

This skill covers the end-to-end workflow of:
1. Creating a Python package with correct build metadata
2. Building distributable artifacts (sdist + wheel)
3. Serving them via a local PEP 503-compatible package index
4. Installing and verifying the package from that index

## Parameters (vary per task instance)

| Parameter | Description | v01 default |
|-----------|-------------|-------------|
| `package_name` | Distribution name (PyPI-normalized) | `vectorops` |
| `version` | Package version string | `0.1.0` |
| `layout` | `src` or `flat` | `src` |
| `import_surface` | What must be importable from top-level | `from vectorops import dotproduct` |
| `functionality` | What the code must do | dot product of two numeric lists |
| `index_tool` | Which local index server to use | `pypiserver` |
| `index_port` | Port for the index service | `8091` |
| `artifact_dir` | Where built artifacts live | `/app/dist` |
| `build_artifacts` | `sdist+wheel`, `wheel-only`, `sdist-only` | `sdist+wheel` |

## Step-by-step Procedure

### Step 1: Create the Source Tree

**For src-layout** (most common, required by v01):
```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py      ← MUST re-export the public API
        └── <modules>.py     ← Implementation modules
```

**For flat-layout**:
```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── <modules>.py
```

**Critical**: The `__init__.py` must explicitly import and re-export all public symbols. If the task says `from <pkg> import <func>`, then `__init__.py` must contain `from .<module> import <func>` or define `<func>` directly.

### Step 2: Write Build Metadata (pyproject.toml)

**For src-layout with setuptools**:
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package_name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**For flat-layout with setuptools**:
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package_name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"
```
(No `where` needed; setuptools finds packages in the project root by default.)

**For setup.py-based projects** (legacy):
```python
from setuptools import setup, find_packages

setup(
    name="<package_name>",
    version="<version>",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
```

### Step 3: Implement the Required Functionality

Write the actual Python code that satisfies the task's behavioral requirements. Key principles:
- Put implementation in submodules (e.g., `_core.py`) for clean separation
- Re-export public API from `__init__.py`
- Handle edge cases (validation, type checking) as specified
- Ensure the callable signature matches exactly what tests expect

### Step 4: Build Distribution Artifacts

```bash
# Install the build tool (not always pre-installed)
pip install build

# Build both sdist and wheel (default behavior)
python -m build /app
```

This creates in `/app/dist/`:
- `<name>-<version>.tar.gz` (source distribution)
- `<name>-<version>-py3-none-any.whl` (pure-Python wheel)

**Variants**:
- Wheel-only: `python -m build --wheel`
- Sdist-only: `python -m build --sdist`
- If `build` is unavailable, use `python -m setuptools.build_meta` directly or `python setup.py sdist bdist_wheel`

### Step 5: Start the Local Package Index

**Using pypiserver** (simplest PEP 503 server):
```bash
pip install pypiserver
pypi-server run -p <port> <artifact_dir> &
```

**Verification**:
```bash
curl -s http://localhost:<port>/simple/
# Should show an HTML page listing your package name
```

**Alternative index tools**:
- `devpi`: More full-featured, supports caching/mirroring
- Static HTML index: Generate PEP 503-compliant directory structure manually
- Custom Flask/FastAPI app implementing `/simple/<name>/` endpoint

**Important**: Point the server at the **directory** containing artifacts (e.g., `/app/dist`), not individual files.

### Step 6: Install and Verify

```bash
pip install --no-cache-dir --index-url http://localhost:<port>/simple <package_name>==<version>
```

**Critical flags**:
- `--no-cache-dir`: Prevents pip from using cached downloads from previous failed attempts
- `--index-url`: Replaces PyPI entirely (no fallback). If the package isn't on your local index, installation fails — which is correct verification behavior.

**Functional verification**:
```bash
python -c "from <package_name> import <func>; print(<func>(<test_args>))"
```

## Common Failure Modes and Fixes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `ModuleNotFoundError: No module named '<pkg>'` | Missing `__init__.py` or wrong package discovery config | Check `where` in pyproject.toml matches layout |
| `pip install` fails with "No matching distribution" | Server not running, wrong port, or wrong artifact directory | `curl localhost:<port>/simple/` to verify |
| Only wheel OR sdist built | Used `--wheel` or `--sdist` flag alone | Use `python -m build` with no flags for both |
| Stale version installed | pip cache from previous attempt | Always use `--no-cache-dir` |
| Function not importable from top-level | Defined in submodule but not re-exported in `__init__.py` | Add `from .<module> import <func>` in `__init__.py` |
| Build fails with "no pyproject.toml" | Missing or malformed build config | Ensure `[build-system]` table exists |
| `pypi-server` command not found | Package not installed | `pip install pypiserver` |

## Distribution Name Normalization

PEP 503 normalizes distribution names: lowercase, runs of `[-_.]` become a single hyphen. So `Vector_Ops`, `vector-ops`, and `vectorops` all normalize to `vectorops`. The local index matches on normalized names.

## Background Process Management

When starting the index server in the background:
```bash
pypi-server run -p <port> <dir> &
sleep 2  # Give it time to bind
# Verify it's listening
curl -s http://localhost:<port>/simple/ > /dev/null && echo "Server running" || echo "Server not ready"
```

If the port is already in use:
```bash
lsof -i :<port>  # Find the process
kill <pid>        # Kill it if stale
# Then restart
```

## Adaptation Checklist for New Task Instances

When facing a new instance of this family:
1. [ ] Read the task to determine: package name, version, layout, required imports, functionality, index tool, port
2. [ ] Create source tree matching the specified layout
3. [ ] Write `__init__.py` that re-exports exactly what the task requires
4. [ ] Write build metadata matching the layout (src vs flat) and build system
5. [ ] Implement the required functionality with correct signatures
6. [ ] Build the required artifact types
7. [ ] Start the specified index tool on the specified port
8. [ ] Verify the index lists the package
9. [ ] Install with `--no-cache-dir --index-url`
10. [ ] Run functional verification matching the task's requirements

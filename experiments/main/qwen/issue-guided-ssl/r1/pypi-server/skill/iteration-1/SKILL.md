---
name: pypi-server
description: >
  Build a Python package from source (src-layout or flat), publish it to a
  local PEP 503-compatible package index (pypiserver or equivalent), and
  install it via pip from that index. Covers project scaffolding, build
  metadata, package index lifecycle, artifact management, and end-to-end
  verification.
---

# PyPI Server: Build, Serve, and Install Python Packages Locally

This skill covers the full pipeline from source code to locally-served
installable package. It handles the four key axes of variation:

1. **Package layout and build metadata** — src-layout, flat layout, multi-module,
   setup.py vs pyproject.toml, package discovery configuration
2. **Package functionality** — correct exports, callable signatures, validation
3. **Package index service** — pypiserver or alternatives, port configuration,
   authentication, lifecycle management
4. **Publication and installation flow** — build artifacts, artifact management,
   clean installation, verification

## Prerequisites

Install required tooling:

```bash
pip install build pypiserver
```

- `build` — PEP 517 build frontend (works with any backend: setuptools, flit, hatchling, poetry)
- `pypiserver` — lightweight PEP 503 Simple Repository API server

## Procedure

### Phase 1: Project Structure and Build Metadata

**Determine the layout.** Inspect the working directory for existing structure:

```bash
# Check for existing project files
ls -la /app/pyproject.toml /app/setup.py /app/setup.cfg 2>/dev/null
ls -la /app/src/ 2>/dev/null
find /app -name "*.py" -maxdepth 3 2>/dev/null
```

**If creating from scratch (src-layout):**

```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py
        └── (modules as needed)
```

**pyproject.toml template (setuptools backend, src-layout):**

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package_name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**CRITICAL for src-layout:** The `[tool.setuptools.packages.find]` section with
`where = ["src"]` is mandatory. Without it, setuptools will not discover packages
inside `src/` and the built wheel will contain no modules. This is the single most
common failure mode.

**If the project uses flat layout** (package directory at root level):

```toml
[tool.setuptools.packages.find]
where = ["."]
```

Or omit the `where` key entirely (defaults to `["."]`).

**If the project uses setup.py instead of pyproject.toml:**
A minimal `pyproject.toml` is still needed for PEP 517 compliance:

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"
```

**If the project already has pyproject.toml:** Verify it has correct package
discovery configuration. Common issues:
- Missing `[tool.setuptools.packages.find]` section
- Wrong `where` path for the layout
- Missing `__init__.py` files in package directories

### Phase 2: Package Code and Exports

The `__init__.py` must expose the required public API. Two patterns:

**Direct definition in `__init__.py`:**
```python
def dotproduct(a, b):
    return sum(x * y for x, y in zip(a, b))
```

**Import from submodule:**
```python
from .core import dotproduct
__all__ = ["dotproduct"]
```

**Verify imports work before building:**
```bash
cd /app && PYTHONPATH=src python3 -c "from <package_name> import <function>; print('OK')"
```

### Phase 3: Build Artifacts

**IMPORTANT: `python -m build` does NOT clean `dist/`.** It appends new artifacts
alongside any existing ones. If you build version 0.1.0 then 0.2.0, `dist/` will
contain artifacts for both versions. Always clean `dist/` before building to avoid
stale artifacts:

```bash
rm -rf /app/dist    # clean stale artifacts first
cd /app && python -m build
```

Use the PEP 517 build frontend (works with any backend):

```bash
cd /app && python -m build
```

This produces both sdist and wheel in `/app/dist/`:
- `<name>-<version>.tar.gz` (source distribution)
- `<name>-<version>-py3-none-any.whl` (wheel)

**If only one format is needed:**
```bash
python -m build --wheel    # wheel only
python -m build --sdist    # sdist only
```

**Verify the wheel contains the expected modules:**
```bash
python -m zipfile -l /app/dist/*.whl | grep "\.py "
```

An empty wheel (no `.py` files) indicates a package discovery problem — go back
to Phase 1 and check the `packages.find` configuration.

### Phase 4: Package Index Service

**Prepare the packages directory (clean stale artifacts first):**
```bash
mkdir -p /app/packages
# Remove old artifacts to prevent stale versions from being served
rm -f /app/packages/*.whl /app/packages/*.tar.gz /app/packages/*.egg
cp /app/dist/* /app/packages/
```

Without the cleanup step, stale artifacts from previous builds accumulate in the
packages directory. pypiserver will serve all of them, and pip may resolve to an
unexpected version — especially when rebuilding the same version number with
different code.

**Stop any existing server on the target port (port-targeted, not blanket):**
```bash
# Kill only the process bound to our specific port
lsof -ti :<PORT> | xargs kill 2>/dev/null || true
sleep 1
```

**Avoid blanket `pkill -f "pypi-server"`** — it kills ALL pypiserver processes on
the system, including ones serving other projects on different ports. Use
port-targeted killing (`lsof -ti :<PORT>`) or track PIDs in a file
(`/tmp/pypiserver-<PORT>.pid`) to only affect the intended instance.

**Start pypiserver:**
```bash
nohup pypi-server run -p <PORT> /app/packages/ > /tmp/pypiserver.log 2>&1 &
sleep 2
```

**Verify the server is running and serving packages:**
```bash
curl -s http://localhost:<PORT>/simple/
# Should show HTML with links to available packages
```

**Common port conflicts:** If port is in use:
```bash
lsof -i :<PORT> 2>/dev/null || ss -tlnp | grep <PORT>
```

**For authenticated uploads (family variation):**
```bash
# Generate password file
pip install passlib
htpasswd -sc /app/.htpasswd <username>
# Start with auth
pypi-server run -p <PORT> -P /app/.htpasswd -a update /app/packages/ &
```

**Alternative index tools:**
- `devpi` — full-featured PyPI proxy/cache
- Static file server — serve a PEP 503 directory structure via nginx/httpd
- Any PEP 503-compatible server

### Phase 5: Install and Verify

**Install from the local index:**
```bash
# Force reinstall to avoid cached versions
pip install --force-reinstall --index-url http://localhost:<PORT>/simple <package_name>==<version>
```

**Key pip flags:**
- `--index-url` — replaces PyPI entirely (use this for local-only)
- `--extra-index-url` — adds local index alongside PyPI
- `--no-deps` — skip dependency resolution (useful for isolated testing)
- `--force-reinstall` — reinstall even if already present
- `--no-cache-dir` — bypass pip cache to ensure fresh download

**Verify the installation:**
```bash
python3 -c "from <package_name> import <function>; print(<function>(<test_args>))"
```

**Verify it came from the local index (not PyPI):**
```bash
pip show <package_name> | grep -i "location\|version"
pip install -v --index-url http://localhost:<PORT>/simple <package_name>==<version> 2>&1 | grep "Downloading"
```

### Phase 6: Troubleshooting

**Empty wheel / no modules in wheel:**
- Check `[tool.setuptools.packages.find]` with correct `where`
- Ensure `__init__.py` exists in every package directory
- Run `python -m zipfile -l dist/*.whl | grep '.py '` to inspect contents

**Import error after install:**
- Verify the package name matches the import name (PEP 503 normalization)
- Check that `__init__.py` exports the expected symbols
- Ensure no namespace conflicts with other installed packages

**pip cannot find package on local index:**
- Verify server is running: `curl http://localhost:<PORT>/simple/`
- Check package name normalization (hyphens ↔ underscores)
- Ensure artifacts are in the directory pypiserver is serving
- Check version specifier matches exactly

**Port already in use:**
- Kill only the process on that port: `lsof -ti :<PORT> | xargs kill`
- Or use a saved PID file: `kill $(cat /tmp/pypiserver-<PORT>.pid)`
- Never use blanket `pkill -f "pypi-server"` — it kills all instances system-wide
- Choose a different port if needed

**Stale artifacts causing wrong version:**
- Clean `dist/` before building: `rm -rf dist/` (build does NOT clean it)
- Clean packages directory before copying: `rm -f packages/*.whl packages/*.tar.gz`
- Use `--force-reinstall` and `--no-cache-dir` with pip

## Parameterized Execution Script

See `scripts/build_serve_install.sh` for a parameterized end-to-end script.

## Family Variation Handling

| Axis | Seed (v01) | Variation Examples |
|------|-----------|-------------------|
| Layout | src-layout, pyproject.toml | flat layout, setup.py, multi-module, package data |
| Functionality | single dotproduct function | multiple functions/classes, validation, cross-module logic |
| Index | pypiserver on port 8091 | devpi, static index, different port, authenticated uploads |
| Publication | both sdist+wheel, clean install | wheel-only, version replacement, stale artifact handling |

The skill handles all these variations through detection, parameterization, and
the troubleshooting patterns above.

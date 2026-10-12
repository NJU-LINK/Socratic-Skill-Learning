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

**Determine the project state.** First, check if a project already exists:

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

#### Diagnostic Flow for Pre-existing or Broken Projects

When a project already exists but may be broken, follow this systematic diagnostic:

**Step 1: Validate pyproject.toml**
```bash
# Check if pyproject.toml exists and has required sections
python3 -c "
import tomllib
with open('/app/pyproject.toml', 'rb') as f:
    config = tomllib.load(f)
assert 'build-system' in config, 'Missing [build-system]'
assert 'project' in config, 'Missing [project]'
print('pyproject.toml structure OK')
print(f'  Package name: {config[\"project\"][\"name\"]}')
print(f'  Version: {config[\"project\"][\"version\"]}')
"
```

**Step 2: Verify package directory structure**
```bash
# Determine layout and check for package directories
if [ -d "/app/src" ]; then
    echo "Detected src-layout"
    # Check if package exists in src/
    ls -la /app/src/<package_name>/ 2>/dev/null || echo "ERROR: Package directory missing in src/"
    # Check for __init__.py
    test -f /app/src/<package_name>/__init__.py || echo "ERROR: Missing __init__.py"
else
    echo "Detected flat layout"
    ls -la /app/<package_name>/ 2>/dev/null || echo "ERROR: Package directory missing"
    test -f /app/<package_name>/__init__.py || echo "ERROR: Missing __init__.py"
fi
```

**Step 3: Verify package discovery configuration**
```bash
# Check if packages.find is configured correctly
python3 -c "
import tomllib
with open('/app/pyproject.toml', 'rb') as f:
    config = tomllib.load(f)
find_config = config.get('tool', {}).get('setuptools', {}).get('packages', {}).get('find', {})
if not find_config:
    print('WARNING: No [tool.setuptools.packages.find] section')
    print('  For src-layout, add: where = [\"src\"]')
    print('  For flat layout, add: where = [\".\"] or omit')
else:
    where = find_config.get('where', ['.'])
    print(f'Package discovery: where = {where}')
"
```

**Step 4: Verify import surface matches file layout**
```bash
# Test if the required imports work before building
cd /app
if [ -d "src" ]; then
    PYTHONPATH=src python3 -c "from <package_name> import <required_function>; print('Import OK')"
else
    python3 -c "from <package_name> import <required_function>; print('Import OK')"
fi
```

**Common failures and fixes:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| Empty wheel (no .py files) | Missing `packages.find` or wrong `where` | Add `[tool.setuptools.packages.find]` with correct `where` |
| `ModuleNotFoundError` after install | Missing `__init__.py` | Create `__init__.py` in package directory |
| `ImportError: cannot import name` | Function not exported in `__init__.py` | Add function to `__init__.py` or import from submodule |
| Build succeeds but package empty | Package name mismatch | Ensure directory name matches `project.name` (with hyphens→underscores) |
| `packages.find` finds wrong packages | Multiple packages in tree | Use explicit `packages = [...]` instead of auto-discovery |

#### Package Data and Multi-module Packages

**Including non-Python files (data, templates, etc.):**
```toml
[tool.setuptools.package-data]
"<package_name>" = ["data/*.json", "templates/*.html", "*.txt"]
```

Or use `include-package-data = true` with a `MANIFEST.in`:
```toml
[tool.setuptools]
include-package-data = true
```

**Multi-module packages (multiple top-level packages):**
```toml
[tool.setuptools.packages.find]
where = ["src"]
include = ["my_package*", "my_utils*"]
```

**Explicit package list (when auto-discovery fails or finds too much):**
```toml
[tool.setuptools]
packages = ["my_package", "my_package.submodule"]
package-dir = {"" = "src"}
```

**When import surface doesn't match file layout:**
If the task requires `from mylib import func` but the code is in `mylib/internal.py`,
you must explicitly re-export in `__init__.py`:
```python
# mylib/__init__.py
from mylib.internal import func
__all__ = ["func"]
```

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

**Use PEP 503 nested directory layout.** The index root should be `/app/pypi/` (or
another configurable location), with artifacts physically placed at
`INDEX_ROOT/simple/<package_name>/`. This ensures physical file paths match the
HTTP URL paths, which is what evaluators and static index tools expect.

```
/app/pypi/               ← INDEX_ROOT (pypiserver --root)
└── simple/
    └── vectorops/       ← per-package artifact directory
        ├── vectorops-0.1.0-py3-none-any.whl
        └── vectorops-0.1.0.tar.gz
```

**Prepare the index directory (clean stale artifacts first):**
```bash
INDEX_ROOT="/app/pypi"
PACKAGE_ARTIFACTS_DIR="$INDEX_ROOT/simple/<package_name>"
mkdir -p "$PACKAGE_ARTIFACTS_DIR"
# Remove old artifacts to prevent stale versions from being served
rm -f "$PACKAGE_ARTIFACTS_DIR"/*.whl "$PACKAGE_ARTIFACTS_DIR"/*.tar.gz "$PACKAGE_ARTIFACTS_DIR"/*.egg
cp /app/dist/* "$PACKAGE_ARTIFACTS_DIR"/
```

Without the cleanup step, stale artifacts from previous builds accumulate. pypiserver
will serve all of them, and pip may resolve to an unexpected version — especially
when rebuilding the same version number with different code.

**Why nested layout matters:**
- Evaluators check physical file existence at `INDEX_ROOT/simple/<package_name>/`
- Static index tools (nginx, httpd) can serve the directory directly as PEP 503
- Physical paths match URL paths: `/simple/vectorops/` → `simple/vectorops/`
- pypiserver auto-detects the `simple/` subdirectory when pointed at INDEX_ROOT

**Stop any existing server (PID-file-based, works in minimal containers):**
```bash
# Primary: use PID file (works without lsof/fuser)
if [ -f /tmp/pypiserver-<PORT>.pid ]; then
    kill "$(cat /tmp/pypiserver-<PORT>.pid)" 2>/dev/null || true
    rm -f /tmp/pypiserver-<PORT>.pid
fi
# Fallback: lsof if available (not in all minimal containers)
if command -v lsof > /dev/null 2>&1; then
    lsof -ti :<PORT> | xargs kill 2>/dev/null || true
fi
sleep 1
```

**Avoid blanket `pkill -f "pypi-server"`** — it kills ALL pypiserver processes on
the system, including ones serving other projects on different ports. Use
PID-file-based killing as the primary method, with port-targeted killing as fallback.

**Start pypiserver (point at INDEX_ROOT, not simple/ subdir):**
```bash
nohup pypi-server run -p <PORT> /app/pypi/ > /tmp/pypiserver.log 2>&1 &
echo $! > /tmp/pypiserver-<PORT>.pid
sleep 2
```

**IMPORTANT:** Point pypiserver at the INDEX_ROOT (`/app/pypi/`), NOT at the
`simple/` subdirectory. pypiserver auto-detects the `simple/` directory and serves
it as the PEP 503 simple index.

**Verify the server is running and serving packages:**
```bash
curl -s http://localhost:<PORT>/simple/
# Should show HTML with links to available packages
```

**Common port conflicts:** If port is in use:
```bash
# Check what's on the port
ss -tlnp | grep <PORT> 2>/dev/null || netstat -tlnp | grep <PORT> 2>/dev/null
# Kill via PID file or lsof (if available)
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
- Kill via PID file: `kill $(cat /tmp/pypiserver-<PORT>.pid)`
- Or via lsof if available: `lsof -ti :<PORT> | xargs kill`
- Never use blanket `pkill -f "pypi-server"` — it kills all instances system-wide
- Choose a different port if needed

**Stale artifacts causing wrong version:**
- Clean `dist/` before building: `rm -rf dist/` (build does NOT clean it)
- Clean index artifacts before copying: `rm -f INDEX_ROOT/simple/<pkg>/*.whl`
- Use `--force-reinstall` and `--no-cache-dir` with pip

**lsof/fuser not available in minimal containers:**
- Use PID-file-based process killing as primary method
- Save PID when starting: `echo $! > /tmp/pypiserver-<PORT>.pid`
- Kill via PID file: `kill $(cat /tmp/pypiserver-<PORT>.pid)`
- Fall back to `ss -tlnp | grep <PORT>` to diagnose port conflicts

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

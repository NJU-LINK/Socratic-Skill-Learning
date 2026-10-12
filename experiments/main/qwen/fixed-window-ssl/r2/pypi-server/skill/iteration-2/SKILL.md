---
name: pypi-server
description: Build Python packages from source and serve them via a local PEP 503-compliant PyPI index for client installation
---

# PyPI Server Package Publication

This skill covers creating, building, and serving Python packages via a local PyPI-compatible index. It handles the full workflow from source code to installable package, with decision points for common variations in package structure, build configuration, and index service setup.

## Family Axes and Variation

The task family varies along four dimensions:

1. **Package layout and build metadata**: src-layout vs flat layout, pyproject.toml vs setup.py, explicit vs automatic package discovery, single vs multi-module packages
2. **Package functionality requirements**: What the package must export and how it must behave (function signatures, validation, edge cases)
3. **Package index service configuration**: pypiserver vs static index vs devpi, port number, authentication, storage location
4. **Publication and installation flow**: wheel-only vs sdist-only, version replacement, artifact cleanup, fresh installation requirements

## Procedure

### Phase 1: Reconnaissance

Determine the starting state:

```bash
# Check if project already exists
ls -la /app/pyproject.toml /app/setup.py /app/setup.cfg 2>/dev/null

# Check existing package structure
find /app -name "*.py" -type f | head -20

# Check for existing dist artifacts
ls -la /app/dist/ 2>/dev/null

# Check if index server is already running
curl -sf http://localhost:PORT/simple/ > /dev/null && echo "Server running" || echo "Server not running"
```

**Decision point**: If project exists but is broken, diagnose before proceeding:
- Missing `[tool.setuptools.packages.find]` with wrong `where` for src-layout
- `package-dir` pointing to wrong location
- Stale `dist/` with wrong versions
- Import surface doesn't match file layout

### Phase 2: Package Structure

#### For src-layout (most common):

```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py
        └── <modules>.py
```

**pyproject.toml template (setuptools)**:
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**Critical**: The `where = ["src"]` directive is required for src-layout. Without it, setuptools defaults to flat layout discovery and produces a wheel with no importable code.

#### For flat layout:

```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── <modules>.py
```

**pyproject.toml adjustment**:
```toml
[tool.setuptools.packages.find]
where = ["."]
```

Or omit the `[tool.setuptools.packages.find]` section entirely (setuptools defaults to flat layout).

#### For multi-module packages:

Explicitly list packages:
```toml
[tool.setuptools]
packages = ["package1", "package2", "package3"]
package-dir = {"" = "src"}
```

#### For setup.py projects:

If only `setup.py` exists (legacy):
```bash
python setup.py sdist bdist_wheel
```

### Phase 3: Implement Package Functionality

Create the required modules in the package directory. The `__init__.py` must export the required public API:

```python
# __init__.py
from <package>.<module> import <function_or_class>

__all__ = ["<function_or_class>"]
```

**Decision point**: If the task requires `from package import function`, ensure the function is imported in `__init__.py`. If it requires `from package.module import function`, the module structure must match.

### Phase 4: Build Artifacts

```bash
# Install build tool if not present
pip install build

# Build both sdist and wheel
cd /app
python -m build
```

This creates `/app/dist/` containing:
- `<package>-<version>.tar.gz` (source distribution)
- `<package>-<version>-py3-none-any.whl` (wheel)

**Decision point**: If only wheel or only sdist is required:
- Wheel only: `python -m build --wheel`
- Sdist only: `python -m build --sdist`

**Verification**:
```bash
ls -la /app/dist/
# Should show both artifacts with correct version
```

### Phase 5: Start Local Index Server

#### Using pypiserver (most common):

```bash
# Install pypiserver
pip install pypiserver

# Clean dist directory to avoid stale artifacts
rm -rf /app/dist/*
# Rebuild if needed
python -m build

# Start server with persistence and save PID
nohup pypi-server run -p <PORT> /app/dist > /tmp/pypi.log 2>&1 &
echo $! > /tmp/pypi.pid

# Wait for startup
sleep 2

# Verify server is running
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server running" || echo "Server failed to start"
```

**Critical server persistence patterns**:
1. Use `nohup` or redirect output to prevent server from dying when shell exits
2. Save the PID manually with `echo $! > /tmp/pypi.pid` after starting (pypiserver's `--pidfile` flag doesn't work in v2.4.1)
3. To kill: use `fuser -k <PORT>/tcp` or `kill $(cat /tmp/pypi.pid)` (minimal containers lack `ps`, `pgrep`, `pkill`)
4. Verify with `curl` health-check, not process inspection tools
5. If server dies, restart pointing at the same dist directory

**Decision point**: If authentication is required:
```bash
pypi-server run -p <PORT> --passwords /path/to/htpasswd /app/dist
```

#### Using static file index:

If pypiserver is unavailable, create a PEP 503-compliant static structure:

```
/app/index/
└── simple/
    └── <package-name>/
        ├── index.html
        ├── <package>-<version>.tar.gz
        └── <package>-<version>-py3-none-any.whl
```

**index.html template**:
```html
<!DOCTYPE html>
<html>
<head><title>Links for <package-name></title></head>
<body>
<h1>Links for <package-name></h1>
<a href="<package>-<version>.tar.gz#sha256=<hash>"><package>-<version>.tar.gz</a><br>
<a href="<package>-<version>-py3-none-any.whl#sha256=<hash>"><package>-<version>-py3-none-any.whl</a><br>
</body>
</html>
```

**⚠️ Caveat**: `python -m http.server` serves raw directory listings, not proper PEP 503 HTML pages. Modern pip can sometimes follow directory listings as links, but this is fragile and not standards-compliant. **Always prefer pypiserver when available.** The static approach is a last resort and requires manually crafted HTML index pages with sha256 fragments as shown above.

If you must use a static server, ensure the HTML structure exactly matches PEP 503 with proper links and hash fragments.

#### Static Index File Layout (Test Requirement)

**Critical**: Some test suites verify that built artifacts physically exist at a specific `INDEX_ROOT` path (e.g., `/app/pypi/simple/<package-name>/<artifact>`). This is a **family invariant**, not a fallback. When tests check both the HTTP API AND the physical file layout:

1. **Build artifacts to `/app/dist/`** as usual
2. **Create the static index structure**:
   ```bash
   mkdir -p /app/pypi/simple/<package-name>
   cp /app/dist/<artifact> /app/pypi/simple/<package-name>/
   ```
3. **Create PEP 503 HTML index pages**:
   - `/app/pypi/simple/index.html` (root index listing all packages)
   - `/app/pypi/simple/<package-name>/index.html` (package index listing all versions)
4. **Serve the static directory**:
   ```bash
   cd /app/pypi && nohup python -m http.server <PORT> --bind 0.0.0.0 > /tmp/httpd.log 2>&1 &
   ```
5. **Verify both**:
   - HTTP API: `curl -s http://localhost:<PORT>/simple/<package-name>/`
   - Physical files: `ls -la /app/pypi/simple/<package-name>/`

**Why this matters**: Tests may assert `(INDEX_ROOT / "simple" / "<package-name>" / "<artifact>").exists()` in addition to checking that `pip install` works. The static layout satisfies both requirements simultaneously.

**When to use**: Always check if the task specifies an `INDEX_ROOT` or if tests verify physical file existence. When in doubt, use the static layout approach as it satisfies both HTTP and filesystem requirements.

### Phase 6: Installation and Verification

```bash
# Install from local index
pip install --index-url http://localhost:<PORT>/simple <package-name>==<version>

# Verify installation
python3 -c "from <package> import <function>; print(<function>(<test_args>))"
```

**Critical**: `--index-url` replaces PyPI entirely (no fallback). If the local index doesn't serve the exact version, installation fails.

## Troubleshooting

### Wheel has no importable code

**Symptom**: `ModuleNotFoundError` after successful installation

**Cause**: Package discovery failure during build

**Fix**:
1. Check `pyproject.toml` for correct `[tool.setuptools.packages.find]` with appropriate `where`
2. For src-layout: `where = ["src"]`
3. For flat layout: `where = ["."]` or omit section
4. Rebuild: `rm -rf dist/ build/ src/*.egg-info && python -m build`
5. Inspect wheel: `unzip -l dist/*.whl` to verify package files are present

### pip install can't find version

**Symptom**: `ERROR: Could not find a version that satisfies the requirement`

**Causes and fixes**:
1. **Artifact not in index directory**: Verify files exist in the directory pypiserver is serving
2. **Name normalization mismatch**: PEP 503 normalizes names to lowercase with hyphens. `VectorOps` becomes `vectorops`
3. **Server not running**: Check with `curl -sf http://localhost:<PORT>/simple/`
4. **Stale artifacts**: Clean dist directory and rebuild

### Server died or not responding

**Symptom**: Connection refused or timeout

**Fix**:
```bash
# Check if server is running
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "OK" || echo "FAILED"

# Restart if needed (pkill/ps may not be available in minimal containers)
fuser -k <PORT>/tcp 2>/dev/null || kill $(cat /tmp/pypi.pid 2>/dev/null) 2>/dev/null || true
sleep 1
nohup pypi-server run -p <PORT> /app/dist > /tmp/pypi.log 2>&1 &
echo $! > /tmp/pypi.pid
sleep 2

# Verify
curl -sf http://localhost:<PORT>/simple/ > /dev/null && echo "Server restarted" || echo "Restart failed"
```

### Stale artifacts serving wrong version

**Symptom**: `pip install` gets old version or multiple versions appear in index

**Fix**:
```bash
# Clean and rebuild
rm -rf /app/dist /app/build /app/src/*.egg-info
python -m build

# Restart server pointing at clean dist
fuser -k <PORT>/tcp 2>/dev/null || kill $(cat /tmp/pypi.pid 2>/dev/null) 2>/dev/null || true
sleep 1
nohup pypi-server run -p <PORT> /app/dist > /tmp/pypi.log 2>&1 &
echo $! > /tmp/pypi.pid
```

## Family Invariants

Regardless of variation, these properties must hold:

1. **PEP 503 compliance**: The index must serve a `/simple/` endpoint with HTML pages listing package versions and artifact links
2. **Name normalization**: Package names in URLs and filenames must be lowercase with hyphens (underscores and mixed case are normalized)
3. **Server persistence**: The index server must remain running across shell exits and test execution
4. **Artifact availability**: Both sdist and wheel (or whichever the task requires) must be present and downloadable
5. **Fresh installation**: `pip install` must succeed from the local index without falling back to PyPI

## Decision Tree Summary

```
Start
├─ Project exists?
│  ├─ Yes → Diagnose pyproject.toml/setup.py, check package structure
│  └─ No → Create from scratch (Phase 2)
├─ Which layout?
│  ├─ src-layout → where = ["src"]
│  ├─ Flat layout → where = ["."] or omit
│  └─ Multi-module → explicit packages list
├─ Which build system?
│  ├─ pyproject.toml → python -m build
│  └─ setup.py → python setup.py sdist bdist_wheel
├─ Test requirements?
│  ├─ Checks physical files at INDEX_ROOT → Use static layout (Phase 5.1)
│  └─ Only checks HTTP API → Use pypiserver or static layout
├─ Which index server?
│  ├─ pypiserver → pypi-server run -p PORT /path/to/dist
│  └─ Static → Create PEP 503 structure at /app/pypi/simple/, serve with http.server
└─ Verification
   ├─ Server running? → curl health-check
   ├─ Artifacts present? → ls dist/ AND ls /app/pypi/simple/<package>/
   ├─ Physical files exist? → Check INDEX_ROOT structure
   └─ Installation works? → pip install --index-url ...
```

---
name: pypi-server
description: Build Python packages from source and serve them via a local PEP 503-compatible package index for installation
---

# PyPI Server Package Publishing

Build Python packages from source code and serve them via a local package index that clients can install from.

## Task Family Overview

This skill handles the full workflow: source code → build artifacts → local index → client installation. The family varies across four dimensions:

1. **Package layout and build metadata**: src-layout vs flat layout, pyproject.toml vs setup.py, explicit package discovery, package data
2. **Package functionality**: What the package must do once installed (functions, classes, validation, edge cases)
3. **Index service configuration**: pypiserver vs devpi vs static HTML, different ports, authenticated uploads, initialization requirements
4. **Publication and installation flow**: wheel-only vs sdist-only, version management, stale artifacts, fresh installation guarantees

## Diagnostic Phase

**Always start by understanding the current state.** Check what exists before deciding what to build or fix.

```bash
# What's in the workspace?
ls -la /app/
find /app -name "pyproject.toml" -o -name "setup.py" -o -name "setup.cfg" 2>/dev/null

# Is there existing source code?
find /app -name "*.py" -type f | head -20

# What's the layout? (src/ vs flat)
ls -la /app/src/ 2>/dev/null || echo "No src/ directory"
ls -la /app/<package_name>/ 2>/dev/null || echo "No flat layout"

# Are there existing build artifacts?
ls -la /app/dist/ 2>/dev/null || echo "No dist/ directory"

# Is an index server already running? (behavioral probe - works in minimal containers)
curl -sf http://localhost:<port>/simple/ > /dev/null && echo "Server is up" || echo "No server running"

# Optional: if ps/ss are available, get more details
ps aux 2>/dev/null | grep -E "(pypi-server|devpi)" | grep -v grep
ss -tlnp 2>/dev/null | grep -E ":(8091|8080|3141)"

# What Python packages are installed?
pip list | grep -E "(pypiserver|devpi|build|setuptools|wheel)"
```

**Decision points:**
- Empty workspace → build from scratch
- Pre-existing project → diagnose what's broken (missing __init__.py, wrong layout, stale dist/, bad metadata)
- Index server already running → check if it's serving the right artifacts on the right port, reuse or replace
- Stale artifacts in dist/ → clean before rebuilding

## Build Phase

### Install Build Tools

```bash
pip install build setuptools wheel
```

**Gotcha**: Install build dependencies *before* starting the local index server. If the index is running and serving an incomplete package set, pip might fail to resolve dependencies.

### Configure Build Metadata

**For src-layout** (package code in `/app/src/<package_name>/`):

```toml
[build-system]
requires = ["setuptools>=64", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package_name>"
version = "<version>"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**For flat layout** (package code in `/app/<package_name>/`):

```toml
[tool.setuptools]
packages = ["<package_name>"]
```

**For explicit package discovery** (when import name differs from directory name):

```toml
[tool.setuptools.packages]
find = {where = ["src"], include = ["<import_name>*"]}

[tool.setuptools.package-dir]
"<import_name>" = "src/<directory_name>"
```

**For package data** (non-Python files):

```toml
[tool.setuptools.package-data]
"<package_name>" = ["*.json", "*.txt", "data/*"]
```

### Ensure Public API

The package's `__init__.py` must export the required symbols:

```python
from .module import function_name

__all__ = ["function_name"]
```

**Common mistake**: Forgetting to import in `__init__.py` means `from <package> import <function>` fails even if the function exists in a submodule.

### Build Artifacts

```bash
cd /app
rm -rf dist/ build/ *.egg-info src/*.egg-info  # Clean stale artifacts
python -m build
```

This creates both `dist/<package>-<version>.tar.gz` (sdist) and `dist/<package>-<version>-py3-none-any.whl` (wheel).

**Verify artifacts exist:**

```bash
ls -la /app/dist/
```

**Troubleshooting:**
- "No module named <package>" → Check layout (src vs flat) and package discovery config
- "Missing __init__.py" → Add it to the package directory
- Build succeeds but package is empty → Check that `packages.find` points to the right directory

## Index Server Phase

### Choose and Install Index Tool

**pypiserver** (simple, read-only, serves a directory):

```bash
pip install pypiserver
```

**devpi** (full-featured, supports uploads, caching):

```bash
pip install devpi-server devpi-web
```

**Static HTML index** (for offline/air-gapped environments):

Generate PEP 503-compliant HTML manually or use a tool like `pip2pi`.

### Start the Index Server

**pypiserver:**

```bash
# Idempotent startup: kill any existing server, save PID for later management
kill $(cat /tmp/pypiserver.pid 2>/dev/null) 2>/dev/null || true
sleep 1

nohup pypi-server run -p <port> /app/dist > /tmp/pypiserver.log 2>&1 &
echo $! > /tmp/pypiserver.pid
sleep 2
```

**Why `nohup`**: Tests may run in a separate shell (`run_tests_in_same_shell: false`). A bare `&` backgrounds the process within the current shell, but the process may be killed when the shell exits depending on the environment's process group handling. `nohup` detaches the process from the shell's process group, ensuring it survives.

**Why save PID**: Minimal containers often lack `pkill`/`pgrep`. Saving the PID at startup lets you kill the server later with `kill $(cat /tmp/pypiserver.pid)` without needing process inspection tools.

The server automatically implements PEP 503's `/simple/` endpoint. It scans the directory for `.tar.gz` and `.whl` files and serves them.

**Verify the server is running and responsive:**

```bash
curl -sf http://localhost:<port>/simple/ > /dev/null && echo "Server is up" || echo "Server failed to start"
curl -s http://localhost:<port>/simple/ | head -20
```

You should see an HTML page listing your package name as a link.

**devpi:**

```bash
devpi-server --start --host 0.0.0.0 --port <port> --serverdir /tmp/devpi &
sleep 3
```

**Static index:**

Serve with any HTTP server:

```bash
cd /path/to/index && python -m http.server <port> &
```

### Handle Authentication (if required)

**pypiserver with password file:**

```bash
pip install passlib
htpasswd -sc .htpasswd <username>
pypi-server run -p <port> -P .htpasswd /app/dist &
```

Client installation:

```bash
pip install --index-url http://<user>:<pass>@localhost:<port>/simple <package>
```

## Installation Phase

### Install from Local Index

```bash
pip install --no-cache-dir --index-url http://localhost:<port>/simple <package>==<version>
```

**Critical flags:**
- `--no-cache-dir`: Prevents pip from using cached wheels from previous installations or public PyPI
- `--index-url`: Points exclusively at your local index (use `--extra-index-url` if you need to fall back to public PyPI for dependencies)

**Verify installation:**

```bash
pip show <package>
python -c "from <package> import <function>; print(<function>(...))"
```

### Handle Version Conflicts

If the package is already installed from a different source:

```bash
pip uninstall -y <package>
pip install --no-cache-dir --index-url http://localhost:<port>/simple <package>==<version>
```

### Handle Dependency Resolution

If your package depends on other packages that aren't in your local index:

```bash
# Option 1: Use --extra-index-url to fall back to public PyPI
pip install --no-cache-dir \
  --index-url http://localhost:<port>/simple \
  --extra-index-url https://pypi.org/simple \
  <package>==<version>

# Option 2: Pre-install dependencies from public PyPI
pip install <dependency1> <dependency2>
pip install --no-cache-dir --no-deps --index-url http://localhost:<port>/simple <package>==<version>
```

## Verification Checklist

After installation, verify:

1. **Package is installed from the correct source:**
   ```bash
   pip show <package> | grep -E "(Name|Version|Location)"
   ```

2. **Public API is accessible:**
   ```bash
   python -c "from <package> import <function>; print(<function>(<test_args>))"
   ```

3. **Functionality is correct:**
   Test with the exact inputs/outputs specified in the requirements.

4. **Edge cases work** (if specified):
   - Empty inputs
   - Mismatched lengths
   - Type validation
   - Error handling

## Normalized Distribution Names

PEP 503 normalizes package names in distribution filenames: hyphens become underscores, names are lowercased. For example, a package named `my-package` produces `my_package-1.0.0-py3-none-any.whl`.

**pypiserver** handles this normalization automatically — it maps requests for `/simple/my-package/` to the `my_package-*.whl` files in the directory.

**Static HTML indexes and devpi** require you to ensure filenames and HTML links use the normalized form. When generating static index HTML:
- Directory name: `/simple/my-package/` (hyphens preserved in URL per PEP 503)
- File links: `my_package-1.0.0-py3-none-any.whl` (underscores in filename)

If a task uses a package name with hyphens, verify that the built artifacts use the normalized name and that the index serves them correctly.

## Common Failure Modes and Recovery

### Build Failures

**Symptom**: `python -m build` fails with "package not found" or "no modules"
**Cause**: Package discovery misconfigured
**Fix**: 
- For src-layout: Ensure `[tool.setuptools.packages.find] where = ["src"]`
- For flat layout: Ensure `[tool.setuptools] packages = ["<name>"]`
- Verify the package directory has `__init__.py`

**Symptom**: Build succeeds but wheel is empty
**Cause**: Wrong package directory or missing `__init__.py`
**Fix**: Check that the package directory structure matches your config

### Index Server Issues

**Symptom**: `curl http://localhost:<port>/simple/` returns 404 or empty
**Cause**: Server not running or pointing at wrong directory
**Fix**:
- Behavioral probe: `curl -sf http://localhost:<port>/simple/ > /dev/null && echo "up" || echo "down"`
- Verify the directory path: `ls /app/dist/`
- Restart server with correct path (use idempotent startup pattern above)

**Symptom**: Package not listed in index
**Cause**: Artifacts not in the served directory or wrong naming
**Fix**:
- Ensure artifacts are in the directory the server is serving
- Check artifact names match PEP 427 (wheel) or sdist conventions
- Restart server after adding new artifacts

### Installation Issues

**Symptom**: `pip install` fails with "No matching distribution found"
**Cause**: Package not in index or version mismatch
**Fix**:
- Verify package is listed: `curl http://localhost:<port>/simple/<package>/`
- Check version: `pip index versions <package> --index-url http://localhost:<port>/simple`
- Ensure you're using `--index-url` not `--extra-index-url`

**Symptom**: Installation succeeds but imports fail
**Cause**: Wrong package installed (from cache or different source)
**Fix**:
- Uninstall: `pip uninstall -y <package>`
- Clear cache: `pip cache purge`
- Reinstall with `--no-cache-dir`

**Symptom**: Old version installed despite specifying new version
**Cause**: Pip cache or different index
**Fix**:
- Use `--no-cache-dir`
- Explicitly uninstall first
- Check `pip show <package>` to verify version and location

## Generalization Notes

This skill handles the full family by focusing on **decision points** rather than fixed commands:

- **Layout detection**: Check for src/ vs flat, adapt pyproject.toml accordingly
- **Build backend**: Support setuptools, flit, poetry, or custom backends
- **Index tool**: pypiserver for simple cases, devpi for full-featured, static HTML for offline
- **Artifact management**: Clean stale artifacts, handle version conflicts, support wheel-only or sdist-only
- **Authentication**: Optional password protection for uploads
- **Dependency resolution**: Handle packages with external dependencies

The diagnostic-first approach ensures you adapt to the actual state of the workspace rather than assuming a clean slate.

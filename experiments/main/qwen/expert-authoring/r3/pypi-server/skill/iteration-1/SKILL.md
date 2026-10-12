---
name: pypi-server
description: >
  Build a Python package from source, publish it to a local PEP 503-compatible
  PyPI index, and verify end-to-end installability. Covers src-layout and flat
  layout packages, pyproject.toml and setup.py metadata, sdist/wheel building,
  pypiserver configuration on arbitrary ports, and pip-based installation from
  the local index.
---

# PyPI Server — Local Package Build & Serve

## Task Family Summary

You are given an empty or partially-populated workspace at `/app`. Your goal is to:

1. Create (or fix) a Python package with the specified name, version, and API.
2. Build distributable artifacts (sdist and/or wheel).
3. Start a local PEP 503-compatible package index on the specified port.
4. Ensure `pip install --index-url http://localhost:<PORT>/simple <pkg>==<ver>` succeeds.
5. Ensure the installed package's public API works correctly at runtime.

---

## Phase 0 — Reconnaissance

Before writing any code, answer these questions from the task instruction:

| Question | Where to look | Default if unspecified |
|---|---|---|
| Package name | instruction text | — |
| Version | instruction text | `0.1.0` |
| Layout | "src layout" vs "flat" vs pre-existing files | `src/` layout |
| Build backend | pyproject.toml vs setup.py vs setup.cfg | `setuptools` with `pyproject.toml` |
| Public API | `from <pkg> import <name>` statements | must read instruction |
| Port | "on port NNNN" | `8091` |
| Artifact types | "wheel and sdist", "wheel only", etc. | both sdist + wheel |
| Index tool | pypiserver / devpi / static | `pypiserver` |

Run `ls -la /app/` and `find /app -type f` to check for pre-existing files.
Run `python3 --version` and `pip list 2>/dev/null | grep -iE 'build|twine|pypiserver|setuptools|wheel'` to check available tooling.

---

## Phase 1 — Install Missing Tools

```bash
pip install build pypiserver 2>&1 | tail -5
```

- `build` provides `python3 -m build` (PEP 517 builder).
- `pypiserver` provides the `pypi-server` command.
- If `twine` is needed for authenticated upload: `pip install twine`.
- If `setuptools` or `wheel` are missing: `pip install setuptools wheel`.

Verify:
```bash
python3 -m build --help >/dev/null 2>&1 && echo "build OK"
pypi-server --version 2>/dev/null && echo "pypiserver OK"
```

---

## Phase 2 — Create / Fix the Package Source

### 2a. Source layout decision

**src-layout** (default when instruction says "src layout"):
```
/app/
├── pyproject.toml
└── src/
    └── <package_name>/
        ├── __init__.py
        └── <module>.py        # implementation
```

**flat layout**:
```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── <module>.py
```

**Pre-existing project**: Inspect what exists, identify what is broken or missing, and fix only what is needed. Do not overwrite working code.

### 2b. pyproject.toml (setuptools backend)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"          # MUST be lowercase, hyphens OK
version = "<version>"
description = "<short description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout, omit the [tool.setuptools.packages.find] section
# or use: where = ["."]
```

**If setup.py is required instead** (legacy project):
```python
from setuptools import setup, find_packages
setup(
    name="<package-name>",
    version="<version>",
    packages=find_packages(where="src"),   # or find_packages() for flat
    package_dir={"": "src"},               # omit for flat
)
```

### 2c. Package code

The `__init__.py` must re-export the public API so that `from <pkg> import <func>` works:

```python
# src/<package_name>/__init__.py
from .<module> import <public_name>
__all__ = ["<public_name>"]
```

The implementation module should handle edge cases mentioned in the instruction (empty lists, mismatched lengths, type validation, etc.). When no specific edge-case behavior is specified, raise `ValueError` for invalid inputs.

### 2d. Multi-module packages

If the instruction requires multiple submodules or helper modules, place them alongside `__init__.py` and import as needed. The public surface is controlled by `__init__.py`.

---

## Phase 3 — Build Artifacts

```bash
cd /app
python3 -m build 2>&1
```

This produces files in `/app/dist/`:
- `<name>-<version>.tar.gz` (sdist)
- `<name>-<version>-py3-none-any.whl` (wheel, for pure-Python packages)

**Variation handling:**
- Wheel only: `python3 -m build --wheel`
- Sdist only: `python3 -m build --sdist`
- If the build fails, read the error — common issues:
  - Missing `__init__.py` → package not discovered
  - Wrong `where` in `[tool.setuptools.packages.find]` → no packages found
  - Import errors in setup.py → fix the import or use pyproject.toml

**Verify artifacts exist:**
```bash
ls -la /app/dist/
# Expect at least one .whl and/or .tar.gz matching the package name and version
```

**Distribution name normalization**: Python package names normalize hyphens/underscores/dots to hyphens in distribution filenames, and to underscores in import names. The sdist/wheel filename uses the normalized form (lowercase, hyphens → underscores for the import part). Do not be surprised if `my-package` produces `my_package-0.1.0-py3-none-any.whl`.

---

## Phase 4 — Start the Local Package Index

### 4a. Basic pypiserver launch

```bash
# Kill any existing server on the target port first
fuser -k <PORT>/tcp 2>/dev/null || true

nohup pypi-server run \
  --host 0.0.0.0 \
  --port <PORT> \
  --disable-fallback \
  /app/dist/ \
  > /tmp/pypiserver.log 2>&1 &

echo "PyPI server PID: $!"
sleep 2
```

Key flags:
- `--disable-fallback` — prevents forwarding to pypi.org; ensures only local packages are served.
- `--port <PORT>` — the port specified in the instruction.
- `--host 0.0.0.0` — bind to all interfaces (safest for container environments).

### 4b. Verify the index is alive

```bash
curl -s http://localhost:<PORT>/simple/
# Should return HTML listing the package name(s)
```

```bash
curl -s http://localhost:<PORT>/simple/<normalized-package-name>/
# Should show links to the .whl and/or .tar.gz files
```

### 4c. Alternate index tools

If the instruction specifies `devpi` or a static index instead of pypiserver:
- **devpi**: `pip install devpi-server devpi-client`, initialize, start on the port.
- **Static index**: Generate a PEP 503 directory structure and serve with `python3 -m http.server <PORT>`.

---

## Phase 5 — Install and Verify

### 5a. Uninstall any pre-existing version

```bash
pip uninstall <package-name> -y 2>/dev/null || true
```

### 5b. Install from the local index

```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  <package-name>==<version> 2>&1
```

If this fails:
1. Check the index is running: `curl http://localhost:<PORT>/simple/`
2. Check the package appears: `curl http://localhost:<PORT>/simple/<name>/`
3. Check version match: the filename version must match the requested version exactly.
4. Add `--no-cache-dir` if pip cached a failed download.
5. Add `--trusted-host localhost` if there are TLS/hostname warnings.

### 5c. Functional verification

```python
python3 -c "
from <package_name> import <public_api>
# Test basic functionality as described in the instruction
result = <public_api>(<test_args>)
print(f'Result: {result}')
assert result == <expected>, f'Expected <expected>, got {result}'
print('PASS')
"
```

Test the exact import path specified in the instruction. If it says `from vectorops import dotproduct`, test exactly that.

### 5d. Installation from clean environment (self-check)

```bash
pip uninstall <package-name> -y 2>/dev/null
pip install --index-url http://localhost:<PORT>/simple <package-name>==<version> --no-cache-dir 2>&1
python3 -c "import <package_name>; print('Import OK')"
```

---

## Phase 6 — Keep the Server Running

The local index must remain running when the task is evaluated. Ensure:

1. The server process is backgrounded (nohup + &).
2. The server is not a child of a process that will exit.
3. Check it is still alive: `curl -s http://localhost:<PORT>/simple/ | head -5`

If the server dies unexpectedly, restart it:
```bash
fuser <PORT>/tcp 2>/dev/null || {
  nohup pypi-server run --host 0.0.0.0 --port <PORT> --disable-fallback /app/dist/ \
    > /tmp/pypiserver.log 2>&1 &
  sleep 2
}
```

---

## Decision Rules

| Situation | Action |
|---|---|
| Instruction says "src layout" | Use `src/<pkg>/` with `[tool.setuptools.packages.find] where = ["src"]` |
| Instruction says "flat layout" | Use `<pkg>/` at project root, omit `where` or set `where = ["."]` |
| Pre-existing pyproject.toml | Read it, fix only what is wrong, preserve intentional settings |
| Pre-existing setup.py, no pyproject.toml | Add a minimal `pyproject.toml` with `[build-system]` or use `python3 setup.py sdist bdist_wheel` |
| Package data needed (non-.py files) | Add `[tool.setuptools.package-data]` or `include_package_data = true` |
| Build says "no packages found" | Check `where` path and ensure `__init__.py` exists |
| `pip install` says "no matching distribution" | Check: server running? Correct port? Correct normalized name? Artifact exists in dist/? |
| Import fails after install | Check `__init__.py` exports, check installed location: `pip show -f <pkg>` |
| Server won't start (port in use) | `fuser -k <PORT>/tcp` then retry |
| Multiple versions in dist/ | Remove stale artifacts; pip may pick the wrong one or get confused |

---

## Common Pitfalls

1. **Normalized names**: `my_package` and `my-package` are the same package. Filenames use underscores in the package part but the simple index URL uses the normalized form.
2. **Stale artifacts**: If you rebuild with a different version, old files in `dist/` may confuse the index. Clean `dist/` before rebuilding when changing versions.
3. **Missing `__init__.py`**: Without it, setuptools won't discover the package directory (unless using implicit namespace packages, which is unusual for this task family).
4. **`pip install` from wrong source**: Always use `--index-url` (not `--extra-index-url`) to avoid falling back to pypi.org and accidentally installing a different package with the same name.
5. **Server lifecycle**: Start the server after building artifacts. If you add artifacts later, restart the server or it may not see the new files (pypiserver scans on startup, though newer versions may watch for changes).

---

## Quick Reference — Minimal Working Example

```bash
# 1. Install tools
pip install build pypiserver

# 2. Create package (src layout)
mkdir -p /app/src/<pkg>
cat > /app/src/<pkg>/__init__.py << 'PYEOF'
from .impl import <func>
__all__ = ["<func>"]
PYEOF

cat > /app/src/<pkg>/impl.py << 'PYEOF'
def <func>(<args>):
    <implementation>
PYEOF

cat > /app/pyproject.toml << 'PYEOF'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<pkg>"
version = "<ver>"

[tool.setuptools.packages.find]
where = ["src"]
PYEOF

# 3. Build
cd /app && python3 -m build

# 4. Serve
nohup pypi-server run --host 0.0.0.0 --port <PORT> --disable-fallback /app/dist/ \
  > /tmp/pypiserver.log 2>&1 &
sleep 2

# 5. Install & verify
pip install --index-url http://localhost:<PORT>/simple <pkg>==<ver>
python3 -c "from <pkg> import <func>; print(<func>(<test_args>))"
```

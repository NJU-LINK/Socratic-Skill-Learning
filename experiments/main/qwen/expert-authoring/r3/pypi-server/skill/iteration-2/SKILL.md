---
name: pypi-server
description: >
  Build a Python package from source, publish it to a local PEP 503-compatible
  PyPI index with a static directory layout, and verify end-to-end installability.
  Covers src-layout and flat layout packages, pyproject.toml and setup.py metadata,
  sdist/wheel building, static PEP 503 directory generation, and pip-based
  installation from the local index.
---

# PyPI Server — Local Package Build & Static Index

## Task Family Summary

You are given an empty or partially-populated workspace at `/app`. Your goal is to:

1. Create (or fix) a Python package with the specified name, version, and API.
2. Build distributable artifacts (sdist and/or wheel) into `/app/dist/`.
3. Create a **static PEP 503 directory** at `/app/pypi/simple/<pkg>/` containing the artifacts.
4. Start an HTTP server on the specified port serving that directory.
5. Ensure `pip install --index-url http://localhost:<PORT>/simple <pkg>==<ver>` succeeds.
6. Ensure the installed package's public API works correctly at runtime.

**Critical**: Tests may check that artifact files physically exist on disk under
`/app/pypi/simple/<package_name>/`. A virtual server endpoint (like pypiserver's
default `/packages/` route) is **not sufficient** — you must create a real directory
structure with real files.

---

## Phase 0 — Reconnaissance

Before writing any code, extract parameters from the task instruction:

| Parameter | Where to look | Default if unspecified |
|---|---|---|
| Package name | instruction text | — |
| Version | instruction text | `0.1.0` |
| Layout | "src layout" vs "flat" vs pre-existing | `src/` layout |
| Build backend | pyproject.toml vs setup.py | `setuptools` + `pyproject.toml` |
| Public API | `from <pkg> import <name>` | must read instruction |
| Port | "on port NNNN" | `8091` |
| Artifact types | "wheel and sdist" etc. | both sdist + wheel |
| Index root | path mentioned in tests/constraints | `/app/pypi` |

Run: `ls -la /app/` and `find /app -type f` to check for pre-existing files.
Run: `python3 --version` and `pip list | grep -iE 'build|twine|pypiserver|setuptools|wheel'`.

---

## Phase 1 — Install Missing Tools

```bash
pip install build pypiserver 2>&1 | tail -5
```

- `build` → provides `python3 -m build` (PEP 517 builder).
- `pypiserver` → provides `pypi-server` (used as fallback server only).
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
        └── <module>.py
```

**flat layout**:
```
/app/
├── pyproject.toml
└── <package_name>/
    ├── __init__.py
    └── <module>.py
```

**Pre-existing project**: Inspect, identify what is broken/missing, fix only what is needed.

### 2b. pyproject.toml (setuptools backend)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<short description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout: omit or set where = ["."]
```

**setup.py variant** (legacy projects):
```python
from setuptools import setup, find_packages
setup(
    name="<package-name>",
    version="<version>",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
```

### 2c. Package code

`__init__.py` re-exports the public API:
```python
from .<module> import <public_name>
__all__ = ["<public_name>"]
```

Implementation module handles edge cases from the instruction. Default to raising `ValueError` for invalid inputs when no behavior is specified.

---

## Phase 3 — Build Artifacts

```bash
cd /app
python3 -m build 2>&1
```

Produces files in `/app/dist/`:
- `<name>-<version>.tar.gz` (sdist)
- `<name>-<version>-py3-none-any.whl` (wheel, pure-Python)

Verify:
```bash
ls -la /app/dist/
```

**Variation handling:**
- Wheel only: `python3 -m build --wheel`
- Sdist only: `python3 -m build --sdist`
- Name normalization: `my-package` produces `my_package-0.1.0-py3-none-any.whl`.

---

## Phase 4 — Create the Static PEP 503 Directory

This is the step most likely to be tested beyond basic pip-install functionality.

### 4a. Directory structure

Create a physical directory at the index root with copies of the artifacts:

```
/app/pypi/
└── simple/
    ├── index.html                  # root: lists all packages
    └── <package-name>/
        ├── index.html              # package: links to artifacts with hash fragments
        ├── <name>-<ver>-py3-none-any.whl   # copied from dist/
        └── <name>-<ver>.tar.gz             # copied from dist/
```

### 4b. Generate the directory and index files

Run this script after building. It copies artifacts and generates PEP 503 HTML:

```bash
PKG_NAME="<package-name>"          # e.g. "vectorops"
DIST_DIR="/app/dist"
INDEX_ROOT="/app/pypi"
SIMPLE_DIR="${INDEX_ROOT}/simple/${PKG_NAME}"

mkdir -p "$SIMPLE_DIR"
cp "$DIST_DIR"/*.whl "$SIMPLE_DIR/" 2>/dev/null
cp "$DIST_DIR"/*.tar.gz "$SIMPLE_DIR/" 2>/dev/null

# Generate root index.html
cat > "${INDEX_ROOT}/simple/index.html" << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="${PKG_NAME}/">${PKG_NAME}</a><br>
</body>
</html>
HTMLEOF

# Generate package index.html with sha256 hash fragments
cd "$SIMPLE_DIR"
python3 -c "
import hashlib, os
links = []
for f in sorted(os.listdir('.')):
    if f == 'index.html': continue
    sha = hashlib.sha256(open(f, 'rb').read()).hexdigest()
    links.append(f'<a href=\"{f}#sha256={sha}\">{f}</a><br>')
html = '<!DOCTYPE html>\n<html>\n<head><title>Links for ${PKG_NAME}</title></head>\n'
html += '<body>\n<h1>Links for ${PKG_NAME}</h1>\n'
html += '\n'.join(links)
html += '\n</body>\n</html>\n'
open('index.html', 'w').write(html)
print(html)
"
```

### 4c. Verify the directory

```bash
# Physical files must exist
ls -la /app/pypi/simple/<package-name>/
# Should show: index.html, .whl file(s), .tar.gz file(s)

# Verify the test-critical assertion:
# /app/pypi/simple/<pkg>/<wheel_filename>.whl exists
# /app/pypi/simple/<pkg>/<sdist_filename>.tar.gz exists
```

### Why not just pypiserver?

`pypi-server run` serves packages through virtual `/packages/` URLs. pip can install
from it, but the artifact files don't physically exist under the simple index path.
Tests that check `(index_root / "simple" / pkg / filename).exists()` will fail.
Always create the static directory **first**, then serve it.

---

## Phase 5 — Start the HTTP Server

### 5a. Preferred: static file server (python3 -m http.server)

```bash
# Aggressively kill any prior server on this port (pypiserver, http.server, etc.)
pkill -9 -f "pypi-server.*<PORT>" 2>/dev/null || true
pkill -9 -f "http.server.*<PORT>" 2>/dev/null || true
fuser -k -9 <PORT>/tcp 2>/dev/null || true
sleep 1

cd /app/pypi
nohup python3 -m http.server <PORT> --bind 0.0.0.0 \
  > /tmp/httpserver.log 2>&1 &

echo "HTTP server PID: $!"
sleep 2
```

**Important**: `fuser -k` without `-9` may not kill all server processes.
Use `pkill -9` first to ensure no lingering server intercepts the port.

This serves `/app/pypi/` as the document root, so:
- `GET /simple/` → `/app/pypi/simple/index.html`
- `GET /simple/vectorops/` → `/app/pypi/simple/vectorops/index.html`
- `GET /simple/vectorops/<file>` → `/app/pypi/simple/vectorops/<file>`

### 5b. Alternative: pypiserver (if dynamic upload or auto-indexing is needed)

If you use pypiserver, point it at the directory containing the package subdirectory:

```bash
pkill -9 -f "pypi-server.*<PORT>" 2>/dev/null || true
pkill -9 -f "http.server.*<PORT>" 2>/dev/null || true
fuser -k -9 <PORT>/tcp 2>/dev/null || true
sleep 1

nohup pypi-server run \
  --host 0.0.0.0 \
  --port <PORT> \
  --disable-fallback \
  /app/pypi/simple/ \
  > /tmp/pypiserver.log 2>&1 &

sleep 2
```

Note: pypiserver discovers packages in subdirectories and generates its own index
pages, so the package-level `index.html` files may be overridden. If tests check
for specific HTML content, prefer the static server (5a).

### 5c. Verify the server is responding

```bash
curl -s http://localhost:<PORT>/simple/
echo "---"
curl -s http://localhost:<PORT>/simple/<package-name>/
```

---

## Phase 6 — Install and Verify

### 6a. Uninstall any pre-existing version

```bash
pip uninstall <package-name> -y 2>/dev/null || true
```

### 6b. Install from the local index

```bash
pip install \
  --index-url http://localhost:<PORT>/simple \
  <package-name>==<version> 2>&1
```

If this fails:
1. Server running? `curl http://localhost:<PORT>/simple/`
2. Package visible? `curl http://localhost:<PORT>/simple/<name>/`
3. Version match? Filenames must match requested version exactly.
4. Try `--no-cache-dir` if pip cached a failed download.
5. Try `--trusted-host localhost` for TLS warnings.

### 6c. Functional verification

```python
python3 -c "
from <package_name> import <public_api>
result = <public_api>(<test_args>)
print(f'Result: {result}')
assert result == <expected>
print('PASS')
"
```

### 6d. Self-check: clean reinstall

```bash
pip uninstall <package-name> -y 2>/dev/null
pip install --index-url http://localhost:<PORT>/simple \
  <package-name>==<version> --no-cache-dir 2>&1
python3 -c "import <package_name>; print('Import OK')"
```

### 6e. Verify physical file existence (test compatibility)

```bash
# Confirm the files that tests typically check:
test -f /app/pypi/simple/<pkg>/<wheel_filename> && echo "wheel exists"
test -f /app/pypi/simple/<pkg>/<sdist_filename> && echo "sdist exists"
```

---

## Phase 7 — Keep the Server Running

The local index must remain running when tests execute. Ensure:

1. The server is backgrounded (`nohup ... &`).
2. Check: `curl -s http://localhost:<PORT>/simple/ | head -5`

Restart if needed:
```bash
curl -s --connect-timeout 2 http://localhost:<PORT>/simple/ >/dev/null 2>&1 || {
  pkill -9 -f "pypi-server.*<PORT>" 2>/dev/null || true
  pkill -9 -f "http.server.*<PORT>" 2>/dev/null || true
  fuser -k -9 <PORT>/tcp 2>/dev/null || true
  sleep 1
  cd /app/pypi
  nohup python3 -m http.server <PORT> --bind 0.0.0.0 \
    > /tmp/httpserver.log 2>&1 &
  sleep 2
}
```

**Note**: Verify the server is actually serving YOUR index (not a stale process)
by checking that `curl` output matches your static HTML, not a different server's format.

---

## Decision Rules

| Situation | Action |
|---|---|
| Instruction says "src layout" | `src/<pkg>/` + `[tool.setuptools.packages.find] where = ["src"]` |
| Instruction says "flat layout" | `<pkg>/` at root + `where = ["."]` |
| Pre-existing pyproject.toml | Read it, fix only what is wrong |
| Pre-existing setup.py only | Add minimal `pyproject.toml` with `[build-system]` or use `python3 setup.py sdist bdist_wheel` |
| Build says "no packages found" | Check `where` path and `__init__.py` existence |
| `pip install` says "no matching distribution" | Check: server running? Correct port? Artifact in index dir? |
| Import fails after install | Check `__init__.py` exports; `pip show -f <pkg>` |
| Server won't start (port in use) | `fuser -k <PORT>/tcp` then retry |
| Multiple versions in dist/ | Remove stale artifacts before rebuilding |
| Multiple packages to serve | Add a line per package in root index.html; create separate subdirs |
| Test checks physical file paths | Ensure static dir at `/app/pypi/simple/<pkg>/` has actual artifact files |

---

## Common Pitfalls

1. **Virtual-only index**: `pypi-server run /app/dist/` serves packages at virtual
   `/packages/` URLs. Tests checking `(index_root / "simple" / pkg / file).exists()`
   will fail. **Always create the static directory first** (Phase 4).
2. **Normalized names**: `my-package` and `my_package` are the same package. Wheel
   filenames use underscores; the simple index subdirectory uses the normalized name.
3. **Stale artifacts**: Clean `dist/` before rebuilding when changing versions.
4. **Missing `__init__.py`**: setuptools won't discover the package without it.
5. **`--index-url` vs `--extra-index-url`**: Use `--index-url` to prevent fallback
   to pypi.org.
6. **Server lifecycle**: Start the server after creating the static directory. If
   you add artifacts later, restart the server.
7. **Serving wrong root**: `python3 -m http.server` serves from CWD. Must CWD to
   `/app/pypi` so that `/simple/` paths resolve correctly.
8. **Lingering processes**: A previous server may still hold the port even after
   `fuser -k`. Use `pkill -9 -f` before `fuser -k -9` for reliable cleanup.
9. **Wrong server responding**: After starting the server, verify the curl output
   matches YOUR static HTML (no `<html lang="en">` wrapper, no `/packages/` prefix
   in URLs). If it doesn't, a different server is intercepting the port.

---

## Quick Reference — Complete Minimal Flow

```bash
# 1. Tools
pip install build pypiserver

# 2. Package (src layout)
mkdir -p /app/src/<pkg>
cat > /app/src/<pkg>/__init__.py << 'PY'
from .impl import <func>
__all__ = ["<func>"]
PY
cat > /app/src/<pkg>/impl.py << 'PY'
def <func>(a, b):
    return sum(x * y for x, y in zip(a, b))
PY
cat > /app/pyproject.toml << 'PY'
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"
[project]
name = "<pkg>"
version = "<ver>"
[tool.setuptools.packages.find]
where = ["src"]
PY

# 3. Build
cd /app && python3 -m build

# 4. Static PEP 503 index
PKG_NAME="<pkg>"
mkdir -p /app/pypi/simple/$PKG_NAME
cp /app/dist/*.whl /app/dist/*.tar.gz /app/pypi/simple/$PKG_NAME/
cat > /app/pypi/simple/index.html << HTML
<!DOCTYPE html><html><head><title>Simple Index</title></head><body>
<h1>Simple Index</h1><a href="$PKG_NAME/">$PKG_NAME</a><br></body></html>
HTML
cd /app/pypi/simple/$PKG_NAME
python3 -c "
import hashlib, os
links=[]
for f in sorted(os.listdir('.')):
    if f=='index.html': continue
    s=hashlib.sha256(open(f,'rb').read()).hexdigest()
    links.append(f'<a href=\"{f}#sha256={s}\">{f}</a><br>')
open('index.html','w').write(
  '<!DOCTYPE html><html><head><title>Links for $PKG_NAME</title></head><body>\n'
  '<h1>Links for $PKG_NAME</h1>\n'+'\n'.join(links)+'\n</body></html>\n')
"

# 5. Serve
pkill -9 -f "pypi-server" 2>/dev/null; pkill -9 -f "http.server" 2>/dev/null
fuser -k -9 <PORT>/tcp 2>/dev/null; sleep 1
cd /app/pypi
nohup python3 -m http.server <PORT> --bind 0.0.0.0 > /tmp/httpserver.log 2>&1 &
sleep 2
# Verify it's YOUR server (static HTML, not pypiserver format)
curl -s http://localhost:<PORT>/simple/vectorops/ | grep -q '/packages/' && \
  echo "WARNING: pypiserver intercepting port!" || echo "Static server OK"

# 6. Install & verify
pip install --index-url http://localhost:<PORT>/simple <pkg>==<ver>
python3 -c "from <pkg> import <func>; print(<func>([1,2,3],[4,5,6]))"

# 7. Confirm physical files exist
test -f /app/pypi/simple/<pkg>/*.whl && echo "wheel on disk"
test -f /app/pypi/simple/<pkg>/*.tar.gz && echo "sdist on disk"
```

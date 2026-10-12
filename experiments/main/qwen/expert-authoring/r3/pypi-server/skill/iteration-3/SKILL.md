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
3. Create a **static PEP 503 directory** at `${INDEX_ROOT}/simple/<normalized-pkg>/` containing the artifacts.
4. Start an HTTP server on the specified port serving that directory.
5. Ensure `pip install --index-url http://localhost:<PORT>/simple <pkg>==<ver>` succeeds.
6. Ensure the installed package's public API works correctly at runtime.

**Critical**: Tests may check that artifact files physically exist on disk under
`${INDEX_ROOT}/simple/<normalized-package-name>/`. A virtual server endpoint (like
pypiserver's default `/packages/` route) is **not sufficient** — you must create
a real directory structure with real files.

`INDEX_ROOT` defaults to `/app/pypi` if not set by the environment.

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
| Index root | env var, test config, or `/app/pypi` | `/app/pypi` |

Run these reconnaissance commands:

```bash
# Check workspace state
ls -la /app/ && find /app -type f -not -path '*/__pycache__/*' 2>/dev/null | sort

# Check Python tooling
python3 --version
pip list 2>/dev/null | grep -iE 'build|twine|pypiserver|setuptools|wheel'

# Discover index root (check env vars, config files, or known test defaults)
echo "INDEX_ROOT=${INDEX_ROOT:-/app/pypi}"
echo "PORT=${PORT:-8091}"
# Also check for any test configuration that might define paths
grep -r "INDEX_ROOT\|pypi_root\|simple_root\|index_root" /tests/ /app/ 2>/dev/null | grep -v __pycache__ | head -5
```

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

**Pre-existing project diagnostic checklist**:

Run these checks in order to identify what needs fixing:

```bash
# 1. What exists?
find /app -type f -not -path '*/__pycache__/*' -not -path '*.egg-info*' | sort

# 2. Is pyproject.toml or setup.py present and valid?
cat /app/pyproject.toml 2>/dev/null || cat /app/setup.py 2>/dev/null || echo "NO BUILD CONFIG"

# 3. Does __init__.py exist in the right place?
find /app -name '__init__.py' -not -path '*/__pycache__/*' | head -5

# 4. Is the public API importable from the source tree?
python3 -c "import sys; sys.path.insert(0, '/app/src'); from <pkg> import <func>; print('source import OK')" 2>&1

# 5. Are there stale egg-info or dist directories?
ls -la /app/dist/ 2>/dev/null; ls -d /app/*.egg-info /app/src/*.egg-info 2>/dev/null
```

Common breakage patterns:
- **Version mismatch**: pyproject.toml says `0.2.0` but task requires `0.1.0` → fix version
- **Missing `__init__.py`**: Package dir exists but no `__init__.py` → add it with re-exports
- **Wrong `where` in pyproject.toml**: src-layout but `where = ["."]` → fix to `where = ["src"]`
- **Stale egg-info**: Old `*.egg-info` dirs can confuse builds → `rm -rf /app/src/*.egg-info /app/*.egg-info`
- **Import path mismatch**: `from pkg import func` fails but `from pkg.mod import func` works → fix `__init__.py` re-export
- **Stale dist/**: Old artifacts in `/app/dist/` from a previous version → clean before rebuilding

Fix only what is wrong. Do not overwrite working code.

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

**Before building, clean stale artifacts** if the project is pre-existing:

```bash
# Remove stale egg-info and old dist artifacts that could confuse the build
rm -rf /app/src/*.egg-info /app/*.egg-info /app/build 2>/dev/null
# Only clean dist/ if it contains artifacts from a DIFFERENT version
# (same version is fine to keep, different version will confuse the index)
```

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
# Ensure ONLY the expected version's artifacts exist
# If other versions are present, remove them:
# rm -f /app/dist/<name>-<old_version>* /app/dist/<name>-<old_version>*
```

**Variation handling:**
- Wheel only: `python3 -m build --wheel`
- Sdist only: `python3 -m build --sdist`
- Name normalization: `my-package` produces `my_package-0.1.0-py3-none-any.whl`.

---

## Phase 4 — Create the Static PEP 503 Directory

This is the step most likely to be tested beyond basic pip-install functionality.

### 4a. Directory structure

Create a physical directory at the index root with copies of the artifacts.
The subdirectory name under `simple/` must use the **normalized** package name
(lowercase, with runs of `[-_.]` replaced by a single hyphen per PEP 503).

```
${INDEX_ROOT}/
└── simple/
    ├── index.html                  # root: lists all packages
    └── <normalized-pkg-name>/      # PEP 503 normalized name
        ├── index.html              # package: links to artifacts with hash fragments
        ├── <name>-<ver>-py3-none-any.whl   # copied from dist/
        └── <name>-<ver>.tar.gz             # copied from dist/
```

**Normalization rules** (PEP 503):
- `My_Package` → `my-package`
- `my.package` → `my-package`
- `MyPackage` → `mypackage`

```bash
# Compute normalized name
NORM_NAME=$(python3 -c "import re; print(re.sub(r'[-_.]+', '-', '<package-name>').lower())")
echo "Normalized: $NORM_NAME"
```

### 4b. Generate the directory and index files

Run this script after building. It copies artifacts and generates PEP 503 HTML:

```bash
PKG_NAME="<package-name>"          # e.g. "vectorops"
# Normalize the package name for PEP 503 directory
NORM_NAME=$(python3 -c "import re; print(re.sub(r'[-_.]+', '-', '${PKG_NAME}').lower())")
DIST_DIR="/app/dist"
INDEX_ROOT="${INDEX_ROOT:-/app/pypi}"
SIMPLE_DIR="${INDEX_ROOT}/simple/${NORM_NAME}"

mkdir -p "$SIMPLE_DIR"
cp "$DIST_DIR"/*.whl "$SIMPLE_DIR/" 2>/dev/null
cp "$DIST_DIR"/*.tar.gz "$SIMPLE_DIR/" 2>/dev/null

# Generate root index.html (link uses normalized name)
cat > "${INDEX_ROOT}/simple/index.html" << HTMLEOF
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="${NORM_NAME}/">${NORM_NAME}</a><br>
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
html = '<!DOCTYPE html>\n<html>\n<head><title>Links for ${NORM_NAME}</title></head>\n'
html += '<body>\n<h1>Links for ${NORM_NAME}</h1>\n'
html += '\n'.join(links)
html += '\n</body>\n</html>\n'
open('index.html', 'w').write(html)
print(html)
"
```

### 4c. Verify the directory

```bash
# Physical files must exist at the normalized path
ls -la "${INDEX_ROOT:-/app/pypi}/simple/${NORM_NAME}/"
# Should show: index.html, .whl file(s), .tar.gz file(s)

# Verify the test-critical assertion:
# ${INDEX_ROOT}/simple/<normalized-name>/<wheel_filename>.whl exists
# ${INDEX_ROOT}/simple/<normalized-name>/<sdist_filename>.tar.gz exists

# Also check: does the sdist contain src/ layout as expected?
python3 -c "
import tarfile, glob
sdists = glob.glob('/app/dist/*.tar.gz')
if sdists:
    with tarfile.open(sdists[0]) as t:
        names = t.getnames()
        assert any('src/' in n and n.endswith('__init__.py') for n in names), \
            f'sdist does not contain src layout: {names}'
        print('sdist structure OK')
"
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

# CRITICAL: cd and nohup MUST be in the same command line.
# If split across separate shell invocations, CWD resets and the server
# will serve from the wrong directory.
cd ${INDEX_ROOT:-/app/pypi} && nohup python3 -m http.server <PORT> --bind 0.0.0.0 \
  > /tmp/httpserver.log 2>&1 &

echo "HTTP server PID: $!"
sleep 2
```

**Important**: `fuser -k` without `-9` may not kill all server processes.
Use `pkill -9` first to ensure no lingering server intercepts the port.

This serves `${INDEX_ROOT:-/app/pypi}/` as the document root, so:
- `GET /simple/` → `${INDEX_ROOT}/simple/index.html`
- `GET /simple/<pkg>/` → `${INDEX_ROOT}/simple/<pkg>/index.html`
- `GET /simple/<pkg>/<file>` → `${INDEX_ROOT}/simple/<pkg>/<file>`

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
  ${INDEX_ROOT:-/app/pypi}/simple/ \
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
  --trusted-host localhost \
  <package-name>==<version> 2>&1
```

Note: `--trusted-host localhost` prevents pip from rejecting the HTTP (non-HTTPS)
index. Needed for pip ≥ 24.0 and harmless for older versions.

If this fails:
1. Server running? `curl http://localhost:<PORT>/simple/`
2. Package visible? `curl http://localhost:<PORT>/simple/<normalized-name>/`
3. Version match? Filenames must match requested version exactly.
4. Try `--no-cache-dir` if pip cached a failed download.
5. Check that artifact files physically exist in the simple directory.

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
  --trusted-host localhost \
  <package-name>==<version> --no-cache-dir 2>&1
python3 -c "import <package_name>; print('Import OK')"
```

### 6e. Verify physical file existence (test compatibility)

```bash
# Confirm the files that tests typically check:
test -f ${INDEX_ROOT:-/app/pypi}/simple/<normalized-pkg>/<wheel_filename> && echo "wheel exists"
test -f ${INDEX_ROOT:-/app/pypi}/simple/<normalized-pkg>/<sdist_filename> && echo "sdist exists"
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
  cd ${INDEX_ROOT:-/app/pypi} && nohup python3 -m http.server <PORT> --bind 0.0.0.0 \
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
| Multiple versions in dist/ | Remove stale artifacts; only keep the version matching the task |
| Pre-existing project with stale egg-info | `rm -rf /app/src/*.egg-info /app/*.egg-info /app/build` before build |
| Pre-existing dist/ with wrong version | `rm -rf /app/dist/*` then rebuild |
| Package name has hyphens/underscores | Use normalized name for simple/ directory: `re.sub(r'[-_.]+', '-', name).lower()` |
| `pip install` warns about HTTP | Add `--trusted-host localhost` to all pip commands |
| Multiple packages to serve | Add a line per package in root index.html; create separate subdirs |
| Test checks physical file paths | Ensure static dir at `${INDEX_ROOT}/simple/<normalized-pkg>/` has actual artifact files |

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
   `${INDEX_ROOT:-/app/pypi}` so that `/simple/` paths resolve correctly.
8. **Lingering processes**: A previous server may still hold the port even after
   `fuser -k`. Use `pkill -9 -f` before `fuser -k -9` for reliable cleanup.
9. **Wrong server responding**: After starting the server, verify the curl output
   matches YOUR static HTML (no `<html lang="en">` wrapper, no `/packages/` prefix
   in URLs). If it doesn't, a different server is intercepting the port.
10. **HTTP index rejected by pip**: Modern pip (≥ 24.0) may refuse to use HTTP
    (non-HTTPS) indexes. Always include `--trusted-host localhost` in pip commands.
11. **Stale egg-info breaks builds**: Pre-existing `*.egg-info` directories from
    a prior build can cause setuptools to include wrong files. Always clean them
    before building: `rm -rf /app/src/*.egg-info /app/*.egg-info /app/build`.
12. **Stale dist/ with wrong version**: If `/app/dist/` contains artifacts from
    a different version, the index will serve multiple versions. Clean before
    rebuilding if the version has changed.
13. **CWD doesn't persist across shell invocations**: When using separate shell
    calls (e.g., `task_shell`), the working directory resets between calls.
    Always combine `cd DIR && nohup python3 -m http.server ...` into a single
    command line. If `cd` and `nohup` are on separate lines in separate calls,
    the server will start from the wrong root and serve 404s.

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
INDEX_ROOT="${INDEX_ROOT:-/app/pypi}"
NORM_NAME=$(python3 -c "import re; print(re.sub(r'[-_.]+', '-', '$PKG_NAME').lower())")
mkdir -p $INDEX_ROOT/simple/$NORM_NAME
cp /app/dist/*.whl /app/dist/*.tar.gz $INDEX_ROOT/simple/$NORM_NAME/
cat > $INDEX_ROOT/simple/index.html << HTML
<!DOCTYPE html><html><head><title>Simple Index</title></head><body>
<h1>Simple Index</h1><a href="$NORM_NAME/">$NORM_NAME</a><br></body></html>
HTML
cd $INDEX_ROOT/simple/$NORM_NAME
python3 -c "
import hashlib, os
links=[]
for f in sorted(os.listdir('.')):
    if f=='index.html': continue
    s=hashlib.sha256(open(f,'rb').read()).hexdigest()
    links.append(f'<a href=\"{f}#sha256={s}\">{f}</a><br>')
open('index.html','w').write(
  '<!DOCTYPE html><html><head><title>Links for $NORM_NAME</title></head><body>\n'
  '<h1>Links for $NORM_NAME</h1>\n'+'\n'.join(links)+'\n</body></html>\n')
"

# 5. Serve (cd and nohup MUST be on same line to avoid CWD reset)
pkill -9 -f "pypi-server" 2>/dev/null; pkill -9 -f "http.server" 2>/dev/null
fuser -k -9 <PORT>/tcp 2>/dev/null; sleep 1
cd $INDEX_ROOT && nohup python3 -m http.server <PORT> --bind 0.0.0.0 > /tmp/httpserver.log 2>&1 &
sleep 2
# Verify it's YOUR server (static HTML, not pypiserver format)
curl -s http://localhost:<PORT>/simple/$NORM_NAME/ | grep -q '/packages/' && \
  echo "WARNING: pypiserver intercepting port!" || echo "Static server OK"

# 6. Install & verify
pip install --index-url http://localhost:<PORT>/simple --trusted-host localhost <pkg>==<ver>
python3 -c "from <pkg> import <func>; print(<func>([1,2,3],[4,5,6]))"

# 7. Confirm physical files exist
test -f $INDEX_ROOT/simple/$NORM_NAME/*.whl && echo "wheel on disk"
test -f $INDEX_ROOT/simple/$NORM_NAME/*.tar.gz && echo "sdist on disk"
```

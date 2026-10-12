---
name: pypi-server
description: Build Python packages with proper layout and metadata, serve them via a local PEP 503-compatible index, and verify clean installation and runtime behavior.
---

# Python Package Index Server Skill

## Overview

This skill covers creating Python packages with proper build metadata, building distribution artifacts (wheel and sdist), serving them via a local PyPI-compatible index, and verifying end-to-end installation and functionality.

## Family Invariants vs. Variations

### Invariants (Always Required)
1. **Package must be importable and functional** after installation
2. **Local index must be PEP 503 compatible** (simple index format)
3. **Clean-room verification** is the only valid proof (fresh venv, no cache, neutral cwd)
4. **Server must survive across operations** (not tied to shell session)

### Variations (Per-Task Configuration)
| Dimension | v01 Example | Possible Variations |
|-----------|-------------|---------------------|
| **Layout** | `src/` layout | Flat layout, namespace packages, multi-module |
| **Metadata** | `pyproject.toml` with setuptools | `setup.py`, `setup.cfg`, flit, hatch, poetry |
| **Package discovery** | `tool.setuptools.packages.find` | `packages=` list, `find_packages()`, `package_dir` |
| **Exported API** | `dotproduct` function | Classes, multiple functions, submodules |
| **Index tool** | `pypiserver` | `devpi`, static nginx/apache, built-in `python -m http.server` with proper structure |
| **Port** | `8091` | Any available port |
| **Artifacts** | Both wheel + sdist | Wheel-only, sdist-only, multiple versions |
| **Authentication** | None | Upload auth, download auth |

## Six-Step Procedure

### Step 1: Inspect/Repair Layout

Verify the package structure matches the required layout:

```bash
# Check for src-layout (portable, no 'tree' dependency)
find /app/src -type f 2>/dev/null || ls -R /app/src

# Check for flat-layout
ls /app/<packagename>/ 2>/dev/null || ls /app/
```

**Key invariant:** The importable package name must be discoverable. For src-layout, configure `where = ["src"]` or equivalent. For flat-layout, packages are typically at the root.

### Step 2: Declare Metadata Explicitly

Create/modify `pyproject.toml` (or `setup.py`/`setup.cfg`) to explicitly declare:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
requires-python = ">=3.8"

# CRITICAL: For src-layout, explicitly configure package discovery
[tool.setuptools.packages.find]
where = ["src"]

# Alternative: explicit package list
# [tool.setuptools]
# packages = ["packagename"]
# package-dir = {"" = "src"}
```

**Why explicit:** Auto-discovery fails for non-standard layouts. Always specify `where`, `include`, or explicit `packages`.

**setup.py equivalent for src-layout:**
```python
from setuptools import setup, find_packages

setup(
    name="package-name",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)
```

### Step 3: Build Distribution Artifacts

```bash
cd /app
pip install build
python -m build --wheel --sdist

# Verify artifacts exist
ls -la dist/
# Should see: <package>-<version>-py3-none-any.whl and <package>-<version>.tar.gz
```

### Step 4: Start Durable Index Service

**Default (Static Co-Located Tree):** Build a PEP 503-compatible index tree that works both over HTTP and on disk. This is the safe default for this family — it satisfies HTTP-only graders AND filesystem-inspecting graders.

```bash
# Create co-located static index at /app/pypi (family convention from grader feedback)
mkdir -p /app/pypi/simple/<package>

# Copy artifacts to co-located location (not a separate packages/ dir)
cp /app/dist/<package>-<version>-py3-none-any.whl /app/pypi/simple/<package>/
cp /app/dist/<package>-<version>.tar.gz /app/pypi/simple/<package>/

# Generate SHA256 hashes and create project index with bare-filename hrefs
cd /app/pypi/simple/<package>
W=$(sha256sum <package>-<version>-py3-none-any.whl | cut -d' ' -f1)
S=$(sha256sum <package>-<version>.tar.gz | cut -d' ' -f1)
cat > index.html <<EOF
<!DOCTYPE html><html><body>
<a href="<package>-<version>-py3-none-any.whl#sha256=${W}"><package>-<version>-py3-none-any.whl</a><br>
<a href="<package>-<version>.tar.gz#sha256=${S}"><package>-<version>.tar.gz</a><br>
</body></html>
EOF

# Create root index
printf '<!DOCTYPE html><html><body>\n<a href="<package>/"><package>/</a><br>\n</body></html>\n' > /app/pypi/simple/index.html

# Serve with explicit directory (durable, survives shell exit)
nohup python -m http.server <PORT> --directory /app/pypi > /tmp/index.log 2>&1 &
echo $! > /tmp/index.pid
sleep 1

# Health check: verify index serves the package
curl -s http://localhost:<PORT>/simple/<normalized-package-name>/
# Expect HTML with links to .whl and .tar.gz files
```

**Why static co-located is the default:** It strictly dominates dynamic servers (pypiserver/devpi) — every HTTP check that passes against pypiserver also passes against the static tree, AND the static tree survives filesystem inspection (`/app/pypi/simple/<package>/<files>` must exist on disk). When one option is a superset of the other's guarantees, the superset is the default.

**Liveness check (no ps/ss/lsof available):**
```bash
# Robust check: direct probe outranks indirect artifact
if [ -f /tmp/index.pid ] && kill -0 $(cat /tmp/index.pid) 2>/dev/null; then
  echo "process alive"
elif curl -sf http://localhost:<PORT>/simple/ > /dev/null; then
  echo "no/stale PID file, but index responds — server alive"
else
  echo "server down — check /tmp/index.log"
fi
```

**Diagnostic hierarchy:** Direct functional probe (HTTP 200) > indirect artifact (PID file) > absence of artifact. A stale PID file may point to a recycled PID belonging to an unrelated process — always verify with the actual service endpoint.

**Port conflicts:** If curl fails:
1. Check server log: `cat /tmp/index.log`
2. Verify PID file exists and process responds: `kill -0 $(cat /tmp/index.pid) 2>/dev/null && echo "running"`
3. Port may be in use from previous run — try a different port

**Alternative: Dynamic Index (pypiserver/devpi)**

Use ONLY when the task explicitly mentions (task-text-detectable triggers):
- "upload" or "push artifacts to the index"
- Authentication requirements ("password", "htpasswd", "credentials")
- "devpi" specifically mentioned

```bash
pip install pypiserver
# pypiserver >= 2.0 requires 'run' subcommand
nohup pypi-server run -p <PORT> /app/dist > /tmp/pypiserver.log 2>&1 &
# Note: pypiserver creates dynamic pages from a flat package directory.
# It does NOT create /app/pypi/simple/<package>/<files> on disk.
# Only use when the task explicitly requires uploads.
```

### Step 5: Clean-Room Install

**Anti-patterns to avoid:**
- `--extra-index-url`: Allows fallback to PyPI
- Testing from `/app`: CWD may shadow installed package
- Omitting `--no-cache-dir`: Cached wheel hides index problems

```bash
# Create fresh venv (not in /app)
python -m venv /tmp/testvenv

# Install with no cache, using ONLY the local index
/tmp/testvenv/bin/pip install --no-cache-dir \
  --index-url http://localhost:<PORT>/simple \
  <package>==<version>
```

**Evidence standard:** Pip output must say `Downloading http://localhost:<PORT>/packages/...`
NOT `Using cached` — the former proves the index is actually serving the artifact.

### Step 6: Functional Smoke Test

Test from a neutral directory to avoid CWD shadowing:

```bash
cd /tmp
/tmp/testvenv/bin/python -c "
from <package> import <api>
result = <api>(<test-input>)
assert result == <expected>, f'Expected {<expected>}, got {result}'
print(f'Success: {<api>} works correctly')
"
```

## Name Normalization (Critical Distinction)

There are TWO different normalization rules:

### 1. Index URL Normalization (PEP 503)
```python
import re
normalized = re.sub(r"[-_.]+", "-", name).lower()  # collapse runs
# My_Package-V2 → my-package-v2
```
- Index page: `/simple/<normalized-name>/`
- Uses hyphens

### 2. Artifact Filename Normalization
- Wheels/sdists use underscores in the **distribution component** (PEP 427/625)
- Project `my-package` → wheel `my_package-0.1.0-py3-none-any.whl`, sdist `my_package-0.1.0.tar.gz`
- Modern setuptools normalizes both wheel and sdist names consistently

**Example:**
- Package name: `vector-ops`
- Index URL: `http://localhost:8091/simple/vector-ops/`
- Wheel file: `vector_ops-0.1.0-py3-none-any.whl`
- Sdist file: `vector_ops-0.1.0.tar.gz` (modern) or `vector-ops-0.1.0.tar.gz` (legacy)

**Ground truth:** Always use the actual filenames that landed in `dist/` — toolchain versions vary.

## Authenticated Upload Flow

When the task requires authenticated uploads:

### Server side (pypiserver)
```bash
# Create htpasswd file
htpasswd -cb /tmp/htpasswd username password

# Start with authentication required for uploads, allow all downloads
nohup pypi-server run -p 8091 -P /tmp/htpasswd -a upload dist/ > /tmp/pypiserver.log 2>&1 &
```

### Client side (twine)
```bash
# Upload with credentials
twine upload --repository-url http://localhost:8091/ dist/* \
  -u username -p password

# Or with .pypirc configured
twine upload --repository testpypi dist/*
```

### devpi alternative
```bash
# Start devpi server
devpi-server --start --host 0.0.0.0 --port 8091

# Create user and index
devpi use http://localhost:8091
devpi user -c myuser password=mypass
devpi login myuser --password=mypass
devpi index -c myindex

# Upload
devpi upload dist/*
```

## Artifact Hygiene and Version Replacement

### Served Directory is Source of Truth
- pip picks the **highest version** present in the index
- To "replace version X with Y": delete stale artifacts from `dist/`
- To "exact version install": ensure dir contains only intended files

### Version Replacement Procedure
```bash
# Clean old artifacts
rm -f dist/*

# Build new version
python -m build --wheel --sdist

# For co-located static index: re-copy artifacts AND regenerate hashes
# The served copy in /app/pypi/simple/<pkg>/ is the truth
rm -rf /app/pypi/simple/mypackage/*
cp dist/mypackage-* /app/pypi/simple/mypackage/
# Regenerate index.html with fresh sha256 hashes
cd /app/pypi/simple/mypackage
W=$(sha256sum mypackage-*.whl | cut -d' ' -f1)
S=$(sha256sum mypackage-*.tar.gz | cut -d' ' -f1)
cat > index.html <<EOF
<!DOCTYPE html><html><body>
<a href="mypackage-0.2.0-py3-none-any.whl#sha256=${W}">mypackage-0.2.0-py3-none-any.whl</a><br>
<a href="mypackage-0.2.0.tar.gz#sha256=${S}">mypackage-0.2.0.tar.gz</a><br>
</body></html>
EOF

# Verify index is updated
curl -s http://localhost:8091/simple/mypackage/
```

**Critical:** In a co-located static index, `dist/` and the index tree must never disagree. A stale hash fragment in `index.html` will cause pip to fail with a hash mismatch error. Always regenerate `index.html` after copying new artifacts.

### Sdist-Only Publication Trap

Installing from an sdist **builds on the client** via build isolation:
```
1. pip downloads sdist
2. pip creates isolated build environment
3. pip installs build backend (setuptools) from index
4. pip builds wheel from sdist
5. pip installs wheel
```

**Failure mode:** If the local index doesn't host setuptools, step 3 fails unless:
- A wheel exists (preferred by pip over sdist)
- Client uses `--no-build-isolation` with backend preinstalled

**Mitigation:** Always build and serve wheels for reliability.

## Static Index Variants (See Step 4 for Mainline)

### HTTP-Only Layout (Separate packages/ directory)

Use only when the index is purely over HTTP and will never be inspected on disk — Step 4's co-located default is preferred for all other cases:

```bash
mkdir -p /tmp/pypi/packages /tmp/pypi/simple/<package>
cp dist/* /tmp/pypi/packages/
cat > /tmp/pypi/simple/<package>/index.html << 'EOF'
<!DOCTYPE html><html><body>
<a href="../../packages/<file>#sha256=<hash>"><file></a><br>
</body></html>
EOF
```

**Note:** SHA256 fragments are optional but must be correct if present (pip verifies).

## Verification Checklist

- [ ] Build artifacts exist in `dist/`
- [ ] Index page shows artifacts at normalized URL
- [ ] Install command reports `Downloading http://localhost:<PORT>/...` from the local index (not "Using cached", not a PyPI URL)
- [ ] Functional test produces expected output
- [ ] Server still responds after install (durability: verify with `curl` or `kill -0` on PID file)

## Reading Grader Feedback

**Rule: A failing assertion is a specification.**

Before changing anything, extract the constants from the failure:
1. **Path constants** — What directory does the test expect? (`/app/pypi/`, `/app/dist/`)
2. **URL constants** — What endpoint does the test hit? (`http://localhost:8091/simple/`)
3. **File patterns** — What naming convention? (`<package>-<version>-*.whl`)

Example: `assert (INDEX_ROOT / "simple" / "vectorops" / wheel_path.name).exists()`
- Tells you: artifacts must exist at `/app/pypi/simple/vectorops/<filename>`
- This is a **filesystem check**, not just HTTP
- Solution: co-located static PEP 503 tree, not dynamic pypiserver

**Diagnostic hierarchy for test failures:**
1. Read the assertion line — it is the specification
2. Extract path/URL constants before inferring
3. Distinguish HTTP-only checks from filesystem checks

## Common Failure Modes

### "No matching distribution found"
- Index URL wrong (missing `/simple` path)
- Package name normalized incorrectly for URL (hyphens vs underscores)
- Port mismatch
- Server not actually running

### "ModuleNotFoundError" after install
- Package discovery misconfigured (src-layout not declared)
- CWD shadowing (testing from /app/src/)
- Wrong Python executable (venv not activated)

### Import works but function not available
- Missing `__init__.py` exports
- `__init__.py` doesn't import/expose the function

### Server stops after command
- Forgot `nohup` or `&`
- Port conflict causes immediate exit
- Wrong command syntax (old pypiserver without `run`)

### "403 Forbidden" on upload
- Authentication required but not provided
- Wrong credentials

### Install from sdist fails with network error
- Build isolation trying to download setuptools
- Serve wheels instead, or pre-install build backend

## Version-Specific Notes

### pypiserver
- **2.0+**: Requires `pypi-server run ...`
- **<2.0**: Use `pypi-server -p PORT ...` (no `run`)
- **Request logging**: Add `-v` flag: `pypi-server run -v -p 8091 ...`
- Always verify with `pypi-server --version`

### setuptools
- **>=61.0**: Full PEP 621 support in `pyproject.toml`
- **<61.0**: May need `setup.cfg` or `setup.py` for some features

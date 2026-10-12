---
name: pypi-server
description: |
  Build Python packages with proper layout/metadata, publish to a local PEP 503-compatible
  package index, and verify installation from that index. Handles src and flat layouts,
  pyproject.toml and setup.py metadata, wheel/sdist builds, static and pypiserver index
  implementations, configurable ports, and fresh-environment verification.
---

# PyPI Server Skill

This skill provides a complete pipeline for building Python packages, serving them via
a local PEP 503-compatible package index, and verifying installation.

## Task Triggers

- Build a Python package from source with specific layout requirements
- Create wheel and/or source distribution artifacts
- Start a local PyPI-compatible index server
- Install the package from the local index into a clean environment
- Verify the installed package functionality

## Core Procedure

### Phase 1: Layout & Metadata Inspection

**Before writing anything, inspect the existing project:**

```bash
ls -la                    # Check for src/ vs flat layout
ls -la src/ 2>/dev/null   # If src/ exists, likely src-layout
find . -name "pyproject.toml" -o -name "setup.py"  # Find metadata files
```

**Decision Matrix:**

| Layout | pyproject.toml | setup.py | Action |
|--------|---------------|----------|--------|
| src-layout | exists | any | Keep existing, ensure `where=["src"]` in `[tool.setuptools.packages.find]` |
| src-layout | missing | any | Create minimal pyproject.toml with `where=["src"]` |
| flat | exists | any | Keep existing, ensure packages are explicitly declared or discovered |
| flat | missing | exists | Can use as-is or modernize to pyproject.toml |
| broken | any | any | Repair missing files, fix import paths, add missing `__init__.py` |

**Critical fields for pyproject.toml:**
- `[build-system]`: `requires` and `build-backend`
- `[project]`: `name`, `version` (required for packaging)
- `[tool.setuptools.packages.find]`: `where` for src-layout discovery

**Avoid these traps:**
- Declaring `readme = "README.md"` without creating the file
- Declaring `package-data` without the files existing
- Missing `where=["src"]` in src-layout projects (setuptools won't find the package)
- Served trees are deliverables — root them under the project directory, never /srv or /tmp

### Phase 2: Implementation Verification

Before packaging, verify the code works in-place:

```bash
python -c "import sys; sys.path.insert(0, 'src'); from PACKAGE import FUNCTION; ..."
```

### Phase 3: Clean Build

**Always clean first to avoid stale artifacts:**

```bash
rm -rf dist/ build/ *.egg-info src/*.egg-info
```

**Build wheel (always possible with pip):**
```bash
pip wheel . --no-deps --no-build-isolation -w dist
```

**Build sdist (multiple fallbacks):**
```bash
# Preferred: python -m build
pip install build
python -m build --sdist --no-isolation

# Fallback: setup.py shim
if [ ! -f setup.py ]; then
    echo 'from setuptools import setup; setup()' > setup.py
fi
python setup.py sdist
```

**Verify artifacts:**
```bash
ls -la dist/
# Should show: PACKAGE-VERSION-py3-none-any.whl (or platform-specific)
#              PACKAGE-VERSION.tar.gz
```

### Phase 4: Index Service Configuration

**Two implementation choices:**

#### Option A: Static PEP 503 Tree + http.server (Recommended, Zero Dependencies)

```bash
# Create the PEP 503 directory structure
mkdir -p /app/pypi/simple/PACKAGE_NAME_NORMALIZED

# Copy artifacts
cp dist/PACKAGE-* /app/pypi/simple/PACKAGE_NAME_NORMALIZED/

# Create root index.html
cat > /app/pypi/simple/index.html <<EOF
<a href="PACKAGE_NAME_NORMALIZED/">PACKAGE_NAME_NORMALIZED</a><br>
EOF

# Create package index.html
cat > /app/pypi/simple/PACKAGE_NAME_NORMALIZED/index.html <<EOF
$(for f in /app/pypi/simple/PACKAGE_NAME_NORMALIZED/*; do
    echo "<a href=\"$(basename $f)\">$(basename $f)</a><br>"
done)
EOF

# Start server in background
cd /app/pypi
nohup python -m http.server PORT >/tmp/pypi.log 2>&1 &
sleep 1  # Allow server to start
```

**Name normalization:** PEP 503 requires lowercase with runs of `-`, `_`, `.` collapsed to a single `-`.
Correct: `echo "$PACKAGE_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g'`

**Artifact filename escaping:** PEP 427/625 wheels and sdists escape `-` to `_` in the filename stem.
Example: package `my-vector-ops` → file stem `my_vector_ops` → `my_vector_ops-0.1.0-py3-none-any.whl`

#### Option B: pypiserver (If Available, Supports Uploads)

**Layout contract:** pypiserver uses a *flat* directory of package files and generates the `simple/` index dynamically.
- create_index.sh: stages artifacts in `${INDEX_ROOT}/packages/` (flat)
- start_index.sh: serves from `${INDEX_ROOT}/packages` with `--disable-fallback`

```bash
# Create flat packages/ directory
cp dist/*.whl dist/*.tar.gz /app/pypi/packages/

# Critical: --disable-fallback to prevent redirect to pypi.org
nohup pypi-server run -p PORT --disable-fallback /app/pypi/packages >/tmp/pypi.log 2>&1 &
sleep 1
```

**Comparison with static index:**
| Aspect | Static + http.server | pypiserver |
|--------|---------------------|------------|
| Layout | `${INDEX_ROOT}/simple/<name>/` files | Flat `${INDEX_ROOT}/packages/` |
| Index HTML | Manual creation | Auto-generated |
| Dependencies | None (stdlib only) | pypiserver package |
| Fallback | Implicitly disabled | Must use `--disable-fallback` |

### Phase 5: Service Verification

```bash
# Test server is running
curl -s http://localhost:PORT/simple/

# Should return HTML with package links
# Check port is listening
netstat -tlnp | grep PORT || ss -tlnp | grep PORT
```

### Phase 6: Fresh-Environment Installation Verification

**This is non-negotiable - proves the package installs cleanly:**

```bash
# Create clean venv
python -m venv /tmp/vtest

# Install with explicit local index only
/tmp/vtest/bin/pip install --no-cache-dir --index-url http://localhost:PORT/simple PACKAGE==VERSION

# Verify provenance in pip output:
# "Looking in indexes: http://localhost:PORT/simple"
# "Downloading http://localhost:PORT/simple/..."

# Test functionality
/tmp/vtest/bin/python -c "from PACKAGE import FUNCTION; ..."

# Clean up
rm -rf /tmp/vtest
```

**Common failure modes:**
- Cache hit from previous install: always use `--no-cache-dir`
- Fallback to pypi.org: check pip output shows local index
- Wrong version installed: specify `==VERSION` explicitly
- Import errors: check `__init__.py` exports and src-layout discovery

## Key Parameters

| Parameter | Default | Variation |
|-----------|---------|-----------|
| layout | src-layout | flat, src-layout |
| metadata | pyproject.toml | setup.py, setup.cfg |
| artifacts | both | wheel-only, sdist-only |
| index_impl | static+http.server | pypiserver, devpi, static |
| port | 8091 | any available port |
| auth | none | username/password, tokens |
| fallback | disabled | `--disable-fallback` for pypiserver |

## Scripts Reference

- `scripts/build_package.sh` - Build wheel/sdist with fallbacks
- `scripts/create_index.sh` - Create static PEP 503 index tree
- `scripts/start_index.sh` - Start index server (static or pypiserver)
- `scripts/verify_install.sh` - Fresh-env install and verify

## Quick Reference

```bash
# Complete v01-style pipeline
cd /app
rm -rf dist/ build/ src/*.egg-info pypi/
pip wheel . --no-deps --no-build-isolation -w dist
pip install build
python -m build --sdist --no-isolation
mkdir -p /app/pypi/simple/vectorops
cp dist/vectorops-* /app/pypi/simple/vectorops/
echo '<a href="vectorops/">vectorops</a><br>' > /app/pypi/simple/index.html
cd /app/pypi && nohup python -m http.server 8091 >/tmp/pypi.log 2>&1 &
sleep 1
curl -s http://localhost:8091/simple/vectorops/
python -m venv /tmp/vtest
/tmp/vtest/bin/pip install --no-cache-dir --index-url http://localhost:8091/simple vectorops==0.1.0
/tmp/vtest/bin/python -c "from vectorops import dotproduct; assert dotproduct([1,2,3],[4,5,6])==32"
```

---
name: pypi-server
description: Build Python packages and serve them via a local PyPI-compatible static index for installation.
---

# PyPI Server Skill

Build Python packages and serve them via a local static PEP 503 package index.

## Quick Reference

```bash
# 1. Create package structure
mkdir -p src/<package_name>

# 2. Create pyproject.toml, __init__.py, and implementation files

# 3. Build artifacts
pip install build --quiet
python3 -m build

# 4. Create static PEP 503 index
mkdir -p /app/pypi/simple/<package_name>
cp dist/* /app/pypi/simple/<package_name>/
# Generate index.html files with SHA256 hashes

# 5. Serve with http.server
cd /app/pypi && nohup python3 -m http.server <PORT> > /tmp/server.log 2>&1 &

# 6. Install and verify
pip install --index-url http://localhost:<PORT>/simple/ <package_name>==<version>
```

## Detailed Workflow

### 1. Package Structure

**Detect existing structure:**
```bash
if [ -d "src" ]; then
  echo "src-layout: package in src/<package_name>/"
else
  echo "flat layout: package in ./<package_name>/"
fi
```

**Create if needed:**
- src-layout: `mkdir -p src/<package_name>`
- flat layout: `mkdir -p <package_name>`

### 2. Build Metadata

**Check for existing:**
```bash
if [ -f "pyproject.toml" ]; then
  echo "pyproject.toml found"
elif [ -f "setup.py" ]; then
  echo "setup.py found"
fi
```

**Create pyproject.toml:**
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
where = ["src"]  # omit for flat layout
```

### 3. Package Implementation

**Create `__init__.py` with exports:**
```python
"""<package_name> - <description>."""

from <package_name>._core import <required_function>

__all__ = ["<required_function>"]
```

**Implement in `_core.py`:**
```python
def <required_function>(...):
    """<docstring>"""
    # Implementation with validation
    pass
```

**Key points:**
- Export all required symbols from `__init__.py`
- Add input validation and edge case handling
- Use type hints for clarity

### 4. Build Artifacts

```bash
# Install build tools
pip install build wheel setuptools --quiet

# Clean stale artifacts
rm -rf dist/ build/ *.egg-info src/*.egg-info

# Build both sdist and wheel
python3 -m build

# Verify
ls -la dist/
```

### 5. Static PEP 503 Index

**CRITICAL**: Use static index (not pypiserver) when tests check filesystem paths.

**Create index structure:**
```bash
INDEX_ROOT="/app/pypi"
mkdir -p "$INDEX_ROOT/simple/<package_name>"

# Copy artifacts
cp dist/<package_name>-<version>-*.whl "$INDEX_ROOT/simple/<package_name>/"
cp dist/<package_name>-<version>.tar.gz "$INDEX_ROOT/simple/<package_name>/"
```

**Generate package index with hashes:**
```bash
cd "$INDEX_ROOT/simple/<package_name>"

# Get filenames (explicit single-file assumption)
WHEEL_FILE=$(ls *.whl | head -1)
SDIST_FILE=$(ls *.tar.gz | head -1)

# Compute hashes
WHEEL_HASH=$(sha256sum "$WHEEL_FILE" | cut -d' ' -f1)
SDIST_HASH=$(sha256sum "$SDIST_FILE" | cut -d' ' -f1)

# Generate HTML (unquoted heredoc for variable expansion)
cat > index.html << HTMLEOF
<!DOCTYPE html>
<html>
<body>
<h1>Links for <package_name></h1>
<a href="${WHEEL_FILE}#sha256=${WHEEL_HASH}">${WHEEL_FILE}</a><br>
<a href="${SDIST_FILE}#sha256=${SDIST_HASH}">${SDIST_FILE}</a><br>
</body>
</html>
HTMLEOF
```

**Generate root index:**
```bash
cat > "$INDEX_ROOT/simple/index.html" << EOF
<!DOCTYPE html>
<html>
<body>
<h1>Simple Index</h1>
<a href="<package_name>/"><package_name></a><br>
</body>
</html>
EOF
```

**Serve with http.server:**
```bash
cd "$INDEX_ROOT"
nohup python3 -m http.server <PORT> --bind 0.0.0.0 > /tmp/server.log 2>&1 &
```

**Wait for server:**
```bash
for i in $(seq 1 10); do
    curl -sf http://localhost:<PORT>/simple/ > /dev/null && break
    sleep 1
done
```

### 6. Install and Verify

```bash
# Uninstall existing
pip uninstall -y <package_name> 2>/dev/null || true

# Install from local index
pip install --index-url http://localhost:<PORT>/simple/ <package_name>==<version>

# Verify functionality
python3 -c "from <package_name> import <function>; print(<function>(<test_args>))"
```

## Critical Issues

### Issue: Filesystem checks fail
**Symptom**: `assert (INDEX_ROOT / "simple" / "vectorops" / wheel.name).exists()` fails
**Cause**: Using pypiserver (dynamic) instead of static index
**Solution**: Create static PEP 503 structure with actual files at `/app/pypi/simple/<package>/`

### Issue: Server not responding after agent exits
**Symptom**: Tests fail to connect to server
**Cause**: Background process not detached
**Solution**: Always use `nohup` with output redirection

### Issue: Package not found
**Symptom**: `pip install` fails with "no matching distribution"
**Cause**: Package discovery misconfigured or wrong index URL
**Solution**: Check `[tool.setuptools.packages.find]` in pyproject.toml

### Issue: Import error
**Symptom**: `ModuleNotFoundError` or `ImportError` after installation
**Cause**: Missing `__init__.py` or incorrect exports
**Solution**: Ensure `__init__.py` exists and exports required symbols

## Key Principles

1. **Static index by default**: Satisfies both filesystem and HTTP checks
2. **Process persistence**: Use `nohup` for servers
3. **Clean builds**: Remove old artifacts before building
4. **Correct hashes**: Compute SHA256 from actual artifacts
5. **Proper exports**: Export all required symbols from `__init__.py`
6. **Verify everything**: Test after each major step

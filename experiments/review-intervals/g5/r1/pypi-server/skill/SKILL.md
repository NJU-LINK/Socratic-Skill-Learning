---
name: pypi-server
description: Build Python packages from source, serve them on a local PEP 503-compatible index, and install them with pip. Handles src-layout and flat-layout projects, pyproject.toml and setup.py metadata, multiple index tools (pypiserver, devpi, static indexes), and various publication flows (wheel-only, sdist-only, both).
---

# PyPI Server Skill

This skill covers the end-to-end workflow of building a Python package from source, serving it on a local package index, and installing it with pip. The task family varies across four axes: package layout and build metadata, functionality requirements, index service configuration, and publication/installation flow.

## General Workflow

1. **Inspect the task spec** to determine:
   - Package name, version, and required imports/APIs
   - Layout (src-layout vs flat-layout)
   - Build system (pyproject.toml vs setup.py)
   - Index tool and port
   - Which artifacts to build (wheel, sdist, or both)

2. **Create or fix the package structure** according to the layout and functionality requirements.

3. **Build the distribution artifacts** using `python3 -m build` or equivalent.

4. **Start the local index service** pointing at the artifacts directory.

5. **Install the package** from the local index and verify it works.

## Axis 1: Package Layout and Build Metadata

### Detecting the Layout

**Src-layout**: Package code lives in `src/<package_name>/`. This is the modern recommended layout.

**Flat-layout**: Package code lives directly in `<package_name>/` at the project root.

**Pre-staged projects**: The task may provide a partially complete or broken project. Inspect with `find /app -name "*.py" -o -name "pyproject.toml" -o -name "setup.py"` to understand what exists.

### Pyproject.toml for Src-Layout

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "package-name"
version = "0.1.0"
description = "Package description"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
```

**Critical**: The `[tool.setuptools.packages.find]` section with `where = ["src"]` is required for src-layout. Without it, setuptools will not find packages in the `src/` directory and the build will produce an empty distribution.

### Pyproject.toml for Flat-Layout

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "package-name"
version = "0.1.0"
description = "Package description"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["."]
```

For flat-layout, `where = ["."]` or omitting the section entirely (setuptools auto-discovery) usually works.

### Setup.py (Legacy)

If the task requires `setup.py` instead of `pyproject.toml`:

```python
from setuptools import setup, find_packages

setup(
    name="package-name",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
)
```

### Multi-Module Packages

If the package has multiple modules (e.g., `vectorops.core`, `vectorops.utils`), ensure all modules are in the package directory and the `__init__.py` exports the required public API.

### Package Data

If the package includes non-Python files (data files, templates), add to `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"package-name" = ["*.json", "*.txt"]
```

### Verifying the Build

After building, inspect the wheel contents:

```bash
unzip -l dist/*.whl | grep -E "\.py$|\.json$"
```

Ensure the expected modules are present. For src-layout, the wheel should contain `<package_name>/__init__.py` and other modules at the top level (not under `src/`).

## Axis 2: Functionality Requirements

### Reading the Spec

The task will specify:
- Required import paths (e.g., `from vectorops import dotproduct`)
- Function/class signatures
- Expected behavior and edge cases

### Implementing the Code

Create the package modules to satisfy the requirements. Common patterns:

- **Single function**: Put it in `__init__.py` or a `_core.py` module and re-export from `__init__.py`
- **Multiple functions/classes**: Organize into logical modules, export from `__init__.py`
- **Validation**: Add input validation and raise appropriate exceptions (ValueError, TypeError)

### Example Implementation

```python
# src/vectorops/__init__.py
from vectorops._core import dotproduct

__all__ = ["dotproduct"]

# src/vectorops/_core.py
def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")
    return sum(x * y for x, y in zip(a, b))
```

### Post-Install Verification

After installation, test the required imports and behavior:

```python
from vectorops import dotproduct

# Test basic functionality
result = dotproduct([1, 2, 3], [4, 5, 6])
assert result == 32, f"Expected 32, got {result}"

# Test edge cases
assert dotproduct([], []) == 0
assert dotproduct([1.5, 2.5], [2.0, 4.0]) == 13.0
```

## Axis 3: Index Service Configuration

### Static PEP 503 Layout (Recommended)

**Why this approach**: Tests often verify file existence at `/app/pypi/simple/<package>/<filename>` on disk, not just HTTP availability. A static layout satisfies both requirements.

**Step 1: Create the directory structure**:

```bash
mkdir -p /app/pypi/simple/package-name
```

**Step 2: Copy artifacts**:

```bash
cp /app/dist/package-name-0.1.0-py3-none-any.whl /app/pypi/simple/package-name/
cp /app/dist/package-name-0.1.0.tar.gz /app/pypi/simple/package-name/
```

**Step 3: Create root index.html** (lists all packages):

```bash
cat > /app/pypi/simple/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="package-name/">package-name</a><br>
</body>
</html>
EOF
```

**Step 4: Create package index.html** (lists all files for the package):

```bash
cat > /app/pypi/simple/package-name/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Links for package-name</title></head>
<body>
<h1>Links for package-name</h1>
<a href="package-name-0.1.0-py3-none-any.whl">package-name-0.1.0-py3-none-any.whl</a><br>
<a href="package-name-0.1.0.tar.gz">package-name-0.1.0.tar.gz</a><br>
</body>
</html>
EOF
```

**Step 5: Serve with HTTP server**:

```bash
nohup python3 -m http.server 8091 --directory /app/pypi > /tmp/httpserver.log 2>&1 &
```

**Critical**: Use `nohup` and redirect output. A bare `&` creates a background process that dies when the shell exit. When `run_tests_in_same_shell: false`, the server must survive shell exit.

**Verifying the server**:

```bash
sleep 2
curl -s http://localhost:8091/simple/ | grep package-name
```

**Why this works**: The HTTP server serves `/app/pypi/` as the root, so `http://localhost:8091/simple/` maps to `/app/pypi/simple/`. The pip install URL is `--index-url http://localhost:8091/simple`.

**Alternative: Programmatic Index Generation** (for complex packages or multiple versions):

```python
python3 << 'PYEOF'
import re
from pathlib import Path
from packaging.utils import parse_wheel_filename, parse_sdist_filename

DIST_DIR = Path('/app/dist')
INDEX_ROOT = Path('/app/pypi/simple')

# Scan for artifacts
artifacts = {}
for f in DIST_DIR.iterdir():
    try:
        if f.name.endswith('.whl'):
            name, version, build, tags = parse_wheel_filename(f.name)
            pkg_name = str(name)  # Already normalized
        elif f.name.endswith('.tar.gz'):
            name, version = parse_sdist_filename(f.name)
            pkg_name = str(name)  # Already normalized
        else:
            continue
        
        if pkg_name not in artifacts:
            artifacts[pkg_name] = []
        artifacts[pkg_name].append(f.name)
    except Exception as e:
        print(f"Warning: Could not parse {f.name}: {e}")

# Create index structure
INDEX_ROOT.mkdir(parents=True, exist_ok=True)

# Root index.html
root_html = ['<!DOCTYPE html>', '<html>', '<head><title>Simple Index</title></head>', '<body>']
for pkg_name in sorted(artifacts.keys()):
    root_html.append(f'<a href="{pkg_name}/">{pkg_name}</a><br>')
root_html.extend(['</body>', '</html>'])
(INDEX_ROOT / 'index.html').write_text('\n'.join(root_html))

# Package index.html files
for pkg_name, files in artifacts.items():
    pkg_dir = INDEX_ROOT / pkg_name
    pkg_dir.mkdir(exist_ok=True)
    
    # Copy artifacts
    for fname in files:
        src = DIST_DIR / fname
        dst = pkg_dir / fname
        dst.write_bytes(src.read_bytes())
    
    # Generate index.html
    pkg_html = ['<!DOCTYPE html>', '<html>', f'<head><title>Links for {pkg_name}</title></head>', '<body>']
    for fname in sorted(files):
        pkg_html.append(f'<a href="{fname}">{fname}</a><br>')
    pkg_html.extend(['</body>', '</html>'])
    (pkg_dir / 'index.html').write_text('\n'.join(pkg_html))

print(f"✓ Created PEP 503 layout for {len(artifacts)} package(s)")
PYEOF
```

**Why use `packaging.utils`**: Wheel filenames encode the package name with underscores (e.g., `my_package-0.1.0-py3-none-any.whl`), and sdist filenames use hyphens. The `packaging` library correctly parses these and returns PEP 503-normalized names, avoiding manual string manipulation errors.

### Pypiserver (Alternative)

Use pypiserver when tests only verify HTTP availability and don't check for physical file existence.

**Installation**:

```bash
pip install pypiserver
```

**Starting the server**:

```bash
nohup pypi-server run --port 8091 /app/dist > /tmp/pypiserver.log 2>&1 &
```

**Critical**: Use `nohup` and redirect output. A bare `&` creates a background process that dies when the shell exits. When `run_tests_in_same_shell: false` in the task config, the test runner uses a different shell, so the server must survive shell exit.

**Verifying the server**:

```bash
sleep 2
curl -s http://localhost:8091/simple/ | grep package-name
```

**Serving multiple packages**: Point pypiserver at a directory containing multiple `.whl` and `.tar.gz` files. It will serve all of them.

**Limitation**: Pypiserver serves from `/app/dist` but doesn't create a physical `/app/pypi/simple/<package>/` directory structure. If tests check for file existence on disk, use the static layout approach instead.

### Devpi (Alternative)

If the task requires devpi:

```bash
pip install devpi-server devpi-web
nohup devpi-server --host 0.0.0.0 --port 8091 --server-dir /tmp/devpi > /tmp/devpi.log 2>&1 &
```

Upload packages:

```bash
devpi upload --from-directory /app/dist
```

### Port Configuration

The task will specify the port. Common ports: 8091, 8080, 9000. Adjust the `--port` flag accordingly.

### Authentication

Some tasks may require authenticated uploads. For pypiserver:

```bash
pypi-server run --port 8091 -P .htpasswd /app/dist
```

Create `.htpasswd` with `htpasswd -c .htpasswd username`.

## Axis 4: Publication and Installation Flow

### Building Artifacts

**Build both sdist and wheel** (default):

```bash
cd /app
python3 -m build
```

This creates `dist/package-name-0.1.0.tar.gz` and `dist/package-name-0.1.0-py3-none-any.whl`.

**Wheel only**:

```bash
python3 -m build --wheel
```

**Sdist only**:

```bash
python3 -m build --sdist
```

### Installing the Build Tool

If `build` is not installed:

```bash
pip install build
```

### Cleaning Old Artifacts

Before building, remove old artifacts to avoid confusion:

```bash
rm -rf /app/dist /app/build /app/*.egg-info
```

### Installing from Local Index

**Basic installation**:

```bash
pip install --index-url http://localhost:8091/simple package-name==0.1.0
```

**Control dependency resolution**:

- **Default (local first, PyPI fallback for deps)**:
  ```bash
  pip install --index-url http://localhost:8091/simple --extra-index-url https://pypi.org/simple package-name==0.1.0
  ```
  This makes pip search the local index first, falling back to PyPI only for packages not found locally. This is the correct default for most packages.

- **Local-only (no PyPI at all)**:
  ```bash
  pip install --index-url http://localhost:8091/simple --no-index package-name==0.1.0
  ```
  `--no-index` disables all indexes except the one specified. **Warning**: This will fail if the package has dependencies that aren't also on your local index.

- **Skip dependency resolution entirely**:
  ```bash
  pip install --index-url http://localhost:8091/simple --no-deps package-name==0.1.0
  ```
  `--no-deps` prevents pip from installing **any** dependencies at all. Use only when you specifically want to skip dependency resolution (e.g., reinstalling the same package without touching already-installed deps).

**Force reinstall** (if already installed):

```bash
pip uninstall -y package-name
pip install --index-url http://localhost:8091/simple package-name==0.1.0
```

Or:

```bash
pip install --index-url http://localhost:8091/simple --force-reinstall package-name==0.1.0
```

### Verifying Installation

Check that the package is installed from the local index:

```bash
pip show package-name
```

The output should show the version and location.

### Distribution Name Normalization

PEP 503 normalizes distribution names: underscores, hyphens, and periods are all treated as equivalent. `vector_ops`, `vector-ops`, and `vector.ops` all normalize to `vector-ops`. The local index URL path uses the normalized name.

## Common Gotchas and Warnings

1. **Bare `&` doesn't survive shell exit**: Always use `nohup ... &` for long-running services.

2. **Src-layout requires explicit package discovery**: Without `[tool.setuptools.packages.find] where = ["src"]`, the build produces an empty distribution.

3. **Empty distributions**: After building, inspect the wheel with `unzip -l dist/*.whl` to verify it contains the expected modules.

4. **Import path mismatches**: The task may require `from package import func` but the code is in `package.module.func`. Ensure `__init__.py` re-exports the required symbols.

5. **Stale artifacts**: Old `.whl` or `.tar.gz` files in `/app/dist` can cause the wrong version to be served. Clean before building.

6. **Port conflicts**: If the port is already in use, kill the old process or use a different port.

7. **Missing build dependencies**: If `python3 -m build` fails, install `build` with `pip install build`.

8. **Wheel platform tags**: Pure Python packages build as `py3-none-any.whl`. Packages with C extensions build platform-specific wheels.

9. **Dependency resolution confusion**: `--no-deps` doesn't prevent PyPI fallback — it prevents ALL dependency installation. To prevent PyPI fallback while still installing dependencies, use `--extra-index-url https://pypi.org/simple` (local first, PyPI fallback) or `--no-index` (local-only, fails if deps aren't local).

10. **File existence checks**: Tests may check for file existence at `/app/pypi/simple/<package>/<filename>` on disk, not just HTTP availability. A static layout with actual files is required. Pypiserver serving from `/app/dist` doesn't satisfy this requirement.

11. **Wheel filename parsing**: Don't manually parse wheel filenames with string splitting. Use `packaging.utils.parse_wheel_filename()` which correctly handles PEP 503 normalization. The `packaging` library is available since it's a dependency of `build`.

12. **Tar.gz suffix**: `Path('file.tar.gz').suffix` returns `.gz`, not `.tar.gz`. Use `filename.endswith('.tar.gz')` instead.

## Complete Example (v01)

```bash
# 1. Create src-layout package
mkdir -p /app/src/vectorops

cat > /app/src/vectorops/__init__.py << 'EOF'
from vectorops._core import dotproduct
__all__ = ["dotproduct"]
EOF

cat > /app/src/vectorops/_core.py << 'EOF'
def dotproduct(a, b):
    if len(a) != len(b):
        raise ValueError("Vectors must have the same length")
    return sum(x * y for x, y in zip(a, b))
EOF

# 2. Create pyproject.toml
cat > /app/pyproject.toml << 'EOF'
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vectorops"
version = "0.1.0"
description = "Vector operations package"
requires-python = ">=3.8"

[tool.setuptools.packages.find]
where = ["src"]
EOF

# 3. Install build tools and build
pip install build
cd /app && python3 -m build

# 4. Create static PEP 503 layout
mkdir -p /app/pypi/simple/vectorops
cp /app/dist/vectorops-0.1.0-py3-none-any.whl /app/pypi/simple/vectorops/
cp /app/dist/vectorops-0.1.0.tar.gz /app/pypi/simple/vectorops/

cat > /app/pypi/simple/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="vectorops/">vectorops</a><br>
</body>
</html>
EOF

cat > /app/pypi/simple/vectorops/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Links for vectorops</title></head>
<body>
<h1>Links for vectorops</h1>
<a href="vectorops-0.1.0-py3-none-any.whl">vectorops-0.1.0-py3-none-any.whl</a><br>
<a href="vectorops-0.1.0.tar.gz">vectorops-0.1.0.tar.gz</a><br>
</body>
</html>
EOF

# 5. Start HTTP server with nohup
nohup python3 -m http.server 8091 --directory /app/pypi > /tmp/httpserver.log 2>&1 &
sleep 2

# 6. Install from local index
pip install --index-url http://localhost:8091/simple vectorops==0.1.0

# 7. Verify
python3 -c "from vectorops import dotproduct; print(dotproduct([1,2,3], [4,5,6]))"
# Output: 32
```

## Checklist

- [ ] Read task spec for package name, version, layout, imports, index port
- [ ] Create or fix package structure (src-layout or flat-layout)
- [ ] Write pyproject.toml or setup.py with correct metadata
- [ ] Implement required functionality
- [ ] Build artifacts with `python3 -m build`
- [ ] Inspect wheel contents to verify modules are present
- [ ] Create static PEP 503 layout at `/app/pypi/simple/<package>/` with copied artifacts and index.html files
- [ ] Start HTTP server with `nohup` serving from `/app/pypi`
- [ ] Verify index is serving the package AND files exist on disk at `/app/pypi/simple/<package>/`
- [ ] Install package from local index with `--index-url`
- [ ] Test required imports and functionality
- [ ] Control dependency resolution: use `--extra-index-url` for PyPI fallback, `--no-index` for local-only, or `--no-deps` to skip deps entirely

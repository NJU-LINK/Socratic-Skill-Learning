---
name: pypi-server
description: >
  Build a Python package from source, publish it to a local PEP 503-compatible
  package index, and verify it installs and runs correctly. Handles arbitrary
  package layouts (src-layout, flat, multi-module), build metadata formats
  (pyproject.toml, setup.py, setup.cfg), various index tools (pypiserver, devpi,
  static file servers), and flexible publication flows (wheel-only, sdist-only,
  both, version replacement).
---

# PyPI Server — Build, Publish, Install

This skill covers the full pipeline: **source → build → local index → install → verify**.

## 1. Inspect the Task Requirements

Before writing any code, extract these from the task description:

| What to extract | Why it matters |
|---|---|
| Package name and version | Drives `pyproject.toml` metadata and `pip install` spec |
| Layout (src/ vs flat) | Determines `packages.find.where` or manual `packages` list |
| Public API surface | Drives `__init__.py` exports — what must be importable |
| Functionality requirements | Drives implementation code |
| Index tool and port | Drives server startup command and `--index-url` |
| Artifact types needed | Wheel, sdist, or both |
| **Index root path** | Where the static PEP 503 directory must be created (e.g., `/app/pypi/`) |

**Critical: Determine the index root path.** The task or tests will specify or imply where the index directory structure must physically exist. Common patterns:
- Explicit: "Create a local index at `/app/pypi/`"
- Implicit: Tests check `(INDEX_ROOT / "simple" / package / filename).exists()` where `INDEX_ROOT` is defined
- Default: If not specified, `/app/pypi/` is a reasonable default

The index root is where you create the `simple/<package-name>/` directory structure. Files must physically exist at these paths — tests often check filesystem presence, not just HTTP availability.

## 2. Create the Package Structure

### 2a. src-layout (most common, required by spec seed)

```
/app/
  pyproject.toml
  src/
    <package_name>/
      __init__.py      # public API exports
      _core.py         # implementation (optional split)
```

### 2b. Flat layout (alternative)

```
/app/
  pyproject.toml
  <package_name>/
    __init__.py
```

### 2c. pyproject.toml template

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "<package-name>"
version = "<version>"
description = "<description>"
requires-python = ">=3.8"

# For src-layout:
[tool.setuptools.packages.find]
where = ["src"]

# For flat layout, omit the [tool.setuptools.packages.find] section
# or use: packages = ["<package_name>"]
```

**Key decisions:**
- Use `setuptools` as the build backend (universally available, handles both layouts).
- For src-layout, `[tool.setuptools.packages.find] where = ["src"]` is essential — without it, setuptools won't find packages under `src/`.
- For flat layout, setuptools auto-discovers packages in the project root.

**PEP 503 Distribution Name Normalization:**

Package names in index URLs must be *normalized*: lowercased, and any run of `[-_.]` collapsed to a single hyphen. This affects:
- The URL path: `/simple/<normalized-name>/`
- Built filenames: wheel and sdist use the normalized form
- The `pip install` specifier

Example: a package named `My_Cool.Package` normalizes to `my-cool-package`. The index URL is `/simple/my-cool-package/`, the wheel is `my_cool_package-1.0.0-py3-none-any.whl`, and you install with `pip install my-cool-package`.

If the task specifies a name with underscores or mixed case, always normalize when constructing URLs. pip handles normalization on the client side, but if you're manually verifying with `curl`, you must normalize yourself.

### 2d. `__init__.py` — Public API

The `__init__.py` must export exactly what the task requires. Common patterns:

```python
# Direct re-export from implementation module
from .<module> import <function_or_class>

# Or define inline
def <function>(...):
    ...

__all__ = ["<exported_names>"]
```

**Critical:** The import path specified in the task (e.g., `from vectorops import dotproduct`) must work. This means the name must be available at the top-level package namespace.

### 2e. Implementation

Implement the required functionality. Key considerations:
- Handle the exact types specified (int, float, mixed)
- Handle edge cases (empty inputs, mismatched lengths if validation required)
- Use standard Python — no external dependencies unless specified

## 3. Install Build Tools

```bash
pip install build
```

The `build` package provides `python3 -m build` which creates both sdist and wheel.

## 4. Build the Distribution

```bash
cd /app && python3 -m build
```

This creates:
- `dist/<name>-<version>.tar.gz` (sdist)
- `dist/<name>-<version>-py3-none-any.whl` (pure-Python wheel)

**Variations:**
- Wheel only: `python3 -m build --wheel`
- Sdist only: `python3 -m build --sdist`

**Verify artifacts exist:**
```bash
ls -la /app/dist/
```

## 5. Create the Local Package Index

The index must be a **static PEP 503 directory structure** with physical files, not just a running server. Tests often check both HTTP serving AND filesystem presence.

### 5a. Create the static directory structure

```bash
# Create PEP 503 directory structure at the index root
mkdir -p <INDEX_ROOT>/simple/<package-name>

# Copy built artifacts to the index directory
cp /app/dist/<package-name>-<version>-*.whl <INDEX_ROOT>/simple/<package-name>/
cp /app/dist/<package-name>-<version>.tar.gz <INDEX_ROOT>/simple/<package-name>/
```

**Critical:** The directory structure must match PEP 503:
- `<INDEX_ROOT>/simple/` — root index directory
- `<INDEX_ROOT>/simple/<package-name>/` — package directory containing artifacts
- Files must physically exist at these paths (tests check filesystem, not just HTTP)

**Example for v01:** If `INDEX_ROOT=/app/pypi/`, create `/app/pypi/simple/vectorops/` and copy artifacts there.

### 5b. Start the HTTP server

**pypiserver (most common):**

```bash
pip install pypiserver
```

**Critical: Use module invocation, not bare command** — pip may install entry-point scripts to directories not on PATH in containers:

```bash
python3 -m pypiserver run --port <PORT> <PACKAGES_DIR>
```

- `<PORT>`: from task spec (e.g., 8091)
- `<PACKAGES_DIR>`: **must be the same directory where you copied the artifacts** (e.g., `<INDEX_ROOT>/simple/<package-name>`)

**Important:** The `<PACKAGES_DIR>` argument to pypiserver must point to the directory containing your `.whl` and `.tar.gz` files. This is the same directory you created in step 5a. The server will serve files from this location, and tests will verify files exist at this path.

**Server persistence — critical for evaluation environments:**

Tests often run in a *separate shell session* from setup commands. A plain `&` job is tied to its parent shell — if that shell exits, the server receives SIGHUP and dies before tests can install from it. Use `nohup` and `disown`:

```bash
nohup python3 -m pypiserver run --port <PORT> <PACKAGES_DIR> > /tmp/pypiserver.log 2>&1 &
disown %1
```

Alternatively, write a `start-server.sh` script that the skill can re-invoke. Always verify the server is alive with a curl check before attempting install.

**Verify the server is up:**
```bash
sleep 2
curl -s http://localhost:<PORT>/simple/
```

You should see HTML listing your package name as a link.

**Verify package links:**
```bash
curl -s http://localhost:<PORT>/simple/<package-name>/
```

You should see links to both the wheel and sdist with sha256 hashes.

### 5c. Alternative index tools

- **devpi**: `devpi-server --start --host 0.0.0.0 --port <PORT>`
- **Static file server**: Any HTTP server serving the `/app/pypi/` directory
- **Custom**: Must implement PEP 503 simple repository API at `/simple/` and `/simple/<package>/`

### 5d. pypiserver options to know

- `--port PORT`: listen port
- `--authenticate` / `-P`: password file for upload authentication
- `--fallback-url`: upstream PyPI mirror for packages not hosted locally
- Packages directory: positional argument, serves all `.whl`, `.tar.gz`, `.zip` files found there

## 6. Install from the Local Index

```bash
# Uninstall any existing version first (ensures fresh install from local index)
pip uninstall -y <package-name> 2>/dev/null || true

# Install from local index
pip install --index-url http://localhost:<PORT>/simple <package-name>==<version>
```

**Key flags:**
- `--index-url`: Replaces the default PyPI entirely. Use this when the package should ONLY come from the local index.
- `--extra-index-url`: Adds the local index as an additional source. Use when falling back to PyPI is acceptable.
- `--no-deps`: Skip dependency resolution if the package has no deps and you want to avoid network calls.

**Troubleshooting install failures:**
- "No matching distribution found": Server not running, wrong port, or artifacts not in served directory
- "Could not find a version": Package name mismatch (check normalization: `my-package` vs `my_package`)
- Connection refused: Server not started or wrong port

## 7. Verify Installation

```python
python3 -c "
from <package> import <function_or_class>
# Test the required functionality
result = <function>(<test_args>)
assert result == <expected>, f'Expected <expected>, got {result}'
print('Verification passed!')
"
```

## 8. Common Pitfalls and Recovery

### Package not found by setuptools
- **Symptom**: Built wheel is empty or has wrong name
- **Fix**: Check `[tool.setuptools.packages.find] where` matches your layout. For src-layout, must be `["src"]`.

### Entry-point script not on PATH
- **Symptom**: `command not found` for pip-installed tools
- **Fix**: Use `python3 -m <module>` invocation instead (e.g., `python3 -m pypiserver`)
- **Alternative**: Find the script with `find / -name <tool> -type f 2>/dev/null`

### Server starts but package not listed
- **Symptom**: `/simple/` shows empty index
- **Fix**: Check that the packages directory path is correct and contains `.whl`/`.tar.gz` files

### Index files not on filesystem
- **Symptom**: HTTP server works and `pip install` succeeds, but test fails with `assert (INDEX_ROOT / "simple" / package / filename).exists()`
- **Fix**: The index must be a **static PEP 503 directory structure** with physical files, not just a running server. Create `/app/pypi/simple/<package-name>/` and copy artifacts there. Point the HTTP server at that directory.
- **Why**: Tests often check both HTTP serving AND filesystem presence. A server pointing at `/app/dist` serves files correctly but the files don't exist at the expected index path.

### Server dies between setup and test
- **Symptom**: `curl` succeeds during setup but `pip install` fails later with connection refused
- **Fix**: Use `nohup ... & disown` to detach from parent shell. Write a startup script that can be re-invoked. Always verify with `curl` immediately before `pip install`, not just after starting the server.

### Name normalization mismatch
- **Symptom**: `curl http://localhost:PORT/simple/My_Package/` returns 404 but the package was built
- **Fix**: PEP 503 normalizes names: lowercase, collapse `[-_.]` runs to single hyphen. `My_Package` → `my-package`. Use the normalized form in all index URLs.

### Stale artifacts in dist/
- **Symptom**: Old versions appear in index
- **Fix**: Clean `dist/` before building: `rm -rf /app/dist/ && python3 -m build`

### Import works but function not found
- **Symptom**: `ImportError: cannot import name 'X'`
- **Fix**: Check `__init__.py` exports. The name must be in the package's top-level namespace.

### Port already in use
- **Symptom**: `Address already in use`
- **Fix**: `kill $(lsof -t -i:<PORT> 2>/dev/null) 2>/dev/null || true` then restart

## 9. Generalized Pipeline Checklist

1. [ ] Read task spec: extract package name, version, layout, API, port, artifact types, **index root path**
2. [ ] Create directory structure matching required layout
3. [ ] Write `pyproject.toml` with correct build metadata and package discovery
4. [ ] Implement `__init__.py` with required public exports
5. [ ] Implement functionality in module(s)
6. [ ] `pip install build` (and `pypiserver` or other index tool)
7. [ ] Clean `dist/` to avoid stale artifacts: `rm -rf /app/dist/`
8. [ ] `python3 -m build` (or `--wheel`/`--sdist` if only one type needed)
9. [ ] Create static PEP 503 directory: `mkdir -p <INDEX_ROOT>/simple/<package-name>/`
10. [ ] Copy artifacts: `cp /app/dist/<artifacts> <INDEX_ROOT>/simple/<package-name>/`
11. [ ] Start index server via `nohup python3 -m <tool> ... & disown` (pointing at `<INDEX_ROOT>/simple/<package-name>/`)
12. [ ] Verify server responds at `/simple/` and lists the package (use normalized name in URL)
13. [ ] Verify files physically exist at `<INDEX_ROOT>/simple/<package-name>/`
14. [ ] `pip install --index-url http://localhost:<PORT>/simple <normalized-name>==<version>`
15. [ ] Verify import and functionality with a test script

**Note:** If tests are available, check whether they verify filesystem presence, HTTP availability, or both. Adjust your index root path accordingly.

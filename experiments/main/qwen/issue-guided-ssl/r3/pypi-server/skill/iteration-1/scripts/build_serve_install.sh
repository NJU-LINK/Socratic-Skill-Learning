#!/usr/bin/env bash
# build_serve_install.sh — Reusable chain for building, serving, and verifying
# a Python package on a local PyPI index.
#
# Usage:
#   ./build_serve_install.sh [OPTIONS]
#
# Options:
#   --project-dir DIR     Project root directory (default: /app)
#   --port PORT           Index server port (default: 8091)
#   --package NAME        Package name to install (default: auto-detect from pyproject.toml)
#   --version VERSION     Package version (default: auto-detect from pyproject.toml)
#   --build-type TYPE     "both" (default), "wheel", or "sdist"
#   --index-tool TOOL     "pypiserver" (default) or "static"
#   --skip-verify         Skip runtime verification step
#   --test-import STR     Python import test string (default: auto from task)
#
# Prerequisites: python3, pip, build, pypiserver (installed automatically if missing)

set -euo pipefail

# Defaults
PROJECT_DIR="/app"
PORT=8091
PACKAGE=""
VERSION=""
BUILD_TYPE="both"
INDEX_TOOL="pypiserver"
SKIP_VERIFY=false
TEST_IMPORT=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --package) PACKAGE="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --build-type) BUILD_TYPE="$2"; shift 2 ;;
        --index-tool) INDEX_TOOL="$2"; shift 2 ;;
        --skip-verify) SKIP_VERIFY=true; shift ;;
        --test-import) TEST_IMPORT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

DIST_DIR="${PROJECT_DIR}/dist"

echo "=== Step 0: Install build tools ==="
pip install build pypiserver --quiet 2>/dev/null

echo "=== Step 1: Auto-detect package metadata ==="
if [[ -z "$PACKAGE" ]] && [[ -f "${PROJECT_DIR}/pyproject.toml" ]]; then
    PACKAGE=$(python3 -c "
import tomllib
with open('${PROJECT_DIR}/pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
print(data['project']['name'])
" 2>/dev/null || echo "")
fi

if [[ -z "$VERSION" ]] && [[ -f "${PROJECT_DIR}/pyproject.toml" ]]; then
    VERSION=$(python3 -c "
import tomllib
with open('${PROJECT_DIR}/pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
print(data['project']['version'])
" 2>/dev/null || echo "")
fi

if [[ -z "$PACKAGE" ]]; then
    echo "ERROR: Could not detect package name. Use --package NAME."
    exit 1
fi
if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not detect version. Use --version VERSION."
    exit 1
fi

echo "Package: ${PACKAGE} v${VERSION}"

echo "=== Step 2: Build ==="
# Clean previous builds
rm -rf "${DIST_DIR}" "${PROJECT_DIR}/build" "${PROJECT_DIR}/src/"*.egg-info

BUILD_ARGS=""
case "$BUILD_TYPE" in
    both) ;; # default builds both
    wheel) BUILD_ARGS="--wheel" ;;
    sdist) BUILD_ARGS="--sdist" ;;
esac

python3 -m build ${BUILD_ARGS} "${PROJECT_DIR}" 2>&1 | tail -3

echo "=== Step 3: Verify build artifacts ==="
ls -la "${DIST_DIR}/"

# Find the wheel file
WHEEL_FILE=$(ls "${DIST_DIR}"/*.whl 2>/dev/null | head -1 || echo "")
if [[ -n "$WHEEL_FILE" ]]; then
    echo "--- Wheel contents ---"
    python3 -m zipfile -l "$WHEEL_FILE"
    
    # Check that the wheel contains the expected package
    PKG_NORMALIZED=$(echo "$PACKAGE" | tr '-' '_' | tr '[:upper:]' '[:lower:]')
    if ! python3 -m zipfile -l "$WHEEL_FILE" | grep -q "${PKG_NORMALIZED}/"; then
        echo "WARNING: Wheel does not contain expected package directory '${PKG_NORMALIZED}/'"
        echo "This likely indicates a package discovery misconfiguration."
        exit 1
    fi
    echo "✓ Wheel contains expected package"
fi

echo "=== Step 4: Start local index ==="
# Kill any existing server on this port
pkill -f "pypi-server.*-p ${PORT}" 2>/dev/null || true
sleep 1

case "$INDEX_TOOL" in
    pypiserver)
        pypi-server run -p "$PORT" "$DIST_DIR" &
        SERVER_PID=$!
        echo "Started pypiserver on port ${PORT} (PID: ${SERVER_PID})"
        ;;
    *)
        echo "Unknown index tool: ${INDEX_TOOL}"
        exit 1
        ;;
esac

# Wait for server to be ready
for i in $(seq 1 10); do
    if curl -s "http://localhost:${PORT}/simple/" > /dev/null 2>&1; then
        echo "✓ Server is ready"
        break
    fi
    if [[ $i -eq 10 ]]; then
        echo "ERROR: Server did not start within timeout"
        exit 1
    fi
    sleep 1
done

echo "=== Step 5: Install from local index ==="
pip install --index-url "http://localhost:${PORT}/simple" "${PACKAGE}==${VERSION}" 2>&1 | tail -5

echo "=== Step 6: Verify installation ==="
pip show "$PACKAGE" | head -5

if [[ "$SKIP_VERIFY" == "false" ]]; then
    if [[ -n "$TEST_IMPORT" ]]; then
        echo "--- Running custom import test ---"
        python3 -c "$TEST_IMPORT"
    else
        echo "--- Basic import check ---"
        python3 -c "import ${PKG_NORMALIZED}; print('Import successful:', ${PKG_NORMALIZED})"
    fi
fi

echo ""
echo "=== COMPLETE ==="
echo "Package ${PACKAGE}==${VERSION} is installed and served from localhost:${PORT}"

#!/bin/bash
# Verify package installation from local index in a clean environment
# Usage: verify_install.sh <package_name> <version> <port> <test_code>

set -e
set -o pipefail

PACKAGE_NAME="${1:-}"
VERSION="${2:-}"
PORT="${3:-8091}"
TEST_CODE="${4:-}"

PROJECT_DIR="${PROJECT_DIR:-/app}"

if [[ -z "$PACKAGE_NAME" || -z "$VERSION" ]]; then
    echo "Usage: verify_install.sh <package_name> <version> [port] [test_code]"
    echo "  package_name: Name of package to install"
    echo "  version: Expected version (e.g., 0.1.0)"
    echo "  port: Server port (default: 8091)"
    echo "  test_code: Python code to run after import (optional)"
    exit 1
fi

VENV_DIR="${VENV_DIR:-${PROJECT_DIR}/.test_venv}"

echo "=== Verifying $PACKAGE_NAME==$VERSION from localhost:$PORT ==="

# Clean up any existing venv
rm -rf "$VENV_DIR"

# Create fresh venv
echo "Creating fresh virtual environment..."
python -m venv "$VENV_DIR"

# Install package from local index
echo "Installing from local index..."
"$VENV_DIR/bin/pip" install --no-cache-dir --index-url "http://localhost:${PORT}/simple" "${PACKAGE_NAME}==${VERSION}" 2>&1 | tee /tmp/pip_install.log

# Verify provenance - check pip used our index (both markers required)
echo "=== Verifying provenance ==="
if ! grep -q "Looking in indexes: http://localhost:${PORT}" /tmp/pip_install.log; then
    echo "ERROR: pip did not report using our index"
    exit 1
fi

if ! grep -q "Downloading http://localhost:${PORT}" /tmp/pip_install.log; then
    echo "ERROR: pip did not download from local index"
    exit 1
fi

echo "Provenance verified: package downloaded from localhost:${PORT}"

# Verify import and functionality
if [[ -n "$TEST_CODE" ]]; then
    echo "Running verification code..."
    "$VENV_DIR/bin/python" -c "$TEST_CODE"
    echo "Verification passed!"
else
    echo "Testing basic import..."
    "$VENV_DIR/bin/python" -c "import ${PACKAGE_NAME}; print('Import successful')"
fi

# Clean up
rm -rf "$VENV_DIR"

echo "=== Verification complete ==="

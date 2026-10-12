#!/usr/bin/env bash
# verify_package.sh — Verify wheel contents, filesystem layout, and runtime
# import correctness for a Python package installed from a local index.
#
# Usage:
#   ./verify_package.sh --package NAME --version VERSION [--port PORT] [--index-root DIR] [--test-code CODE]
#
# Checks:
#   1. Wheel file exists in dist/
#   2. Wheel contains expected package directory
#   3. Wheel contains dist-info metadata
#   4. Artifacts exist at INDEX_ROOT/simple/<package>/ (filesystem check)
#   5. Package is installed (pip show)
#   6. Import works from installed location (not project dir)
#   7. Runtime test code executes correctly (if provided)
#   8. Index server is serving the package via HTTP

set -euo pipefail

PACKAGE=""
VERSION=""
PORT=8091
PROJECT_DIR="/app"
INDEX_ROOT="/app/pypi"
TEST_CODE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --package) PACKAGE="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --index-root) INDEX_ROOT="$2"; shift 2 ;;
        --test-code) TEST_CODE="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$PACKAGE" ]] || [[ -z "$VERSION" ]]; then
    echo "ERROR: --package and --version are required"
    exit 1
fi

PKG_NORMALIZED=$(echo "$PACKAGE" | tr '-' '_' | tr '[:upper:]' '[:lower:]')
DIST_DIR="${PROJECT_DIR}/dist"
INDEX_SIMPLE="${INDEX_ROOT}/simple"
ERRORS=0

echo "=== Verification: ${PACKAGE}==${VERSION} ==="
echo "Index root: ${INDEX_ROOT}"
echo ""

# Check 1: Wheel exists
echo "[1/8] Checking wheel file exists in dist/..."
WHEEL=$(ls "${DIST_DIR}"/${PACKAGE//-/_}-${VERSION}-*.whl 2>/dev/null | head -1 || \
        ls "${DIST_DIR}"/${PKG_NORMALIZED}-${VERSION}-*.whl 2>/dev/null | head -1 || echo "")
if [[ -z "$WHEEL" ]]; then
    echo "  FAIL: No wheel found in ${DIST_DIR}/"
    ERRORS=$((ERRORS + 1))
else
    echo "  PASS: $(basename "$WHEEL")"
fi

# Check 2: Wheel contains package
echo "[2/8] Checking wheel contains package directory..."
if [[ -n "$WHEEL" ]]; then
    CONTENTS=$(python3 -m zipfile -l "$WHEEL" 2>/dev/null)
    if echo "$CONTENTS" | grep -q "${PKG_NORMALIZED}/"; then
        echo "  PASS: Wheel contains ${PKG_NORMALIZED}/"
    else
        echo "  FAIL: Wheel does not contain ${PKG_NORMALIZED}/"
        echo "  Contents: $CONTENTS"
        ERRORS=$((ERRORS + 1))
    fi
fi

# Check 3: Wheel contains dist-info
echo "[3/8] Checking wheel contains dist-info metadata..."
if [[ -n "$WHEEL" ]]; then
    if echo "$CONTENTS" | grep -q "dist-info/METADATA"; then
        echo "  PASS: Wheel contains dist-info/METADATA"
    else
        echo "  FAIL: Wheel missing dist-info/METADATA"
        ERRORS=$((ERRORS + 1))
    fi
fi

# Check 4: Filesystem layout at INDEX_ROOT
echo "[4/8] Checking filesystem layout at INDEX_ROOT..."
INDEX_PKG_DIR="${INDEX_SIMPLE}/${PKG_NORMALIZED}"
if [[ -d "$INDEX_PKG_DIR" ]]; then
    FILE_COUNT=$(find "$INDEX_PKG_DIR" -type f \( -name "*.whl" -o -name "*.tar.gz" \) | wc -l)
    if [[ $FILE_COUNT -gt 0 ]]; then
        echo "  PASS: Found $FILE_COUNT artifact(s) at ${INDEX_PKG_DIR}/"
        ls -1 "$INDEX_PKG_DIR" | sed 's/^/    /'
    else
        echo "  FAIL: Directory exists but no artifacts found at ${INDEX_PKG_DIR}/"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  FAIL: Directory does not exist: ${INDEX_PKG_DIR}/"
    ERRORS=$((ERRORS + 1))
fi

# Check 5: Package is installed
echo "[5/8] Checking package is installed..."
INSTALLED_VERSION=$(pip show "$PACKAGE" 2>/dev/null | grep "^Version:" | awk '{print $2}' || echo "")
if [[ "$INSTALLED_VERSION" == "$VERSION" ]]; then
    echo "  PASS: ${PACKAGE}==${VERSION} is installed"
else
    echo "  FAIL: Expected ${VERSION}, got '${INSTALLED_VERSION}'"
    ERRORS=$((ERRORS + 1))
fi

# Check 6: Import works from installed location
echo "[6/8] Checking import from installed location..."
IMPORT_RESULT=$(cd /tmp && python3 -c "
import sys
# Remove project dir from path to ensure we import from site-packages
sys.path = [p for p in sys.path if '${PROJECT_DIR}' not in p]
import ${PKG_NORMALIZED}
print('OK:', ${PKG_NORMALIZED}.__file__)
" 2>&1) || true

if echo "$IMPORT_RESULT" | grep -q "^OK:"; then
    echo "  PASS: $IMPORT_RESULT"
else
    echo "  FAIL: Import error: $IMPORT_RESULT"
    ERRORS=$((ERRORS + 1))
fi

# Check 7: Runtime test (if provided)
echo "[7/8] Running runtime test..."
if [[ -n "$TEST_CODE" ]]; then
    TEST_RESULT=$(cd /tmp && python3 -c "$TEST_CODE" 2>&1) || true
    if [[ $? -eq 0 ]] && ! echo "$TEST_RESULT" | grep -qi "error\|traceback\|exception"; then
        echo "  PASS: Runtime test succeeded"
        echo "  Output: $TEST_RESULT"
    else
        echo "  FAIL: Runtime test failed"
        echo "  Output: $TEST_RESULT"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  SKIP: No test code provided"
fi

# Check 8: Index server is serving the package
echo "[8/8] Checking index server..."
INDEX_RESPONSE=$(curl -s "http://localhost:${PORT}/simple/${PKG_NORMALIZED}/" 2>/dev/null || echo "")
if echo "$INDEX_RESPONSE" | grep -qi "${PACKAGE}\|${PKG_NORMALIZED}"; then
    echo "  PASS: Index server lists ${PACKAGE}"
else
    echo "  FAIL: Index server does not list ${PACKAGE}"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [[ $ERRORS -eq 0 ]]; then
    echo "=== ALL CHECKS PASSED ==="
    exit 0
else
    echo "=== ${ERRORS} CHECK(S) FAILED ==="
    exit 1
fi

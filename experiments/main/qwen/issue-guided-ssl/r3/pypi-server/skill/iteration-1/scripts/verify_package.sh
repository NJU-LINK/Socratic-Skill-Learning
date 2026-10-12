#!/usr/bin/env bash
# verify_package.sh — Verify wheel contents and runtime import correctness
# for a Python package installed from a local index.
#
# Usage:
#   ./verify_package.sh --package NAME --version VERSION [--port PORT] [--test-code CODE]
#
# Checks:
#   1. Wheel file exists in dist/
#   2. Wheel contains expected package directory
#   3. Wheel contains dist-info metadata
#   4. Package is installed (pip show)
#   5. Import works from installed location (not project dir)
#   6. Runtime test code executes correctly (if provided)

set -euo pipefail

PACKAGE=""
VERSION=""
PORT=8091
PROJECT_DIR="/app"
TEST_CODE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --package) PACKAGE="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
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
ERRORS=0

echo "=== Verification: ${PACKAGE}==${VERSION} ==="
echo ""

# Check 1: Wheel exists
echo "[1/6] Checking wheel file exists..."
WHEEL=$(ls "${DIST_DIR}"/${PACKAGE//-/_}-${VERSION}-*.whl 2>/dev/null | head -1 || \
        ls "${DIST_DIR}"/${PKG_NORMALIZED}-${VERSION}-*.whl 2>/dev/null | head -1 || echo "")
if [[ -z "$WHEEL" ]]; then
    echo "  FAIL: No wheel found in ${DIST_DIR}/"
    ERRORS=$((ERRORS + 1))
else
    echo "  PASS: $(basename "$WHEEL")"
fi

# Check 2: Wheel contains package
echo "[2/6] Checking wheel contains package directory..."
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
echo "[3/6] Checking wheel contains dist-info metadata..."
if [[ -n "$WHEEL" ]]; then
    if echo "$CONTENTS" | grep -q "dist-info/METADATA"; then
        echo "  PASS: Wheel contains dist-info/METADATA"
    else
        echo "  FAIL: Wheel missing dist-info/METADATA"
        ERRORS=$((ERRORS + 1))
    fi
fi

# Check 4: Package is installed
echo "[4/6] Checking package is installed..."
INSTALLED_VERSION=$(pip show "$PACKAGE" 2>/dev/null | grep "^Version:" | awk '{print $2}' || echo "")
if [[ "$INSTALLED_VERSION" == "$VERSION" ]]; then
    echo "  PASS: ${PACKAGE}==${VERSION} is installed"
else
    echo "  FAIL: Expected ${VERSION}, got '${INSTALLED_VERSION}'"
    ERRORS=$((ERRORS + 1))
fi

# Check 5: Import works from installed location
echo "[5/6] Checking import from installed location..."
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

# Check 6: Runtime test (if provided)
echo "[6/6] Running runtime test..."
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

# Check 7: Index server is serving the package
echo "[7/7] Checking index server..."
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

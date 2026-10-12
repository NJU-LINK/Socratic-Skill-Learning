#!/usr/bin/env bash
# build_package.sh - Build Python package artifacts
# Usage: build_package.sh [PROJECT_DIR] [BUILD_TYPE]
#
# BUILD_TYPE: "both" (default), "wheel-only", or "sdist-only"
#
# Handles:
# - Cleaning stale artifacts before build
# - Installing build dependencies
# - Building wheel, sdist, or both
# - Verifying artifacts were created

set -euo pipefail

PROJECT_DIR="${1:-.}"
BUILD_TYPE="${2:-both}"

cd "$PROJECT_DIR"

# Ensure build tools are available
pip install build wheel setuptools --quiet 2>/dev/null || true

# Clean stale artifacts
echo "Cleaning stale artifacts..."
rm -rf dist/ build/
find . -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true

# Build based on type
case "$BUILD_TYPE" in
    wheel-only)
        echo "Building wheel only..."
        python3 -m build --wheel
        ;;
    sdist-only)
        echo "Building sdist only..."
        python3 -m build --sdist
        ;;
    both|*)
        echo "Building sdist and wheel..."
        python3 -m build
        ;;
esac

# Verify artifacts exist
if [ ! -d "dist" ] || [ -z "$(ls -A dist/ 2>/dev/null)" ]; then
    echo "ERROR: No artifacts found in dist/ after build"
    exit 1
fi

echo "Build artifacts:"
ls -la dist/

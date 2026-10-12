#!/bin/bash
# Build Python package artifacts (wheel and/or sdist)
# Usage: build_package.sh [wheel|sdist|both]

set -e

BUILD_TYPE="${1:-both}"
PROJECT_DIR="${PROJECT_DIR:-/app}"
DIST_DIR="${PROJECT_DIR}/dist"

echo "=== Phase 1: Clean previous builds ==="
rm -rf "${DIST_DIR}" "${PROJECT_DIR}/build" "${PROJECT_DIR}"/*.egg-info "${PROJECT_DIR}"/src/*.egg-info 2>/dev/null || true

mkdir -p "${DIST_DIR}"

if [[ "$BUILD_TYPE" == "wheel" || "$BUILD_TYPE" == "both" ]]; then
    echo "=== Phase 2: Building wheel ==="
    pip wheel "${PROJECT_DIR}" --no-deps --no-build-isolation -w "${DIST_DIR}"
    echo "Wheel built successfully"
fi

if [[ "$BUILD_TYPE" == "sdist" || "$BUILD_TYPE" == "both" ]]; then
    echo "=== Phase 3: Building sdist ==="
    
    # Try python -m build first
    if python -c "import build" 2>/dev/null; then
        echo "Using python -m build for sdist"
        python -m build "${PROJECT_DIR}" --sdist --no-isolation -o "${DIST_DIR}"
    else
        echo "Fallback: using setup.py for sdist"
        cd "${PROJECT_DIR}"
        
        # Track if we created a shim, so we don't delete a user's real setup.py
        CREATED_SHIM=0
        
        # Create setup.py shim if pyproject.toml exists but no setup.py
        if [[ -f "pyproject.toml" && ! -f "setup.py" ]]; then
            echo 'from setuptools import setup; setup()' > setup.py
            CREATED_SHIM=1
            echo "Created temporary setup.py shim"
        fi
        
        if [[ -f "setup.py" ]]; then
            python setup.py sdist --dist-dir "${DIST_DIR}"
            # Only remove the file if we created it
            if [[ "$CREATED_SHIM" == "1" ]]; then
                rm -f setup.py
                echo "Removed temporary setup.py shim"
            fi
        else
            echo "ERROR: Cannot build sdist - no pyproject.toml or setup.py found"
            exit 1
        fi
    fi
    echo "Sdist built successfully"
fi

echo "=== Phase 4: Verify artifacts ==="
ls -la "${DIST_DIR}"

echo "Build complete!"

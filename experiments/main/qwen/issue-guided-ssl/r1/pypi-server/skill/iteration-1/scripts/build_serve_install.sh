#!/usr/bin/env bash
# build_serve_install.sh — Parameterized build-serve-install pipeline
#
# Usage:
#   ./build_serve_install.sh [OPTIONS]
#
# Options:
#   --project-dir DIR     Project root (default: /app)
#   --package-name NAME   Package import name (default: vectorops)
#   --dist-name NAME      Distribution name for pip (default: same as package-name)
#   --version VERSION     Package version (default: 0.1.0)
#   --port PORT           Index server port (default: 8091)
#   --packages-dir DIR    Directory for served artifacts (default: PROJECT_DIR/packages)
#   --index-tool TOOL     Index server tool: pypiserver|devpi (default: pypiserver)
#   --build-only          Only build, don't serve or install
#   --skip-build          Skip build step (use existing dist/)
#   --verify              Run post-install verification
#   --help                Show this help
#
# Examples:
#   # Default: build vectorops 0.1.0, serve on 8091, install
#   ./build_serve_install.sh
#
#   # Custom package and port
#   ./build_serve_install.sh --package-name mylib --version 1.2.3 --port 9000
#
#   # Just rebuild and refresh artifacts on existing server
#   ./build_serve_install.sh --skip-build --port 8091

set -euo pipefail

# Defaults
PROJECT_DIR="/app"
PACKAGE_NAME="vectorops"
DIST_NAME=""
VERSION="0.1.0"
PORT="8091"
PACKAGES_DIR=""
INDEX_TOOL="pypiserver"
BUILD_ONLY=false
SKIP_BUILD=false
VERIFY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)    PROJECT_DIR="$2"; shift 2 ;;
        --package-name)   PACKAGE_NAME="$2"; shift 2 ;;
        --dist-name)      DIST_NAME="$2"; shift 2 ;;
        --version)        VERSION="$2"; shift 2 ;;
        --port)           PORT="$2"; shift 2 ;;
        --packages-dir)   PACKAGES_DIR="$2"; shift 2 ;;
        --index-tool)     INDEX_TOOL="$2"; shift 2 ;;
        --build-only)     BUILD_ONLY=true; shift ;;
        --skip-build)     SKIP_BUILD=true; shift ;;
        --verify)         VERIFY=true; shift ;;
        --help)           head -30 "$0"; exit 0 ;;
        *)                echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Derived defaults
DIST_NAME="${DIST_NAME:-$PACKAGE_NAME}"
PACKAGES_DIR="${PACKAGES_DIR:-$PROJECT_DIR/packages}"

echo "=== Configuration ==="
echo "  Project dir:    $PROJECT_DIR"
echo "  Package name:   $PACKAGE_NAME"
echo "  Dist name:      $DIST_NAME"
echo "  Version:        $VERSION"
echo "  Port:           $PORT"
echo "  Packages dir:   $PACKAGES_DIR"
echo "  Index tool:     $INDEX_TOOL"
echo ""

# Step 0: Install tooling
echo "=== Step 0: Installing tooling ==="
pip install build pypiserver --quiet 2>/dev/null
echo "Tooling ready."
echo ""

# Step 1: Build
if [ "$SKIP_BUILD" = false ]; then
    echo "=== Step 1: Building package ==="
    cd "$PROJECT_DIR"

    # Detect layout
    if [ -d "$PROJECT_DIR/src/$PACKAGE_NAME" ]; then
        echo "  Detected src-layout"
    elif [ -d "$PROJECT_DIR/$PACKAGE_NAME" ]; then
        echo "  Detected flat layout"
    else
        echo "  WARNING: No package directory found for '$PACKAGE_NAME'"
    fi

    # Check pyproject.toml exists
    if [ ! -f "$PROJECT_DIR/pyproject.toml" ] && [ ! -f "$PROJECT_DIR/setup.py" ]; then
        echo "  ERROR: No pyproject.toml or setup.py found"
        exit 1
    fi

    # Clean dist/ before building — python -m build appends, it does NOT clean
    rm -rf "$PROJECT_DIR"/dist
    echo "  Cleaned dist/ to avoid stale artifacts"

    # Build
    python -m build "$PROJECT_DIR"
    echo ""

    # Verify wheel contents
    echo "=== Step 1b: Verifying wheel contents ==="
    WHEEL_FILE=$(ls "$PROJECT_DIR"/dist/*.whl 2>/dev/null | head -1)
    if [ -n "$WHEEL_FILE" ]; then
        PY_COUNT=$(python -m zipfile -l "$WHEEL_FILE" | grep -c "\.py " || true)
        echo "  Wheel: $WHEEL_FILE"
        echo "  Python files in wheel: $PY_COUNT"
        if [ "$PY_COUNT" -eq 0 ]; then
            echo "  ERROR: Wheel contains no Python files! Check package discovery config."
            exit 1
        fi
    else
        echo "  WARNING: No wheel found in dist/"
    fi
    echo ""
else
    echo "=== Step 1: SKIPPED (--skip-build) ==="
    echo ""
fi

if [ "$BUILD_ONLY" = true ]; then
    echo "=== Build-only mode, exiting ==="
    exit 0
fi

# Step 2: Prepare packages directory (clean stale artifacts first)
echo "=== Step 2: Preparing packages directory ==="
mkdir -p "$PACKAGES_DIR"
# Remove old artifacts to prevent stale versions from being served
rm -f "$PACKAGES_DIR"/*.whl "$PACKAGES_DIR"/*.tar.gz "$PACKAGES_DIR"/*.egg
echo "  Cleaned stale artifacts from packages dir"
cp "$PROJECT_DIR"/dist/* "$PACKAGES_DIR"/ 2>/dev/null || true
echo "  Packages dir contents:"
ls -la "$PACKAGES_DIR"/
echo ""

# Step 3: Start index server
echo "=== Step 3: Starting index server ==="
# Kill only the process bound to our specific port (not blanket pkill)
if lsof -ti :"$PORT" > /dev/null 2>&1; then
    lsof -ti :"$PORT" | xargs kill 2>/dev/null || true
    echo "  Killed existing process on port $PORT"
fi
# Also clean up any saved PID file for this port
if [ -f /tmp/pypiserver-"$PORT".pid ]; then
    kill "$(cat /tmp/pypiserver-"$PORT".pid)" 2>/dev/null || true
    rm -f /tmp/pypiserver-"$PORT".pid
fi
sleep 1

case "$INDEX_TOOL" in
    pypiserver)
        nohup pypi-server run -p "$PORT" "$PACKAGES_DIR" > /tmp/pypiserver.log 2>&1 &
        SERVER_PID=$!
        echo "$SERVER_PID" > /tmp/pypiserver-"$PORT".pid
        echo "  Started pypiserver (PID: $SERVER_PID) on port $PORT"
        ;;
    *)
        echo "  ERROR: Unknown index tool: $INDEX_TOOL"
        exit 1
        ;;
esac

# Wait for server to be ready
echo "  Waiting for server..."
for i in $(seq 1 10); do
    if curl -sf "http://localhost:$PORT/simple/" > /dev/null 2>&1; then
        echo "  Server is ready!"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "  ERROR: Server did not start within timeout"
        cat /tmp/pypiserver.log
        exit 1
    fi
    sleep 1
done
echo ""

# Step 4: Install from local index
echo "=== Step 4: Installing from local index ==="
pip uninstall -y "$DIST_NAME" 2>/dev/null || true
pip install \
    --force-reinstall \
    --no-cache-dir \
    --index-url "http://localhost:$PORT/simple" \
    "$DIST_NAME==$VERSION"
echo ""

# Step 5: Verify
echo "=== Step 5: Verification ==="
python3 -c "import $PACKAGE_NAME; print(f'  Successfully imported {\"$PACKAGE_NAME\"}')"

if [ "$VERIFY" = true ]; then
    echo "  Running additional verification..."
    pip show "$DIST_NAME" | grep -E "^(Name|Version|Location):" | sed 's/^/  /'
fi

echo ""
echo "=== Pipeline complete ==="
echo "  Package: $DIST_NAME==$VERSION"
echo "  Index:   http://localhost:$PORT/simple"
echo "  Install: pip install --index-url http://localhost:$PORT/simple $DIST_NAME==$VERSION"

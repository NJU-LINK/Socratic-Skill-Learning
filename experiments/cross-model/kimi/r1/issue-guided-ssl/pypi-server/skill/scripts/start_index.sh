#!/bin/bash
# Start a PEP 503-compatible package index server
# Usage: start_index.sh [port] [implementation]

set -e

PORT="${1:-8091}"
IMPLEMENTATION="${2:-static}"  # static or pypiserver
PROJECT_DIR="${PROJECT_DIR:-/app}"
INDEX_ROOT="${INDEX_ROOT:-${PROJECT_DIR}/pypi}"

echo "=== Starting package index on port $PORT (implementation: $IMPLEMENTATION) ==="

# Kill any existing server on this port
pkill -f "http.server $PORT" 2>/dev/null || true
pkill -f "pypi-server run.*$PORT" 2>/dev/null || true
sleep 1

if [[ "$IMPLEMENTATION" == "pypiserver" ]]; then
    # Check if pypiserver is available
    if ! command -v pypi-server &> /dev/null; then
        echo "pypiserver not found, installing..."
        pip install pypiserver --quiet
    fi
    
    echo "Starting pypiserver with packages from ${INDEX_ROOT}/packages..."
    # --disable-fallback is critical: prevents redirect to pypi.org
    nohup pypi-server run -p "$PORT" --disable-fallback "${INDEX_ROOT}/packages" > /tmp/pypi.log 2>&1 &
else
    # Static index + http.server
    echo "Starting static index with http.server from ${INDEX_ROOT}..."
    cd "$INDEX_ROOT"
    nohup python -m http.server "$PORT" > /tmp/pypi.log 2>&1 &
fi

# Wait for server to start
sleep 2

# Verify server is running
echo "=== Verifying server ==="
if curl -s "http://localhost:${PORT}/simple/" > /dev/null 2>&1; then
    echo "Server is running at http://localhost:${PORT}/simple/"
    echo "Index contents:"
    curl -s "http://localhost:${PORT}/simple/" | head -20
else
    echo "ERROR: Server failed to start"
    cat /tmp/pypi.log
    exit 1
fi

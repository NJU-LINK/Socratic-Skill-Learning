#!/usr/bin/env bash
# ensure_pypi_server.sh - Idempotent package index server startup
# Usage: ensure_pypi_server.sh [PORT] [PACKAGES_DIR] [MODE]
#
# MODE: "static" (default) or "dynamic"
#   static:  Creates PEP 503 file structure at PACKAGES_DIR/simple/, serves with http.server
#   dynamic: Uses pypiserver to serve PACKAGES_DIR dynamically
#
# For static mode, PACKAGES_DIR should contain the built artifacts (e.g., /app/dist)
# and the script creates the index structure under PACKAGES_DIR/../pypi/simple/
#
# This script is designed to be called from the skill or test harness.
# It checks if a server is already running, starts one if not, and
# waits until the server is confirmed responding.

set -euo pipefail

PORT="${1:-8091}"
PACKAGES_DIR="${2:-./dist}"
MODE="${3:-static}"
HOST="0.0.0.0"
LOG_FILE="/tmp/pypi_server_${PORT}.log"

# Check if server is already responding
if curl -sf "http://localhost:${PORT}/simple/" > /dev/null 2>&1; then
    echo "Server already running on port ${PORT}"
    exit 0
fi

# Kill any stale process on this port
# Try standard tools first, fall back to /proc scanning if unavailable
if command -v fuser &>/dev/null; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
elif command -v pkill &>/dev/null; then
    pkill -f "http.server.*${PORT}" 2>/dev/null || true
    pkill -f "pypiserver.*--port $PORT" 2>/dev/null || true
else
    # Minimal container without standard process tools - use /proc
    python3 << PYEOF 2>/dev/null || true
import os, signal
for pid_dir in os.listdir('/proc'):
    if not pid_dir.isdigit(): continue
    try:
        with open(f'/proc/{pid_dir}/cmdline', 'rb') as f:
            cmdline = f.read().decode('utf-8', errors='replace')
        if ('http.server' in cmdline or 'pypiserver' in cmdline) and str($PORT) in cmdline:
            os.kill(int(pid_dir), signal.SIGTERM)
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        pass
PYEOF
fi

# Wait briefly for port to be released
sleep 2

if [ "$MODE" = "static" ]; then
    # Static index mode: create PEP 503 structure and serve with http.server
    
    # Determine the index root (sibling of dist dir)
    PARENT_DIR=$(dirname "$PACKAGES_DIR")
    INDEX_ROOT="${PARENT_DIR}/pypi"
    
    echo "Creating static PEP 503 index at ${INDEX_ROOT}/simple/"
    
    # Process each artifact in the packages directory
    declare -A SEEN_PKGS
    
    for pkg_file in "$PACKAGES_DIR"/*; do
        [ -f "$pkg_file" ] || continue
        filename=$(basename "$pkg_file")
        # Extract package name (normalize: before first hyphen-digit, underscores to hyphens)
        pkg_name=$(echo "$filename" | sed -E 's/-[0-9].*//' | tr '_' '-')
        
        # Skip if already processed this package
        [ "${SEEN_PKGS[$pkg_name]+x}" ] && continue
        SEEN_PKGS[$pkg_name]=1
        
        pkg_dir="$INDEX_ROOT/simple/$pkg_name"
        mkdir -p "$pkg_dir"
        
        # Copy artifacts to static index location
        for f in "$PACKAGES_DIR"/*; do
            [ -f "$f" ] || continue
            fname=$(basename "$f")
            f_normalized=$(echo "$fname" | sed -E 's/-[0-9].*//' | tr '_' '-')
            [ "$f_normalized" = "$pkg_name" ] || continue
            cp "$f" "$pkg_dir/"
        done
        
        # Generate package index HTML with correct hashes
        {
            echo '<!DOCTYPE html>'
            echo '<html>'
            echo '<body>'
            echo "<h1>Links for ${pkg_name}</h1>"
            
            for f in "$pkg_dir"/*; do
                [ -f "$f" ] || continue
                [ "$(basename "$f")" = "index.html" ] && continue
                fname=$(basename "$f")
                sha256=$(sha256sum "$f" | cut -d' ' -f1)
                echo "<a href=\"${fname}#sha256=${sha256}\">${fname}</a><br>"
            done
            
            echo '</body>'
            echo '</html>'
        } > "$pkg_dir/index.html"
    done
    
    # Generate root simple index
    {
        echo '<!DOCTYPE html>'
        echo '<html>'
        echo '<body>'
        echo '<h1>Simple Index</h1>'
        for d in "$INDEX_ROOT/simple"/*/; do
            [ -d "$d" ] || continue
            pkg=$(basename "$d")
            echo "<a href=\"${pkg}/\">${pkg}</a><br>"
        done
        echo '</body>'
        echo '</html>'
    } > "$INDEX_ROOT/simple/index.html"
    
    # Serve from index root
    cd "$INDEX_ROOT"
    nohup python3 -m http.server "$PORT" --bind "$HOST" > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "Started static http.server (PID: ${SERVER_PID}) on port ${PORT}"
    
else
    # Dynamic mode: use pypiserver
    
    # Ensure pypiserver is installed
    if ! python3 -c "import pypiserver" 2>/dev/null; then
        echo "Installing pypiserver..."
        pip install pypiserver --quiet
    fi
    
    # Ensure packages directory exists
    if [ ! -d "$PACKAGES_DIR" ]; then
        echo "Warning: packages directory '$PACKAGES_DIR' does not exist"
        mkdir -p "$PACKAGES_DIR"
    fi
    
    nohup python3 -m pypiserver run \
        --port "$PORT" \
        --host "$HOST" \
        "$PACKAGES_DIR" \
        > "$LOG_FILE" 2>&1 &
    
    SERVER_PID=$!
    echo "Started pypiserver (PID: ${SERVER_PID}) on port ${PORT}"
fi

# Wait for server to become ready (up to 30 seconds)
READY=false
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/simple/" > /dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 1
done

if [ "$READY" = true ]; then
    echo "Server confirmed responding on port ${PORT}"
    exit 0
else
    echo "ERROR: Server failed to start within 30 seconds"
    echo "--- Log output ---"
    cat "$LOG_FILE" 2>/dev/null || true
    exit 1
fi

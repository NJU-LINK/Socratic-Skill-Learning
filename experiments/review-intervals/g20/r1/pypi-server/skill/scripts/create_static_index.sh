#!/usr/bin/env bash
# create_static_index.sh - Create a static PEP 503 index from built artifacts
# Usage: create_static_index.sh [DIST_DIR] [INDEX_ROOT] [PORT]
#
# Creates a static PEP 503 index structure with actual artifact files
# and serves it with Python's http.server.
#
# This satisfies both filesystem checks and HTTP access.

set -euo pipefail

DIST_DIR="${1:-./dist}"
INDEX_ROOT="${2:-/app/pypi}"
PORT="${3:-8091}"

# Check if dist directory exists
if [ ! -d "$DIST_DIR" ]; then
    echo "ERROR: Distribution directory '$DIST_DIR' does not exist"
    exit 1
fi

# Check if there are any artifacts
if [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
    echo "ERROR: No artifacts found in '$DIST_DIR'"
    exit 1
fi

echo "Creating static PEP 503 index at $INDEX_ROOT"

# Track processed packages to avoid duplicates
declare -A SEEN_PKGS

# Process each artifact
for pkg_file in "$DIST_DIR"/*; do
    [ -f "$pkg_file" ] || continue
    filename=$(basename "$pkg_file")
    
    # Extract package name (normalize: before first hyphen-digit, underscores to hyphens)
    pkg_name=$(echo "$filename" | sed -E 's/-[0-9].*//' | tr '_' '-')
    
    # Skip if already processed this package
    [ "${SEEN_PKGS[$pkg_name]+x}" ] && continue
    SEEN_PKGS[$pkg_name]=1
    
    pkg_dir="$INDEX_ROOT/simple/$pkg_name"
    mkdir -p "$pkg_dir"
    
    # Copy all artifacts for this package
    for f in "$DIST_DIR"/*; do
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
    
    echo "  Created index for $pkg_name"
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

echo "✓ Static index created"

# Kill any existing server on this port
python3 << PYEOF 2>/dev/null || true
import os, signal
for pid_dir in os.listdir('/proc'):
    if not pid_dir.isdigit(): continue
    try:
        with open(f'/proc/{pid_dir}/cmdline', 'rb') as f:
            cmdline = f.read().decode('utf-8', errors='replace')
        if 'http.server' in cmdline and str($PORT) in cmdline:
            os.kill(int(pid_dir), signal.SIGTERM)
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        pass
PYEOF

sleep 1

# Start HTTP server
cd "$INDEX_ROOT"
nohup python3 -m http.server "$PORT" --bind 0.0.0.0 > /tmp/http_server.log 2>&1 &
SERVER_PID=$!

echo "Started http.server on port $PORT (PID: $SERVER_PID)"

# Wait for server to be ready
for i in $(seq 1 10); do
    if curl -sf "http://localhost:$PORT/simple/" > /dev/null 2>&1; then
        echo "✓ Server is ready"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Server failed to start"
cat /tmp/http_server.log 2>/dev/null || true
exit 1

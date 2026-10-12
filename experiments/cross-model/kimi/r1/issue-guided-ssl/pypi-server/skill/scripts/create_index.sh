#!/bin/bash
# Create a static PEP 503-compatible package index
# Usage: create_index.sh <package_name> <port> [implementation]

set -e

PACKAGE_NAME="${1:-}"
PORT="${2:-8091}"
IMPLEMENTATION="${3:-static}"  # static or pypiserver
PROJECT_DIR="${PROJECT_DIR:-/app}"
DIST_DIR="${DIST_DIR:-${PROJECT_DIR}/dist}"
INDEX_ROOT="${INDEX_ROOT:-${PROJECT_DIR}/pypi}"

if [[ -z "$PACKAGE_NAME" ]]; then
    echo "Usage: create_index.sh <package_name> [port] [implementation]"
    echo "  package_name: The package name as it will appear in pip install"
    echo "  port: The port number (default: 8091)"
    echo "  implementation: static (default) or pypiserver"
    exit 1
fi

# Normalize package name for PEP 503: lowercase, collapse runs of -_. to single -
# Per PEP 503: re.sub(r'[-_.]+', '-', name).lower()
NORMALIZED_NAME=$(echo "$PACKAGE_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/-/g')

# Compute file stem (PEP 427/625: escape - to _)
FILE_STEM=$(echo "$PACKAGE_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[-_.]+/_/g')

echo "=== Creating PEP 503 index for $PACKAGE_NAME ==="
echo "  Normalized name: $NORMALIZED_NAME"
echo "  File stem: $FILE_STEM"
echo "  Implementation: $IMPLEMENTATION"

if [[ "$IMPLEMENTATION" == "pypiserver" ]]; then
    # pypiserver uses flat packages/ directory
    PACKAGE_DIR="${INDEX_ROOT}/packages"
    mkdir -p "$PACKAGE_DIR"
    
    echo "Copying artifacts for pypiserver (flat layout)"
    shopt -s nullglob
    
    # Find wheel and sdist by file stem (PEP 427/625 escaping)
    found_any=0
    for artifact in "${DIST_DIR}/${FILE_STEM}"-*.{whl,tar.gz}; do
        if [[ -f "$artifact" ]]; then
            echo "  Copying: $(basename "$artifact")"
            cp "$artifact" "$PACKAGE_DIR/"
            found_any=1
        fi
    done
    
    if [[ "$found_any" == 0 ]]; then
        echo "ERROR: No artifacts found in ${DIST_DIR} with stem ${FILE_STEM}"
        echo "Contents of ${DIST_DIR}:"
        ls -la "${DIST_DIR}" || true
        exit 1
    fi
    
    echo "Index created at ${INDEX_ROOT}/packages/"
    echo "pypiserver will serve at: http://localhost:${PORT}/simple/${NORMALIZED_NAME}/"
    
else
    # Static index: simple/<normalized_name>/ directory
    PACKAGE_DIR="${INDEX_ROOT}/simple/${NORMALIZED_NAME}"
    mkdir -p "$PACKAGE_DIR"
    
    echo "Copying artifacts for static index"
    shopt -s nullglob
    
    # Find and copy artifacts
    found_any=0
    for artifact in "${DIST_DIR}/${FILE_STEM}"-*.{whl,tar.gz}; do
        if [[ -f "$artifact" ]]; then
            echo "  Copying: $(basename "$artifact")"
            cp "$artifact" "$PACKAGE_DIR/"
            found_any=1
        fi
    done
    
    if [[ "$found_any" == 0 ]]; then
        echo "ERROR: No artifacts found in ${DIST_DIR} with stem ${FILE_STEM}"
        echo "Contents of ${DIST_DIR}:"
        ls -la "${DIST_DIR}" || true
        exit 1
    fi
    
    # Create root index.html
    cat > "${INDEX_ROOT}/simple/index.html" <<EOF
<!DOCTYPE html>
<html>
<head><title>Simple Index</title></head>
<body>
<h1>Simple Index</h1>
<a href="${NORMALIZED_NAME}/">${NORMALIZED_NAME}</a><br>
</body>
</html>
EOF
    
    # Create package index.html
    {
        echo '<!DOCTYPE html><html><head><title>Links for '"$NORMALIZED_NAME"'</title></head><body><h1>Links for '"$NORMALIZED_NAME"'</h1>'
        for f in "$PACKAGE_DIR"/*.{whl,tar.gz}; do
            if [[ -f "$f" ]]; then
                filename=$(basename "$f")
                echo '<a href="'"$filename"'">'"$filename"'</a><br>'
            fi
        done
        echo '</body></html>'
    } > "${PACKAGE_DIR}/index.html"
    
    echo "Index created at ${INDEX_ROOT}/simple/"
    echo "Package available at: http://localhost:${PORT}/simple/${NORMALIZED_NAME}/"
fi

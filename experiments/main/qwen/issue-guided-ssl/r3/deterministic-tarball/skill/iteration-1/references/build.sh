#!/bin/bash
# Reference implementation: deterministic release packaging script
# Adapts this template by changing SRC, OUTPUT, and DISTIGNORE paths
set -euo pipefail

SRC="/app/src"
STAGING="/tmp/release-staging"
OUTPUT="/app/release.tar.zst"
DISTIGNORE="$SRC/.distignore"

# Determine mtime from SOURCE_DATE_EPOCH or default
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

# Clean and create staging area
rm -rf "$STAGING"
mkdir -p "$STAGING"

# Copy source tree preserving symlinks (-a = -dR --preserve=all)
cp -a "$SRC"/. "$STAGING"/

# Parse .distignore and remove excluded paths
if [ -f "$DISTIGNORE" ]; then
    while IFS= read -r pattern || [ -n "$pattern" ]; do
        # Skip blank lines and comments
        [[ -z "$pattern" || "$pattern" =~ ^[[:space:]]*# ]] && continue
        # Trim trailing whitespace
        pattern="${pattern%"${pattern##*[![:space:]]}"}"
        [[ -z "$pattern" ]] && continue
        
        # Handle ** patterns (match at any depth)
        if [[ "$pattern" == **\*\*/* ]]; then
            # Strip leading **/
            base_pattern="${pattern#\*\*/}"
            # Strip trailing /
            base_pattern="${base_pattern%/}"
            
            if [[ "$pattern" == */ ]]; then
                # Directory pattern
                find "$STAGING" -type d -name "$base_pattern" -exec rm -rf {} + 2>/dev/null || true
            else
                # File pattern - could be glob
                find "$STAGING" -type f -name "$base_pattern" -delete 2>/dev/null || true
            fi
        elif [[ "$pattern" == */ ]]; then
            # Directory pattern at root
            dir_name="${pattern%/}"
            rm -rf "$STAGING/$dir_name"
        elif [[ "$pattern" == *[*?]* ]]; then
            # File glob pattern at any depth
            find "$STAGING" -type f -name "$pattern" -delete 2>/dev/null || true
        else
            # Literal path at root
            rm -rf "$STAGING/$pattern"
        fi
    done < "$DISTIGNORE"
fi

# Exclude files with mode exactly 0600
find "$STAGING" -type f -perm 0600 -delete 2>/dev/null || true

# Normalize permissions (order matters: check shebang/exec BEFORE chmod)
find "$STAGING" -type d -exec chmod 0755 {} +

find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    if [ -x "$f" ] || { [ -s "$f" ] && head -c 2 "$f" | grep -q '^#!'; }; then
        chmod 0755 "$f"
    else
        chmod 0644 "$f"
    fi
done

# Normalize line endings for text files only
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    encoding=$(file --mime-encoding -b "$f" 2>/dev/null || echo "binary")
    if [ "$encoding" != "binary" ]; then
        sed -i 's/\r$//' "$f"
    fi
done

# Create deterministic tar archive and compress with zstd
tar --create \
    --file=- \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${MTIME}" \
    -C "$STAGING" \
    . \
| zstd -19 --long --no-check --single-thread -f -o "$OUTPUT"

# Clean up staging area
rm -rf "$STAGING"

echo "Created $OUTPUT"

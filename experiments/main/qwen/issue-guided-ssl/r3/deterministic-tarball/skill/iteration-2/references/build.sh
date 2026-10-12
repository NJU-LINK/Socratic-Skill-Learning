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
# Follows gitignore semantics for pattern matching
if [ -f "$DISTIGNORE" ]; then
    while IFS= read -r pattern || [ -n "$pattern" ]; do
        # Skip blank lines and comments
        [[ -z "$pattern" || "$pattern" =~ ^[[:space:]]*# ]] && continue
        # Trim whitespace
        pattern="${pattern#"${pattern%%[![:space:]]*}"}"
        pattern="${pattern%"${pattern##*[![:space:]]}"}"
        [[ -z "$pattern" ]] && continue
        
        # Skip negation patterns (not supported)
        [[ "$pattern" == !* ]] && continue
        
        # Determine if pattern is directory-only (trailing /)
        is_dir_only=false
        if [[ "$pattern" == */ ]]; then
            is_dir_only=true
            pattern="${pattern%/}"
        fi
        
        # Check if pattern contains literal ** (match at any depth)
        # IMPORTANT: Use *"**"* not **/** to detect literal ** substring
        if [[ "$pattern" == *"**"* ]]; then
            # Remove all ** components to get the base pattern
            base_pattern="${pattern//\*\*\/}"
            base_pattern="${base_pattern//\/\*\*}"
            base_pattern="${base_pattern//\*\*}"
            
            # Skip if base pattern is empty (pure ** matches everything)
            [ -z "$base_pattern" ] && continue
            
            if [ "$is_dir_only" = true ] || [[ "$base_pattern" == */* ]]; then
                # Directory pattern or path pattern - use last component for matching
                dir_name="${base_pattern##*/}"
                find "$STAGING" -type d -name "$dir_name" -exec rm -rf {} + 2>/dev/null || true
            else
                # File pattern - match at any depth
                find "$STAGING" -type f -name "$base_pattern" -delete 2>/dev/null || true
            fi
        elif [[ "$pattern" == */* ]]; then
            # Pattern contains / but no ** - root-relative path
            if [ "$is_dir_only" = true ]; then
                rm -rf "$STAGING/$pattern"
            else
                if [ -d "$STAGING/$pattern" ]; then
                    rm -rf "$STAGING/$pattern"
                elif [ -f "$STAGING/$pattern" ]; then
                    rm -f "$STAGING/$pattern"
                fi
            fi
        elif [[ "$pattern" == *[*?]* ]]; then
            # Glob pattern without / - match at any depth
            if [ "$is_dir_only" = true ]; then
                find "$STAGING" -type d -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            else
                find "$STAGING" -type f -name "$pattern" -delete 2>/dev/null || true
            fi
        else
            # Literal name without / - match at any depth (gitignore semantics)
            if [ "$is_dir_only" = true ]; then
                find "$STAGING" -type d -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            else
                find "$STAGING" -type f -name "$pattern" -delete 2>/dev/null || true
                find "$STAGING" -type d -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            fi
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

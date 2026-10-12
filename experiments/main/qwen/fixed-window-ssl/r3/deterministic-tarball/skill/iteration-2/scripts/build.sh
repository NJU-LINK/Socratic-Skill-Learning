#!/bin/bash
# Deterministic release packaging script
# Produces a bit-for-bit reproducible tar.zst archive from a source tree
#
# Usage: bash build.sh
# Environment: SOURCE_DATE_EPOCH (optional, defaults to 946684800)
#
# This is a reference implementation. Adapt paths and normalization rules
# to match specific variant requirements.

set -euo pipefail

# --- Configuration (adapt for variants) ---
SRC_DIR="/app/src"
OUTPUT="/app/release.tar.zst"
DISTIGNORE="$SRC_DIR/.distignore"

# Timestamp: use SOURCE_DATE_EPOCH if set, otherwise default
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# --- Staging directory setup ---
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# Copy source tree CONTENTS preserving symlinks
# Copy contents of SRC_DIR to STAGING root (not SRC_DIR itself)
# This ensures archive paths are relative to source root
cp -a "$SRC_DIR/." "$STAGING/"

# --- Apply exclusion rules from .distignore ---
# Parses gitignore-style patterns with three cases:
# 1. Recursive globs (**/pattern): match basename at any depth
# 2. Path patterns (dir/file): literal path relative to source root
# 3. Simple names/globs (*.ext, name): match by name at any depth
if [ -f "$DISTIGNORE" ]; then
    while IFS= read -r pattern || [ -n "$pattern" ]; do
        # Skip empty lines and comments
        [[ -z "$pattern" || "$pattern" == \#* ]] && continue

        is_dir=false
        if [[ "$pattern" == */ ]]; then
            is_dir=true
            pattern="${pattern%/}"
        fi

        if [[ "$pattern" == \*\*/* ]]; then
            # Case 1: Recursive glob like **/__pycache__
            basename_part="${pattern#\*\*/}"
            if $is_dir; then
                find "$STAGING" -type d -name "$basename_part" -exec rm -rf {} + 2>/dev/null || true
            else
                find "$STAGING" -name "$basename_part" -exec rm -rf {} + 2>/dev/null || true
            fi
        elif [[ "$pattern" == */* ]]; then
            # Case 2: Path relative to root like vendor/js
            target="$STAGING/$pattern"
            if [ -e "$target" ] || [ -L "$target" ]; then
                rm -rf "$target"
            fi
        else
            # Case 3: Simple name or glob like *.tmp, .hg, scratch
            if $is_dir; then
                find "$STAGING" -type d -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            else
                find "$STAGING" -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            fi
        fi
    done < "$DISTIGNORE"
fi

# --- Remove files with mode exactly 0600 (sensitive files) ---
find "$STAGING" -type f -perm 0600 -delete 2>/dev/null || true

# --- Remove empty directories left after exclusions ---
find "$STAGING" -mindepth 1 -type d -empty -delete 2>/dev/null || true

# --- Normalize line endings for text files ---
# Use file --mime-encoding to detect text vs binary
# Only modify files where encoding is NOT "binary"
find "$STAGING" -type f | while IFS= read -r filepath; do
    encoding=$(file -b --mime-encoding "$filepath")
    if [ "$encoding" != "binary" ]; then
        # Text file: convert CRLF to LF
        sed -i 's/\r$//' "$filepath"
    fi
done

# --- Normalize permissions ---
# Directories: 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Regular files: check execute permission OR shebang
# If either is present → 0755, otherwise → 0644
# Also check original source permissions as fallback (in case cp -a loses bits)
find "$STAGING" -type f | while IFS= read -r filepath; do
    orig_file="$SRC_DIR/${filepath#$STAGING/}"
    if [ -x "$filepath" ] || [ -x "$orig_file" ] 2>/dev/null; then
        chmod 0755 "$filepath"
    elif head -c 2 "$filepath" 2>/dev/null | grep -q '#!'; then
        chmod 0755 "$filepath"
    else
        chmod 0644 "$filepath"
    fi
done

# --- Build sorted file list ---
# List all entries (dirs, files, symlinks) relative to staging, sorted
FILELIST=$(mktemp)
cd "$STAGING"
find . -mindepth 1 | sed 's|^\./||' | LC_ALL=C sort > "$FILELIST"

# --- Create deterministic tar archive ---
# Critical flags:
# --format=gnu: Use GNU tar format
# --sort=name: Sort entries by name
# --owner=0 --group=0 --numeric-owner: Set owner/group to 0:0
# --mtime: Set modification time to epoch
# --no-recursion: Don't recurse (use explicit file list)
# -C: Change to staging directory (must come before --files-from)
tar --create \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${EPOCH}" \
    --no-recursion \
    -C "$STAGING" \
    --files-from="$FILELIST" \
    | zstd -19 --long --no-check --single-thread > "$OUTPUT"

rm -f "$FILELIST"

echo "Created $OUTPUT"

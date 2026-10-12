#!/usr/bin/env bash
# Deterministic release packaging script template.
# Adapt SRC, OUT, DISTIGNORE_FILE, and compression flags per variant.
set -euo pipefail

# --- Configuration (override per variant) ---
SRC="${SRC:-/app/src}"
OUT="${OUT:-/app/release.tar.zst}"
DISTIGNORE_FILE="${DISTIGNORE_FILE:-.distignore}"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# Permission rules (override per variant)
DIR_PERM="${DIR_PERM:-0755}"
EXEC_PERM="${EXEC_PERM:-0755}"
FILE_PERM="${FILE_PERM:-0644}"

# Compression flags (override per variant)
ZSTD_FLAGS="${ZSTD_FLAGS:--19 --long --no-check --single-thread}"

# --- Staging directory (never modify source in place) ---
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# Copy source tree preserving symlinks as symlinks
cp -a "$SRC/." "$STAGING/"

# --- Apply .distignore exclusions ---
DISTIGNORE="$STAGING/$DISTIGNORE_FILE"
if [ -f "$DISTIGNORE" ]; then
    while IFS= read -r pattern || [ -n "$pattern" ]; do
        # Strip trailing CR if .distignore has CRLF line endings
        pattern="${pattern%$'\r'}"
        # Skip empty lines and comments
        [ -z "$pattern" ] && continue
        [[ "$pattern" == \#* ]] && continue

        is_dir=0
        if [[ "$pattern" == */ ]]; then
            is_dir=1
            pattern="${pattern%/}"   # strip trailing /
        fi

        any_depth=0
        if [[ "$pattern" == \*\*/* ]]; then
            any_depth=1
            pattern="${pattern#\*\*/}"   # strip leading **/
        fi

        # After stripping, skip if empty
        [ -z "$pattern" ] && continue

        if [ $is_dir -eq 1 ]; then
            # Directory pattern
            if [ $any_depth -eq 1 ] || [[ "$pattern" != */* ]]; then
                # Match directory at any depth
                find "$STAGING" -mindepth 1 -type d -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            else
                # Rooted path
                rm -rf "$STAGING/$pattern"
            fi
        else
            # File / generic pattern
            if [ $any_depth -eq 1 ] || [[ "$pattern" != */* ]]; then
                # Match at any depth
                find "$STAGING" -mindepth 1 -name "$pattern" -delete 2>/dev/null || true
            else
                # Rooted path
                rm -rf "$STAGING/$pattern"
            fi
        fi
    done < "$DISTIGNORE"
fi

# --- Exclude files whose mode is exactly 0600 ---
find "$STAGING" -type f -perm 0600 -delete

# --- Remove empty directories left behind after exclusions ---
# -depth processes children before parents so nested empties cascade
find "$STAGING" -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true

# --- Normalize permissions and line endings ---
# CRITICAL: Use -print0 and read -d '' to handle filenames with newlines,
# spaces, and other special characters. Do NOT use find | while read.
find "$STAGING" -mindepth 1 -print0 | while IFS= read -r -d '' entry; do
    # Skip symlinks — they have no stored permissions in tar
    if [ -L "$entry" ]; then
        continue
    fi

    if [ -d "$entry" ]; then
        chmod "$DIR_PERM" "$entry"
    elif [ -f "$entry" ]; then
        # Capture shebang and execute status BEFORE any modification
        has_shebang=0
        if [ -s "$entry" ] && head -c2 "$entry" 2>/dev/null | grep -q '#!'; then
            has_shebang=1
        fi

        has_exec=0
        if [ -x "$entry" ]; then
            has_exec=1
        fi

        # Text vs binary detection and CRLF → LF normalization
        enc=$(file --mime-encoding -b "$entry")
        if [ "$enc" != "binary" ]; then
            chmod u+w "$entry"
            sed -i 's/\r$//' "$entry"
        fi

        # Set final permissions
        if [ $has_shebang -eq 1 ] || [ $has_exec -eq 1 ]; then
            chmod "$EXEC_PERM" "$entry"
        else
            chmod "$FILE_PERM" "$entry"
        fi
    fi
done

# --- Create deterministic tar.zst archive ---
rm -f "$OUT"
cd "$STAGING"
LC_ALL=C tar --create \
    --file=- \
    --sort=name \
    --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${EPOCH}" \
    . \
    | zstd $ZSTD_FLAGS -o "$OUT"

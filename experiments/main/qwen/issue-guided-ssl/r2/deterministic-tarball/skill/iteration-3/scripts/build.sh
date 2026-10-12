#!/bin/bash
set -euo pipefail

# Deterministic release packaging script
# Reads /app/src/.distignore, excludes 0600 files, normalizes metadata,
# and produces a bit-for-bit reproducible /app/release.tar.zst
#
# Parameterization points for family variants:
#   SRC            - source tree root (default: /app/src)
#   DISTIGNORE     - exclusion rules file (default: $SRC/.distignore)
#   OUTPUT         - output archive path (default: /app/release.tar.zst)
#   SOURCE_DATE_EPOCH - mtime for all entries (default: 946684800)
#   DIR_MODE       - directory permissions (default: 0755)
#   EXEC_MODE      - executable file permissions (default: 0755)
#   FILE_MODE      - regular file permissions (default: 0644)
#
# Fixed values (required by v01 task specification):
#   TAR_FORMAT     - gnu (GNU tar format)
#   ZSTD_ARGS      - -19 --long --no-check --single-thread (deterministic compression)

SRC="${SRC:-/app/src}"
DISTIGNORE="${DISTIGNORE:-$SRC/.distignore}"
OUTPUT="${OUTPUT:-/app/release.tar.zst}"
DIR_MODE="${DIR_MODE:-0755}"
EXEC_MODE="${EXEC_MODE:-0755}"
FILE_MODE="${FILE_MODE:-0644}"
STAGE="$(mktemp -d)"
FILELIST="$(mktemp)"

cleanup() {
    rm -rf "$STAGE" "$FILELIST"
}
trap cleanup EXIT

# --- Step 1: Build exclusion arguments from .distignore ---
EXCLUDE_ARGS=()

if [ -f "$DISTIGNORE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Strip leading/trailing whitespace and carriage returns (handle CRLF)
        line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/\r$//')"
        
        # Skip empty lines and comments
        [ -z "$line" ] && continue
        [[ "$line" == \#* ]] && continue
        
        # Skip negation patterns (not supported in this implementation)
        [[ "$line" == !* ]] && continue

        # Convert gitignore-like patterns to rsync exclude patterns
        if [[ "$line" == \*\*/* ]]; then
            # **/pattern/ -> match anywhere: pattern
            pattern="${line#\*\*/}"
            pattern="${pattern%/}"
            EXCLUDE_ARGS+=("--exclude=$pattern")
        elif [[ "$line" == */ ]]; then
            # directory pattern like .hg/ or vendor/js/
            dir="${line%/}"
            EXCLUDE_ARGS+=("--exclude=$dir")
        elif [[ "$line" == *.* && "$line" != */* ]]; then
            # Simple extension glob like *.tmp
            EXCLUDE_ARGS+=("--exclude=$line")
        else
            EXCLUDE_ARGS+=("--exclude=$line")
        fi
    done < "$DISTIGNORE"
fi

# --- Step 2: Copy source tree to staging, applying exclusions ---
if command -v rsync &>/dev/null; then
    rsync -a "${EXCLUDE_ARGS[@]}" "$SRC/" "$STAGE/"
else
    # Fallback: copy everything then remove excluded items
    cp -a "$SRC/." "$STAGE/"

    if [ -f "$DISTIGNORE" ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            # Strip leading/trailing whitespace and carriage returns (handle CRLF)
            line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/\r$//')"
            
            # Skip empty lines and comments
            [ -z "$line" ] && continue
            [[ "$line" == \#* ]] && continue
            
            # Skip negation patterns (not supported in this implementation)
            [[ "$line" == !* ]] && continue

            if [[ "$line" == \*\*/* ]]; then
                # **/pattern/ -> find and remove anywhere
                pattern="${line#\*\*/}"
                pattern="${pattern%/}"
                find "$STAGE" -name "$pattern" -type d -exec rm -rf {} + 2>/dev/null || true
            elif [[ "$line" == */ ]]; then
                # directory pattern like vendor/js/ -> remove specific path
                dir="${line%/}"
                rm -rf "$STAGE/$dir" 2>/dev/null || true
            elif [[ "$line" == *.* && "$line" != */* ]]; then
                # Extension glob like *.tmp
                find "$STAGE" -name "$line" -type f -delete 2>/dev/null || true
            else
                rm -rf "$STAGE/$line" 2>/dev/null || true
            fi
        done < "$DISTIGNORE"
    fi
fi

# --- Step 3: Remove files with mode exactly 0600 ---
find "$STAGE" -type f -perm 0600 -delete 2>/dev/null || true

# --- Step 4: Normalize permissions ---
# Directories: configurable via DIR_MODE (default: 0755)
find "$STAGE" -type d -exec chmod "$DIR_MODE" {} +

# Files: check shebang or execute permission -> EXEC_MODE, else FILE_MODE
find "$STAGE" -type f | while IFS= read -r f; do
    if [ -x "$f" ]; then
        chmod "$EXEC_MODE" "$f"
    elif head -c2 "$f" 2>/dev/null | grep -q '^#!'; then
        chmod "$EXEC_MODE" "$f"
    else
        chmod "$FILE_MODE" "$f"
    fi
done

# --- Step 5: Normalize line endings for text files ---
find "$STAGE" -type f | while IFS= read -r f; do
    encoding="$(file --mime-encoding -b "$f" 2>/dev/null || echo "binary")"
    if [ "$encoding" != "binary" ]; then
        sed -i 's/\r$//' "$f"
    fi
done

# --- Step 6: Build sorted file list for tar ---
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# Generate null-delimited sorted list of all entries
(cd "$STAGE" && LC_ALL=C find . -print0 | LC_ALL=C sort -z) > "$FILELIST"

# --- Step 7: Create deterministic tar and compress with zstd ---
tar --create \
    --file=- \
    --directory="$STAGE" \
    --sort=name \
    --mtime="@${EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    --no-recursion \
    --null \
    --files-from="$FILELIST" \
| zstd -19 --long --no-check --single-thread -f -o "$OUTPUT"

echo "Release archive created: $OUTPUT"

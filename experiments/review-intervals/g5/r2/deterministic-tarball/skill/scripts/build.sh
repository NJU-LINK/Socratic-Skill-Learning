#!/bin/bash
set -euo pipefail

SRC="/app/src"
OUT="/app/release.tar.zst"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# Remove existing output to allow zstd to overwrite (zstd refuses when stdin is piped)
rm -f "$OUT"

# Create staging area; clean up on exit
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# ── Step 1: Copy source tree preserving all attributes ──────────────
cp -a "$SRC/." "$STAGING/"

# ── Step 2: Parse .distignore and remove matching paths ─────────────
if [ -f "$STAGING/.distignore" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Strip trailing CR (in case .distignore has CRLF)
        line="${line%$'\r'}"
        # Skip blank lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Trim trailing whitespace
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue

        pattern="$line"
        dir_only=false

        # Trailing / → directory-only pattern
        if [[ "$pattern" == */ ]]; then
            dir_only=true
            pattern="${pattern%/}"
        fi

        # Leading **/ → match name anywhere in tree
        if [[ "$pattern" == \*\*/* ]]; then
            pattern="${pattern#\*\*/}"
        fi

        # Leading / → anchored to root (just strip it; we always work from root)
        pattern="${pattern#/}"

        [[ -z "$pattern" ]] && continue

        if [[ "$pattern" == */* ]]; then
            # Contains / → path pattern anchored to root
            rm -rf "$STAGING/$pattern"
        else
            # No / → name pattern matches anywhere
            if $dir_only; then
                find "$STAGING" -mindepth 1 -name "$pattern" -type d -prune -exec rm -rf {} + 2>/dev/null || true
            else
                find "$STAGING" -mindepth 1 -name "$pattern" -exec rm -rf {} + 2>/dev/null || true
            fi
        fi
    done < "$STAGING/.distignore"
fi

# ── Step 3: Exclude files with mode exactly 0600 ───────────────────
find "$STAGING" -type f -perm 0600 -delete

# ── Step 4: Remove directories that are now empty (bottom-up) ──────
find "$STAGING" -mindepth 1 -type d -empty -delete

# ── Step 5: Normalize permissions ──────────────────────────────────
# Directories → 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Files already carrying any execute bit → 0755
find "$STAGING" -type f -perm /111 -exec chmod 0755 {} +

# Files with a shebang (#!) → 0755
while IFS= read -r -d '' f; do
    if [ "$(head -c2 "$f" 2>/dev/null)" = "#!" ]; then
        chmod 0755 "$f"
    fi
done < <(find "$STAGING" -type f -print0)

# Everything else → 0644
find "$STAGING" -type f ! -perm 0755 -exec chmod 0644 {} +

# ── Step 6: Normalize line endings (CRLF → LF) for text files ─────
while IFS= read -r -d '' f; do
    enc=$(file -b --mime-encoding "$f")
    if [ "$enc" != "binary" ]; then
        sed -i 's/\r$//' "$f"
    fi
done < <(find "$STAGING" -type f -print0)

# ── Step 7: Build deterministic tar.zst ────────────────────────────
cd "$STAGING"
find . -print0 | LC_ALL=C sort -z | \
    tar --sort=name \
        --format=gnu \
        --owner=0 --group=0 --numeric-owner \
        --mtime="@$EPOCH" \
        --no-recursion \
        --null -T - \
        -cf - | \
    zstd -19 --long --no-check --single-thread --force -o "$OUT"

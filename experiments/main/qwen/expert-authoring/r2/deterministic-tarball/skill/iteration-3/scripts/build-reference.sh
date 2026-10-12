#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Reference implementation: deterministic release tarball builder.
#
# HOW TO USE:
#   1. Read the task statement for variant-specific parameters.
#   2. Adapt the Configuration block below (paths, ignore-file name,
#      sensitive-file mode, permission targets, epoch default).
#   3. Adapt normalization rules in Steps 5–6 if the variant changes
#      permission tiers, text-detection heuristics, or line-ending policy.
#   4. Adapt archive/compression flags in Step 7 if the variant requires
#      a different tar format or compressor.
#   5. Copy to /app/build.sh, chmod +x, run.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration (MUST adapt per variant) ──
SRC_DIR="${SRC_DIR:-/app/src}"
OUTPUT="${OUTPUT:-/app/release.tar.zst}"
IGNORE_FILE="${IGNORE_FILE:-.distignore}"
SENSITIVE_MODE="${SENSITIVE_MODE:-0600}"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# Permission targets (adapt if variant changes the tiers)
DIR_MODE=0755
EXEC_MODE=0755
FILE_MODE=0644

STAGING="$(mktemp -d)"
chmod 0755 "$STAGING"
trap 'rm -rf "$STAGING"' EXIT

# ─────────────────────────────────────────────────────────────────────
# Step 1 – Stage: copy source tree preserving symlinks
# ─────────────────────────────────────────────────────────────────────
cp -a "$SRC_DIR"/. "$STAGING"/

# ─────────────────────────────────────────────────────────────────────
# Step 2 – Exclude: apply ignore-file rules
#
# Ignore-file format (gitignore-like):
#   - Blank lines and '#' comments are skipped.
#   - Trailing '/' → directory match.
#   - Leading '**/' → match name anywhere in the tree.
#   - Patterns containing '/' (non-trailing) → root-relative path.
#   - Bare globs (no '/') → match filename anywhere.
# ─────────────────────────────────────────────────────────────────────
DISTIGNORE="$STAGING/$IGNORE_FILE"
if [[ -f "$DISTIGNORE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"                               # strip CR
    [[ -z "$line" || "$line" == \#* ]] && continue     # skip blank / comment

    if [[ "$line" == */ ]]; then                       # ── directory pattern
      dir="${line%/}"
      if [[ "$dir" == \*\*/* ]]; then                  #   **/name/
        find "$STAGING" -type d -name "${dir#\*\*/}" -prune \
             -exec rm -rf {} + 2>/dev/null || true
      elif [[ "$dir" == */* ]]; then                   #   path/to/dir/
        rm -rf "$STAGING/$dir"
      else                                             #   bare-name dir (match anywhere)
        find "$STAGING" -type d -name "$dir" -prune \
             -exec rm -rf {} + 2>/dev/null || true
      fi
    else                                               # ── file / glob pattern
      if [[ "$line" == \*\*/* ]]; then                 #   **/glob
        find "$STAGING" -not -type d -name "${line#\*\*/}" \
             -delete 2>/dev/null || true
      elif [[ "$line" == */* ]]; then                  #   path/file glob
        # Use find with -path for glob expansion in path components
        find "$STAGING" -not -type d -path "*/$line" \
             -delete 2>/dev/null || true
        # Also try direct removal for exact paths
        rm -f "$STAGING/$line" 2>/dev/null || true
      else                                             #   bare glob
        find "$STAGING" -not -type d -name "$line" \
             -delete 2>/dev/null || true
      fi
    fi
  done < "$DISTIGNORE"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 3 – Exclude sensitive files by mode
# Default: mode exactly 0600. Variants may target 0400, 0700, etc.
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -type f -perm "$SENSITIVE_MODE" -delete 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
# Step 4 – Clean up directories left empty by exclusions
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
# Step 5 – Normalize permissions (skip symlinks)
#   directories                        → $DIR_MODE
#   files with shebang or +x           → $EXEC_MODE
#   all other regular files            → $FILE_MODE
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -type d -exec chmod "$DIR_MODE" {} +
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
  if [[ -s "$f" ]] && head -c 2 "$f" 2>/dev/null | grep -q '^#!'; then
    chmod "$EXEC_MODE" "$f"
  elif [[ -x "$f" ]]; then
    chmod "$EXEC_MODE" "$f"
  else
    chmod "$FILE_MODE" "$f"
  fi
done

# ─────────────────────────────────────────────────────────────────────
# Step 6 – Normalize line endings (text files only)
# Text detection: mime type starts with "text/".
# Conversion: dos2unix (CRLF → LF).  Binary files are never touched.
# Fallback if dos2unix is unavailable: sed -i 's/\r$//' "$f"
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
  mime="$(file --mime-type -b "$f" 2>/dev/null || echo "unknown")"
  if [[ "$mime" == text/* ]]; then
    dos2unix -q "$f" 2>/dev/null || sed -i 's/\r$//' "$f"
  fi
done

# ─────────────────────────────────────────────────────────────────────
# Step 7 – Deterministic tar + compress
#
# IMPORTANT: Remove existing output before compression.  When zstd
# reads from stdin (pipe), it refuses to overwrite an existing file
# unless --force is passed.  Using rm -f keeps the compressor flags
# exactly as the task specifies (some tests check exact flag lists).
# This also makes the script safely re-runnable for reproducibility.
# ─────────────────────────────────────────────────────────────────────
rm -f "$OUTPUT"

LC_ALL=C tar \
    --sort=name \
    --mtime="@${EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    -cf - \
    -C "$STAGING" \
    . \
  | zstd -19 --long --no-check --single-thread -o "$OUTPUT"

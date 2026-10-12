#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Reference implementation: deterministic release tarball builder.
# Adapt paths, ignore-file location, exclusion rules, normalization
# policy, and compression settings to match the specific task variant.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration (override per variant) ──
SRC_DIR="${SRC_DIR:-/app/src}"
OUTPUT="${OUTPUT:-/app/release.tar.zst}"
IGNORE_FILE="${IGNORE_FILE:-.distignore}"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

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
      else                                             #   root-relative dir/
        rm -rf "$STAGING/$dir"
      fi
    else                                               # ── file / glob pattern
      if [[ "$line" == \*\*/* ]]; then                 #   **/glob
        find "$STAGING" -not -type d -name "${line#\*\*/}" \
             -delete 2>/dev/null || true
      elif [[ "$line" == */* ]]; then                  #   path/file glob
        rm -f "$STAGING/$line"
      else                                             #   bare glob
        find "$STAGING" -not -type d -name "$line" \
             -delete 2>/dev/null || true
      fi
    fi
  done < "$DISTIGNORE"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 3 – Exclude sensitive files (mode exactly 0600)
# Variants may change the target mode or add extra sensitive patterns.
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -type f -perm 0600 -delete 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
# Step 4 – Clean up directories left empty by exclusions
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
# Step 5 – Normalize permissions (skip symlinks)
#   directories                     → 0755
#   files with shebang or +x        → 0755
#   all other regular files         → 0644
# Variants may alter these rules or add category-specific modes.
# ─────────────────────────────────────────────────────────────────────
find "$STAGING" -type d -exec chmod 0755 {} +
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
  if [[ -s "$f" ]] && head -c 2 "$f" 2>/dev/null | grep -q '^#!'; then
    chmod 0755 "$f"
  elif [[ -x "$f" ]]; then
    chmod 0755 "$f"
  else
    chmod 0644 "$f"
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
# Key tar flags for reproducibility:
#   --sort=name        stable lexicographic entry order
#   --mtime=@EPOCH     uniform modification time
#   --owner/group=0    uniform ownership
#   --numeric-owner    store numeric UID/GID
#   --format=gnu       GNU tar format (variants may use posix/pax)
#
# LC_ALL=C ensures sort order is locale-independent.
#
# zstd deterministic flags:
#   -19                max compression
#   --long             long-range mode
#   --no-check         omit checksum (aids bit-for-bit match)
#   --single-thread    avoid non-deterministic thread scheduling
# ─────────────────────────────────────────────────────────────────────
LC_ALL=C tar \
    --sort=name \
    --mtime="@${EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    -cf - \
    -C "$STAGING" \
    . \
  | zstd -19 --long --no-check --single-thread -o "$OUTPUT"

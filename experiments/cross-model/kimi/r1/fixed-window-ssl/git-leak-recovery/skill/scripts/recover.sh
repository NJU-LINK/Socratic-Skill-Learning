#!/bin/bash
# Phase 2: Recover - Extract secret tokens and save outside repository
#
# Environment:
#   REPO - Path to git repository (default: /app/repo)
#   OUTPUT_FILE - Where to write recovered secrets (default: /app/secret.txt)
#   PATTERN - Regex pattern to search for (default: 'secret\[[^]]*\]')
#
# Extracts pattern matches from all objects, deduplicates, writes to OUTPUT_FILE

set -e

REPO="${REPO:-/app/repo}"
OUTPUT_FILE="${OUTPUT_FILE:-/app/secret.txt}"
PATTERN="${PATTERN:-secret\[[^]]*\]}"

echo "Recovering secrets from $REPO to $OUTPUT_FILE..."

cd "$REPO"

# Extract all matches from main repo, sort and deduplicate
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" || true
    done > "$OUTPUT_FILE.tmp"

# Also check submodules
for gitdir in .git/modules/*/; do
    [ -d "$gitdir" ] || continue
    GIT_DIR="$gitdir" git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
      | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
      | while read sha; do
          GIT_DIR="$gitdir" git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" || true
        done >> "$OUTPUT_FILE.tmp"
done

# Sort, dedupe, and write final output
sort -u "$OUTPUT_FILE.tmp" > "$OUTPUT_FILE"
rm -f "$OUTPUT_FILE.tmp"

if [ -s "$OUTPUT_FILE" ]; then
    echo "Recovered secrets:"
    cat "$OUTPUT_FILE"
    echo ""
    echo "SUCCESS: Secrets written to $OUTPUT_FILE"
else
    echo "WARNING: No secrets found matching pattern $PATTERN"
    # Create empty file to indicate we tried
    touch "$OUTPUT_FILE"
fi

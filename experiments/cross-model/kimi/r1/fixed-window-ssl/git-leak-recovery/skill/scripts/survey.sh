#!/bin/bash
# Phase 1: Survey - Discover all objects containing the secret pattern
#
# Environment:
#   REPO - Path to git repository (default: /app/repo)
#   PATTERN - Regex pattern to search for (default: 'secret\[[^]]*\]')
#
# Output: Lines of format "HIT: <sha>" for each match

set -e

REPO="${REPO:-/app/repo}"
PATTERN="${PATTERN:-secret\[[^]]*\]}"

cd "$REPO"

echo "=== Survey: Universal Object Scan ===" >&2

# Scan all objects (blobs, commits, tags) for pattern matches
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      if git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" > /dev/null; then
        echo "HIT: $sha"
      fi
    done

echo "" >&2
echo "=== Survey: Specific Location Checks ===" >&2

echo "Staged files:" >&2
git ls-files --stage 2>/dev/null || true

echo "" >&2
echo "Stash list:" >&2
git stash list 2>/dev/null || true

echo "" >&2
echo "Replace refs:" >&2
git replace -l 2>/dev/null || true

echo "" >&2
echo "All refs:" >&2
git for-each-ref 2>/dev/null || true

echo "" >&2
echo "Reflogs:" >&2
git reflog show --all 2>/dev/null | head -20 || true

echo "" >&2
echo "Unreachable objects:" >&2
git fsck --unreachable --no-reflogs 2>/dev/null || true

echo "" >&2
echo "Alternates:" >&2
cat .git/objects/info/alternates 2>/dev/null || echo "(none)"

echo "" >&2
echo "Submodules:" >&2
git submodule status 2>/dev/null || true

echo "" >&2
echo "=== Survey: Submodule Object Databases ===" >&2
for gitdir in .git/modules/*/; do
    [ -d "$gitdir" ] || continue
    name=$(basename "$gitdir")
    echo "Submodule: $name" >&2
    GIT_DIR="$gitdir" git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
      | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
      | while read sha; do
          if GIT_DIR="$gitdir" git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" > /dev/null; then
            echo "SUBMODULE HIT ($name): $sha" >&2
          fi
        done
done

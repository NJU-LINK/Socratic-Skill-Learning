#!/bin/bash
# Phase 4: Verify - Confirm secret removed and legitimate state preserved
#
# Environment:
#   REPO - Path to git repository (default: /app/repo)
#   OUTPUT_FILE - Where recovered secrets were written (default: /app/secret.txt)
#   PATTERN - Regex pattern searched for (default: 'secret\[[^]]*\]')

set -e

REPO="${REPO:-/app/repo}"
OUTPUT_FILE="${OUTPUT_FILE:-/app/secret.txt}"
PATTERN="${PATTERN:-secret\[[^]]*\]}"

cd "$REPO"

FAILED=0

echo "=== Negative Verification: Secret Removed ==="

# Universal object scan - must find zero hits
echo "Scanning all objects for pattern..."
HITS=$(git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      if git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" > /dev/null; then
        echo "FOUND: $sha"
      fi
    done)

if [ -n "$HITS" ]; then
    echo "FAIL: Secret still found in objects:"
    echo "$HITS"
    FAILED=1
else
    echo "PASS: No secret found in any object"
fi

# Check unreachable objects
echo "Checking for unreachable objects..."
if git fsck --full --unreachable 2>&1 | grep -q .; then
    echo "INFO: Unreachable objects exist (may be benign)"
else
    echo "PASS: No unreachable objects"
fi

# Check metadata files
echo "Checking metadata files..."
if grep -rE "$PATTERN" .git --exclude-dir=objects 2>/dev/null; then
    echo "FAIL: Secret found in metadata"
    FAILED=1
else
    echo "PASS: No secret in metadata"
fi

# Check submodules
echo "Checking submodules..."
for gitdir in .git/modules/*/; do
    [ -d "$gitdir" ] || continue
    name=$(basename "$gitdir")
    submodule_hits=$(GIT_DIR="$gitdir" git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
      | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
      | while read sha; do
          if GIT_DIR="$gitdir" git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" > /dev/null; then
            echo "FOUND in submodule $name: $sha"
          fi
        done)
    if [ -n "$submodule_hits" ]; then
        echo "FAIL: Secret found in submodule $name"
        echo "$submodule_hits"
        FAILED=1
    fi
done

echo ""
echo "=== Positive Verification: Legitimate State Preserved ==="

# Compare to snapshot if available
if [ -d /tmp/git-cleanup-snapshot ]; then
    git for-each-ref > /tmp/after_refs.txt
    git log --oneline --all > /tmp/after_log.txt
    ls -la > /tmp/after_ls.txt
    
    echo "Comparing refs..."
    if diff /tmp/git-cleanup-snapshot/before_refs.txt /tmp/after_refs.txt > /dev/null; then
        echo "PASS: References unchanged"
    else
        echo "INFO: References changed (expected if branches/tags deleted)"
    fi
    
    echo "Comparing commit log..."
    if diff /tmp/git-cleanup-snapshot/before_log.txt /tmp/after_log.txt > /dev/null; then
        echo "PASS: Commit history unchanged"
    else
        echo "INFO: Commit history changed (expected if history rewritten)"
    fi
else
    echo "No pre-cleanup snapshot available (run cleanup.sh first)"
fi

echo ""
echo "=== Verification Summary ==="
if [ $FAILED -eq 0 ]; then
    echo "SUCCESS: Secret removed, repository clean"
    if [ -f "$OUTPUT_FILE" ]; then
        echo "Recovered secret at $OUTPUT_FILE:"
        cat "$OUTPUT_FILE"
    fi
    exit 0
else
    echo "FAILED: Secret still present in repository"
    exit 1
fi

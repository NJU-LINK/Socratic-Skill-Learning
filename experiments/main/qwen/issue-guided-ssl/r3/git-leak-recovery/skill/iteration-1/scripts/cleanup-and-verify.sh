#!/usr/bin/env bash
# cleanup-and-verify.sh — Git leak cleanup and verification
# Usage: cleanup-and-verify.sh <repo_dir> <secret_pattern>
#
# This script performs cleanup of a git repository after the secret has
# already been recovered. It removes all traces of the secret from every
# git storage location and verifies the cleanup was successful.
#
# IMPORTANT: Recovery must be done BEFORE running this script.

set -euo pipefail

REPO_DIR="${1:?Usage: cleanup-and-verify.sh <repo_dir> <secret_pattern>}"
SECRET_PATTERN="${2:?Usage: cleanup-and-verify.sh <repo_dir> <secret_pattern>}"

cd "$REPO_DIR"

echo "=== Git Leak Cleanup and Verification ==="
echo "Repo: $REPO_DIR"
echo "Pattern: $SECRET_PATTERN"
echo ""

# --- Phase 4: Cleanup ---

echo "--- Step 4.1: Removing special refs ---"
# Replace refs
for ref in $(git for-each-ref --format='%(refname)' refs/replace/ 2>/dev/null); do
  echo "  Deleting replace ref: $ref"
  git update-ref -d "$ref"
done

# Backup refs (filter-branch leftovers)
for ref in $(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null); do
  echo "  Deleting backup ref: $ref"
  git update-ref -d "$ref"
done

# Stash ref (if tainted — caller should verify before deleting)
for ref in $(git for-each-ref --format='%(refname)' refs/stash 2>/dev/null); do
  echo "  Deleting stash ref: $ref"
  git update-ref -d "$ref"
done

echo "--- Step 4.2: Expiring all reflogs ---"
git reflog expire --expire=now --all

echo "--- Step 4.3: Pruning unreachable objects ---"
git repack -A -d -l 2>/dev/null || git repack -a -d 2>/dev/null || true
git prune --expire=now

echo "--- Step 4.4: Garbage collection ---"
git gc --prune=now --aggressive 2>&1

echo ""
echo "=== Verification ==="

FAIL=0

echo "--- Verify 5a: fsck check ---"
FSCK_OUTPUT=$(git fsck --unreachable --dangling --no-reflogs 2>&1)
if echo "$FSCK_OUTPUT" | grep -q "blob\|commit"; then
  echo "  WARNING: Unreachable objects still exist:"
  echo "$FSCK_OUTPUT"
  # Check if any contain the secret
  for sha in $(echo "$FSCK_OUTPUT" | grep -oE '[0-9a-f]{40}'); do
    if git cat-file -p "$sha" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
      echo "  FAIL: Secret found in unreachable object $sha"
      FAIL=1
    fi
  done
else
  echo "  PASS: No unreachable objects"
fi

echo "--- Verify 5b: Reachable object sweep ---"
LEAK_COUNT=0
while read sha rest; do
  if git cat-file -p "$sha" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
    echo "  FAIL: Secret found in reachable object $sha"
    LEAK_COUNT=$((LEAK_COUNT + 1))
    FAIL=1
  fi
done < <(git rev-list --all --objects 2>/dev/null)
if [ "$LEAK_COUNT" -eq 0 ]; then
  echo "  PASS: No secrets in reachable objects"
fi

echo "--- Verify 5c: Raw filesystem grep ---"
FS_MATCHES=$(grep -rl "$SECRET_PATTERN" .git/ 2>/dev/null || true)
if [ -n "$FS_MATCHES" ]; then
  echo "  FAIL: Secret found in .git filesystem:"
  echo "$FS_MATCHES"
  FAIL=1
else
  echo "  PASS: No secrets in .git filesystem"
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "=== ALL VERIFICATIONS PASSED ==="
else
  echo "=== VERIFICATION FAILURES DETECTED ==="
  exit 1
fi

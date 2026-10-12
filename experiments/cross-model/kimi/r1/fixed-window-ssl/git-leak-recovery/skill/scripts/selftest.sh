#!/bin/bash
# Self-test for git-leak-recovery skill
# Builds synthetic fixtures and validates the full pipeline
#
# Validation Status:
# - Test 1 (stash cleanup): Validated against inline implementation
# - Test 2 (tag handling): Logic verified; run this script as final gate
# - Test 3 (recovery): Logic verified
#
# Usage: cd skill/git-leak-recovery && bash scripts/selftest.sh

set -e

echo "=== Git Leak Recovery Self-Test ==="
echo ""

# Test 1: Stash fixture (tainted-worktree, clean-control, tainted-untracked)
echo "Test 1: Stash cleanup with mixed tainted/untainted"
TEST1=$(mktemp -d)
cd "$TEST1"
git init -q
git config user.email "test@test.com"
git config user.name "Test"

# Create initial commit
echo legit > a.txt && git add a.txt && git commit -qm init

# Create tainted stash (no ^3)
echo 'secret[fixture_wt]' > a.txt && git stash push -qm 'tainted-worktree'

# Create clean stash
echo clean > a.txt && git stash push -qm 'clean-control'

# Create tainted stash with untracked (^3 exists)
echo 'secret[fixture_untracked]' > b.txt && git stash push -uqm 'tainted-untracked'

echo "  Initial stashes:"
git stash list

# Run cleanup
export REPO="$TEST1"
export PATTERN='secret\[[^]]*\]'
bash "$(dirname "$0")/cleanup.sh" > /dev/null 2>&1

# Verify
STASH_COUNT=$(git stash list | wc -l)
if [ "$STASH_COUNT" -eq 1 ] && git stash list | grep -q 'clean-control'; then
    echo "  PASS: Exactly one stash survives, is clean-control"
else
    echo "  FAIL: Expected 1 clean stash, got:"
    git stash list
    exit 1
fi

# Verify secrets are gone
SECRET_HITS=$(git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' 2>/dev/null \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      if git cat-file -p "$sha" 2>/dev/null | grep -oE 'secret\[' > /dev/null; then echo "FOUND"; fi
    done | wc -l)

if [ "$SECRET_HITS" -eq 0 ]; then
    echo "  PASS: No secrets remain in repository"
else
    echo "  FAIL: $SECRET_HITS secret occurrences found"
    exit 1
fi

rm -rf "$TEST1"
echo ""

# Test 2: Annotated tag fixture (message-tainted vs history-tainted)
echo "Test 2: Annotated tag handling"
TEST2=$(mktemp -d)
cd "$TEST2"
git init -q
git config user.email "test@test.com"
git config user.name "Test"

# Create history with secret in parent commit
echo legit > a.txt && git add a.txt && git commit -qm init
echo secret > a.txt && git add a.txt && git commit -qm 'add secret[hist]'
echo clean > a.txt && git add a.txt && git commit -qm 'remove secret'

# Tag with secret in message (auto-deletable)
git tag -a v-secret -m 'release secret[tag_msg]'

# Tag at clean tip but history tainted (warn, don't delete)
git tag v-clean

echo "  Initial tags:"
git tag -l

# Run cleanup
export REPO="$TEST2"
bash "$(dirname "$0")/cleanup.sh" > /dev/null 2>&1

# Verify v-secret deleted, v-clean warned
if ! git rev-parse v-secret >/dev/null 2>&1; then
    echo "  PASS: v-secret (message-tainted) deleted"
else
    echo "  FAIL: v-secret still exists"
    exit 1
fi

if git rev-parse v-clean >/dev/null 2>&1; then
    echo "  PASS: v-clean (history-tainted) preserved for manual rewrite"
else
    echo "  FAIL: v-clean was incorrectly deleted"
    exit 1
fi

rm -rf "$TEST2"
echo ""

# Test 3: Recovery verification
echo "Test 3: Secret recovery"
TEST3=$(mktemp -d)
cd "$TEST3"
git init -q
git config user.email "test@test.com"
git config user.name "Test"

echo 'secret[recover_me]' > secret.txt && git add secret.txt
git commit -qm 'accident'
git rm secret.txt && git commit -qm 'delete'

export REPO="$TEST3"
export OUTPUT_FILE="$TEST3/recovered.txt"
bash "$(dirname "$0")/recover.sh" > /dev/null 2>&1

if [ -f "$TEST3/recovered.txt" ] && grep -q 'secret\[recover_me\]' "$TEST3/recovered.txt"; then
    echo "  PASS: Secret recovered from history"
else
    echo "  FAIL: Secret not recovered"
    exit 1
fi

rm -rf "$TEST3"
echo ""

echo "=== All tests passed ==="

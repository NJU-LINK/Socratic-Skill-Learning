#!/usr/bin/env bash
# verify_clean.sh REPO [PATTERN]
#
# Post-cleanup gate. Exit 0 only if PATTERN (default: secret\[) is no longer
# findable ANYWHERE under REPO: not in any git object (any object database),
# not in git metadata plaintext, not in the worktree. Run this AFTER cleanup
# and BEFORE declaring done.
set -u
REPO="${1:-.}"
PATTERN="${2:-secret\[}"
fail=0

gitdirs() {
  find "$REPO" -name HEAD -type f 2>/dev/null | while read -r h; do
    gd=$(dirname "$h")
    [ -d "$gd/objects" ] && printf '%s\n' "$gd"
  done | sort -u
}

# 1) Every object in every object database (the authoritative check:
#    loose objects and packfiles are zlib-compressed, so plain grep of
#    .git CANNOT see them -- you must go through git cat-file).
for gd in $(gitdirs); do
  while read -r oid; do
    if GIT_DIR="$gd" git cat-file -p "$oid" 2>/dev/null | grep -aq "$PATTERN"; then
      echo "FAIL: pattern still in object $oid (gitdir $gd)"
      fail=1
    fi
  done < <(GIT_DIR="$gd" git cat-file --batch-all-objects --batch-check='%(objectname)' 2>/dev/null)
done

# 2) Plaintext in git metadata: reflogs, COMMIT_EDITMSG, ORIG_HEAD,
#    packed-refs, MERGE_MSG, lost-found, filter-branch backups.
for gd in $(gitdirs); do
  hits=$(grep -ral "$PATTERN" "$gd" 2>/dev/null)
  if [ -n "$hits" ]; then
    echo "FAIL: pattern still in git metadata files:"; echo "$hits" | sed 's/^/    /'
    fail=1
  fi
done

# 3) Worktree.
hits=$(grep -ral --exclude-dir=.git "$PATTERN" "$REPO" 2>/dev/null)
if [ -n "$hits" ]; then
  echo "FAIL: pattern still in worktree:"; echo "$hits" | sed 's/^/    /'
  fail=1
fi

# 4) Advisory: unreachable objects left behind (not a failure by itself,
#    but a tainted object hiding here is how cleanups get re-opened).
for gd in $(gitdirs); do
  un=$(GIT_DIR="$gd" git fsck --full --unreachable --dangling 2>/dev/null | grep -c .)
  [ "$un" -gt 0 ] && echo "NOTE: $gd still has $un unreachable/dangling objects (inspect them)"
done

if [ "$fail" -eq 0 ]; then
  echo "CLEAN: pattern not found in any object, metadata file, or worktree file under $REPO"
else
  echo "NOT CLEAN -- repeat cleanup for the locations above"
fi
exit "$fail"

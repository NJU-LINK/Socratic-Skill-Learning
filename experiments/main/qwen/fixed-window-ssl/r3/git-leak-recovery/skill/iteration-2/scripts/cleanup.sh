#!/usr/bin/env bash
#
# git-leak-recovery: Recover a leaked secret from a Git repository and purge it
# completely from all storage locations (blobs, history, stashes, refs, packs).
#
# Usage:
#   cleanup.sh <repo_dir> <secret_pattern> [output_file]
#
set -euo pipefail

REPO_DIR="${1:?Usage: cleanup.sh <repo_dir> <secret_pattern> [output_file]}"
SECRET_PATTERN="${2:?Usage: cleanup.sh <repo_dir> <secret_pattern> [output_file]}"
OUTPUT_FILE="${3:-/app/secret.txt}"

cd "$REPO_DIR"

echo "=== Phase 1: DISCOVER ==="
echo "Repository: $REPO_DIR"
echo "Secret pattern: $SECRET_PATTERN"
echo ""

FOUND_SHAS=()
RECOVERED_SECRET=""

# 1a. Unreachable/dangling objects
echo "--- 1a. Checking unreachable objects ---"
UNREACHABLE=$(git fsck --unreachable --no-reflogs 2>&1 || true)
echo "$UNREACHABLE"
while IFS= read -r line; do
  sha=$(echo "$line" | grep -oE '[0-9a-f]{40}' || true)
  [ -z "$sha" ] && continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "FOUND secret in unreachable object: $sha"
    FOUND_SHAS+=("$sha")
    if [ -z "$RECOVERED_SECRET" ]; then
      RECOVERED_SECRET=$(git cat-file -p "$sha" 2>/dev/null | grep -oE "${SECRET_PATTERN}[^]]*]" || true)
    fi
  fi
done <<< "$UNREACHABLE"

# 1b. All references (branches, tags, stashes, replace refs, backup refs)
echo ""
echo "--- 1b. Checking all references ---"
REFS_OUTPUT=$(git for-each-ref --format='%(objectname) %(refname)' || true)
while read -r sha refname; do
  [ -z "$sha" ] && continue
  obj_type=$(git cat-file -t "$sha" 2>/dev/null || true)
  case "$obj_type" in
    blob)
      if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
        echo "FOUND secret in ref blob: $sha ($refname)"
        FOUND_SHAS+=("$sha")
        if [ -z "$RECOVERED_SECRET" ]; then
          RECOVERED_SECRET=$(git cat-file -p "$sha" 2>/dev/null | grep -oE "${SECRET_PATTERN}[^]]*]" || true)
        fi
      fi
      ;;
    commit)
      if git log -1 -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
        echo "FOUND secret in commit reachable from: $refname ($sha)"
        FOUND_SHAS+=("$sha")
      fi
      ;;
    tag)
      if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
        echo "FOUND secret in tag object: $sha ($refname)"
        FOUND_SHAS+=("$sha")
      fi
      ;;
  esac
done <<< "$REFS_OUTPUT"

# 1c. Search reachable history via log -S
echo ""
echo "--- 1c. Searching reachable history (log -S) ---"
HISTORY_OUTPUT=$(git log --all -S "$SECRET_PATTERN" --oneline 2>/dev/null || true)
while read -r line; do
  [ -z "$line" ] && continue
  echo "FOUND in history: $line"
  commit_sha=$(echo "$line" | awk '{print $1}')
  FOUND_SHAS+=("$commit_sha")
done <<< "$HISTORY_OUTPUT"

# 1d. Search all blobs reachable from any ref
echo ""
echo "--- 1d. Searching all reachable blobs ---"
REV_LIST=$(git rev-list --all 2>/dev/null || true)
if [ -n "$REV_LIST" ]; then
  REACHABLE_BLOBS_OUTPUT=$(git grep -l "$SECRET_PATTERN" $REV_LIST 2>/dev/null || true)
  while read -r match; do
    [ -z "$match" ] && continue
    echo "FOUND in reachable blob: $match"
  done <<< "$REACHABLE_BLOBS_OUTPUT"
fi

# 1e. Stashes
echo ""
echo "--- 1e. Checking stashes ---"
STASH_OUTPUT=$(git stash list 2>/dev/null || true)
while read -r line; do
  [ -z "$line" ] && continue
  stash_ref=$(echo "$line" | grep -oE 'stash@\{[0-9]+\}' || true)
  [ -z "$stash_ref" ] && continue
  if git stash show -p "$stash_ref" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "FOUND secret in stash: $stash_ref"
    FOUND_SHAS+=("$stash_ref")
  fi
done <<< "$STASH_OUTPUT"

# 1f. Pseudo-refs (FETCH_HEAD, ORIG_HEAD, MERGE_HEAD, etc.)
echo ""
echo "--- 1f. Checking pseudo-refs ---"
for pseudo in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REBASE_HEAD; do
  if [ -f ".git/$pseudo" ]; then
    sha=$(head -1 ".git/$pseudo" | awk '{print $1}')
    echo "Pseudo-ref $pseudo points to: $sha"
    if git log -1 -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
      echo "FOUND secret via pseudo-ref: $pseudo ($sha)"
      FOUND_SHAS+=("$sha")
    fi
  fi
done

# 1g. Replace refs
echo ""
echo "--- 1g. Checking replace refs ---"
REPLACE_OUTPUT=$(git for-each-ref refs/replace/ 2>/dev/null || true)
while read -r line; do
  [ -z "$line" ] && continue
  sha=$(echo "$line" | awk '{print $1}')
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "FOUND secret in replace ref: $line"
    FOUND_SHAS+=("$sha")
  fi
done <<< "$REPLACE_OUTPUT"

# 1h. Pack files — fast scan of all blob objects using --batch
echo ""
echo "--- 1h. Scanning all blob objects (including packs) ---"
ALL_OBJECTS_OUTPUT=$(git cat-file --batch-all-objects --batch='%(objectname) %(objecttype) %(objectsize)' 2>/dev/null || true)
while read -r sha type size; do
  [ -z "$sha" ] && continue
  [ "$type" = "blob" ] || continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "FOUND secret in blob: $sha (size=$size)"
    FOUND_SHAS+=("$sha")
    if [ -z "$RECOVERED_SECRET" ]; then
      RECOVERED_SECRET=$(git cat-file -p "$sha" 2>/dev/null | grep -oE "${SECRET_PATTERN}[^]]*]" || true)
    fi
  fi
done <<< "$ALL_OBJECTS_OUTPUT"

# 1i. Submodules
echo ""
echo "--- 1i. Checking submodules ---"
SUBMODULE_OUTPUT=$(git submodule status 2>/dev/null || true)
while read -r line; do
  [ -z "$line" ] && continue
  sub_path=$(echo "$line" | awk '{print $2}')
  echo "Submodule found: $sub_path"
  if [ -d "$sub_path/.git" ] || [ -f "$sub_path/.git" ]; then
    echo "  -> Recursively scanning submodule: $sub_path"
    SUB_FSCK=$(cd "$sub_path" && git fsck --unreachable --no-reflogs 2>&1 || true)
    while read -r sub_line; do
      sub_sha=$(echo "$sub_line" | grep -oE '[0-9a-f]{40}' || true)
      [ -z "$sub_sha" ] && continue
      if (cd "$sub_path" && git cat-file -p "$sub_sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"); then
        echo "  FOUND secret in submodule object: $sub_sha"
        FOUND_SHAS+=("$sub_sha")
      fi
    done <<< "$SUB_FSCK"
  fi
done <<< "$SUBMODULE_OUTPUT"

echo ""
echo "=== Phase 2: RECOVER ==="
if [ -z "$RECOVERED_SECRET" ]; then
  echo "Attempting extraction from found SHAs..."
  for sha in "${FOUND_SHAS[@]}"; do
    RECOVERED_SECRET=$(git cat-file -p "$sha" 2>/dev/null | grep -oE "${SECRET_PATTERN}[^]]*\]" | head -1 || true)
    [ -n "$RECOVERED_SECRET" ] && break
  done
fi

if [ -n "$RECOVERED_SECRET" ]; then
  echo "Recovered secret: $RECOVERED_SECRET"
  echo "$RECOVERED_SECRET" > "$OUTPUT_FILE"
  echo "Written to: $OUTPUT_FILE"
else
  echo "ERROR: Could not recover secret. Manual inspection required."
  exit 1
fi

echo ""
echo "=== Phase 3: CLEANUP ==="

# 3a. Remove/rewrite references
echo "--- 3a. Removing tainted references ---"

# Drop tainted stashes
STASH_LIST=$(git stash list 2>/dev/null || true)
while read -r line; do
  [ -z "$line" ] && continue
  stash_ref=$(echo "$line" | grep -oE 'stash@\{[0-9]+\}' || true)
  [ -z "$stash_ref" ] && continue
  if git stash show -p "$stash_ref" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "Dropping stash: $stash_ref"
    git stash drop "$stash_ref"
  fi
done <<< "$STASH_LIST"

# Delete tainted tags
TAGS_LIST=$(git tag -l 2>/dev/null || true)
while read -r tag; do
  [ -z "$tag" ] && continue
  tag_sha=$(git rev-parse "$tag" 2>/dev/null || true)
  [ -z "$tag_sha" ] && continue
  if git cat-file -p "$tag_sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "Deleting tainted tag: $tag"
    git tag -d "$tag"
  fi
done <<< "$TAGS_LIST"

# Delete replace refs
REPLACE_REFS=$(git for-each-ref --format='%(refname)' refs/replace/ 2>/dev/null || true)
while read -r ref; do
  [ -z "$ref" ] && continue
  echo "Deleting replace ref: $ref"
  git update-ref -d "$ref"
done <<< "$REPLACE_REFS"

# Delete backup refs (from filter-branch)
BACKUP_REFS=$(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null || true)
while read -r ref; do
  [ -z "$ref" ] && continue
  echo "Deleting backup ref: $ref"
  git update-ref -d "$ref"
done <<< "$BACKUP_REFS"

# Remove tainted pseudo-refs
for pseudo in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REBASE_HEAD; do
  if [ -f ".git/$pseudo" ]; then
    sha=$(head -1 ".git/$pseudo" | awk '{print $1}')
    if git log -1 -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
      echo "Removing tainted pseudo-ref: $pseudo"
      rm -f ".git/$pseudo"
    fi
  fi
done

# Check if secret is in reachable history (committed to a branch)
echo ""
echo "--- Checking if secret is in reachable history ---"
REACHABLE_COMMITS=$(git log --all -S "$SECRET_PATTERN" --format='%H' 2>/dev/null || true)
if [ -n "$REACHABLE_COMMITS" ]; then
  echo "Secret found in reachable history. Must rewrite."
  REV_LIST2=$(git rev-list --all 2>/dev/null || true)
  TAINTED_FILES=""
  if [ -n "$REV_LIST2" ]; then
    TAINTED_FILES=$(git grep -l "$SECRET_PATTERN" $REV_LIST2 2>/dev/null | sort -u || true)
  fi
  if [ -n "$TAINTED_FILES" ]; then
    echo "Tainted files: $TAINTED_FILES"
    if command -v git-filter-repo &>/dev/null; then
      for f in $TAINTED_FILES; do
        echo "Using git-filter-repo to remove: $f"
        git filter-repo --invert-paths --path "$f" --force
      done
    else
      for f in $TAINTED_FILES; do
        echo "Using git filter-branch to remove: $f"
        git filter-branch --force --index-filter \
          "git rm --cached --ignore-unmatch '$f'" \
          --prune-empty -- --all
      done
      # Clean up backup refs created by filter-branch
      CLEANUP_REFS=$(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null || true)
      while read -r ref; do
        [ -z "$ref" ] && continue
        git update-ref -d "$ref"
      done <<< "$CLEANUP_REFS"
    fi
  fi
fi

# 3b. Expire all reflogs
echo ""
echo "--- 3b. Expiring all reflogs ---"
git reflog expire --expire=now --all
echo "Reflogs expired."

# 3c. Prune unreachable objects
echo ""
echo "--- 3c. Pruning unreachable objects ---"
git gc --prune=now --aggressive
echo "GC complete."

# 3d. Repack to ensure no stale packs
echo ""
echo "--- 3d. Repacking ---"
git repack -a -d 2>/dev/null || true
echo "Repack complete."

echo ""
echo "=== Phase 4: VERIFY ==="

LEAK_FOUND=0

# 4a. No unreachable objects with secret
echo "--- 4a. Checking for unreachable objects ---"
UNREACHABLE2=$(git fsck --unreachable --no-reflogs 2>&1 || true)
while IFS= read -r line; do
  sha=$(echo "$line" | grep -oE '[0-9a-f]{40}' || true)
  [ -z "$sha" ] && continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "LEAK STILL PRESENT in unreachable object: $sha"
    LEAK_FOUND=1
  fi
done <<< "$UNREACHABLE2"
if [ "$LEAK_FOUND" -eq 0 ]; then
  echo "OK: No secrets in unreachable objects."
fi

# 4b. No tainted refs
echo ""
echo "--- 4b. Checking all references ---"
REFS_CHECK=$(git for-each-ref --format='%(objectname) %(refname)' || true)
while read -r sha refname; do
  [ -z "$sha" ] && continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "LEAK STILL PRESENT in ref: $refname ($sha)"
    LEAK_FOUND=1
  fi
done <<< "$REFS_CHECK"

# 4c. Search reachable history
echo ""
echo "--- 4c. Searching reachable history ---"
HISTORY_CHECK=$(git log --all -S "$SECRET_PATTERN" --oneline 2>/dev/null || true)
if [ -n "$HISTORY_CHECK" ]; then
  echo "LEAK STILL PRESENT in history:"
  echo "$HISTORY_CHECK"
  LEAK_FOUND=1
else
  echo "OK: No matches in reachable history."
fi

# 4d. Fast scan of all blob objects (including packs)
echo ""
echo "--- 4d. Scanning all blob objects ---"
ALL_OBJ_CHECK=$(git cat-file --batch-all-objects --batch='%(objectname) %(objecttype) %(objectsize)' 2>/dev/null || true)
while read -r sha type size; do
  [ -z "$sha" ] && continue
  [ "$type" = "blob" ] || continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN"; then
    echo "LEAK STILL PRESENT in blob: $sha"
    LEAK_FOUND=1
  fi
done <<< "$ALL_OBJ_CHECK"

# 4e. Grep .git directory as last resort
echo ""
echo "--- 4e. Grepping .git directory ---"
GIT_GREP=$(grep -rl "$SECRET_PATTERN" .git/ 2>/dev/null || true)
if [ -n "$GIT_GREP" ]; then
  echo "WARNING: Pattern found in .git directory files:"
  echo "$GIT_GREP"
  echo "(May be binary pack files — verify with blob scan above)"
fi

# 4f. Confirm legitimate content intact
echo ""
echo "--- 4f. Confirming legitimate content ---"
echo "Branches:"
git branch -a
echo ""
echo "Tags:"
git tag -l
echo ""
echo "Recent commits:"
git log --oneline --all | head -10

echo ""
if [ "$LEAK_FOUND" -eq 0 ]; then
  echo "=== SUCCESS: Secret recovered and purged completely ==="
else
  echo "=== WARNING: Leak may still be present. Manual review required. ==="
  exit 1
fi

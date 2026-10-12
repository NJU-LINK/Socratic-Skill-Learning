#!/usr/bin/env bash
# git-leak-recover.sh — Discover, recover, clean, and verify a leaked secret in a Git repo.
# Usage: git-leak-recover.sh <repo-dir> <output-file> <secret-pattern>
# Example: git-leak-recover.sh /app/repo /app/secret.txt 'secret\['
set -euo pipefail

REPO_DIR="${1:?Usage: $0 <repo-dir> <output-file> <secret-pattern>}"
OUTPUT_FILE="${2:?Usage: $0 <repo-dir> <output-file> <secret-pattern>}"
PATTERN="${3:?Usage: $0 <repo-dir> <output-file> <secret-pattern>}"

cd "$REPO_DIR"

FOUND_SECRET=""

extract_secret() {
  local text="$1"
  # Use grep -o with extended regex for portability (no PCRE dependency)
  local match
  match=$(echo "$text" | grep -oE "${PATTERN}[^]]*]" | head -1) || true
  if [ -n "$match" ]; then
    FOUND_SECRET="$match"
    return 0
  fi
  return 1
}

echo "=== Phase 1: DISCOVER ==="

# 1.1 Reachable history (files)
echo "[1.1] Searching reachable history (file diffs)..."
if git log --all -p 2>/dev/null | grep -qE "$PATTERN"; then
  echo "  FOUND in reachable history"
  extract_secret "$(git log --all -p 2>/dev/null)" || true
fi

# 1.2 Staged index
echo "[1.2] Searching staged index..."
while read mode type hash stage; do
  if [ "$type" = "blob" ]; then
    content=$(git cat-file -p "$hash" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in staged blob $hash"
      break
    fi
  fi
done < <(git ls-files --stage 2>/dev/null)

# 1.3 Stashes
echo "[1.3] Searching stashes..."
stash_count=$(git stash list 2>/dev/null | wc -l)
for ((i=0; i<stash_count; i++)); do
  content=$(git stash show -p "stash@{$i}" 2>/dev/null) || continue
  if extract_secret "$content" 2>/dev/null; then
    echo "  FOUND in stash@{$i}"
    break
  fi
done

# 1.4 Reflogs
echo "[1.4] Searching reflogs..."
while read sha rest; do
  content=$(git show "$sha" 2>/dev/null) || continue
  if extract_secret "$content" 2>/dev/null; then
    echo "  FOUND in reflog entry $sha"
    break
  fi
done < <(git reflog --all 2>/dev/null)

# 1.4b Commit messages
echo "[1.4b] Searching commit messages..."
commit_msgs=$(git log --all --format=%B 2>/dev/null) || true
if echo "$commit_msgs" | grep -qE "$PATTERN"; then
  echo "  FOUND in commit message"
  extract_secret "$commit_msgs" || true
fi

# 1.5 Unreachable objects
echo "[1.5] Searching unreachable objects..."
while read kind hash; do
  if [ "$kind" = "unreachable" ] || [ "$kind" = "dangling" ]; then
    content=$(git cat-file -p "$hash" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in unreachable object $hash"
      break
    fi
  fi
done < <(git fsck --unreachable --no-reflogs 2>&1)

# 1.6 Replace refs
echo "[1.6] Searching replace refs..."
if git replace -l 2>/dev/null | grep -q .; then
  while read line; do
    ref=$(echo "$line" | awk '{print $1}')
    content=$(git cat-file -p "$ref" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in replace ref $ref"
      break
    fi
  done < <(git replace -l 2>/dev/null)
fi

# 1.7 Annotated tags
echo "[1.7] Searching annotated tags..."
for tag in $(git tag -l 2>/dev/null); do
  if [ "$(git cat-file -t "$tag" 2>/dev/null)" = "tag" ]; then
    content=$(git cat-file -p "$tag" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in annotated tag $tag"
      break
    fi
  fi
done

# 1.8 Backup refs
echo "[1.8] Searching backup refs..."
for ref in $(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null); do
  content=$(git show "$ref" 2>/dev/null) || continue
  if extract_secret "$content" 2>/dev/null; then
    echo "  FOUND in backup ref $ref"
    break
  fi
done

# 1.9 Special HEAD files
echo "[1.9] Searching special HEAD files..."
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  if [ -f ".git/$f" ]; then
    sha=$(cat ".git/$f" 2>/dev/null | head -1)
    content=$(git show "$sha" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in $f"
      break
    fi
  fi
done

# 1.10 Submodule object databases
echo "[1.10] Searching submodule object databases..."
if [ -d ".git/modules" ]; then
  for moddir in .git/modules/*/; do
    [ -d "$moddir" ] || continue
    while read kind hash; do
      if [ "$kind" = "unreachable" ] || [ "$kind" = "dangling" ]; then
        content=$(GIT_DIR="$moddir" git cat-file -p "$hash" 2>/dev/null) || continue
        if extract_secret "$content" 2>/dev/null; then
          echo "  FOUND in submodule $moddir object $hash"
          break 2
        fi
      fi
    done < <(GIT_DIR="$moddir" git fsck --unreachable --no-reflogs 2>&1)
  done
fi

# 1.10b Git notes
echo "[1.10b] Searching git notes..."
if git notes list 2>/dev/null | grep -q .; then
  notes_content=$(git notes list 2>/dev/null | while read blob_sha obj_sha; do
    git notes show "$obj_sha" 2>/dev/null
  done) || true
  if echo "$notes_content" | grep -qE "$PATTERN"; then
    echo "  FOUND in git notes"
    extract_secret "$notes_content" || true
  fi
fi

# 1.12 Rerere cache
echo "[1.12] Searching rerere cache..."
if [ -d ".git/rr-cache" ]; then
  rr_content=$(find .git/rr-cache/ -type f 2>/dev/null | while read f; do
    cat "$f" 2>/dev/null
  done) || true
  if echo "$rr_content" | grep -qE "$PATTERN"; then
    echo "  FOUND in rerere cache"
    extract_secret "$rr_content" || true
  fi
fi

# 1.13 Exhaustive scan (nuclear option)
if [ -z "$FOUND_SECRET" ]; then
  echo "[1.13] Running exhaustive object scan..."
  all_hashes=$(git rev-list --all --objects 2>/dev/null | awk '{print $1}')
  for hash in $all_hashes; do
    content=$(git cat-file -p "$hash" 2>/dev/null) || continue
    if extract_secret "$content" 2>/dev/null; then
      echo "  FOUND in object $hash (exhaustive scan)"
      break
    fi
  done
fi

# 1.14 Raw binary grep
if [ -z "$FOUND_SECRET" ]; then
  echo "[1.14] Running raw binary grep of .git/..."
  matches=$(grep -rl "$PATTERN" .git/ 2>/dev/null) || true
  if [ -n "$matches" ]; then
    echo "  FOUND references in: $matches"
    for f in $matches; do
      if extract_secret "$(strings "$f" 2>/dev/null)" 2>/dev/null; then
        echo "  Extracted from $f"
        break
      fi
    done
  fi
fi

if [ -z "$FOUND_SECRET" ]; then
  echo "ERROR: Secret not found in any location!"
  exit 1
fi

echo ""
echo "=== Phase 2: RECOVER ==="
echo "Secret: $FOUND_SECRET"
echo "$FOUND_SECRET" > "$OUTPUT_FILE"
echo "Written to: $OUTPUT_FILE"

echo ""
echo "=== Phase 3: CLEAN ==="

# 3.1 Remove tainted refs
echo "[3.1] Removing tainted refs..."
# Drop stashes containing the secret
stash_count=$(git stash list 2>/dev/null | wc -l)
for ((i=stash_count-1; i>=0; i--)); do
  if git stash show -p "stash@{$i}" 2>/dev/null | grep -qE "$PATTERN"; then
    git stash drop "stash@{$i}" 2>/dev/null || true
  fi
done

# Delete tainted tags
for tag in $(git tag -l 2>/dev/null); do
  if git cat-file -p "$tag" 2>/dev/null | grep -qE "$PATTERN"; then
    git tag -d "$tag" 2>/dev/null || true
  fi
done

# Delete replace refs
for ref in $(git replace -l 2>/dev/null | awk '{print $1}'); do
  git replace -d "$ref" 2>/dev/null || true
done

# Delete backup refs
for ref in $(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null); do
  git update-ref -d "$ref" 2>/dev/null || true
done

# Delete special HEAD files
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  rm -f ".git/$f" 2>/dev/null || true
done

# 3.2 Rewrite reachable history if needed
echo "[3.2] Checking if reachable history contains secret..."
needs_rewrite=false

# Check file content
if git log --all -p 2>/dev/null | grep -qE "$PATTERN"; then
  echo "  Secret found in reachable file history — rewriting..."
  needs_rewrite=true
fi

# Check commit messages
if git log --all --format=%B 2>/dev/null | grep -qE "$PATTERN"; then
  echo "  Secret found in commit messages — rewriting..."
  needs_rewrite=true
fi

if [ "$needs_rewrite" = true ]; then
  if command -v git-filter-repo &>/dev/null; then
    # Create expressions file for text replacement
    echo "regex:${PATTERN}[^]]*]=>*REMOVED*<" > /tmp/expressions.txt
    git filter-repo --replace-text /tmp/expressions.txt --force 2>/dev/null || true
    rm -f /tmp/expressions.txt
  else
    # Fallback to filter-branch (built-in, works everywhere)
    echo "  Using filter-branch (git-filter-repo not available)..."
    export FILTER_BRANCH_SQUELCH_WARNING=1
    
    # Find the file path containing the secret
    SECRET_FILE=$(git log --all -p 2>/dev/null | grep -B2 "$PATTERN" | grep "^+++ b/" | head -1 | sed 's|^+++ b/||')
    if [ -n "$SECRET_FILE" ]; then
      echo "  Removing file: $SECRET_FILE"
      git filter-branch --force --index-filter \
        "git rm --cached --ignore-unmatch '$SECRET_FILE'" \
        --prune-empty -- --all 2>/dev/null || true
    fi
    
    # Also clean commit messages
    git filter-branch --force --msg-filter \
      "sed -E 's/${PATTERN}[^]]*]/*REMOVED*/g'" -- --all 2>/dev/null || true
  fi
  # Delete any backup refs created by filter-branch/filter-repo
  for ref in $(git for-each-ref --format='%(refname)' refs/original/ refs/rewritten/ 2>/dev/null); do
    git update-ref -d "$ref" 2>/dev/null || true
  done
fi

# 3.2b Clean git notes
echo "[3.2b] Cleaning git notes..."
if git notes list 2>/dev/null | grep -qE "$PATTERN"; then
  git notes remove --all 2>/dev/null || true
fi
# Delete all note refs
for ref in $(git for-each-ref --format='%(refname)' refs/notes/ 2>/dev/null); do
  git update-ref -d "$ref" 2>/dev/null || true
done

# 3.2c Clean rerere cache
echo "[3.2c] Cleaning rerere cache..."
if [ -d ".git/rr-cache" ]; then
  rm -rf .git/rr-cache/*
fi

# 3.3 Expire reflogs
echo "[3.3] Expiring all reflogs..."
git reflog expire --expire=now --all

# 3.4 Prune unreachable objects
echo "[3.4] Pruning unreachable objects..."
git gc --prune=now --aggressive

# 3.5 Handle submodules
echo "[3.5] Cleaning submodules..."
if [ -d ".git/modules" ]; then
  for moddir in .git/modules/*/; do
    [ -d "$moddir" ] || continue
    (cd "$moddir" && git reflog expire --expire=now --all && git gc --prune=now --aggressive) 2>/dev/null || true
  done
fi

echo ""
echo "=== Phase 4: VERIFY ==="

# 4.1 No tainted objects
echo "[4.1] Checking for remaining unreachable objects..."
remaining=$(git fsck --unreachable --no-reflogs 2>&1) || true
if echo "$remaining" | grep -q "unreachable\|dangling"; then
  while read kind hash; do
    if [ "$kind" = "unreachable" ] || [ "$kind" = "dangling" ]; then
      if git cat-file -p "$hash" 2>/dev/null | grep -qE "$PATTERN"; then
        echo "  WARNING: Secret still found in $hash!"
      fi
    fi
  done <<< "$remaining"
fi

echo "[4.2] Binary grep of .git/..."
if grep -rl "$PATTERN" .git/ 2>/dev/null; then
  echo "  WARNING: Secret pattern still found in .git/!"
else
  echo "  CLEAN: No secret pattern found in .git/"
fi

echo "[4.3] Checking commit messages..."
if git log --all --format=%B 2>/dev/null | grep -qE "$PATTERN"; then
  echo "  WARNING: Secret still found in commit messages!"
else
  echo "  CLEAN: No secret in commit messages"
fi

echo "[4.4] Checking git notes..."
notes_content=$(git notes list 2>/dev/null | while read blob_sha obj_sha; do
  git notes show "$obj_sha" 2>/dev/null
done) || true
if echo "$notes_content" | grep -qE "$PATTERN"; then
  echo "  WARNING: Secret still found in git notes!"
else
  echo "  CLEAN: No secret in git notes"
fi

echo "[4.5] Verifying legitimate content..."
echo "  Branches: $(git branch -a 2>/dev/null | wc -l)"
echo "  Tags: $(git tag -l 2>/dev/null | wc -l)"
echo "  Commits: $(git log --all --oneline 2>/dev/null | wc -l)"
git log --all --oneline 2>/dev/null

echo ""
echo "=== DONE ==="
echo "Secret recovered to: $OUTPUT_FILE"
echo "Value: $FOUND_SECRET"

---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository and clean it from all storage
  locations while preserving legitimate content. Handles secrets in unreachable
  blobs, stashes, reflogs, reachable history, deleted branches, tags, replace
  refs, and packed objects.
---

# Git Leak Recovery

## Overview

A secret was accidentally introduced into a Git repository. It may reside in
reachable history, unreachable/dangling objects, stashes, reflogs, tags, replace
refs, or any combination thereof. The task is to:

1. **Recover** the secret and write it to `/app/secret.txt`
2. **Clean** the repository so the secret cannot be found anywhere
3. **Preserve** all legitimate branches, files, tags, and commit messages

## Secret Format

The secret matches the pattern `secret[...]` — a literal string of the form
`secret[<content>]`. There is exactly one such string in the repository.

## Phase 1: Recovery — Find the Secret

Search every place Git can store data. Work through these systematically.

### 1a. Reachable history (commits, trees, blobs on any ref)

```bash
# Search all reachable commits for the secret pattern in diffs
git log --all -p -S 'secret[' 2>/dev/null

# IMPORTANT: Also search commit MESSAGES — the secret may be in a
# commit subject or body, not just in blob content.
git log --all --format="%H %s%n%b" | grep -B1 'secret\['
# Extract the exact secret from a matching commit message:
git log --all --format="%H %s%n%b" | grep -oP 'secret\[[^\]]*\]'

# Search blob contents of all reachable objects
git rev-list --all --objects | while read hash rest; do
  if git cat-file -t "$hash" 2>/dev/null | grep -q blob; then
    if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in reachable blob $hash ($rest)"
      git cat-file -p "$hash" | grep -oP 'secret\[[^\]]*\]'
    fi
  fi
done
```

### 1b. Unreachable / dangling objects

```bash
# Find all unreachable objects (blobs, commits, trees)
git fsck --unreachable --no-reflogs 2>&1

# Check unreachable blobs
git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk '{print $3}' | while read hash; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in unreachable blob $hash"
    git cat-file -p "$hash" | grep -oP 'secret\[[^\]]*\]'
  fi
done

# Check unreachable commits — secret may be in the commit MESSAGE
# or in the commit's tree blobs.
git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable commit" | awk '{print $3}' | while read hash; do
  # Check commit message (subject + body)
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in commit message of unreachable commit $hash"
    git cat-file -p "$hash" | grep -oP 'secret\[[^\]]*\]'
  fi
  # Check blobs in the commit's tree
  git ls-tree -r "$hash" 2>/dev/null | while read mode type obj name; do
    if [ "$type" = "blob" ]; then
      if git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in unreachable commit $hash, blob $obj ($name)"
        git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
      fi
    fi
  done
done
```

### 1c. Stashes

```bash
git stash list 2>/dev/null
# Inspect each stash for the secret
git stash list --format="%gd %H" | while read ref hash; do
  if git diff-tree --no-commit-id -r -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in stash $ref ($hash)"
  fi
  # Also check the stash's tree blobs directly
  git ls-tree -r "$hash" 2>/dev/null | while read mode type obj name; do
    if [ "$type" = "blob" ] && git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in stash $ref, blob $obj ($name)"
      git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
    fi
  done
done
```

### 1d. Reflog entries

```bash
git reflog --all 2>/dev/null
# Check each reflog entry's tree for the secret
git reflog --all --format="%H" | sort -u | while read hash; do
  git ls-tree -r "$hash" 2>/dev/null | while read mode type obj name; do
    if [ "$type" = "blob" ]; then
      if git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in reflog entry $hash, blob $obj ($name)"
        git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
      fi
    fi
  done
done
```

### 1e. Tags (annotated tags have their own object with a message)

```bash
git tag -l 2>/dev/null
git tag -l | while read tag; do
  # Check annotated tag message
  tagobj=$(git rev-parse "refs/tags/$tag")
  if [ "$(git cat-file -t "$tagobj")" = "tag" ]; then
    if git cat-file -p "$tagobj" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in tag message of $tag"
    fi
  fi
  # Check blobs reachable from the tagged commit/tree
  git ls-tree -r "$tag" 2>/dev/null | while read mode type obj name; do
    if [ "$type" = "blob" ] && git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in tag $tag, blob $obj ($name)"
      git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
    fi
  done
done
```

### 1f. Replace refs and notes

```bash
# Replace refs
git replace -l 2>/dev/null | while read orig arrow repl; do
  if git cat-file -p "$repl" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in replace ref $orig -> $repl"
  fi
done

# Git notes
git notes list 2>/dev/null | while read hash; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in git note $hash"
  fi
done
```

### 1g. Submodules

```bash
# Check for submodules
if [ -f .gitmodules ]; then
  git submodule status 2>/dev/null
  # Enter each submodule and search its objects
  git submodule foreach --recursive '
    git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk "{print \$3}" | while read hash; do
      if git cat-file -p "$hash" 2>/dev/null | grep -q "secret\\["; then
        echo "FOUND in submodule $name, blob $hash"
      fi
    done
  ' 2>/dev/null
fi
```

### 1h. Exhaustive fallback scan

If the secret hasn't been found yet, enumerate ALL objects (loose + packed):

```bash
{
  git rev-list --all --objects 2>/dev/null
  git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'
  # Also enumerate packed objects directly
  for idx in .git/objects/pack/*.idx; do
    [ -f "$idx" ] && git verify-pack -v "$idx" 2>/dev/null | awk '/^[0-9a-f]{40}/{print $1}'
  done
} | sort -u | while read hash; do
  if [ -n "$hash" ] && git cat-file -t "$hash" 2>/dev/null | grep -q blob; then
    if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in blob $hash"
      git cat-file -p "$hash" | grep -oP 'secret\[[^\]]*\]'
    fi
  fi
done
```

### Step 2: Save the Secret

```bash
# Extract the exact secret string (from whichever source found it)
SECRET=$(git cat-file -p <blob_hash> | grep -oP 'secret\[[^\]]*\]')
echo "$SECRET" > /app/secret.txt
```

## Phase 2: Cleanup — Remove the Secret

Apply ALL applicable steps. Order matters: rewrite reachable history BEFORE
pruning unreachable objects, because rewriting creates new unreachable objects.

### A: Remove from Reachable History

If the secret exists in any reachable commit's tree OR in any commit
message, rewrite history. Use `git filter-repo` (install via pip if
needed). Both blob content and commit messages must be cleaned in a
single pass (both rewrite history).

```bash
pip install git-filter-repo 2>/dev/null

# --- Clean commit MESSAGES first (or combined with blob cleanup) ---
# If the secret appears in commit messages:
echo 'literal:secret[...]==>REDACTED' > /tmp/msg-replacements
git filter-repo --replace-message /tmp/msg-replacements --force

# Or use a message callback for more control:
# git filter-repo --message-callback 'return message.replace(b"secret[...]", b"REDACTED")' --force

# --- Clean blob CONTENT ---
# Strip specific blobs by hash:
git filter-repo --strip-blobs-with-ids <(echo "<blob_hash>") --force

# Alternative: replace text in all blobs
# echo 'literal:secret[...]==>REDACTED' > /tmp/blob-replacements
# git filter-repo --replace-text /tmp/blob-replacements --force

# NOTE: If both commit messages AND blobs need cleaning, combine into
# a single filter-repo invocation to avoid multiple history rewrites:
# git filter-repo --replace-message /tmp/msg-replacements \
#                 --strip-blobs-with-ids <(echo "<blob_hash>") --force

# Fallback: git filter-branch (handles blobs only; for messages use
# --msg-filter):
# git filter-branch --force --index-filter \
#   'git rm --cached --ignore-unmatch <filename>' \
#   --msg-filter 'sed "s/secret\[...\]/REDACTED/g"' \
#   --prune-empty -- --all

# Clean up filter-branch backup refs
git for-each-ref --format="%(refname)" refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

### B: Remove from Stashes

```bash
# Drop specific tainted stashes or clear all
git stash clear
```

### C: Remove Replace Refs and Notes

```bash
git replace -l 2>/dev/null | awk '{print $1}' | while read ref; do
  git replace -d "$ref" 2>/dev/null
done
# Delete all notes refs (makes note objects unreachable → pruned by gc)
git for-each-ref --format="%(refname)" refs/notes/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref" 2>/dev/null
done
```

### D: Remove Tainted Tags

IMPORTANT: Use process substitution (`< <(...)`) instead of pipes to
avoid subshell variable scoping issues. Variables set inside a piped
`while read` loop are lost when the subshell exits.

```bash
while read tag; do
  tainted=false
  tagobj=$(git rev-parse "refs/tags/$tag" 2>/dev/null)
  if [ -n "$tagobj" ] && [ "$(git cat-file -t "$tagobj" 2>/dev/null)" = "tag" ]; then
    git cat-file -p "$tagobj" 2>/dev/null | grep -q 'secret\[' && tainted=true
  fi
  # Use process substitution to keep tainted in this shell's scope
  while read mode type obj name; do
    [ "$type" = "blob" ] && git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\[' && tainted=true
  done < <(git ls-tree -r "$tag" 2>/dev/null)
  [ "$tainted" = "true" ] && git tag -d "$tag"
done < <(git tag -l)
```

### E: Expire Reflogs, Clean Special Refs, and Prune

This is ALWAYS needed:

```bash
# Expire ALL reflogs
git reflog expire --expire=now --all

# Remove special refs that may point to tainted commits
for specialref in FETCH_HEAD MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD BISECT_HEAD; do
  git update-ref -d "$specialref" 2>/dev/null
done

# Remove any backup refs from filter-branch
git for-each-ref --format="%(refname)" refs/original/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref"
done

# Garbage collect and prune ALL unreachable objects
git gc --prune=now --aggressive

# Repack to ensure no stale pack files remain
git repack -a -d -l
git prune --expire=now
```

## Phase 3: Verification

After cleanup, confirm the secret is completely gone and legitimate content survives.

IMPORTANT: Use a temp file for the FOUND flag, because the piped
`while read` runs in a subshell and variable changes don't propagate.

```bash
# 1. No unreachable objects should remain
echo "=== Unreachable objects ==="
git fsck --unreachable --no-reflogs 2>&1

# 2. Exhaustive scan of ALL remaining objects (blobs AND commit messages)
echo "=== Scanning all objects ==="
TMPF=$(mktemp)
echo "0" > "$TMPF"

# Check all blob contents
{
  git rev-list --all --objects 2>/dev/null
  git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'
} | sort -u | while read hash; do
  if [ -n "$hash" ] && git cat-file -t "$hash" 2>/dev/null | grep -q blob; then
    if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "STILL FOUND in blob $hash — CLEANUP FAILED"
      echo "1" > "$TMPF"
    fi
  fi
done

# Also check ALL commit messages (reachable + unreachable)
{
  git log --all --format="%H %s%n%b" 2>/dev/null
  git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable commit" | awk '{print $3}' | while read chash; do
    git cat-file -p "$chash" 2>/dev/null
  done
} | grep -q 'secret\[' && {
  echo "STILL FOUND in a commit message — CLEANUP FAILED"
  echo "1" > "$TMPF"
}

[ "$(cat "$TMPF")" = "0" ] && echo "CLEAN: No secret found in any object or commit message"
rm -f "$TMPF"

# 3. Verify legitimate content is preserved
echo "=== Legitimate content ==="
git log --oneline --all
git branch -a
git tag -l
git status
```

## Key Principles

1. **Recover before cleanup.** Always extract and save the secret first.
2. **Search exhaustively.** The secret may be in multiple locations simultaneously (e.g., reachable history AND unreachable blobs from a dropped stash).
3. **Clean in the right order.** Rewrite reachable history → drop stashes → remove replace refs → delete tainted tags → expire reflogs → prune objects.
4. **Verify thoroughly.** After cleanup, scan every remaining object (loose and packed) to confirm the secret is gone.
5. **Preserve legitimate content.** Never delete branches, commits, tags, or files that don't contain the secret. When rewriting history, verify the result retains all expected commits, branches, and files.
6. **Handle packed objects.** After `git gc`, objects may be in pack files. Verification must check packed objects too.
7. **Reflogs are a recovery vector.** Always expire reflogs as part of cleanup, since they can reference commits containing the secret.
8. **Special refs matter.** `FETCH_HEAD`, `MERGE_HEAD`, etc. can keep tainted commits reachable.
9. **Submodules have separate object stores.** If the repo has submodules, search and clean them independently.

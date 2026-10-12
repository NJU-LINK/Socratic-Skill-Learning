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

A secret matching `secret[...]` was accidentally introduced into a Git repository. It may reside in reachable history, unreachable/dangling objects, stashes, reflogs, tags, replace refs, commit messages, the index, submodules, or any combination thereof.

**Tasks:**
1. **Recover** the secret and write it to `/app/secret.txt`
2. **Clean** the repository so the secret cannot be found anywhere
3. **Preserve** all legitimate branches, files, tags, and commit messages

## Quick Diagnostic Procedure

Run this unified search to find ALL locations where the secret exists. The secret may be in multiple places simultaneously — check ALL results.

```bash
cd /app/repo

# Unified search: finds secret in ALL locations
{
  # 1. Reachable blobs (in committed history)
  git rev-list --all --objects 2>/dev/null | while read hash rest; do
    [ "$(git cat-file -t "$hash" 2>/dev/null)" = "blob" ] && \
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "REACHABLE_BLOB:$hash:$rest"
  done
  
  # 2. Unreachable blobs (dropped stash, reset commits, deleted branches)
  git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk '{print $3}' | while read hash; do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "UNREACHABLE_BLOB:$hash"
  done
  
  # 3. Commit messages (reachable commits)
  git log --all --format="%H" 2>/dev/null | while read hash; do
    git log -1 --format="%B" "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "COMMIT_MSG:$hash"
  done
  
  # 4. Unreachable commit messages
  git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable commit" | awk '{print $3}' | while read hash; do
    git log -1 --format="%B" "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "UNREACHABLE_COMMIT:$hash"
  done
  
  # 5. Index (staged files)
  git ls-files --stage 2>/dev/null | while read mode hash stage name; do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "INDEX:$hash:$name"
  done
  
  # 6. Stashes
  git stash list --format="%H" 2>/dev/null | while read hash; do
    git ls-tree -r "$hash" 2>/dev/null | while read mode type obj name; do
      [ "$type" = "blob" ] && git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\[' && \
      echo "STASH:$hash:$obj:$name"
    done
  done
  
  # 7. Tags (annotated tag messages)
  git tag -l 2>/dev/null | while read tag; do
    tagobj=$(git rev-parse "refs/tags/$tag" 2>/dev/null)
    [ "$(git cat-file -t "$tagobj" 2>/dev/null)" = "tag" ] && \
    git cat-file -p "$tagobj" 2>/dev/null | grep -q 'secret\[' && \
    echo "TAG_MSG:$tag"
  done
  
  # 8. Replace refs
  git replace -l 2>/dev/null | while read orig arrow repl; do
    git cat-file -p "$repl" 2>/dev/null | grep -q 'secret\[' && \
    echo "REPLACE:$orig->$repl"
  done
  
  # 9. Git notes
  git notes list 2>/dev/null | while read hash; do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "NOTE:$hash"
  done
  
  # 10. Submodules (if present)
  if [ -f .gitmodules ]; then
    git submodule foreach --recursive '
      git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk "{print \$3}" | while read hash; do
        git cat-file -p "$hash" 2>/dev/null | grep -q "secret\\[" && echo "SUBMODULE:$name:$hash"
      done
    ' 2>/dev/null
  fi
} | sort -u
```

**Extract the secret** from any found location:
```bash
# From a blob:
git cat-file -p <blob_hash> | grep -oP 'secret\[[^\]]*\]'

# From a commit message:
git log -1 --format="%B" <commit_hash> | grep -oP 'secret\[[^\]]*\]'

# Save to file:
echo "secret[...]" > /app/secret.txt
```

## Cleanup Procedure

Apply cleanup steps based on what the diagnostic found. **Order matters**: rewrite reachable history BEFORE pruning unreachable objects.

### Step 1: Clean Reachable History (if REACHABLE_BLOB or COMMIT_MSG found)

If the secret exists in any reachable commit's tree OR in any commit message, rewrite history using `git filter-repo`:

```bash
# Install git-filter-repo if needed
pip install git-filter-repo 2>/dev/null

# CRITICAL: Always use a SINGLE combined invocation.
# Sequential invocations break blob hash references because the first
# rewrite changes all downstream commit/tree/blob hashes.

# Build replacement files (non-matching patterns are harmless no-ops)
echo 'literal:secret[...]==>REDACTED' > /tmp/msg-replacements
echo 'literal:secret[...]==>REDACTED' > /tmp/blob-replacements

# Single pass: clean messages + replace text in all blobs
git filter-repo \
  --replace-message /tmp/msg-replacements \
  --replace-text /tmp/blob-replacements \
  --force

# Clean up filter-branch backup refs (if using filter-branch fallback)
git for-each-ref --format="%(refname)" refs/original/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref"
done
```

**Fallback if git-filter-repo unavailable:**
```bash
# CRITICAL: Combine both operations in a SINGLE filter-branch invocation.
# Sequential invocations break blob hash references.
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <filename>' \
  --msg-filter 'sed "s/secret\[[^]]*\]/REDACTED/g"' \
  --prune-empty -- --all
```

### Step 2: Clean Index (if INDEX found)

```bash
# Remove the file from the index
git rm --cached <filename>
```

### Step 3: Clean Stashes (if STASH found)

```bash
git stash clear
```

### Step 4: Clean Tags (if TAG_MSG found)

Delete tags whose messages contain the secret:

```bash
while read tag; do
  tagobj=$(git rev-parse "refs/tags/$tag" 2>/dev/null)
  if [ "$(git cat-file -t "$tagobj" 2>/dev/null)" = "tag" ]; then
    git cat-file -p "$tagobj" 2>/dev/null | grep -q 'secret\[' && git tag -d "$tag"
  fi
done < <(git tag -l)
```

### Step 5: Clean Replace Refs and Notes (if REPLACE or NOTE found)

```bash
# Remove replace refs
git replace -l 2>/dev/null | awk '{print $1}' | while read ref; do
  git replace -d "$ref" 2>/dev/null
done

# Remove all notes
git for-each-ref --format="%(refname)" refs/notes/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref" 2>/dev/null
done
```

### Step 6: Expire Reflogs and Prune (ALWAYS needed)

This removes unreachable objects (UNREACHABLE_BLOB, UNREACHABLE_COMMIT) and cleans reflogs:

```bash
# Expire ALL reflogs
git reflog expire --expire=now --all

# Remove special refs
for specialref in FETCH_HEAD MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD BISECT_HEAD; do
  git update-ref -d "$specialref" 2>/dev/null
done

# Garbage collect and prune ALL unreachable objects
git gc --prune=now --aggressive

# Repack to ensure no stale pack files remain
git repack -a -d -l
git prune --expire=now
```

## Verification

After cleanup, verify the secret is completely gone:

```bash
# Re-run the unified diagnostic - should return nothing
{
  git rev-list --all --objects 2>/dev/null | while read hash rest; do
    [ "$(git cat-file -t "$hash" 2>/dev/null)" = "blob" ] && \
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "FOUND:reachable_blob:$hash"
  done
  
  git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk '{print $3}' | while read hash; do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "FOUND:unreachable_blob:$hash"
  done
  
  git log --all --format="%H" 2>/dev/null | while read hash; do
    git log -1 --format="%B" "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "FOUND:commit_msg:$hash"
  done
  
  git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable commit" | awk '{print $3}' | while read hash; do
    git log -1 --format="%B" "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "FOUND:unreachable_commit:$hash"
  done
} | sort -u

# If any "FOUND:" lines appear, cleanup failed. Otherwise:
echo "CLEAN: Secret completely removed"

# Verify legitimate content preserved
git log --oneline --all
git branch -a
git tag -l
git status
```

## Key Principles

1. **Run the unified diagnostic FIRST** to find ALL locations where the secret exists.
2. **Recover before cleanup** — always extract and save the secret to `/app/secret.txt` first.
3. **Clean in order** — rewrite reachable history → clean index/stashes/tags/refs → expire reflogs → prune objects.
4. **The secret may be in multiple locations** — check ALL diagnostic results and apply ALL relevant cleanup steps.
5. **Verify thoroughly** — re-run the diagnostic after cleanup to confirm the secret is gone.
6. **Preserve legitimate content** — never delete branches, commits, tags, or files that don't contain the secret.
7. **Reflogs keep objects reachable** — always expire reflogs as part of cleanup.
8. **Packed objects must be checked** — after `git gc`, objects may be in pack files. The verification step checks both loose and packed objects.

---
name: git-leak-recovery
description: >
  Recover a leaked secret hidden somewhere in a Git repository's storage
  (objects, refs, reflogs, stashes, history, tags, replace refs, pack files),
  write it to a specified output file, then fully purge all traces of the secret
  from the repository while preserving legitimate content.
---

# Git Leak Recovery

## Overview

A Git repository contains a leaked secret. You must:
1. **Recover** the secret and write it to the output file.
2. **Purge** every trace of the secret from the repository.
3. **Preserve** all legitimate branches, commits, files, tags, and messages.

## Step 0 — Read Task Parameters

Before touching the repo, extract these from `task.yaml`:

| Parameter | Where to find it | Example |
|-----------|------------------|---------|
| Repo path | Hint section | `/app/repo` |
| Secret pattern | Hint section | `secret[...]` — match this exactly |
| Output path | Instruction step 1 | `/app/secret.txt` |

**Use the actual pattern from the task** in all grep/search commands below.
The pattern `secret\[` is just a placeholder; replace it everywhere if the
task specifies a different format.

## Step 1 — Universal Discovery (run this first)

Run one comprehensive scan that covers **all** Git storage locations at once:

```bash
cd <repo-path>

# --- Pass 1: Unreachable objects (dangling blobs, lost-found, etc.) ---
for h in $(git fsck --unreachable --no-reflogs 2>&1 | awk '{print $NF}'); do
  content=$(git cat-file -p "$h" 2>/dev/null)
  if echo "$content" | grep -q '<SECRET_PATTERN>'; then
    echo "FOUND (unreachable $h): $content"
  fi
done

# --- Pass 2: All reachable objects ---
git rev-list --all --objects 2>/dev/null | awk '{print $1}' | while read h; do
  if [ "$(git cat-file -t "$h" 2>/dev/null)" = "blob" ]; then
    content=$(git cat-file -p "$h" 2>/dev/null)
    if echo "$content" | grep -q '<SECRET_PATTERN>'; then
      echo "FOUND (reachable blob $h): $content"
    fi
  fi
done

# --- Pass 3: Reflogs, stash, special HEAD files ---
git log -g --all -p 2>/dev/null | grep '<SECRET_PATTERN>'
git stash list 2>/dev/null
for f in .git/MERGE_HEAD .git/ORIG_HEAD .git/FETCH_HEAD .git/CHERRY_PICK_HEAD; do
  [ -f "$f" ] && echo "Special ref: $f -> $(cat "$f")"
done

# --- Pass 4: Special refs (replace, backup, tags) ---
find .git/refs -type f 2>/dev/null | while read f; do
  echo "$f: $(cat "$f")"
done
find .git/refs/original -type f 2>/dev/null
ls .git/refs/replace/ 2>/dev/null

# --- Pass 5: lost-found directory ---
ls -la .git/lost-found/ 2>/dev/null
find .git/lost-found -type f 2>/dev/null | while read f; do
  content=$(cat "$f" 2>/dev/null)
  if echo "$content" | grep -q '<SECRET_PATTERN>'; then
    echo "FOUND (lost-found $f): $content"
  fi
done

# --- Pass 6: Pack file objects ---
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  git verify-pack -v "$idx" 2>/dev/null | awk '/^[0-9a-f]/{print $1}' | while read h; do
    if [ "$(git cat-file -t "$h" 2>/dev/null)" = "blob" ]; then
      content=$(git cat-file -p "$h" 2>/dev/null)
      if echo "$content" | grep -q '<SECRET_PATTERN>'; then
        echo "FOUND (pack blob $h): $content"
      fi
    fi
  done
done

# --- Pass 7: Nested/submodule repos ---
find . -name ".git" -not -path "./.git" 2>/dev/null
```

Replace `<SECRET_PATTERN>` with the actual pattern from task.yaml.

### Classification

After discovery, classify every location where the secret was found:

| Location type | Cleanup method |
|---------------|---------------|
| Unreachable/dangling blob only | → **Step 2a** |
| Committed in reachable history | → **Step 2b** |
| In a stash entry | → **Step 2c** |
| In special refs (replace, backup, lost-found) | → **Step 2d** |
| Multiple locations | Handle **each**, then proceed to Step 3 |

## Step 2 — Recover & Targeted Cleanup

### 2a. Dangling / unreachable blob

```bash
# 1. Extract the secret EXACTLY (no trailing newline unless part of secret)
git cat-file -p <blob-hash> | grep -o '<SECRET_PATTERN>' > <output-path>

# 2. Verify recovery BEFORE destructive cleanup
cat <output-path>

# 3. Expire reflogs FIRST (critical: gc won't prune reflog-referenced objects)
git reflog expire --expire=now --all

# 4. THEN prune unreachable objects
git gc --prune=now
```

> ⚠️ **Order matters**: `reflog expire` must run before `gc --prune=now`.
> If reversed, the blob may survive inside a pack file.

If the blob's full content IS the secret (the file contained only the secret),
use `git cat-file -p <blob-hash>` directly. If the file contained the secret
among other content, use `grep -o` to extract just the matching string.

### 2b. Secret in reachable commit history

```bash
# 1. Extract the secret first
git show <commit>:<path> | grep -o '<SECRET_PATTERN>' > <output-path>
cat <output-path>  # verify

# 2. Rewrite history to remove the tainted file
# Option A: git filter-branch (always available)
git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch <secret-file>' \
  --prune-empty -- --all

# Option B: git filter-repo (if installed — check with: which git-filter-repo)
git filter-repo --invert-paths --path <secret-file> --force

# 3. Clean up artifacts
rm -rf .git/refs/original        # filter-branch backup
rm -f .git/refs/replace/*        # if any
git reflog expire --expire=now --all
git gc --prune=now
```

If the secret is embedded **inside** a file (not a standalone file):
```bash
git filter-branch --force \
  --tree-filter "sed -i '/<SECRET_PATTERN>/d' <file> 2>/dev/null || true" \
  --prune-empty -- --all
```

**Preserving legitimate content**: After rewriting, verify:
```bash
git branch -a          # all branches still exist
git log --all --oneline  # commit messages preserved
git tag -l             # tags preserved
```

If `--prune-empty` removed a legitimate empty commit, recreate it:
```bash
git checkout <parent-of-empty>
git commit --allow-empty -m "<original message>"
# Then re-attach any child commits via cherry-pick if needed
```

### 2c. Secret in a stash

```bash
# Extract
git stash show -p stash@{N} | grep -o '<SECRET_PATTERN>' > <output-path>
cat <output-path>  # verify

# Remove
git stash drop stash@{N}
git reflog expire --expire=now refs/stash
git gc --prune=now
```

### 2d. Secret behind special refs or lost-found

```bash
# Extract the secret content first (cat the relevant object/file)

# Replace ref
git update-ref -d refs/replace/<name>

# Backup ref
rm -f .git/refs/original/<path>

# lost-found
rm -rf .git/lost-found

# Then prune
git reflog expire --expire=now --all
git gc --prune=now
```

## Step 3 — Global Purge Verification

After cleanup, run this verification block. **Every check must return clean.**

```bash
cd <repo-path>

# Check 1: No unreachable objects
unreachable=$(git fsck --unreachable --no-reflogs 2>&1)
echo "Unreachable: '${unreachable}'"  # should be empty

# Check 2: No dangling objects
dangling=$(git fsck --dangling 2>&1)
echo "Dangling: '${dangling}'"  # should be empty

# Check 3: No secret in ANY object (reachable + packed)
count=$(git rev-list --all --objects 2>/dev/null | awk '{print $1}' | \
  while read h; do git cat-file -p "$h" 2>/dev/null; done | \
  grep -c '<SECRET_PATTERN>')
echo "Reachable object matches: $count"  # must be 0

# Check 4: No loose objects with secret
find .git/objects -type f | grep -v '/pack/' | grep -v '/info/' | while read f; do
  hash=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$hash" 2>/dev/null | grep -q '<SECRET_PATTERN>' && \
    echo "LEAK in loose object $hash"
done

# Check 5: No lost-found
ls .git/lost-found 2>/dev/null && echo "LEAK: lost-found exists"

# Check 6: No special HEAD files pointing to tainted commits
for f in .git/MERGE_HEAD .git/ORIG_HEAD .git/FETCH_HEAD; do
  [ -f "$f" ] && echo "Special HEAD exists: $f"
done

# Check 7: Raw binary search
grep -rl '<SECRET_PATTERN>' .git/ 2>/dev/null && echo "LEAK: binary match found"
```

### If any check fails

- **Loose object remains**: `git gc --prune=now` (ensure reflogs expired first)
- **Pack file contains secret**: `git repack -a -d --no-reuse-delta && git gc --prune=now`
- **lost-found remains**: `rm -rf .git/lost-found`
- Then re-run all checks

## Step 4 — Preserve Legitimate Content (final verification)

```bash
# All branches intact
git branch -a

# All tags intact
git tag -l

# Commit history preserved
git log --all --oneline

# Working tree clean
git status

# Key files present and correct
cat README.md  # or check whatever legitimate files should exist
```

If history was rewritten (Step 2b), confirm:
- Branch names unchanged
- Commit messages for non-tainted commits preserved
- File contents for legitimate files match their expected state

## Quick-Reference: Complete Workflow in Minimal Commands

For the **most common case** (dangling blob, simple repo):

```bash
cd <repo-path>

# 1. Find it
HASH=$(git fsck --unreachable --no-reflogs 2>&1 | grep 'blob' | awk '{print $NF}')
git cat-file -p $HASH

# 2. Extract it
git cat-file -p $HASH | grep -o '<SECRET_PATTERN>' > <output-path>
cat <output-path>  # verify

# 3. Purge it (order matters!)
git reflog expire --expire=now --all
git gc --prune=now

# 4. Verify it's gone
git fsck --unreachable --no-reflogs 2>&1  # should be empty
git rev-list --all --objects | awk '{print $1}' | \
  while read h; do git cat-file -p "$h" 2>/dev/null; done | \
  grep -c '<SECRET_PATTERN>'  # should be 0

# 5. Verify legit content intact
git log --all --oneline
git status
```

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

A Git repository contains a leaked secret matching a known pattern (e.g.
`secret[...]`). The secret may reside in any part of Git's storage layer. You
must:

1. **Recover** the secret and write it to the output file.
2. **Purge** every trace of the secret from the repository.
3. **Preserve** all legitimate branches, commits, files, tags, and messages.

## Phase 1 — Discovery: Find the Secret

Search **every** location where Git can store data. Run these checks
independently; the secret may appear in one or more locations.

### 1a. Unreachable / dangling objects (most common for staged-then-removed)

```bash
cd /app/repo
git fsck --unreachable --no-reflogs 2>&1
git fsck --dangling 2>&1
```

For each reported object, inspect its content:

```bash
git cat-file -p <hash>
```

### 1b. All reachable objects (secret committed in history)

```bash
# List every object reachable from any ref, then search content
git rev-list --all --objects | awk '{print $1}' | \
  while read h; do
    type=$(git cat-file -t "$h" 2>/dev/null)
    if [ "$type" = "blob" ]; then
      content=$(git cat-file -p "$h" 2>/dev/null)
      if echo "$content" | grep -q 'secret\['; then
        echo "FOUND in blob $h: $content"
      fi
    fi
  done
```

Also search diffs across all history:

```bash
git log --all -p -S 'secret['
```

### 1c. Reflogs (point to commits that may contain the secret)

```bash
git reflog --all
# For each reflog entry, check if the commit/tree contains the secret
git log -g --all -p -S 'secret['
```

### 1d. Stashes

```bash
git stash list
# For each stash entry:
git stash show -p stash@{N}   # check diff
git cat-file -p stash@{N}     # check the stash commit tree
```

### 1e. Special refs

```bash
# Replace refs
ls -la .git/refs/replace/ 2>/dev/null
# Backup refs (filter-branch originals)
find .git/refs/original -type f 2>/dev/null
# Any other non-standard refs
find .git/refs -type f
```

### 1f. Pack files

```bash
# List all objects inside pack files and search them
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] && git verify-pack -v "$idx"
done
```

### 1g. Annotated tags

```bash
git tag -l
# For each tag, check if it points to an object containing the secret
git cat-file -p <tag-name>
```

### 1h. Submodule object databases

```bash
find . -name ".git" -type d   # detect nested repos
# For each nested repo, repeat discovery steps
```

### Decision rule

- If the secret is found **only** in unreachable/dangling objects → go to
  **Phase 2a**.
- If the secret is in **reachable history** (commits on branches) → go to
  **Phase 2b**.
- If the secret is in a **stash** → go to **Phase 2c**.
- If the secret is in **special refs** (replace, backup) → go to **Phase 2d**.
- If found in **multiple locations**, handle each one before proceeding to
  Phase 3.

## Phase 2 — Recovery & Targeted Cleanup

### 2a. Dangling / unreachable blob

```bash
# Extract the secret
git cat-file -p <blob-hash> > /app/secret.txt

# Remove reflogs so the blob becomes truly unreachable
git reflog expire --expire=now --all

# Prune unreachable objects
git gc --prune=now
```

### 2b. Secret in reachable commit history

```bash
# Extract the secret first
git show <commit>:<path> > /app/secret.txt
# or extract from a diff line

# Option A: git filter-branch (always available)
git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch <secret-file>' \
  --prune-empty -- --all

# Option B: git filter-repo (if installed, faster and safer)
git filter-repo --invert-paths --path <secret-file>

# Clean up backup refs created by filter-branch
rm -rf .git/refs/original
git reflog expire --expire=now --all
git gc --prune=now
```

If the secret was embedded inside a file (not a whole file), use
`--tree-filter` with `sed` instead:

```bash
git filter-branch --force \
  --tree-filter "sed -i '/secret\[/d' <file> || true" \
  --prune-empty -- --all
```

### 2c. Secret in a stash

```bash
# Extract the secret content first
git stash show -p stash@{N}   # identify the secret
# Write it to /app/secret.txt

# Drop the stash entry
git stash drop stash@{N}

# Expire stash reflog and prune
git reflog expire --expire=now refs/stash
git gc --prune=now
```

### 2d. Secret behind special refs

```bash
# Replace ref: delete it
git update-ref -d refs/replace/<name>

# Backup ref (from filter-branch): delete it
rm -f .git/refs/original/<path>

# Then prune
git reflog expire --expire=now --all
git gc --prune=now
```

## Phase 3 — Global Purge Verification

After targeted cleanup, run a comprehensive sweep to ensure **no trace**
remains in any object (loose or packed).

### 3a. Search all objects in the repository

```bash
cd /app/repo

# Search every object (loose + packed) for the secret pattern
git rev-list --all --objects | awk '{print $1}' | \
  while read h; do
    git cat-file -p "$h" 2>/dev/null
  done | grep -c 'secret\['
```

The count must be **0**. If not, return to Phase 1 and find the remaining
source.

### 3b. Search loose objects not reachable from any ref

```bash
# Check for any remaining loose objects
find .git/objects -type f | grep -v '/pack/' | grep -v '/info/' | while read f; do
  hash=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$hash" 2>/dev/null | grep 'secret\[' && echo "LEAK in $hash"
done
```

### 3c. Search pack files directly

```bash
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  git verify-pack -v "$idx" | awk '{print $1}' | while read h; do
    git cat-file -p "$h" 2>/dev/null | grep -q 'secret\[' && echo "LEAK in pack: $h"
  done
done
```

### 3d. Raw binary search as a final safety net

```bash
# Search the .git directory at the byte level (catches packed objects too)
grep -rl 'secret\[' .git/ 2>/dev/null
```

> **Note**: If pack files contain the secret as compressed data, `grep` may
> not match. Use `git cat-file` based checks above as the authoritative test.
> If `grep` does match a loose object file, that object needs to be pruned.

### 3e. Force repack if leaks persist in pack files

```bash
# Remove old packs and repack only reachable objects
git repack -a -d --no-reuse-delta
git gc --prune=now
```

## Phase 4 — Preserve Legitimate Content

After cleanup, verify the repository is intact:

```bash
# All branches should exist
git branch -a

# All tags should exist
git tag -l

# Commit history should be preserved
git log --all --oneline

# Working tree should be clean
git status

# Key files should be present and correct
cat README.md   # or whatever legitimate files should exist
```

If history was rewritten (Phase 2b), ensure:
- Branch names are unchanged
- Commit messages for non-tainted commits are preserved
- File contents for legitimate files match their expected state

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `git fsck` shows no unreachable objects | Objects already in pack file | Search pack objects (Phase 3c) |
| Secret persists after `git gc` | Reflog still references it | `git reflog expire --expire=now --all` first |
| `filter-branch` creates backup refs | Normal behavior | Delete `.git/refs/original/` after |
| Pack file still contains secret blob | GC didn't repack | `git repack -a -d` then `git gc --prune=now` |
| Stash reflog keeps blob alive | Stash reflog not expired | `git reflog expire --expire=now refs/stash` |

## Quick-Reference: Single-Command Full Sweep

When the secret location is unknown, this one-liner searches **everything**:

```bash
cd /app/repo && \
for h in $(git fsck --unreachable --no-reflogs 2>&1 | awk '{print $NF}') \
         $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'); do
  content=$(git cat-file -p "$h" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND: $h"
    echo "$content" | grep -o 'secret\[[^]]*\]'
  fi
done
```

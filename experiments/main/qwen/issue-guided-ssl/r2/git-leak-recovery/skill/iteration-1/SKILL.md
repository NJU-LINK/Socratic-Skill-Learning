---
name: git-leak-recovery
description: >
  Recover leaked secrets from any Git storage location (unreachable blobs,
  staged index, reachable history, stashes, reflogs, replace refs, annotated
  tags, submodule object databases, deleted branches) and then scrub the
  repository so the secret is irrecoverable while preserving all legitimate
  content (branches, tags, commit messages, working-tree files).
---

# Git Leak Recovery

## Overview

A secret may be accidentally introduced into a Git repository through staging,
committing, stashing, tagging, or other operations, and later partially removed.
The secret can persist in multiple Git storage locations. This skill provides a
systematic procedure to:

1. **Discover** the secret across all possible Git storage locations
2. **Recover** it to a specified output file
3. **Clean** the repository so the secret cannot be recovered
4. **Verify** that cleanup is complete and legitimate content is intact

## Phase 1: DISCOVER — Find the Secret

Search locations in order from cheapest/most-specific to most-exhaustive.
The secret format is typically `secret[...]` but adapt the pattern to the task.

### 1.1 Reachable History (committed secrets)

```bash
# Search all branches/tags for the secret pattern in diffs
git log --all -S "secret[" --oneline
# Also search full diff content
git log --all -p | grep -n "secret\["
```

### 1.2 Staged Index (still tracked)

```bash
# List all staged blobs with their hashes
git ls-files --stage
# For each blob hash, inspect content
git cat-file -p <blob-hash>
```

### 1.3 Stashes

```bash
# List all stashes
git stash list
# Inspect each stash (including dropped stashes that may still be reachable)
git stash show -p stash@{N}
```

### 1.4 Reflogs (amended, reset, deleted branches)

```bash
# Show all reflog entries across all refs
git reflog --all
# Inspect each referenced commit
git show <reflog-sha>
# Also check for branch-level reflogs
ls .git/logs/refs/heads/
```

### 1.5 Unreachable Objects (dangling blobs, commits, trees)

```bash
# Find unreachable objects (reflogs expired to avoid false negatives)
git fsck --unreachable --no-reflogs 2>&1
# Inspect each unreachable object
git cat-file -p <hash>
```

### 1.6 Replace Refs

```bash
# List replace refs
git replace -l
# Inspect each replaced object
git cat-file -p <replace-ref>
```

### 1.7 Annotated Tags

```bash
# List all tags
git tag -l
# For each tag, check if it's annotated and inspect
git cat-file -t <tag-name>   # "tag" means annotated
git cat-file -p <tag-name>   # shows tag object including message
```

### 1.8 Backup Refs (from filter-branch, etc.)

```bash
# Check for backup refs
git for-each-ref refs/original/
# Inspect each
git show <ref>
```

### 1.9 FETCH_HEAD, ORIG_HEAD, MERGE_HEAD

```bash
# Check these special refs
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [ -f ".git/$f" ] && echo "=== $f ===" && cat ".git/$f"
done
```

### 1.10 Submodule Object Databases

```bash
# Check for submodules
cat .gitmodules 2>/dev/null
ls .git/modules/ 2>/dev/null
# For each submodule, repeat discovery within its own repo
cd .git/modules/<submodule> && git fsck --unreachable --no-reflogs
```

### 1.11 Exhaustive Object Scan (nuclear option)

If the secret hasn't been found yet, scan ALL objects in the repository:

```bash
# Enumerate every reachable object
git rev-list --all --objects | awk '{print $1}' | while read hash; do
  git cat-file -p "$hash" 2>/dev/null
done | grep "secret\["

# Also scan ALL loose objects in .git/objects/
find .git/objects -type f | grep -v pack | while read f; do
  hash=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$hash" 2>/dev/null
done | grep "secret\["

# Scan packed objects
for pack in .git/objects/pack/*.idx; do
  [ -f "$pack" ] && git verify-pack -v "$pack" | awk '{print $1}' | while read hash; do
    git cat-file -p "$hash" 2>/dev/null
  done | grep "secret\["
done
```

### 1.12 Raw Binary Scan of .git/

```bash
# Last resort: grep the entire .git directory (handles binary content)
grep -rl "secret\[" .git/ 2>/dev/null
```

## Phase 2: RECOVER — Extract the Secret

1. Extract the exact secret string matching the expected pattern (e.g., `secret[...]`)
2. Write it to the specified output file:
   ```bash
   echo 'secret[the_actual_value]' > /app/secret.txt
   ```
3. Confirm the file contents match exactly.

## Phase 3: CLEAN — Make Secret Irrecoverable

**Critical ordering**: Reflogs must be expired BEFORE pruning, because reflogs
keep objects reachable. The cleanup sequence matters.

### 3.1 Remove Tainted Refs

```bash
# Drop tainted stashes
git stash drop stash@{N}

# Delete replace refs
git replace -d <ref>

# Delete tainted tags
git tag -d <tag-name>

# Delete backup refs (from filter-branch)
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done

# Delete special HEAD files if they reference tainted objects
rm -f .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD \
      .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
```

### 3.2 Rewrite Reachable History (if secret is in committed history)

If the secret exists in reachable commits, rewrite history to remove it:

```bash
# Option A: git filter-repo (preferred, faster, safer)
# Install: pip install git-filter-repo
git filter-repo --replace-text expressions.txt --force
# Where expressions.txt contains: secret[...]==>*REMOVED*<

# Option B: git filter-branch (built-in, slower)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <path-to-secret-file>' \
  --prune-empty -- --all

# IMPORTANT: filter-branch creates backup refs — delete them!
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

### 3.3 Expire All Reflogs

```bash
git reflog expire --expire=now --all
```

### 3.4 Prune All Unreachable Objects

```bash
# Aggressive gc repacks and prunes
git gc --prune=now --aggressive

# Alternative: explicit prune
git prune --expire=now
```

### 3.5 Handle Submodules

If the repo has submodules, repeat the entire cleanup for each:

```bash
git submodule foreach '
  git reflog expire --expire=now --all
  git gc --prune=now --aggressive
'
```

### 3.6 Handle Nested Repositories

If `.git/modules/` contains submodule object databases:

```bash
for moddir in .git/modules/*/; do
  (cd "$moddir" && git reflog expire --expire=now --all && git gc --prune=now --aggressive)
done
```

## Phase 4: VERIFY — Confirm Cleanup and Preservation

### 4.1 No Tainted Objects Remain

```bash
# Should produce no output (or only non-tainted objects)
git fsck --unreachable --no-reflogs 2>&1

# Binary grep of entire .git directory — should find nothing
grep -rl "secret\[" .git/ 2>/dev/null
# If anything found, go back to Phase 3
```

### 4.2 Legitimate Content Preserved

```bash
# Verify branches exist
git branch -a

# Verify tags exist
git tag -l

# Verify commit history
git log --all --oneline

# Verify working tree files
ls -la

# Verify no unintended changes
git status
git diff
```

### 4.3 Final Sanity Check

```bash
# Ensure the repo is in a clean state
git status  # should show clean working tree
git fsck    # should show no errors
```

## Key Pitfalls and Decision Points

1. **Reflog-before-prune ordering**: Always expire reflogs before running gc/prune.
   Reflogs keep objects reachable; pruning while reflogs exist is ineffective.

2. **`--no-reflogs` on fsck**: Critical for discovery. Without it, fsck skips
   objects that reflogs reference, hiding unreachable blobs.

3. **filter-branch backup refs**: filter-branch creates `refs/original/` backups.
   These MUST be deleted before pruning, or the secret remains reachable.

4. **Dropped stashes persist**: A dropped stash may still exist as a dangling
   commit. Use `git fsck` to find them after dropping.

5. **Packed objects**: `git gc --aggressive` repacks, eliminating packed copies.
   Plain `git prune` may miss objects inside packs.

6. **Multiple locations**: The secret may exist in multiple places simultaneously.
   Discovery must check ALL locations; cleanup must address ALL of them.

7. **Binary content in .git/**: Use `grep -r` (not `grep -R`) and consider
   `strings` or hex tools if the secret is embedded in pack files.

8. **Repo complexity scaling**: For repos with many branches/merges/tags,
   the exhaustive scan (1.11) becomes expensive. Use targeted searches first.

## Adaptation Guide

| Scenario | Key Actions |
|---|---|
| Secret was `git add` then removed (v01) | fsck --unreachable → cat-file → expire reflogs → gc |
| Secret was committed then reverted | log -p → filter-repo/branch → delete backup refs → expire → gc |
| Secret in stash | stash show → stash drop → expire → gc |
| Secret in deleted branch | reflog → find tip → fsck → expire → gc |
| Secret in annotated tag | cat-file tag → tag -d → expire → gc |
| Secret in replace ref | replace -l → replace -d → expire → gc |
| Secret in submodule | Enter submodule dir → repeat full procedure |
| Secret in multiple locations | Combine all applicable recovery + cleanup steps |

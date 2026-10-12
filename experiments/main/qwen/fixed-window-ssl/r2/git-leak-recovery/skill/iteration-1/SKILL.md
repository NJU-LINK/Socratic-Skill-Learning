---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository and then purge it from all
  Git storage (reachable history, unreachable objects, stash, tags, reflogs,
  pack files, backup/replace refs) while preserving all legitimate repository
  content (branches, commits, files, tags, commit messages).
---

# Git Leak Recovery

## Overview

A secret was accidentally introduced into a Git repository — staged, committed,
stashed, tagged, or otherwise stored — and must be (a) recovered and written to
a specified output file, and (b) completely purged from the repository so it
cannot be found anywhere in `.git/`. All legitimate repository content must be
preserved untouched.

## Core Principles

1. **Recovery before cleanup.** Never destroy what you haven't extracted. Always
   identify and extract the secret value first.
2. **Survey before acting.** Scan every possible storage location to build a
   complete picture of where the secret lives before making any changes.
3. **Order matters.** Reflog expiration must precede `git gc`. History rewrites
   must precede reflog expiration. Stash drops must precede gc.
4. **Preserve legitimate content.** Branches, files, commit messages, tags (that
   don't contain the secret), and other commits must remain intact.
5. **Verify exhaustively.** After cleanup, brute-force search the entire `.git/`
   directory. A single remaining reference means cleanup is incomplete.

## Phase 1 — Survey the Repository

Run all of these to understand the repo's topology and locate the secret:

```bash
# Basic topology
git log --all --oneline --graph
git branch -a
git tag -l
git status
git stash list

# Reflog — reveals recently-dropped references
git reflog
git reflog --all

# Unreachable objects — blobs, trees, commits no ref points to
git fsck --unreachable --no-reflogs 2>&1

# Special refs that may reference tainted commits
ls .git/refs/original/ 2>/dev/null
ls .git/refs/replace/ 2>/dev/null
cat .git/FETCH_HEAD 2>/dev/null
cat .git/ORIG_HEAD 2>/dev/null
cat .git/MERGE_HEAD 2>/dev/null

# Check the index for staged content
git ls-files --stage
```

## Phase 2 — Recover the Secret

Search every location identified in Phase 1. The secret format is typically
`secret[...]` — grep for that pattern.

### Unreachable blobs (staged-then-removed, or reset-away files)
```bash
# From fsck output, extract blob SHAs
git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable blob" | awk '{print $3}' | while read sha; do
  git cat-file -p "$sha"
done
```

### Reachable history (committed then amended/reset/filtered)
```bash
# Search all commits for the secret
git log --all --format="%H" | while read sha; do
  git diff-tree --no-commit-id -r "$sha" 2>/dev/null | awk '{print $4}' | while read blob; do
    git cat-file -p "$blob" 2>/dev/null | grep -l "secret\[" && echo "Found in commit $sha blob $blob"
  done
done
# Or simpler: search tree contents
git log --all --format="%H" | while read sha; do
  git show "$sha" 2>/dev/null | grep "secret\[" && echo "Found in commit $sha"
done
```

### Stash entries
```bash
git stash list
# For each stash entry:
git stash show -p stash@{N} | grep "secret\["
# Or dump the full stash content:
git cat-file -p stash@{N}
```

### Tags (annotated tags may contain secret in message)
```bash
git tag -l | while read tag; do
  git cat-file -p "$tag" 2>/dev/null | grep "secret\["
done
```

### Index (currently staged)
```bash
git ls-files --stage | awk '{print $2}' | while read blob; do
  git cat-file -p "$blob" 2>/dev/null | grep "secret\["
done
```

### Brute-force search (catches everything)
```bash
# Search all objects in the object store
find .git/objects -type f | while read f; do
  # Convert path to SHA: .git/objects/ab/cdef... -> abcdef...
  sha=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$sha" 2>/dev/null | grep "secret\[" && echo "FOUND in $sha ($f)"
done
```

**Write the recovered secret to the output file immediately** (typically `/app/secret.txt` or as specified).

## Phase 3 — Cleanup

Execute only the steps relevant to what Phase 1 found. The order below is
critical.

### 3a. Remove secret from reachable history (if committed)

If the secret exists in any reachable commit, rewrite history:

```bash
# Option A: git filter-repo (preferred, faster, safer)
# Remove a specific file from all history:
git filter-repo --invert-paths --path <file-with-secret> --force
# Or replace content in all blobs:
git filter-repo --replace-text <(echo "secret[...]===DELETE===") --force

# Option B: git filter-branch (older, available everywhere)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <file-with-secret>' \
  --prune-empty -- --all
```

**Important:** After filter-branch, backup refs are created at `refs/original/`.
These must be deleted in step 3d.

### 3b. Drop tainted stash entries
```bash
# Drop specific stash:
git stash drop stash@{N}
# Or clear all stashes:
git stash clear
```

### 3c. Delete tainted tags
```bash
# Only delete tags that contain or point to tainted content
git tag -d <tag-name>
```

### 3d. Remove backup and replace refs
```bash
# Remove filter-branch backups
git for-each-ref --format="%(refname)" refs/original/ | while read ref; do
  git update-ref -d "$ref"
done

# Remove replace refs
git for-each-ref --format="%(refname)" refs/replace/ | while read ref; do
  git update-ref -d "$ref"
done
```

### 3e. Remove transient HEAD references
```bash
rm -f .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD .git/CHERRY_PICK_HEAD
```

### 3f. Expire ALL reflogs (MUST come before gc)
```bash
git reflog expire --expire=now --all
```

### 3g. Prune unreachable objects (MUST come after reflog expiration)
```bash
git gc --prune=now --aggressive
```

## Phase 4 — Verify (Non-Negotiable)

After cleanup, verify exhaustively that the secret is gone AND legitimate
content is preserved.

### 4a. Brute-force search for the secret pattern
```bash
# Search entire .git directory (binary-safe grep)
grep -ra "secret\[" .git/ 2>/dev/null
# If this returns ANY output, cleanup is INCOMPLETE.
```

### 4b. Check no unreachable objects contain the secret
```bash
git fsck --unreachable --no-reflogs 2>&1
# Any remaining unreachable objects should be inspected:
git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable" | awk '{print $3}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep "secret\[" && echo "STILL FOUND in $sha"
done
```

### 4c. Search pack files specifically
```bash
grep -ra "secret\[" .git/objects/pack/ 2>/dev/null
```

### 4d. Verify legitimate content preserved
```bash
# All branches still exist
git branch -a
# All commits still present (check messages unchanged)
git log --all --oneline
# Working tree files intact
git status
# Tags preserved (unless intentionally deleted)
git tag -l
```

## Decision Tree

```
Survey repo
  │
  ├─ Secret in unreachable blob only?
  │   → Recover via git cat-file -p
  │   → Cleanup: reflog expire + gc --prune=now
  │
  ├─ Secret in reachable commit(s)?
  │   → Recover via git show / git cat-file
  │   → Cleanup: filter-branch/filter-repo → delete refs/original →
  │     reflog expire → gc --prune=now
  │
  ├─ Secret in stash?
  │   → Recover via git stash show -p
  │   → Cleanup: git stash drop/clear → reflog expire → gc
  │
  ├─ Secret in annotated tag?
  │   → Recover via git cat-file -p <tag>
  │   → Cleanup: git tag -d → reflog expire → gc
  │
  ├─ Secret in multiple locations?
  │   → Recover from ALL locations first
  │   → Apply all relevant cleanup steps in order
  │
  └─ Secret in index (currently staged)?
      → Recover via git cat-file -p <blob-sha-from-ls-files>
      → Cleanup: git rm --cached → reflog expire → gc
```

## Common Pitfalls

- **Skipping reflog expiration before gc.** Reflogs keep objects "reachable"
  from git's perspective. Without expiring them first, `git gc --prune=now`
  will NOT delete the objects.
- **Forgetting `refs/original/` after filter-branch.** These backup refs keep
  the old (tainted) commits reachable. Must be deleted before gc.
- **Not using binary-safe grep.** Pack files are binary. Use `grep -a` or
  `grep -r` with appropriate flags.
- **Deleting all tags indiscriminately.** Only delete tags that contain or
  point to tainted content. Legitimate tags must be preserved.
- **Not checking FETCH_HEAD/ORIG_HEAD/MERGE_HEAD.** These transient refs can
  reference tainted commits and survive gc.

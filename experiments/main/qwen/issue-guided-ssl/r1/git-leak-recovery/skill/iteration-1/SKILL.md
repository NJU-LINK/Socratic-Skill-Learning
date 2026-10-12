---
name: git-leak-recovery
description: >
  Recover leaked secrets from Git repositories and clean them from all storage
  locations. Handles secrets in reachable history, stashes, reflogs, unreachable
  blobs, replace refs, backup refs, tags, submodule ODBs, and any combination.
  Follows an ordered search-first-then-clean protocol to ensure recovery before
  destructive cleanup.
---

# Git Leak Recovery

## Family Axes

This skill covers the `git-leak-recovery` family defined by three axes:

### 1. secret_location (where the leaked value lives)
- Unreachable blobs (staged then removed, never committed)
- Reachable history (committed then left in branch history)
- Stashes (live or dropped)
- Reflogs (commits reachable only via reflog entries)
- Replace refs (original objects replaced by grafts)
- Backup refs (`refs/original/...` from filter-branch)
- Annotated tags (tag objects referencing tainted commits/trees)
- Submodule object databases (separate `.git` dirs)
- Notes, merge commits, amended/reset-away commits, deleted branches

### 2. repo_complexity (topology to preserve)
- Single branch, few commits (v01)
- Multiple branches, tags, merges
- Nested repositories / submodules
- Dozens of legitimate commits
- Both reachable and unreachable histories

### 3. cleanup_scope (what keeps the leak recoverable)
- Dropped stashes, removed replace/backup refs
- Deleted tainted tags
- Rewritten reachable history (filter-branch / filter-repo)
- Expired reflogs, pruned unreachable objects
- All relevant object databases

## Core Principle

**Recovery MUST happen before destructive cleanup.** If you expire reflogs, prune objects, or rewrite history before searching, you may destroy the only copy of the secret.

## Ordered Search Protocol

Search these locations **in order**, collecting candidates from each before any cleanup:

1. **Reachable history** — `git log --all -p`, `git grep` across all revisions
2. **Stashes** — `git stash list`, then `git stash show -p stash@{N}`
3. **Reflogs** — `git reflog --all`, inspect each entry's commit/tree
4. **Unreachable/dangling objects** — `git fsck --unreachable --no-reflogs`
5. **Replace refs** — `git replace -l`, examine original objects
6. **All refs** — `git for-each-ref`, check backup refs, notes, etc.
7. **Tags** — annotated tag objects may reference tainted content
8. **Submodule ODBs** — each submodule's `.git` has its own object store

## Cleanup Methodology (After Recovery)

1. **Remove the source** — drop tainted stash, delete tainted branch/ref, remove replace ref, delete tainted tag, or rewrite history with `git filter-branch` / `git filter-repo`
2. **Expire all reflogs** — `git reflog expire --expire=now --all`
3. **Prune unreachable objects** — `git gc --prune=now --aggressive`
4. **Remove pack references** — `git repack -a -d` if needed
5. **Verify** — Re-run the full search. If the secret is still found, repeat cleanup for that location.

## Script

The primary executable is `scripts/recover_and_clean.sh`. See its header for usage.

## Verification

After cleanup, the script re-runs the search protocol. The repo must:
- Contain zero instances of the secret pattern in any object
- Retain all legitimate branches, files, tags, and commit messages

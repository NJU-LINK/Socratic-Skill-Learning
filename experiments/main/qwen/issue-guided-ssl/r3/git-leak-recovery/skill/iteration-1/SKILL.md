---
name: git-leak-recovery
description: >
  Recover leaked secrets from Git repositories and perform thorough cleanup.
  Handles secrets in unreachable blobs, reflog-reachable commits, stashes
  (live/dropped), reachable history, special refs (replace, backup, stash),
  tags, and submodule object databases. Preserves legitimate repo content.
---

# Git Leak Recovery

## Overview

This skill recovers accidentally-leaked secrets from Git repositories and removes all traces. The secret format is typically `secret[...]`. The procedure works across all Git storage locations and repo topologies.

## Critical Invariant

**Recovery MUST complete before any cleanup.** Once objects are pruned, the secret is irrecoverable.

## General Procedure

### Phase 1: Survey the Repository

Understand the repo topology before touching anything:

```bash
# Basic topology
git branch -a
git tag -l
git stash list
git for-each-ref --format='%(refname) %(objecttype) %(objectname)' | sort

# Check for special refs
ls .git/refs/original/ 2>/dev/null
ls .git/refs/replace/ 2>/dev/null
cat .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null

# Check for submodules
cat .gitmodules 2>/dev/null
ls .git/modules/ 2>/dev/null
```

### Phase 2: Detect the Secret in All Locations

Search every possible storage location systematically. Use the known secret pattern (e.g., `secret[`) to locate it.

#### 2a. Unreachable/Dangling Blobs

These arise when a file was `git add`-ed then unstaged/deleted without ever being committed.

```bash
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep -E "^(unreachable|dangling) blob" | awk '{print $NF}'
```

For each blob SHA found:
```bash
git cat-file -p <sha>
```

#### 2b. Reflog-Reachable Commits

Any branch movement (reset, amend, rebase) leaves old commits in the reflog.

```bash
git reflog --all --format='%H %gs'
```

For each commit SHA in the reflog:
```bash
git show <sha> --stat
git diff <sha>^ <sha> 2>/dev/null || git show <sha>  # for initial commits
```

Or search all reflog commits for the pattern:
```bash
git reflog --all --format='%H' | while read sha; do
  git log -1 -p "$sha" 2>/dev/null | grep -l "secret\[" && echo "Found in reflog commit $sha"
done
```

#### 2c. Stashes

Live stashes are visible via `git stash list`. Dropped stashes become dangling merge commits found by `git fsck`.

```bash
# Live stashes
git stash list
git stash show -p stash@{N}

# Dropped stashes (dangling commits from fsck)
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep "commit" | awk '{print $NF}' | while read sha; do
  git show "$sha" 2>/dev/null | grep "secret\[" && echo "Found in dangling commit $sha"
done
```

#### 2d. Reachable History (Committed then Reverted)

```bash
# Search all reachable commits for the pattern
git log --all -S "secret[" -p
# Or search all diffs
git log --all -p | grep -B5 -A5 "secret\["
```

#### 2e. Special Refs

Replace refs, backup refs (from filter-branch), and stash refs can point to tainted objects.

```bash
# Replace refs
git for-each-ref refs/replace/ --format='%(objectname)' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep "secret\[" && echo "Found in replace ref $sha"
done

# Backup refs (filter-branch leftovers)
git for-each-ref refs/original/ --format='%(objectname)' | while read sha; do
  git log -1 -p "$sha" 2>/dev/null | grep "secret\[" && echo "Found in backup ref $sha"
done
```

#### 2f. Tags

Tags can point to commits or trees containing secrets.

```bash
git tag -l | while read tag; do
  git show "$tag" 2>/dev/null | grep "secret\[" && echo "Found in tag $tag"
done
```

#### 2g. Submodule Object Databases

Each submodule has its own `.git/modules/<name>/objects/`. Run the same detection procedure inside each submodule.

#### 2h. Raw Object Database Sweep

As a catch-all, enumerate ALL objects and search their content:

```bash
# All reachable objects
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "FOUND in reachable object $sha"
done

# All objects including unreachable (from pack files and loose)
find .git/objects -type f | while read f; do
  # Extract SHA from path
  sha=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "FOUND in object $sha"
done
```

### Phase 3: Recover the Secret

Once located, extract the secret value and write it to the required output location (typically `/app/secret.txt`):

```bash
# For a blob:
git cat-file -p <blob_sha> > /app/secret.txt

# For content in a commit diff:
git show <commit_sha> -- <path> | grep "secret\[" > /app/secret.txt
```

**Confirm recovery before proceeding to cleanup.**

### Phase 4: Cleanup (Ordered)

Remove the secret from every location. Order matters:

#### Step 4.1: Delete Special Refs Pointing to Tainted Objects

```bash
# Remove replace refs
git for-each-ref --format='%(refname)' refs/replace/ | xargs -r -n1 git update-ref -d

# Remove backup refs (filter-branch leftovers)
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d

# Remove stash if tainted
git for-each-ref --format='%(refname)' refs/stash | xargs -r -n1 git update-ref -d
```

#### Step 4.2: Remove Tainted Tags

Only delete tags that reference tainted objects. Preserve legitimate tags.

```bash
# For each tainted tag:
git tag -d <tagname>
```

#### Step 4.3: Rewrite Reachable History (if secret was committed)

If the secret exists in reachable commit history, use `git filter-repo` (preferred) or `git filter-branch`:

```bash
# Using git filter-repo (requires git-filter-repo installed)
git filter-repo --strip-blobs-with-ids <blob_ids_file>

# Or using filter-branch
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <path_to_secret_file>' \
  --prune-empty -- --all
```

**Warning**: History rewriting changes commit SHAs. This is destructive to shared history.

#### Step 4.4: Expire All Reflogs

Reflogs keep old commits reachable. Expire them all:

```bash
git reflog expire --expire=now --all
```

#### Step 4.5: Prune Unreachable Objects

```bash
# Repack to consolidate, removing unreachable objects
git repack -A -d -l

# Prune loose unreachable objects
git prune --expire=now

# Final garbage collection sweep
git gc --prune=now --aggressive
```

#### Step 4.6: Handle Submodule Object Databases

If submodules contain the secret, repeat the cleanup procedure inside each submodule's git directory.

### Phase 5: Verify (Multi-Method)

Do not trust a single verification method. Use all of these:

#### 5a. fsck Check

```bash
git fsck --unreachable --dangling --no-reflogs 2>&1
# Should show NO unreachable blobs/commits containing the secret
```

#### 5b. Reachable Object Sweep

```bash
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK STILL PRESENT in $sha"
done
```

#### 5c. Raw Filesystem Grep

```bash
# Search the entire .git directory for the secret pattern
grep -rl "secret\[" .git/ 2>/dev/null
# Should return nothing
```

#### 5d. Ref Verification

```bash
# Confirm no refs point to tainted objects
git for-each-ref --format='%(refname) %(objectname)' | while read ref sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK in ref $ref -> $sha"
done
```

### Phase 6: Preservation Check

Confirm legitimate content is intact:

```bash
# All branches still exist
git branch -a

# All legitimate tags still exist
git tag -l

# Commit messages unchanged (if history was not rewritten)
git log --oneline --all

# Working tree clean
git status

# Legitimate files present
ls -la
```

## Decision Points

| Situation | Action |
|-----------|--------|
| Secret only in unreachable blob | Recover via `git cat-file -p`, then `git gc --prune=now` |
| Secret in reflog commit | Recover from reflog commit, expire reflogs, then gc |
| Secret in live stash | Recover from stash, `git stash drop`, then gc |
| Secret in dropped stash | Find dangling commit via fsck, recover, then gc |
| Secret in reachable history | Recover, then `git filter-repo` or `git filter-branch` to rewrite |
| Secret in replace/backup ref | Delete the ref, then gc |
| Secret in tag | Delete the tag, then gc |
| Secret in submodule | Repeat entire procedure inside submodule |
| Multiple locations | Recover first from ALL locations, then clean ALL locations |

## Edge Cases

- **Packed objects**: After `git gc`, objects may be in pack files. The raw filesystem grep (Phase 5c) catches these.
- **Shallow clones**: May not have full history. Use `git fetch --unshallow` first if needed.
- **Bare repositories**: No working tree; all content is in objects. Adjust file checks accordingly.
- **Multiple secrets**: The procedure works for any number of secrets; just ensure all are recovered before cleanup.
- **Large repos**: The object-by-object sweep can be slow. Use `git grep` for reachable content and `git fsck` for unreachable content as faster alternatives.

## Reference Script

See `scripts/cleanup-and-verify.sh` for an automated cleanup and verification script.

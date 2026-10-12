---
name: git-leak-recovery
description: Recover secrets leaked into Git storage and permanently remove them while preserving legitimate repository content.
---

# Git Leak Recovery Skill

## Overview

Recover secrets (format: `secret[...]`) from Git repositories and permanently remove them while preserving legitimate content.

## Core Mental Model: Pins and Reachability

**Question:** What pins the secret-bearing object in the Git database?

**Answer:** Remove every pin, then prune unreachable objects.

### Two Remediation Regimes

| Regime | Condition | Solution |
|--------|-----------|----------|
| **Unreachable** | Secret in objects not referenced by refs | `reflog expire --expire=now --all && prune --expire=now && gc --prune=now` |
| **Reachable** | Secret in commit history referenced by branches/tags | Rewrite history with `git-filter-repo` |

### Pin Types

| Pin | What It Holds | Removal |
|-----|--------------|---------|
| Index entry | Blob | `git rm --cached <file>` |
| Branch/tag refs | Commit chain | History rewrite |
| Reflog entries | Any object | `reflog expire --expire=now --all` |
| Stash ref | Stash commit | `git stash clear` |
| Replace refs | Replacement object | `git replace --delete <ref>` |

## Phase 1: Discovery (Non-Destructive)

**CRITICAL:** Extract the secret BEFORE any cleanup.

```bash
# Check all locations
secret=""

# 1. Worktree
grep -r "secret\[" . --include="*" 2>/dev/null | grep -v ".git/" | head -1

# 2. Index
git ls-files --stage | while read mode hash stage path; do
    git cat-file -p "$hash" 2>/dev/null | grep -q "secret\[" && echo "In index: $path"
done

# 3. Stashes (check before reachable - stashes appear in rev-list)
git stash list --format='%H' | while read h; do
    git grep "secret\[" "$h" -- 2>/dev/null && echo "In stash: $h"
done

# 4. Reachable commits
for commit in $(git rev-list --all); do
    # Skip stash commits
    is_stash=0
    for sh in $(git stash list --format='%H'); do
        [ "$commit" = "$sh" ] && is_stash=1 && break
    done
    [ "$is_stash" -eq 1 ] && continue
    git grep "secret\[" "$commit" -- 2>/dev/null && echo "In commit: $commit"
done

# 5. Unreachable objects (DISPATCH ON TYPE - critical!)
git fsck --unreachable --no-reflogs | while read type hash; do
    objtype=$(git cat-file -t "$hash" 2>/dev/null)
    if [ "$objtype" = "commit" ]; then
        # For commits: use git grep to check tree contents
        git grep "secret\[" "$hash" -- 2>/dev/null && echo "In unreachable commit: $hash"
    else
        # For blobs/tags: use cat-file directly
        git cat-file -p "$hash" 2>/dev/null | grep "secret\[" && echo "In unreachable $objtype: $hash"
    fi
done

# 6. Annotated tags
for tag in $(git tag -l); do
    git cat-file -p "$tag" 2>/dev/null | grep "secret\[" && echo "In tag: $tag"
done

# 7. Replace refs (original objects behind replacements)
for ref in $(GIT_NO_REPLACE_OBJECTS=1 git replace -l 2>/dev/null); do
    GIT_NO_REPLACE_OBJECTS=1 git cat-file -p "$ref" 2>/dev/null | grep "secret\[" && echo "In replace ref: $ref"
done

# 8. Submodules (separate object databases)
for mod in .git/modules/*; do
    [ -d "$mod" ] || continue
    GIT_DIR="$mod" git cat-file --batch-all-objects --buffer 2>/dev/null | \
        while read hash type size; do
            [ "$type" = "blob" ] || continue
            GIT_DIR="$mod" git cat-file -p "$hash" 2>/dev/null | grep "secret\[" && echo "In submodule: $mod"
        done
done
```

## Phase 2: Extraction

Once found, extract and save BEFORE cleanup:

```bash
# From blob/tag content
secret=$(git cat-file -p <hash> | grep -oE 'secret\[[^]]*\]' | head -1)

# From commit (git grep output)
match=$(git grep "secret\[" <commit> -- | head -1)
secret=$(echo "$match" | grep -oE 'secret\[[^]]*\]' | head -1)

# Save to output file
echo "$secret" > /app/secret.txt
```

## Phase 3: Cleanup by Regime

### Regime 1: Unreachable Objects

```bash
# Remove all pins
git reflog expire --expire=now --all
git stash clear 2>/dev/null || true
for ref in $(git replace -l); do git replace --delete "$ref"; done

# Remove tainted annotated tags
for tag in $(git tag -l); do
    git cat-file -p "$tag" 2>/dev/null | grep -q "secret\[" && git tag -d "$tag"
done

# Prune unreachable objects
git prune --expire=now
git gc --prune=now --aggressive
```

### Regime 2: Reachable History

```bash
# Requires git-filter-repo
pip install git-filter-repo 2>/dev/null || pip3 install git-filter-repo
git filter-repo --replace-text <(echo 'regex:secret\[[^]]*\]==>***REMOVED***') --force

# Remove pins after rewrite
git reflog expire --expire=now --all
git repack -ad
git prune --expire=now
```

**Note:** `git filter-branch` can only remove files, not rewrite blob content. For true redaction, `git-filter-repo` is required.

## Phase 4: Verification

```bash
verify_failed=0

# Worktree
grep -rq "secret\[" . --include="*" 2>/dev/null && verify_failed=1

# Index
git ls-files --stage | while read m h s p; do
    git cat-file -p "$h" 2>/dev/null | grep -q "secret\[" && verify_failed=1
done

# Commits
for commit in $(git rev-list --all); do
    git grep -q "secret\[" "$commit" -- 2>/dev/null && verify_failed=1
done

# Unreachable (with type dispatch)
git fsck --unreachable --no-reflogs | while read type hash; do
    objtype=$(git cat-file -t "$hash" 2>/dev/null)
    if [ "$objtype" = "commit" ]; then
        git grep -q "secret\[" "$hash" -- 2>/dev/null && verify_failed=1
    else
        git cat-file -p "$hash" 2>/dev/null | grep -q "secret\[" && verify_failed=1
    fi
done

# Tags
for tag in $(git tag -l); do
    git cat-file -p "$tag" 2>/dev/null | grep -q "secret\[" && verify_failed=1
done

# Replace refs
for ref in $(GIT_NO_REPLACE_OBJECTS=1 git replace -l 2>/dev/null); do
    GIT_NO_REPLACE_OBJECTS=1 git cat-file -p "$ref" 2>/dev/null | grep -q "secret\[" && verify_failed=1
done

# MUST fail if secret remains
[ "$verify_failed" -eq 0 ] || exit 1
```

## Critical Implementation Details

1. **Type Dispatch**: For unreachable objects, use `git cat-file -t` to check type. Use `git grep` for commits (checks tree), `cat-file -p` for blobs/tags.

2. **Commit Content**: `git cat-file -p <commit>` shows metadata (tree, parents, message), NOT file contents. Use `git grep` to check file contents.

3. **Replace Refs**: Git transparently shows replacements. Use `GIT_NO_REPLACE_OBJECTS=1` to see original objects.

4. **Stash Detection**: Stash commits appear in `git rev-list --all`. Check stashes first, then skip them when checking reachable commits.

5. **Stash Index**: A stash has two commits - `$stash` (worktree) and `$stash^2` (index). Check both.

6. **Worktree Cleanup**: After `git rm --cached`, delete the file from disk with `rm`.

7. **Force Flag**: Use `git rm -f --cached` to handle staged modifications.

8. **Order Matters**: Extract → Cleanup → Verify. Never clean before extracting.

9. **Fatal Verification**: Any remaining secret MUST cause exit code 1.

## Secret Location Variations

| Location | Regime | Notes |
|----------|--------|-------|
| Unreachable blob (v01) | Unreachable | Staged then removed from index |
| Staged file | Unreachable | Remove from index + worktree |
| Live stash | Unreachable | `git stash clear` |
| Dropped stash | Unreachable | Already unreachable |
| Reachable commit | Reachable | Needs filter-repo |
| Annotated tag | Varies | Delete tag; may need history rewrite |
| Replace ref | Unreachable | Delete replace ref + prune |
| Submodule | Varies | Check `.git/modules/*` |

## Usage

```bash
./recover-secret.sh [repo_path] [output_file]
```

See `scripts/recover-secret.sh` for complete implementation.

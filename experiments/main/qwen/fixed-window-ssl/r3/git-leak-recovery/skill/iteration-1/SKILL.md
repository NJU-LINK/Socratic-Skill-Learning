---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository (from any storage location —
  unreachable blobs, reachable history, stashes, deleted branches, replace refs,
  tags, pack files, pseudo-refs, submodules) and then purge it completely so no
  copy remains anywhere in the repository's object database, references,
  reflogs, or pack files, while preserving all legitimate content (branches,
  commits, files, tags, messages).
---

# Git Leak Recovery

## Quick Start

A standalone script implementing all phases is available at:
```
scripts/cleanup.sh <repo_dir> <secret_pattern> [output_file]
```

For manual or partial execution, follow the four-phase procedure below.

## Overview

A secret (any string matching a known pattern, e.g. `secret[...]`) has been
accidentally introduced into a Git repository. It may live in:

- An unreachable (dangling) blob — staged then removed before commit
- Reachable history — committed to a branch, possibly later amended/reset away
- A stash (live or dropped)
- A deleted branch still referenced by reflog
- A replace ref (`refs/replace/`)
- An annotated tag object
- A pack file containing the blob
- Pseudo-refs (`FETCH_HEAD`, `ORIG_HEAD`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REBASE_HEAD`)
- A nested repository's object database (submodules)

This skill provides a **four-phase procedure** that works regardless of where
the secret lives, and a verification step that proves it is gone.

## Phase 1 — Discover

Enumerate every object and reference in the repository. Collect all SHAs that
contain the secret pattern.

```bash
REPO_DIR="<path-to-repo>"
SECRET_PATTERN='secret\['   # adjust to match the actual secret format
cd "$REPO_DIR"

# 1a. Unreachable/dangling objects
git fsck --unreachable --no-reflogs 2>&1

# 1b. All references (branches, tags, stashes, replace refs, backup refs, hidden refs)
git for-each-ref --format='%(objectname) %(refname)'

# 1c. Search reachable history for the pattern
git log --all -S "$SECRET_PATTERN" --oneline 2>/dev/null

# 1d. Search all blobs reachable from any ref
git grep -l "$SECRET_PATTERN" $(git rev-list --all) 2>/dev/null

# 1e. Stashes
git stash list 2>/dev/null

# 1f. Pseudo-refs (these are files in .git/ that hold commit SHAs)
for pseudo in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REBASE_HEAD; do
  [ -f ".git/$pseudo" ] && echo "$pseudo: $(cat .git/$pseudo)"
done

# 1g. Replace refs
git for-each-ref refs/replace/ 2>/dev/null

# 1h. ALL blob objects (including packs) — fast scan
ALL_BLOBS=$(git cat-file --batch-all-objects --batch='%(objectname) %(objecttype) %(objectsize)' | awk '$2=="blob"')
while read sha type size; do
  git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN" && echo "FOUND: $sha"
done <<< "$ALL_BLOBS"

# 1i. Submodules — recursively scan each submodule's object database
SUBMODULES=$(git submodule status 2>/dev/null | awk '{print $2}')
while read sub; do
  [ -z "$sub" ] && continue
  [ -d "$sub/.git" ] || [ -f "$sub/.git" ] && \
    (cd "$sub" && git fsck --unreachable --no-reflogs 2>&1)
done <<< "$SUBMODULES"
```

For each SHA found, inspect it:
```bash
git cat-file -t <sha>    # blob, tree, commit, tag
git cat-file -p <sha>    # print contents
```

## Phase 2 — Recover

Extract the secret value from whichever location(s) contain it.

| Location | Recovery command |
|----------|-----------------|
| Unreachable blob | `git cat-file -p <sha>` |
| Reachable history (committed file) | `git show <commit>:<path>` or `git log -p -S "secret["` |
| Stash | `git stash show -p stash@{N}` |
| Replace ref target | `git cat-file -p <replace-ref-sha>` |
| Tag object | `git cat-file -p <tag-sha>` |
| Pack file blob | `git cat-file -p <sha>` (after finding SHA from batch scan) |
| Pseudo-ref commit | `git log -1 -p <sha>` |
| Submodule blob | `(cd <sub> && git cat-file -p <sha>)` |

Write the recovered secret to the output file:
```bash
echo '<recovered-secret-value>' > /app/secret.txt
```

If multiple copies exist, they should all contain the same secret. Recover from
the first one found; the cleanup phase will remove all copies.

## Phase 3 — Cleanup (ORDER IS CRITICAL)

The cleanup must happen in this exact order. Doing it out of order will leave
the secret recoverable.

### Step 3a: Remove or rewrite references that make the secret reachable

This is the most important step. If the secret is reachable from any ref,
`git gc` will NOT remove it.

**For unreachable blobs only** (secret was staged but never committed, or was
in a dropped stash): No reference removal needed — the blob is already
unreachable. Skip to 3b.

**For reachable history** (secret was committed to a branch):
- If `git filter-repo` is available:
  ```bash
  git filter-repo --invert-paths --path <file-containing-secret> --force
  ```
- If only `git filter-branch` is available:
  ```bash
  git filter-branch --force --index-filter \
    'git rm --cached --ignore-unmatch <file>' \
    --prune-empty -- --all
  ```
- Or use interactive rebase to drop the specific commit:
  ```bash
  git rebase -i <commit-before-the-leak>
  # drop or edit the commit containing the secret
  ```

**For stashes containing the secret:**
```bash
git stash drop stash@{N}
```

**For tainted branches:**
```bash
git branch -D <branch-name>
```

**For tainted tags:**
```bash
git tag -d <tag-name>
```

**For replace refs:**
```bash
git for-each-ref --format='%(refname)' refs/replace/ | xargs -r git update-ref -d
```

**For backup refs left by filter-branch:**
```bash
git for-each-ref --format='%(refname)' refs/original/ | xargs -r git update-ref -d
```

**For tainted pseudo-refs:**
```bash
rm -f .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD .git/CHERRY_PICK_HEAD .git/REBASE_HEAD
```

### Step 3b: Expire ALL reflogs

Reflogs keep objects reachable even after refs are deleted.
```bash
git reflog expire --expire=now --all
```

### Step 3c: Prune unreachable objects

```bash
git gc --prune=now --aggressive
```

### Step 3d: Remove any remaining pack references

If packs still contain the secret blob (e.g., it was reachable until now):
```bash
git repack -a -d 2>/dev/null
```

## Phase 4 — Verify Exhaustively

Never assume cleanup worked. Run ALL of these checks:

```bash
# 4a. No unreachable objects remain
git fsck --unreachable --no-reflogs 2>&1
# Should produce no output (or only "notice" lines)

# 4b. No refs point to tainted objects
git for-each-ref --format='%(objectname) %(refname)'

# 4c. Search all reachable history
git log --all -S "$SECRET_PATTERN" --oneline 2>/dev/null
# Should produce no output

# 4d. Fast scan of ALL blob objects (including packs)
ALL_BLOBS=$(git cat-file --batch-all-objects --batch='%(objectname) %(objecttype) %(objectsize)' | awk '$2=="blob"')
while read sha type size; do
  git cat-file -p "$sha" 2>/dev/null | grep -qE "$SECRET_PATTERN" && \
    echo "LEAK STILL PRESENT in blob $sha"
done <<< "$ALL_BLOBS"

# 4e. Grep the raw .git directory as a last resort
grep -rl "$SECRET_PATTERN" .git/ 2>/dev/null
# May match pack files (binary); if so, re-check with cat-file as above

# 4f. Confirm legitimate content is intact
git log --oneline --all
git branch -a
git tag -l
```

If ANY check finds the secret, return to Phase 3 and address the specific
location found.

## Decision Tree

```
Is the secret in reachable history (committed to a branch)?
├── YES → Rewrite history (filter-repo/filter-branch/rebase), then 3b→3c→3d→4
└── NO ↓

Is the secret in a stash?
├── YES → Drop stash, then 3b→3c→3d→4
└── NO ↓

Is the secret in a branch/tag/replace-ref/pseudo-ref?
├── YES → Delete the ref, then 3b→3c→3d→4
└── NO ↓

Is the secret only in unreachable objects (dangling blobs)?
├── YES → Just 3b→3c→3d→4 (reflog expire + gc prune)
└── NO → Something unexpected; manually investigate with Phase 1
```

## Key Invariants (Family Properties)

1. **Recovery before cleanup**: Always extract the secret value before
   destroying the objects that contain it.
2. **Remove refs before pruning**: Objects reachable from any ref survive
   `git gc`. References must be removed/rewritten first.
3. **Expire reflogs before gc**: Reflogs keep objects reachable. Without
   expiring them, gc won't prune the objects.
4. **Verify after cleanup**: Never trust that cleanup succeeded without
   exhaustive verification including binary pack search.
5. **Preserve legitimate content**: The final repo must have all legitimate
   branches, files, tags, and commit messages intact. Only the secret and
   its containing objects/refs should be removed.

## Bash Pitfalls

When scripting this procedure, avoid these common bash errors:

1. **Pipe-to-subshell variable loss**: `cmd | while read ...` runs the while
   loop in a subshell. Variable assignments inside are lost. Fix: capture
   output first, then iterate with here-string:
   ```bash
   OUTPUT=$(git for-each-ref ...)
   while read sha refname; do
     # variables persist here
   done <<< "$OUTPUT"
   ```

2. **`--batch-all-objects` + `--batch-check` don't combine**: Use
   `--batch-all-objects --batch='%(objectname) %(objecttype) %(objectsize)'`
   to list all objects with type info.

## Variation Handling

- **secret_location**: The discovery phase walks ALL possible locations
  (unreachable objects, refs, stashes, pseudo-refs, replace refs, packs,
  submodules). The cleanup phase uses the decision tree to handle each
  location correctly.
- **repo_complexity**: The procedure works for any repo topology. `--all` flags
  ensure all branches are checked. `for-each-ref` catches all reference types.
- **cleanup_scope**: The verification phase checks every scope — loose objects,
  pack files, all ref types, reflogs. If any scope still contains the secret,
  the loop continues.

---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's storage (reachable or unreachable objects,
  reflogs, stashes, replace refs, tags, branches) and then fully purge it from the repo
  while preserving all legitimate content.
---

# Git Leak Recovery

## Overview

A secret was accidentally introduced into a Git repository and must be:
1. **Recovered** — find the exact secret string and write it to `/app/secret.txt`.
2. **Purged** — remove every trace of the secret from the repository so it cannot be
   recovered from any Git object, reflog, stash, pack, or loose object.
3. **Preserved** — all legitimate branches, commits, tags, files, and messages must
   remain intact and untouched.

The repo is at `/app/repo`. The secret matches the pattern `secret[...]`.

---

## Phase 1: Reconnaissance

Map the full topology of the repository before touching anything.

```bash
cd /app/repo

# 1. Branches, tags, remotes
git branch -a
git tag -l
git remote -v

# 2. Full commit graph
git log --all --oneline --graph --decorate

# 3. Stashes
git stash list

# 4. Special refs (replace, backup, original, stash)
ls -R .git/refs/
cat .git/packed-refs 2>/dev/null

# 5. Reflogs (may reference otherwise-deleted commits)
git reflog --all

# 6. Special HEAD files
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  cat .git/$f 2>/dev/null
done
```

---

## Phase 2: Locate the Secret

Search **every** Git object — reachable and unreachable — for the secret pattern.

### 2a. Unreachable / dangling objects

```bash
# List all unreachable objects (blobs, trees, commits)
git fsck --unreachable --no-reflogs 2>&1
git fsck --dangling 2>&1
```

For each unreachable object, inspect its content:

```bash
git cat-file -t <sha>          # type: blob, tree, or commit
git cat-file -p <sha>          # print content
```

If the object is a **blob** containing `secret[...]`, record both the value and the SHA.

### 2b. Reachable objects

```bash
# Walk every object reachable from any ref
for sha in $(git rev-list --all --objects | awk '{print $1}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in $sha ($(git cat-file -t $sha))"
  fi
done
```

### 2c. Stash entries

```bash
git stash list
# If stashes exist, inspect each:
for i in $(seq 0 $(git stash list | wc -l | tr -d ' ')); do
  git stash show -p "stash@{$i}" 2>/dev/null | grep 'secret\['
done
```

### 2d. Replace refs and backup refs

```bash
ls .git/refs/replace/ 2>/dev/null
ls .git/refs/original/ 2>/dev/null
ls .git/refs/stash 2>/dev/null
```

### 2e. Pack files

```bash
# If objects are packed, verify-pack lists them
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] && git verify-pack -v "$idx"
done
```

### 2f. Reflog entries

Reflogs can keep commits (and their trees/blobs) reachable even after branch deletion
or reset. Check whether any reflog entry references a commit containing the secret.

```bash
git reflog --all --format='%H %gd %gs'
```

---

## Phase 3: Recover the Secret

Once found, write the exact secret string to `/app/secret.txt`:

```bash
echo -n 'secret[...]' > /app/secret.txt
```

Verify:

```bash
cat /app/secret.txt
```

---

## Phase 4: Purge the Secret

The cleanup strategy depends on **where** the secret was found. Apply every
relevant step below.

### 4a. Drop stash entries containing the secret

```bash
# Drop specific stash entry (0-indexed, drop highest index first to avoid shifting)
git stash drop "stash@{N}"

# Or clear all stashes if they all contain the secret
git stash clear
```

### 4b. Remove replace refs

```bash
git update-ref -d refs/replace/<sha>
```

### 4c. Remove backup/original refs (left behind by filter-branch)

```bash
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

### 4d. Delete tainted tags

```bash
git tag -d <tagname>
```

### 4e. Rewrite reachable history (if secret is in a reachable commit)

Use `git filter-branch` or `git filter-repo` to remove the secret from history
while preserving legitimate commits and content.

```bash
# If filter-repo is available (preferred):
git filter-repo --invert-paths --path <leaked-file>

# Fallback: filter-branch
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <leaked-file>' \
  --prune-empty -- --all

# After filter-branch, remove backup refs:
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d
```

**Important**: After history rewriting, legitimate commit messages, branches,
and file contents must remain intact. Verify with `git log --all --oneline`.

### 4f. Expire all reflogs

Reflogs can retain references to commits that contain the secret, preventing
garbage collection.

```bash
git reflog expire --expire=now --all
```

### 4g. Prune unreachable objects

```bash
# Aggressive prune with immediate expiry
git gc --prune=now --aggressive

# Alternative: manual prune
git prune --expire=now
```

### 4h. Remove loose objects that still contain the secret

If `git gc` packed objects instead of removing them, or if loose objects persist:

```bash
# Find and remove the specific loose object file
# Object <sha> lives at .git/objects/<first-2-chars>/<remaining-38-chars>
sha="<sha-of-leaked-object>"
prefix="${sha:0:2}"
suffix="${sha:2}"
rm -f ".git/objects/${prefix}/${suffix}"
```

### 4i. Handle packed objects

If the secret ended up in a pack file, repack without it:

```bash
git repack -a -d --no-reuse-delta
git prune-packed
```

---

## Phase 5: Verification

Run a comprehensive check that the secret is **completely gone**.

### 5a. No dangling/unreachable objects with the secret

```bash
git fsck --unreachable --no-reflogs 2>&1
# Should show no blobs, or only blobs that don't contain the secret
```

### 5b. No reachable objects with the secret

```bash
for sha in $(git rev-list --all --objects | awk '{print $1}'); do
  git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\[' && echo "LEAK in $sha"
done
# Should produce no output
```

### 5c. No stashes remain (unless clean)

```bash
git stash list
```

### 5d. Reflogs are empty or clean

```bash
git reflog --all
# Should be empty or contain only clean entries
```

### 5e. No secret in any loose or packed object

```bash
# Brute-force scan of every object in the object database
for obj_dir in .git/objects/??; do
  prefix=$(basename "$obj_dir")
  for obj_file in "$obj_dir"/*; do
    suffix=$(basename "$obj_file")
    sha="${prefix}${suffix}"
    git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\[' && echo "LEAK: $sha"
  done
done
```

### 5f. Legitimate content preserved

```bash
git log --all --oneline        # all expected commits present
git branch -a                  # all expected branches present
git tag -l                     # all expected tags present
git status                     # clean working tree
cat <important-file>           # legitimate file content intact
```

### 5g. Final confirmation

```bash
cat /app/secret.txt            # secret was recovered correctly
```

---

## Decision Matrix: Secret Location → Cleanup Actions

| Secret Location               | Cleanup Actions                                      |
|-------------------------------|------------------------------------------------------|
| Dangling blob (staged, then `git rm --cached`) | 4f + 4g (expire reflog, prune)              |
| Reachable commit in history   | 4e (rewrite history) + 4c + 4f + 4g         |
| Stash entry                   | 4a (drop stash) + 4f + 4g                   |
| Replace ref                   | 4b (delete ref) + 4f + 4g                   |
| Backup ref (refs/original/)   | 4c (delete ref) + 4f + 4g                   |
| Annotated tag object          | 4d (delete tag) + 4f + 4g                   |
| Deleted branch (in reflog)    | 4f (expire reflog) + 4g (prune)             |
| Pack file                     | 4f + 4g + 4i (repack)                       |

Multiple locations may apply simultaneously. Always apply 4f + 4g as the
final universal cleanup step.

---

## Common Pitfalls

1. **Forgetting reflogs**: Even after deleting a branch or resetting, the reflog
   keeps old commits alive. Always `git reflog expire --expire=now --all`.

2. **`git gc` packing instead of deleting**: `git gc` may pack unreachable
   objects into a pack file rather than deleting them. Use `--prune=now` and
   verify with a brute-force scan.

3. **Stash index shifting**: When dropping multiple stash entries, drop from
   highest index first to avoid index shifting.

4. **History rewriting changes SHAs**: After `filter-branch` or `filter-repo`,
   all downstream commit SHAs change. Tags on rewritten commits must be
   re-created or will be lost.

5. **Submodule object databases**: If the repo has submodules, check their
   `.git` directories too.

6. **Writing secret.txt with trailing newline**: Use `echo -n` or `printf` to
   avoid an unwanted trailing newline unless the secret itself ends with one.

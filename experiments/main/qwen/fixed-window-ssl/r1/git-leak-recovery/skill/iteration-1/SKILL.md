---
name: git-leak-recovery
description: >
  Recover leaked secrets from Git repositories (including unreachable blobs,
  stashes, replace refs, tags, reachable history, and other object stores) and
  perform thorough cleanup so the secret cannot be recovered from any part of
  the repository. Preserves all legitimate branches, commits, tags, and files.
---

# Git Secret Recovery & Cleanup

A reusable procedure for finding secrets that were accidentally committed,
staged, stashed, tagged, or otherwise stored in a Git repository, extracting
them, and then purging every trace from the repository while preserving all
legitimate content.

## Key Principles

1. **Recover BEFORE cleanup** — cleanup is destructive; always extract the
   secret first.
2. **Reflog expire must precede gc** — `git gc --prune=now` will NOT prune
   objects still referenced by reflogs. Always expire reflogs first.
3. **Clean from outermost reference inward** — remove refs/stash/replace-refs
   first, then expire reflogs, then gc. If the secret is in reachable history,
   rewrite history first.
4. **Verify with multiple independent checks** — no single check is sufficient.

---

## Phase 1: Reconnaissance — Locate the Secret

Understand the repo topology and find every place the secret might reside.

```bash
# 1. Basic topology
git log --oneline --all --graph
git status
git branch -a
git tag -l

# 2. Unreachable objects (blobs, commits, trees not reachable from any ref)
git fsck --unreachable --no-reflogs 2>&1
# Also check with reflogs included to see what reflogs are keeping alive:
git fsck --unreachable 2>&1

# 3. Stashes
git stash list

# 4. Replace refs (can hide tainted objects behind clean-looking ones)
git replace --list

# 5. All refs — look for backup/original refs (refs/original/, refs/backup/, etc.)
git for-each-ref

# 6. Inspect each suspicious object
git cat-file -p <hash>
# For blobs: shows raw content
# For commits: shows tree, parent, author, message
# For trees: shows entries (filename + hash)
```

### Where secrets hide (by `secret_location` axis)

| Location | How to find | How to extract |
|---|---|---|
| Unreachable blob (staged then removed) | `git fsck --unreachable` | `git cat-file -p <blob-hash>` |
| Reachable commit in history | `git log -p --all -S 'secret'` or grep objects | Read from commit diff or blob |
| Stash entry | `git stash list` then `git stash show -p stash@{N}` | `git cat-file -p` on stash commit's tree |
| Replace ref | `git replace --list` | `git cat-file -p <original-or-replacement>` |
| Annotated tag | `git tag -l` then `git cat-file -p <tag-hash>` | Tag message or pointed-to object |
| Deleted branch | `git fsck --unreachable` (commits become unreachable) | `git cat-file -p <commit>` then walk its tree |
| Packed objects | `git verify-pack -v .git/objects/pack/*.idx` then `git cat-file -p` | Same as above |

### Searching for the secret pattern

```bash
# Search all reachable objects
git rev-list --all --objects | while read hash rest; do
  git cat-file -p "$hash" 2>/dev/null
done | grep -i 'secret\['

# Search unreachable objects specifically
git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $NF}' | while read hash; do
  git cat-file -p "$hash" 2>/dev/null
done | grep -i 'secret\['

# Raw filesystem search (catches anything in loose objects or packs)
grep -rl 'secret\[' .git/ 2>/dev/null
```

---

## Phase 2: Recovery

Once the secret is located, extract it and write it to the required output
(typically `/app/secret.txt` or as specified by the task).

```bash
echo '<the-secret-value>' > /app/secret.txt
```

**Critical: complete recovery before any cleanup.** Cleanup operations are
irreversible and may destroy the only copy of the secret.

---

## Phase 3: Cleanup

The cleanup strategy depends on where the secret was found. Apply the
appropriate combination:

### A. Secret only in unreachable objects (e.g., staged-then-removed)

```bash
# Step 1: Expire all reflogs (otherwise gc cannot prune reflog-referenced objects)
git reflog expire --expire=now --all

# Step 2: Aggressive garbage collection
git gc --prune=now --aggressive

# Step 3: Remove any stale pack files that might still contain the blob
# (gc usually handles this, but verify)
```

### B. Secret in reachable history (committed in a past commit)

```bash
# Step 1: Rewrite history to remove the secret
# Option A: git filter-repo (preferred, faster, safer)
git filter-repo --replace-text <(echo 'literal:SECRET_VALUE==>REMOVED') --force

# Option B: git filter-branch (older, more widely available)
git filter-branch --tree-filter 'find . -type f -exec sed -i "s/SECRET_VALUE//g" {} +' -- --all

# Step 2: Remove backup refs created by the rewrite
rm -rf .git/refs/original/

# Step 3: Expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### C. Secret in a stash

```bash
git stash drop stash@{N}   # drop specific stash
# or
git stash clear             # drop all stashes
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### D. Secret in replace refs

```bash
git replace -d <replace-ref>
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### E. Secret in annotated tags

```bash
git tag -d <tainted-tag>
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### F. Secret in deleted branches

After removing the branch ref, the commits become unreachable. Then:
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

---

## Phase 4: Verification

Run ALL of these checks. The cleanup is only complete when every check passes.

### Check 1: No tainted unreachable objects
```bash
git fsck --unreachable --no-reflogs 2>&1
# Should show no unreachable objects containing the secret
```

### Check 2: No secret in any reachable object
```bash
git rev-list --all --objects | while read hash rest; do
  git cat-file -p "$hash" 2>/dev/null
done | grep -i 'secret\[' || echo "CLEAN: no secrets in reachable objects"
```

### Check 3: Raw filesystem scan
```bash
grep -r 'secret\[' .git/ 2>/dev/null || echo "CLEAN: no secrets in .git directory"
```

### Check 4: No stashes, replace refs, or backup refs remain
```bash
git stash list          # should be empty (or not contain tainted entries)
git replace --list      # should be empty (or not reference tainted objects)
git for-each-ref        # no refs/original/ or other backup refs
```

### Check 5: Legitimate content preserved
```bash
git log --oneline --all   # all legitimate commits still present
git branch -a             # all legitimate branches intact
git tag -l                # legitimate tags preserved
# Verify key files still exist and have correct content
cat README.md             # or whatever files the task requires preserved
```

---

## Decision Flowchart

```
Is the secret in a reachable commit/tree?
  YES → Rewrite history (filter-repo/filter-branch), then remove backup refs,
        then expire reflogs, then gc.
  NO  → Is it in a stash?
          YES → Drop stash, then expire reflogs, then gc.
          NO  → Is it in a replace ref?
                  YES → Delete replace ref, then expire reflogs, then gc.
                  NO  → Is it in a tag?
                          YES → Delete tag, then expire reflogs, then gc.
                          NO  → It's an unreachable object.
                                 Expire reflogs, then gc.
```

In all cases, the terminal steps are: expire reflogs → gc --prune=now → verify.

---

## Common Pitfalls

- **Running `git gc --prune=now` without expiring reflogs first**: The blob
  survives because reflog entries still reference it.
- **Forgetting `refs/original/`**: `git filter-branch` creates backup refs
  there; if not removed, the tainted objects remain reachable.
- **Only checking `git fsck` without `--no-reflogs`**: Reflog entries can mask
  unreachable objects.
- **Not checking packed objects**: After gc, surviving objects may be in pack
  files. Use `git verify-pack -v` to enumerate and inspect.
- **Cleaning before recovering**: Destructive cleanup can destroy the only copy
  of the secret. Always recover first.

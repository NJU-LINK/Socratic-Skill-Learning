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

# 6. Special refs that can keep objects alive
ls -la .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD 2>&1

# 7. Lost+found directory (created by git fsck --lost-found)
ls -la .git/lost+found/ 2>&1

# 8. Submodules and nested repos (independent object stores!)
git submodule status 2>&1
ls -la .git/modules/ 2>&1
find . -name .git -not -path './.git' 2>/dev/null
# IMPORTANT: Each submodule/nested repo has its OWN object database.
# The parent repo's git fsck/git gc will NOT scan or clean them.
# You must check and clean each one independently.

# 9. Git notes (metadata attached to commits, stored in refs/notes/)
git notes list 2>&1
git for-each-ref refs/notes/ 2>&1
# Notes are stored as blobs in refs/notes/commits (by default)
# They have their own object database and must be checked separately

# 10. Git rerere cache (reuse recorded resolution)
ls -la .git/rr-cache/ 2>&1
# Stores conflict resolutions; can contain secrets if they were part of a merge

# 11. Inspect each suspicious object
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
| `.git/lost+found/` | `ls -la .git/lost+found/` | Files are copies of unreachable objects; inspect with `git cat-file -p` |
| Special refs (MERGE_HEAD, etc.) | `ls .git/MERGE_HEAD .git/FETCH_HEAD ...` | `git cat-file -p` on the commit hash stored in the file |
| Submodule object database | `git submodule status` + `ls .git/modules/` | `git --git-dir=.git/modules/<path> fsck --unreachable` then `git --git-dir=.git/modules/<path> cat-file -p <hash>` |
| Nested repo (independent `.git/`) | `find . -name .git -not -path './.git'` | `git -C <nested-repo> fsck --unreachable` then inspect objects |
| Git notes (`refs/notes/`) | `git notes list` + `git for-each-ref refs/notes/` | `git cat-file -p` on each note blob; notes are keyed by the commit they annotate |
| Git rerere cache (`.git/rr-cache/`) | `ls -la .git/rr-cache/` | Files contain pre/post conflict resolution content |

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
# Step 1: Remove special refs that might keep objects alive
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD

# Step 2: Remove lost+found directory if it exists (contains copies of unreachable objects)
rm -rf .git/lost+found/

# Step 3: Expire all reflogs (otherwise gc cannot prune reflog-referenced objects)
git reflog expire --expire=now --all

# Step 4: Aggressive garbage collection
git gc --prune=now --aggressive

# Step 5: Verify lost+found is gone and no tainted objects remain
ls -la .git/lost+found/ 2>&1  # should not exist
git fsck --unreachable --no-reflogs 2>&1  # should show no tainted objects
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

# Step 3: Remove special refs and lost+found
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
rm -rf .git/lost+found/

# Step 4: Expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### C. Secret in a stash

```bash
git stash drop stash@{N}   # drop specific stash
# or
git stash clear             # drop all stashes
# Remove special refs and lost+found
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
rm -rf .git/lost+found/
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### D. Secret in replace refs

```bash
git replace -d <replace-ref>
# Remove special refs and lost+found
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
rm -rf .git/lost+found/
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### E. Secret in annotated tags

```bash
git tag -d <tainted-tag>
# Remove special refs and lost+found
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
rm -rf .git/lost+found/
# Then reflog expire + gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### F. Secret in deleted branches

After removing the branch ref, the commits become unreachable. Then:
```bash
# Remove special refs and lost+found
rm -f .git/MERGE_HEAD .git/FETCH_HEAD .git/ORIG_HEAD .git/CHERRY_PICK_HEAD .git/REVERT_HEAD
rm -rf .git/lost+found/
# Expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### G. Secret in a submodule or nested repo object database

**Critical**: Each submodule and nested repo has its own independent object store.
The parent repo's `git gc` will NOT clean them. You must clean each one separately.

**For submodules** (object store at `.git/modules/<submodule-path>/`):
```bash
# Step 1: If secret is in reachable history within the submodule, rewrite it first
git -C <submodule-path> filter-repo --replace-text <(echo 'literal:SECRET_VALUE==>REMOVED') --force
# Or use filter-branch if filter-repo is not available

# Step 2: Remove backup refs in the submodule
rm -rf .git/modules/<submodule-path>/refs/original/

# Step 3: Remove special refs and lost+found in the submodule
rm -f .git/modules/<submodule-path>/MERGE_HEAD
rm -f .git/modules/<submodule-path>/FETCH_HEAD
rm -f .git/modules/<submodule-path>/ORIG_HEAD
rm -rf .git/modules/<submodule-path>/lost+found/

# Step 4: Expire reflogs and gc in the submodule
git --git-dir=.git/modules/<submodule-path> reflog expire --expire=now --all
git --git-dir=.git/modules/<submodule-path> gc --prune=now --aggressive
```

**For nested repos** (independent `.git/` directory at `<nested-repo-path>/.git/`):
```bash
# Step 1: If secret is in reachable history, rewrite it first
git -C <nested-repo-path> filter-repo --replace-text <(echo 'literal:SECRET_VALUE==>REMOVED') --force

# Step 2: Remove backup refs
rm -rf <nested-repo-path>/.git/refs/original/

# Step 3: Remove special refs and lost+found
rm -f <nested-repo-path>/.git/MERGE_HEAD
rm -f <nested-repo-path>/.git/FETCH_HEAD
rm -f <nested-repo-path>/.git/ORIG_HEAD
rm -rf <nested-repo-path>/.git/lost+found/

# Step 4: Expire reflogs and gc in the nested repo
git -C <nested-repo-path> reflog expire --expire=now --all
git -C <nested-repo-path> gc --prune=now --aggressive
```

### H. Secret in git notes

Git notes are metadata attached to commits, stored in `refs/notes/commits` (by default).
They have their own blob objects and must be cleaned separately.

```bash
# Step 1: List all notes and find tainted ones
git notes list  # shows <note-blob-hash> <annotated-commit-hash>
for note_ref in $(git for-each-ref --format='%(refname)' refs/notes/); do
  git notes --ref="$note_ref" list 2>/dev/null
done

# Step 2: Remove tainted notes
git notes remove <annotated-commit-hash>  # removes note from default refs/notes/commits
git notes --ref=<note-ref> remove <annotated-commit-hash>  # for custom note refs
# Or remove all notes in a namespace:
git update-ref -d refs/notes/commits  # removes entire notes ref

# Step 3: Expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### I. Secret in git rerere cache

Git rerere (reuse recorded resolution) stores conflict resolutions in `.git/rr-cache/`.
If a secret was part of a merge conflict, the resolution might be cached here.

```bash
# Step 1: Remove the rerere cache
rm -rf .git/rr-cache/

# Step 2: Expire reflogs and gc
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

### Check 3: Raw filesystem scan (loose objects and text files only)
```bash
grep -r 'secret\[' .git/ 2>/dev/null || echo "CLEAN: no secrets in .git directory"
```

**Important limitation**: Raw `grep` on `.git/` will NOT find secrets inside binary
pack files. The authoritative check is Check 2 (enumerating all objects with
`git cat-file`). Raw grep is useful for finding secrets in loose objects, reflogs,
config files, and `.git/lost+found/`, but pack files require object enumeration.

### Check 3b: Lost+found directory
```bash
ls -la .git/lost+found/ 2>&1  # should not exist, or should be empty
# If it exists, remove it:
rm -rf .git/lost+found/
```

### Check 4: No stashes, replace refs, backup refs, or special refs remain
```bash
git stash list          # should be empty (or not contain tainted entries)
git replace --list      # should be empty (or not reference tainted objects)
git for-each-ref        # no refs/original/ or other backup refs
# Check special refs
for f in MERGE_HEAD FETCH_HEAD ORIG_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [ -f .git/$f ] && echo "WARNING: .git/$f exists" || true
done
```

### Check 5: Legitimate content preserved
```bash
git log --oneline --all   # all legitimate commits still present
git branch -a             # all legitimate branches intact
git tag -l                # legitimate tags preserved
# Verify key files still exist and have correct content
cat README.md             # or whatever files the task requires preserved
```

### Check 6: Submodule and nested repo object stores are clean
```bash
# For each submodule
for mod_dir in .git/modules/*/; do
  if [ -d "$mod_dir" ]; then
    echo "Checking submodule: $mod_dir"
    # Check unreachable objects
    git --git-dir="$mod_dir" fsck --unreachable --no-reflogs 2>&1 | grep -i 'secret\[' && echo "WARNING: secret found in $mod_dir"
    # Check all reachable objects
    git --git-dir="$mod_dir" rev-list --all --objects 2>/dev/null | while read h r; do
      git --git-dir="$mod_dir" cat-file -p "$h" 2>/dev/null
    done | grep -i 'secret\[' && echo "WARNING: secret found in reachable objects of $mod_dir"
  fi
done

# For each nested repo
find . -name .git -type d -not -path './.git' -not -path './.git/modules/*' 2>/dev/null | while read nested_git; do
  nested_repo=$(dirname "$nested_git")
  echo "Checking nested repo: $nested_repo"
  # Check unreachable objects
  git -C "$nested_repo" fsck --unreachable --no-reflogs 2>&1 | grep -i 'secret\[' && echo "WARNING: secret found in $nested_repo"
  # Check all reachable objects
  git -C "$nested_repo" rev-list --all --objects 2>/dev/null | while read h r; do
    git -C "$nested_repo" cat-file -p "$h" 2>/dev/null
  done | grep -i 'secret\[' && echo "WARNING: secret found in reachable objects of $nested_repo"
done
```

### Check 7: Git notes and rerere cache are clean
```bash
# Check git notes
for note_ref in $(git for-each-ref --format='%(refname)' refs/notes/ 2>/dev/null); do
  git notes --ref="$note_ref" list 2>/dev/null | while read note_hash commit_hash; do
    git cat-file -p "$note_hash" 2>/dev/null
  done | grep -i 'secret\[' && echo "WARNING: secret found in notes ref $note_ref"
done

# Check rerere cache
if [ -d .git/rr-cache/ ]; then
  find .git/rr-cache/ -type f -exec grep -l 'secret\[' {} \; 2>/dev/null && echo "WARNING: secret found in rerere cache"
fi
```

---

## Decision Flowchart

```
Is the secret in a reachable commit/tree (parent or submodule/nested)?
  YES → Rewrite history (filter-repo/filter-branch) in that repo, then remove
        backup refs, then remove special refs and lost+found, then expire
        reflogs, then gc.
  NO  → Is it in a stash?
          YES → Drop stash, then remove special refs and lost+found,
                then expire reflogs, then gc.
          NO  → Is it in a replace ref?
                  YES → Delete replace ref, then remove special refs and lost+found,
                        then expire reflogs, then gc.
                  NO  → Is it in a tag?
                          YES → Delete tag, then remove special refs and lost+found,
                                then expire reflogs, then gc.
                          NO  → Is it in git notes (refs/notes/)?
                                  YES → Remove tainted notes or delete notes ref,
                                        then remove special refs and lost+found,
                                        then expire reflogs, then gc.
                                  NO  → Is it in .git/rr-cache/ (rerere)?
                                          YES → Remove .git/rr-cache/,
                                                then expire reflogs, then gc.
                                          NO  → Is it in a submodule or nested repo object store?
                                                  YES → Clean that repo's object store independently
                                                        (its own reflog expire + gc).
                                                  NO  → It's an unreachable object in the parent.
                                                         Remove special refs and lost+found,
                                                         then expire reflogs, then gc.
```

In all cases, the terminal steps are:
1. Remove special refs (MERGE_HEAD, FETCH_HEAD, ORIG_HEAD, etc.)
2. Remove `.git/lost+found/` if it exists
3. Expire reflogs (`git reflog expire --expire=now --all`)
4. Garbage collect (`git gc --prune=now --aggressive`)
5. Verify (all checks in Phase 4)

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
- **Forgetting `.git/lost+found/`**: If `git fsck --lost-found` was run, it
  creates `.git/lost+found/` with copies of unreachable objects. Must be
  removed during cleanup.
- **Ignoring special refs**: `MERGE_HEAD`, `FETCH_HEAD`, `ORIG_HEAD`,
  `CHERRY_PICK_HEAD`, `REVERT_HEAD` can keep objects alive. Remove them
  before gc.
- **Relying only on raw `grep -r .git/`**: This won't find secrets in binary
  pack files. Always use object enumeration (`git rev-list --all --objects`
  + `git cat-file`) as the authoritative check.
- **Assuming parent `git gc` cleans submodule objects**: It doesn't. Each
  `.git/modules/<path>/` is an independent object store requiring its own
  cleanup. Similarly, nested repos with their own `.git/` directories are
  completely separate and must be cleaned independently.
- **Forgetting git notes**: Notes are stored in `refs/notes/` and have their
  own blob objects. `git fsck` and `git gc` on the parent repo will not clean
  note objects unless the notes ref is deleted. Check `git notes list` and
  `git for-each-ref refs/notes/`.
- **Ignoring `.git/rr-cache/`**: Git rerere stores conflict resolutions here.
  If a secret was part of a merge conflict, the resolution might be cached.
  Remove `.git/rr-cache/` during cleanup.

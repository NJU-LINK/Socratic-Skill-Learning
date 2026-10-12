---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's object storage, metadata, or
  references, write it to a designated output file, then fully purge every
  recoverable trace of the secret while preserving all legitimate repository
  content (branches, tags, files, commit messages).
---

# Git Leak Recovery

## Task Summary

A secret matching the pattern `secret[...]` was accidentally introduced into a
Git repository (staged, committed, stashed, tagged, etc.) and may have been
partially removed. You must:

1. **Recover** the secret and write it to `/app/secret.txt`.
2. **Clean** every trace of the secret from the repository.
3. **Preserve** all legitimate files, branches, tags, and commit messages.

The repository lives at `/app/repo`.

---

## Phase 1 — Enumerate Every Place a Secret Can Hide

Git stores data in multiple layers. A leaked value may persist in any of them.
Probe **all** of the following before concluding the search is complete.

| Layer | Command / Method |
|---|---|
| **Dangling / unreachable objects** | `git fsck --unreachable --no-reflogs 2>&1` |
| **All reachable blobs** | `git rev-list --all --objects \| while read sha _; do git cat-file -t "$sha" 2>/dev/null \| grep -q blob && git cat-file -p "$sha"; done` |
| **Index (staged files)** | `git ls-files --stage` and inspect each blob sha |
| **Stash** | `git stash list`; for each `stash@{N}` inspect with `git stash show -p stash@{N}` |
| **Reflogs** | `git reflog --all` — note every referenced commit sha |
| **All refs (branches, tags, remotes)** | `git for-each-ref --format='%(refname) %(objectname)'` |
| **Replace refs** | `git replace --list 2>/dev/null` |
| **Backup refs** | `find .git/refs/original -type f 2>/dev/null` |
| **Annotated tags** | `git tag -l`; for each: `git cat-file -t <tag>` — if `tag`, inspect the tag object and its target |
| **Pack files** | `git verify-pack -v .git/objects/pack/*.idx 2>/dev/null` to list packed objects |
| **Loose objects** | `find .git/objects -type f` (skip `pack/` and `info/` dirs) |
| **Submodule object DBs** | `find . -name ".git" -not -path "./.git"` — check each nested `.git` |
| **FETCH_HEAD / ORIG_HEAD / MERGE_HEAD** | `cat .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null` |
| **Reachable history diffs** | `git log --all -p` to scan every patch |

### Search Strategy

```bash
cd /app/repo

# 1. Collect ALL object SHAs (loose + packed + reachable + unreachable)
all_objects() {
  # Loose objects
  find .git/objects -type f \
    | grep -v '/pack/' | grep -v '/info/' \
    | sed 's|.git/objects/||;s|/||'
  # Packed objects
  for idx in .git/objects/pack/*.idx; do
    [ -f "$idx" ] && git verify-pack -v "$idx" 2>/dev/null | awk '/^[0-9a-f]/ {print $1}'
  done
  # Unreachable (fsck)
  git fsck --unreachable --no-reflogs 2>&1 \
    | awk '/unreachable|dangling/ {print $NF}'
  # Reachable
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  # Stash
  git stash list --format='%H' 2>/dev/null
  # Reflog
  git reflog --all --format='%H' 2>/dev/null
}

# 2. Deduplicate and inspect every blob
all_objects | sort -u | while read sha; do
  type=$(git cat-file -t "$sha" 2>/dev/null) || continue
  if [ "$type" = "blob" ]; then
    content=$(git cat-file -p "$sha" 2>/dev/null)
    if echo "$content" | grep -qE 'secret\['; then
      echo "FOUND in blob $sha"
      echo "$content"
    fi
  fi
done
```

Also grep through commit messages and tag annotations:

```bash
git log --all --format='%H %s %b' | grep -E 'secret\['
git for-each-ref --format='%(refname)' | while read ref; do
  git cat-file -p "$ref" 2>/dev/null | grep -E 'secret\['
done
```

### Extract the Secret

Once found, write **exactly** the matching string (e.g., `secret[...]`) to
`/app/secret.txt`:

```bash
echo -n 'secret[whatever_was_found]' > /app/secret.txt
```

---

## Phase 2 — Clean Every Trace of the Secret

The cleanup must be **thorough**: after completion, no Git command or raw
object inspection should reveal the secret. Work in this order to avoid
re-introducing references.

### 2a. Remove or Rewrite Tainted Commits

If the secret appears in **reachable history** (committed to a branch):

```bash
# Use git filter-branch or git filter-repo to rewrite history
# Prefer filter-repo if available; fall back to filter-branch
git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch <leaked_filename>' \
  --prune-empty -- --all
```

If the secret is in commit messages or tag annotations, use `--msg-filter` or
`--tag-name-filter` accordingly.

For **amended / reset-away commits** that are now unreachable, they will be
handled by the prune step below — but first remove any reflogs that reference
them.

### 2b. Drop Tainted Stash Entries

```bash
# Drop specific stash entry (index may shift, so drop from highest first)
git stash drop stash@{N}
# Or clear all stashes if they all contain the secret
git stash clear
```

### 2c. Delete Tainted Tags

```bash
git tag -d <tagname>
```

### 2d. Remove Replace Refs and Backup Refs

```bash
git replace --delete <ref> 2>/dev/null
rm -rf .git/refs/original 2>/dev/null
```

### 2e. Expire All Reflogs

Reflogs keep references to old commits alive even after rewriting.

```bash
git reflog expire --expire=now --all
```

### 2f. Prune Unreachable Objects

```bash
# Remove loose unreachable objects
git gc --prune=now --aggressive

# Also run prune directly for thoroughness
git prune --expire=now
```

### 2g. Handle Pack Files

If `gc` repacked objects, tainted blobs may still be in a pack. Force a
repack that excludes unreachable objects:

```bash
git repack -a -d -l --no-reuse-object 2>/dev/null
# Then prune again
git prune --expire=now
git gc --prune=now --aggressive
```

### 2h. Check Submodule Object Databases

If the repo contains submodules, repeat the cleanup inside each one:

```bash
git submodule foreach 'git reflog expire --expire=now --all && git gc --prune=now --aggressive'
```

---

## Phase 3 — Verify Cleanup

Run **every** check below. If any reveals the secret, go back to Phase 2.

```bash
cd /app/repo

# 1. fsck — no dangling objects containing the secret
git fsck --unreachable --no-reflogs 2>&1

# 2. Search ALL remaining objects
find .git/objects -type f | grep -v '/pack/' | grep -v '/info/' \
  | sed 's|.git/objects/||;s|/||' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -cF 'secret[' && echo "LEAK in $sha"
done

# For packed objects
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] && git verify-pack -v "$idx" 2>/dev/null \
    | awk '/^[0-9a-f]/ {print $1}' | while read sha; do
    git cat-file -p "$sha" 2>/dev/null | grep -cF 'secret[' && echo "LEAK in packed $sha"
  done
done

# 3. Search all reachable content
git log --all -p 2>/dev/null | grep -cF 'secret['
git rev-list --all --objects | while read sha _; do
  git cat-file -p "$sha" 2>/dev/null | grep -cF 'secret[' && echo "LEAK reachable $sha"
done

# 4. Check stash, reflogs, special refs
git stash list 2>/dev/null | grep -cF 'secret['
git reflog --all 2>/dev/null
cat .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null | grep -cF 'secret['

# 5. Check index
git ls-files --stage | while read mode sha stage path; do
  git cat-file -p "$sha" 2>/dev/null | grep -cF 'secret[' && echo "LEAK in index $path"
done
```

If every check returns zero matches, the cleanup is complete.

---

## Phase 4 — Verify Legitimate Content Preserved

Confirm the repository still has its expected state:

```bash
# Branches still exist
git branch -a

# Tags still exist (only legitimate ones)
git tag -l

# Files are intact
git ls-files
cat <expected_files>

# Commit messages preserved
git log --all --oneline

# Working tree is clean
git status
```

---

## Decision Rules

| Situation | Action |
|---|---|
| Secret only in dangling blob | Skip rewrite; just expire reflogs + prune |
| Secret in reachable commit | Rewrite history with filter-branch/filter-repo |
| Secret in stash | `git stash drop` or `git stash clear` |
| Secret in annotated tag | `git tag -d` then prune |
| Secret in replace ref | `git replace --delete` then prune |
| Secret in reflog only | `git reflog expire --expire=now --all` then prune |
| Secret in multiple places | Handle each, then single final prune pass |
| Multiple secrets / same value in several blobs | Remove all instances |
| Legitimate blobs have similar content | Only remove objects whose content matches `secret[...]` pattern |

## Common Pitfalls

- **Reflogs re-introduce pruned objects.** Always expire reflogs *before* gc.
- **`git gc` alone doesn't remove reachable tainted commits.** You must rewrite
  or delete the referencing refs first.
- **Filter-branch creates backup refs in `refs/original/`.** Delete them before
  pruning.
- **Pack files can retain objects** even after loose copies are removed. Use
  `--aggressive` gc or explicit repack.
- **Submodules have independent object databases.** Check them separately.
- **`git prune` only removes loose objects.** Packed objects need repacking.

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

## Command Recipes

Concrete commands for each secret_location variant. Use these directly.

### Search Commands (execute in order, stop when secret found)

**1. Reachable history:**
```bash
git log --all -p | grep -oP 'secret\[[^\]]*\]' | head -1
```

**2. Stashes:**
```bash
git stash list  # enumerate
for i in $(seq 0 $(git stash list | wc -l)); do
  git stash show -p "stash@{$i}" | grep -oP 'secret\[[^\]]*\]'
done
```

**3. Reflogs:**
```bash
for sha in $(git reflog --all --format='%H'); do
  git rev-list --objects "$sha" | while read obj rest; do
    [ "$(git cat-file -t "$obj")" = "blob" ] && git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
  done
done | head -1
```

**4. Unreachable objects (git fsck):**
```bash
git fsck --unreachable --no-reflogs --dangling 2>&1 | grep -E '^(unreachable|dangling) (blob|commit|tree)' | awk '{print $3}' | while read sha; do
  type=$(git cat-file -t "$sha")
  if [ "$type" = "blob" ]; then
    git cat-file -p "$sha" | grep -oP 'secret\[[^\]]*\]'
  elif [ "$type" = "commit" ] || [ "$type" = "tree" ]; then
    git rev-list --objects "$sha" | while read obj rest; do
      [ "$(git cat-file -t "$obj")" = "blob" ] && git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
    done
  fi
done | head -1
```

**5. Replace refs:**
```bash
git replace -l | while read orig repl; do
  git cat-file -p "$orig" | grep -oP 'secret\[[^\]]*\]'
done
```

**6. All refs (backup refs, notes):**
```bash
git for-each-ref --format='%(refname) %(objectname)' | while read refname refsha; do
  type=$(git cat-file -t "$refsha")
  if [ "$type" = "commit" ]; then
    git rev-list --objects "$refsha" | while read obj rest; do
      [ "$(git cat-file -t "$obj")" = "blob" ] && git cat-file -p "$obj" | grep -oP 'secret\[[^\]]*\]'
    done
  elif [ "$type" = "blob" ]; then
    git cat-file -p "$refsha" | grep -oP 'secret\[[^\]]*\]'
  fi
done | head -1
```

**7. Annotated tags:**
```bash
for tag in $(git tag -l); do
  tag_sha=$(git rev-parse "refs/tags/$tag")
  [ "$(git cat-file -t "$tag_sha")" = "tag" ] && git cat-file -p "$tag_sha" | grep -oP 'secret\[[^\]]*\]'
done
```

**8. Submodule ODBs:**
```bash
if [ -f .gitmodules ]; then
  git submodule--helper list | while read mode sha path; do
    for candidate in "$path/.git" ".git/modules/$path"; do
      [ -d "$candidate/objects" ] && GIT_DIR="$candidate" git fsck --unreachable --no-reflogs 2>&1 | grep 'unreachable blob' | awk '{print $3}' | while read bsha; do
        GIT_DIR="$candidate" git cat-file -p "$bsha" | grep -oP 'secret\[[^\]]*\]'
      done
    done
  done
fi
```

### Cleanup Commands (after recovery, execute based on where secret was found)

**If in reachable history (requires history rewrite):**
```bash
# Find tainted files
git log --all -p | grep -B5 'secret\[' | grep '^diff --git' | awk '{print $3}' | sed 's|^a/||' | sort -u > /tmp/tainted_files.txt

# Rewrite history to remove tainted files
FILTER_CMD=$(cat /tmp/tainted_files.txt | while read f; do echo "rm -f '$f';"; done | tr '\n' ' ')
git filter-branch --force --tree-filter "$FILTER_CMD" --prune-empty -- --all

# Remove backup refs created by filter-branch
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do git update-ref -d "$ref"; done
```

**If in stash:**
```bash
git stash drop "stash@{N}"  # replace N with stash index
```

**If in replace ref:**
```bash
git replace -d <original-sha>
```

**If in annotated tag:**
```bash
git tag -d <tagname>
```

**If in backup ref or notes:**
```bash
git update-ref -d <refname>
```

**Universal cleanup (always execute after location-specific cleanup):**
```bash
# Expire all reflogs
git reflog expire --expire=now --all

# Prune unreachable objects
git gc --prune=now --aggressive

# Repack
git repack -a -d
```

### Verification Commands (after cleanup)

```bash
# Check all objects in ODB
find .git/objects -type f ! -path '*/pack/*' ! -path '*/info/*' | sed 's|.git/objects/||;s|/||' | while read sha; do
  [ "$(git cat-file -t "$sha")" = "blob" ] && git cat-file -p "$sha" | grep -oP 'secret\[[^\]]*\]'
done

# Check packed objects
for pack in .git/objects/pack/*.idx; do
  [ -f "$pack" ] && git verify-pack -v "$pack" | grep '^[a-f0-9]\{40\} blob' | awk '{print $1}' | while read sha; do
    git cat-file -p "$sha" | grep -oP 'secret\[[^\]]*\]'
  done
done

# Check unreachable
git fsck --unreachable --no-reflogs --dangling 2>&1 | grep 'unreachable blob' | awk '{print $3}' | while read sha; do
  git cat-file -p "$sha" | grep -oP 'secret\[[^\]]*\]'
done

# Check stashes, replace refs, tags (repeat search commands above)
```

No output from verification commands = cleanup successful.

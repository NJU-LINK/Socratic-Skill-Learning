---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's object store (dangling blobs,
  stashes, reflogs, reachable history, deleted branches, replace refs, tags,
  commit messages, submodule object databases, etc.), write it to /app/secret.txt,
  then purge it from every location in the repo while preserving all legitimate
  content (branches, files, tags, commit messages).
---

# Git Leak Recovery

## Overview

A secret (matching pattern `secret[...]`) was accidentally introduced into a Git
repository. It may reside anywhere Git stores data: unreachable blobs, stashes,
reflogs, reachable commits, deleted branches, replace refs, annotated tags, commit
messages, author/committer metadata, submodule object databases, lost-found
directories, or metadata files (COMMIT_EDITMSG, MERGE_MSG, etc.). The task is to:

1. **Recover** the secret and write it to `/app/secret.txt`
2. **Purge** it from every location in the repo
3. **Preserve** all legitimate content (branches, files, tags, commit messages)

## Quick-Reference Procedure

```
1. DISCOVER  → Run tiered search (Section A) to find the secret and ALL its locations
2. EXTRACT   → Save to /app/secret.txt BEFORE any cleanup
3. PLAN      → Map found locations to cleanup steps (Section B.1 decision table)
4. PURGE     → Execute cleanup in dependency order (Section B.2)
5. VERIFY    → Re-run discovery to confirm purge (Section C)
```

---

## Section A: Tiered Secret Discovery

### A.1 — Phase 1: Find the secret (fast path)

Start with the most common locations. If found, proceed to Phase 2 to find ALL locations.

```bash
cd /app/repo

echo "=== Phase 1: Searching for secret[...] ==="

# Search ALL objects in the object store (reachable + unreachable, loose + packed)
ALL_HASHES=$(
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
    | grep -E '^(unreachable|dangling)' | awk '{print $3}'
)

for hash in $(echo "$ALL_HASHES" | sort -u); do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    type=$(git cat-file -t "$hash" 2>/dev/null)
    echo "FOUND in $type $hash:"
    echo "$content" | grep 'secret\['
  fi
done

echo "=== Phase 1 complete ==="
```

**If found**: Extract the secret and save to `/app/secret.txt` immediately.

```bash
# Extract from the blob where it was found:
git cat-file -p BLOB_HASH | grep -oP 'secret\[[^\]]*\]' > /app/secret.txt
cat /app/secret.txt
```

**Critical: Save BEFORE any cleanup.** Then proceed to Phase 2 to find ALL locations.

### A.2 — Phase 2: Find ALL locations (comprehensive)

After extracting the secret, search ALL possible locations to determine the full cleanup scope.

```bash
cd /app/repo

echo "=== Phase 2: Finding ALL locations of secret ==="

# Track which locations contain the secret
LOCATIONS=""

# 1. Check reachable objects (commits, blobs, trees)
for hash in $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    type=$(git cat-file -t "$hash" 2>/dev/null)
    echo "FOUND in reachable $type $hash"
    LOCATIONS="$LOCATIONS reachable"
  fi
done

# 2. Check unreachable/dangling objects
for hash in $(git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
              | grep -E '^(unreachable|dangling)' | awk '{print $3}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in unreachable object $hash"
    LOCATIONS="$LOCATIONS unreachable"
  fi
done

# 3. Check commit messages
if git log --all --format="%B" 2>/dev/null | grep -q 'secret\['; then
  echo "FOUND in commit messages"
  LOCATIONS="$LOCATIONS commit_msg"
fi

# 4. Check author/committer metadata
if git log --all --format="%an%n%ae%n%cn%n%ce" 2>/dev/null | grep -q 'secret\['; then
  echo "FOUND in author/committer metadata"
  LOCATIONS="$LOCATIONS metadata"
fi

# 5. Check stashes
git stash list --format="%gd" 2>/dev/null | while read stash_ref; do
  if git ls-tree -r "$stash_ref" 2>/dev/null | awk '{print $3}' | while read hash; do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && echo "found"
  done | grep -q "found"; then
    echo "FOUND in stash $stash_ref"
    echo "stash" >> /tmp/locations
  fi
done
[ -f /tmp/locations ] && LOCATIONS="$LOCATIONS stash" && rm /tmp/locations

# 6. Check special git metadata files
for f in .git/COMMIT_EDITMSG .git/MERGE_MSG .git/SQUASH_MSG \
         .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD; do
  if [ -f "$f" ] && grep -q 'secret\[' "$f" 2>/dev/null; then
    echo "FOUND in $f"
    LOCATIONS="$LOCATIONS special_files"
  fi
done

# 7. Check lost-found directory
if [ -d .git/lost-found ]; then
  if find .git/lost-found -type f -exec grep -l 'secret\[' {} \; 2>/dev/null | grep -q .; then
    echo "FOUND in .git/lost-found/"
    LOCATIONS="$LOCATIONS lost_found"
  fi
fi

# 8. Check replace refs, notes, backup refs
for ref in $(git for-each-ref --format='%(refname)' refs/replace/ refs/notes/ refs/original/ 2>/dev/null); do
  hash=$(git rev-parse "$ref" 2>/dev/null)
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in ref $ref"
    LOCATIONS="$LOCATIONS special_refs"
  fi
done

# 9. Check submodule, nested-repo, and worktree object databases
GIT_DIRS=$(
  # Nested repos (directories)
  find . -name '.git' -type d 2>/dev/null
  # Worktrees (files containing "gitdir: ...")
  find . -name '.git' -type f 2>/dev/null | while read gitfile; do
    if grep -q '^gitdir:' "$gitfile" 2>/dev/null; then
      gitdir=$(sed 's/^gitdir: //' "$gitfile")
      if [[ "$gitdir" != /* ]]; then
        gitdir="$(dirname "$gitfile")/$gitdir"
      fi
      echo "$gitdir"
    fi
  done
  # Also check .git/worktrees/* directly
  find .git/worktrees -maxdepth 1 -mindepth 1 -type d 2>/dev/null
  # Submodule object databases
  find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||'
)
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')

for gitdir in $GIT_DIRS; do
  SUB_HASHES=$(
    GIT_DIR="$gitdir" git rev-list --all --objects 2>/dev/null | awk '{print $1}'
    GIT_DIR="$gitdir" git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
      | grep -E '^(unreachable|dangling)' | awk '{print $3}'
  )
  for hash in $(echo "$SUB_HASHES" | sort -u); do
    if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND in worktree/nested repo $gitdir object $hash"
      LOCATIONS="$LOCATIONS worktree"
    fi
  done
  # Check worktree index for staged secrets
  if [ -f "$gitdir/index" ]; then
    GIT_DIR="$gitdir" git ls-files --stage 2>/dev/null | while read mode hash stage name; do
      if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in worktree $gitdir index: $name ($hash)"
        echo "worktree_index" >> /tmp/locations
      fi
    done
    [ -f /tmp/locations ] && LOCATIONS="$LOCATIONS worktree_index" && rm /tmp/locations
  fi
done

# 10. Check git alternates (external object databases)
if [ -f .git/objects/info/alternates ]; then
  echo "WARNING: alternates file exists"
  while read altdir; do
    [ -z "$altdir" ] && continue
    echo "--- Searching alternate object database: $altdir ---"
    find "$altdir" -type f | while read f; do
      hash=$(echo "$f" | sed "s|$altdir/||;s|/||")
      if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in alternate $altdir object $hash"
        echo "alternate" >> /tmp/locations
      fi
    done
  done < .git/objects/info/alternates
  [ -f /tmp/locations ] && LOCATIONS="$LOCATIONS alternate" && rm /tmp/locations
fi

echo "=== Locations found: $LOCATIONS ==="
```

**Record the LOCATIONS variable** — you'll use it to choose the cleanup strategy.

---

## Section B: Ordered Cleanup

### B.1 — Cleanup Decision Table

Based on the LOCATIONS found in Phase 2, determine which cleanup steps to execute.

| Location | Cleanup Step | Notes |
|----------|--------------|-------|
| `unreachable` | Step 4 (reflog expire) + Step 6 (gc) | Simplest case |
| `reachable` | Step 2 (filter-branch) + Step 3 (delete backups) | Rewrites history |
| `commit_msg` | Step 2 (filter-branch --msg-filter) | Changes commit hashes |
| `metadata` | Step 2 (filter-branch --env-filter) | Changes commit hashes |
| `stash` | Step 1 (git stash drop) | |
| `special_refs` | Step 1 (git update-ref -d) | replace/notes/original refs |
| `special_files` | Step 5 (rm/truncate files) | COMMIT_EDITMSG, etc. |
| `lost_found` | Step 5 (rm -rf .git/lost-found/) | |
| `submodule` | Apply full procedure inside submodule | Use GIT_DIR= |
| `worktree` | Step 2 (filter-branch with GIT_DIR=) + Step 4 (reflog expire) | Worktrees share object DB |
| `worktree_index` | Step 1 (GIT_DIR= git rm --cached) + Step 4 (reflog expire) | Staged secrets in worktree |
| `alternate` | Step 6 (gc in main repo) + clean alternate dir | Objects in external DB |

### B.2 — Cleanup Dependency Chain (MANDATORY ORDER)

Execute these steps in order. **Skip steps that don't apply** based on your LOCATIONS, but **never reorder**.

```
Step 1: Drop explicit references
  → git stash drop stash@{N}    (if LOCATIONS contains "stash")
  → git tag -d TAG_NAME         (if tainted tags exist)
  → git update-ref -d refs/replace/...  (if LOCATIONS contains "special_refs")
  → git update-ref -d refs/notes/...

Step 2: Rewrite reachable history (if LOCATIONS contains "reachable", "commit_msg", or "metadata")
  → git filter-branch ... (see techniques below)
  Creates backup refs in refs/original/

Step 3: Delete backup refs (if Step 2 was executed)
  → rm -rf .git/refs/original/
  → git for-each-ref --format='delete %(refname)' refs/original/ | git update-ref --stdin

Step 4: Expire ALL reflogs
  → git reflog expire --expire=now --all

Step 5: Clean auxiliary files/directories (if LOCATIONS contains "special_files" or "lost_found")
  → rm -rf .git/lost-found/
  → Truncate/clean .git/COMMIT_EDITMSG, .git/MERGE_MSG, etc. if tainted

Step 6: Prune unreachable objects
  → git gc --prune=now --aggressive
  This is ALWAYS the last step.
```

**Why order matters:**
- If you run `git gc` before deleting `refs/original/`, gc sees old commits as
  reachable through backup refs and **keeps them**.
- If you expire reflogs before rewriting history, you lose the reflog entries
  that identify which commits contained the secret.
- If you run filter-branch before dropping stashes, the stash objects remain
  and can resurrect the secret.

### B.3 — Filter-branch Techniques

#### File removal (secret in standalone file)

```bash
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch PATH_TO_SECRET_FILE' \
  --prune-empty -- --all
```

#### Content replacement (text file)

```bash
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all
```

#### Content replacement (binary file)

```bash
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     perl -0777 -pi -e "s/secret\[.*?\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all
```

#### Commit messages

```bash
git filter-branch --force --msg-filter '
  sed "s/secret\[[^]]*\]/REDACTED/g"
' -- --all
```

#### Author/committer metadata

```bash
git filter-branch --force --env-filter '
  export GIT_AUTHOR_NAME=$(echo "$GIT_AUTHOR_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_AUTHOR_EMAIL=$(echo "$GIT_AUTHOR_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_NAME=$(echo "$GIT_COMMITTER_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_EMAIL=$(echo "$GIT_COMMITTER_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
' -- --all
```

#### Combining multiple filters

```bash
git filter-branch --force \
  --tree-filter 'if [ -f PATH ]; then sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH; fi' \
  --msg-filter 'sed "s/secret\[[^]]*\]/REDACTED/g"' \
  --prune-empty -- --all
```

**Critical flags:**
- `-- --all` is **mandatory** — without it, only the current branch is rewritten
- `--prune-empty` removes commits that become empty after file removal

**Note:** Rewriting changes ALL commit hashes downstream. Messages are preserved but hashes change.

### B.4 — Submodule, Worktree, and Alternates Cleanup

#### Submodule and nested-repo cleanup

If the secret is in a submodule, apply the full cleanup procedure inside the submodule:

```bash
# Find all submodule/nested-repo .git directories
GIT_DIRS=$(find . -name '.git' -type d 2>/dev/null; find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||')
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')

for gitdir in $GIT_DIRS; do
  echo "=== Cleaning submodule: $gitdir ==="
  # Apply the same cleanup steps (B.2) using GIT_DIR="$gitdir"
  # Example for unreachable objects:
  GIT_DIR="$gitdir" git reflog expire --expire=now --all
  rm -rf "$gitdir/lost-found/"
  GIT_DIR="$gitdir" git gc --prune=now --aggressive
done
```

#### Worktree cleanup

Worktrees share the main repo's object database but have separate HEAD, index, and reflogs:

```bash
# Find all worktree gitdirs
GIT_DIRS=$(
  find . -name '.git' -type f 2>/dev/null | while read gitfile; do
    if grep -q '^gitdir:' "$gitfile" 2>/dev/null; then
      gitdir=$(sed 's/^gitdir: //' "$gitfile")
      if [[ "$gitdir" != /* ]]; then
        gitdir="$(dirname "$gitfile")/$gitdir"
      fi
      echo "$gitdir"
    fi
  done
  find .git/worktrees -maxdepth 1 -mindepth 1 -type d 2>/dev/null
)

for gitdir in $GIT_DIRS; do
  echo "=== Cleaning worktree: $gitdir ==="
  # If secret is in worktree's reachable history, rewrite it
  # GIT_DIR="$gitdir" git filter-branch ... (use same techniques as B.3)
  
  # If secret is in worktree's index (staged file)
  if [ -f "$gitdir/index" ]; then
    GIT_DIR="$gitdir" git ls-files --stage 2>/dev/null | while read mode hash stage name; do
      if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        GIT_DIR="$gitdir" git rm --cached "$name"
      fi
    done
  fi
  
  # Clean worktree reflogs
  GIT_DIR="$gitdir" git reflog expire --expire=now --all
done

# Then run gc in main repo (worktrees share object database)
git reflog expire --expire=now --all
rm -rf .git/lost-found/
git gc --prune=now --aggressive
```

#### Alternates cleanup

If the secret is in an alternate object database:

```bash
if [ -f .git/objects/info/alternates ]; then
  echo "Cleaning alternate object databases"
  while read altdir; do
    [ -z "$altdir" ] && continue
    # Remove tainted objects from alternate directory
    find "$altdir" -type f | while read f; do
      hash=$(echo "$f" | sed "s|$altdir/||;s|/||")
      if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        rm -f "$f"
      fi
    done
  done < .git/objects/info/alternates
  
  # Then run gc in main repo to repack without alternates if needed
  git reflog expire --expire=now --all
  git gc --prune=now --aggressive
fi
```

Then clean the main repo:

```bash
git reflog expire --expire=now --all
rm -rf .git/lost-found/
git gc --prune=now --aggressive
```

---

## Section C: Verification

After cleanup, **re-run Phase 2 discovery** to confirm the secret is gone from ALL locations.

```bash
cd /app/repo

echo "=== Verification: Re-running Phase 2 discovery ==="

# Re-run the comprehensive search from A.2
# It should find NOTHING

found=0

# Check all objects (reachable + unreachable)
for hash in $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'; \
              git fsck --full --no-reflogs --unreachable 2>&1 | awk '/^(unreachable|dangling)/ {print $3}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in object $hash"
    found=1
  fi
done

# Check commit messages
if git log --all --format="%B" 2>/dev/null | grep -q 'secret\['; then
  echo "FAIL: secret still in commit messages"
  found=1
fi

# Check metadata
if git log --all --format="%an%n%ae%n%cn%n%ce" 2>/dev/null | grep -q 'secret\['; then
  echo "FAIL: secret still in metadata"
  found=1
fi

# Check stashes
if git stash list 2>/dev/null | grep -q .; then
  echo "WARN: stashes still exist"
fi

# Check special files
for f in .git/COMMIT_EDITMSG .git/MERGE_MSG .git/SQUASH_MSG; do
  if [ -f "$f" ] && grep -q 'secret\[' "$f" 2>/dev/null; then
    echo "FAIL: secret still in $f"
    found=1
  fi
done

# Check lost-found
if [ -d .git/lost-found ]; then
  if find .git/lost-found -type f -exec grep -l 'secret\[' {} \; 2>/dev/null | grep -q .; then
    echo "FAIL: secret still in .git/lost-found/"
    found=1
  fi
fi

# Check submodules, worktrees, and nested repos
GIT_DIRS=$(
  find . -name '.git' -type d 2>/dev/null
  find . -name '.git' -type f 2>/dev/null | while read gitfile; do
    if grep -q '^gitdir:' "$gitfile" 2>/dev/null; then
      gitdir=$(sed 's/^gitdir: //' "$gitfile")
      if [[ "$gitdir" != /* ]]; then
        gitdir="$(dirname "$gitfile")/$gitdir"
      fi
      echo "$gitdir"
    fi
  done
  find .git/worktrees -maxdepth 1 -mindepth 1 -type d 2>/dev/null
  find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||'
)
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')

for gitdir in $GIT_DIRS; do
  for hash in $(GIT_DIR="$gitdir" git rev-list --all --objects 2>/dev/null | awk '{print $1}'; \
                GIT_DIR="$gitdir" git fsck --full --no-reflogs --unreachable 2>&1 | awk '/^(unreachable|dangling)/ {print $3}'); do
    if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "FAIL: secret still in worktree/submodule $gitdir object $hash"
      found=1
    fi
  done
  # Check worktree index
  if [ -f "$gitdir/index" ]; then
    GIT_DIR="$gitdir" git ls-files --stage 2>/dev/null | while read mode hash stage name; do
      if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FAIL: secret still in worktree $gitdir index: $name"
        echo "found" >> /tmp/verify_found
      fi
    done
    [ -f /tmp/verify_found ] && found=1 && rm /tmp/verify_found
  fi
done

# Check alternates
if [ -f .git/objects/info/alternates ]; then
  while read altdir; do
    [ -z "$altdir" ] && continue
    find "$altdir" -type f | while read f; do
      hash=$(echo "$f" | sed "s|$altdir/||;s|/||")
      if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FAIL: secret still in alternate $altdir object $hash"
        echo "found" >> /tmp/verify_found
      fi
    done
  done < .git/objects/info/alternates
  [ -f /tmp/verify_found ] && found=1 && rm /tmp/verify_found
fi

[ "$found" = "0" ] && echo "PASS: secret not found in any location"

# Verify legitimate content is intact
echo "=== Legitimate content ==="
git log --all --oneline
git branch -a
git tag -l
git status
```

---

## Section D: Decision Flowchart

```
Phase 1: FIND
  → Search objects (rev-list + fsck)
  → If found: extract and save to /app/secret.txt

Phase 2: MAP
  → Run comprehensive search to find ALL locations
  → Record LOCATIONS variable

Phase 3: PLAN
  → Consult decision table (B.1)
  → Determine which steps to execute

Phase 4: PURGE (strict order)
  → Step 1: Drop explicit refs (stash, tag, replace, notes)
  → Step 2: Rewrite history if needed (filter-branch -- --all)
  → Step 3: Delete backup refs (rm refs/original/)
  → Step 4: Expire reflogs
  → Step 5: Clean lost-found + metadata files
  → Step 6: gc --prune=now --aggressive
  [Skip non-applicable steps; never reorder]

Phase 5: VERIFY
  → Re-run Phase 2 discovery — must find nothing
  → Check legitimate content intact
```

---

## Key Principles

1. **Two-phase discovery** — Phase 1 finds the secret fast; Phase 2 maps ALL locations for cleanup planning
2. **Recover before cleaning** — write to /app/secret.txt before any destructive operations
3. **Preserve legitimate content** — never delete branches, tags, or commits that don't contain the secret
4. **Cleanup order is a hard dependency** — follow the 6-step chain; never run gc before deleting backup refs
5. **Use the decision table** — map LOCATIONS to cleanup steps; don't guess
6. **Verify by re-running full discovery** — abbreviated checks miss edge cases
7. **Reflogs can resurrect** — always expire reflogs before gc
8. **Pack files count** — objects in pack files must also be checked and purged
9. **filter-branch leaves backups** — always remove refs/original/ after filter-branch
10. **`-- --all` is mandatory** — without it, filter-branch only rewrites the current branch
11. **Rewriting changes hashes** — commit messages are preserved but hashes change
12. **Secrets can be in metadata** — check commit messages, author/committer fields, tag annotations, COMMIT_EDITMSG, MERGE_MSG
13. **Clean lost-found** — `git fsck --lost-found` creates `.git/lost-found/` with copies of dangling objects; must be removed before gc
14. **Search submodules recursively** — submodules have separate object databases at `.git/modules/<name>/objects/`; the discovery must iterate over all `.git` directories in the repo tree
15. **Search worktrees** — worktrees use `.git` files (not directories) pointing to shared gitdirs; they have separate HEAD, index, and reflogs that must be checked
16. **Check git alternates** — `.git/objects/info/alternates` can point to external object databases; objects there must be searched and cleaned separately

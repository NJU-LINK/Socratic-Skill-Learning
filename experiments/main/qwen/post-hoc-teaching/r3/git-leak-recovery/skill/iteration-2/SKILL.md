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
1. DISCOVER  → Run the unified search (Section A) to find the secret
2. EXTRACT   → Save to /app/secret.txt BEFORE any cleanup
3. PURGE     → Follow the ordered cleanup chain (Section B)
4. VERIFY    → Re-run the unified search to confirm purge (Section C)
```

---

## Section A: Unified Secret Discovery

### A.1 — Single comprehensive search command

Run this ONE command to search ALL locations at once. It covers reachable objects,
unreachable objects, pack files, loose objects, commit messages, metadata, stashes,
tags, and special git files.

```bash
cd /app/repo

echo "=== Searching ALL git storage for secret[...] ==="

# 1. All objects in the object store (reachable + unreachable, loose + packed)
#    This is the ultimate search — covers blobs, commits, trees, tags
ALL_HASHES=$(
  # Reachable objects
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  # Unreachable/dangling objects
  git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
    | grep -E '^(unreachable|dangling)' | awk '{print $3}'
)
UNIQ_HASHES=$(echo "$ALL_HASHES" | sort -u)

for hash in $UNIQ_HASHES; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    type=$(git cat-file -t "$hash" 2>/dev/null)
    echo "FOUND in $type $hash:"
    echo "$content" | grep 'secret\['
  fi
done

# 2. Commit messages (subject + body)
git log --all --format="COMMIT_MSG %H%n%B%n---END---" | awk '
  /^COMMIT_MSG / { hash=$2; next }
  /^---END---/ { next }
  /secret\[/ { print "FOUND in commit message of " hash ": " $0 }
'

# 3. Author/committer metadata
git log --all --format="%H|%an|%ae|%cn|%ce" | while IFS='|' read hash an ae cn ce; do
  for field in "$an" "$ae" "$cn" "$ce"; do
    if echo "$field" | grep -q 'secret\['; then
      echo "FOUND in metadata of $hash: $field"
    fi
  done
done

# 4. Stash contents
git stash list --format="%gd" 2>/dev/null | while read stash_ref; do
  git ls-tree -r "$stash_ref" 2>/dev/null | while read mode type hash name; do
    if [ "$type" = "blob" ]; then
      if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in stash $stash_ref blob $hash ($name)"
      fi
    fi
  done
done

# 5. Special git metadata files
for f in .git/COMMIT_EDITMSG .git/MERGE_MSG .git/SQUASH_MSG \
         .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD; do
  if [ -f "$f" ] && grep -q 'secret\[' "$f" 2>/dev/null; then
    echo "FOUND in $f:"
    grep 'secret\[' "$f"
  fi
done

# 6. lost-found directory (created by git fsck --lost-found)
if [ -d .git/lost-found ]; then
  find .git/lost-found -type f | while read f; do
    if grep -q 'secret\[' "$f" 2>/dev/null; then
      echo "FOUND in $f:"
      grep 'secret\[' "$f"
    fi
  done
fi

# 7. Replace refs, notes, backup refs
git for-each-ref refs/replace/ refs/notes/ refs/original/ 2>/dev/null | while read hash type ref; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in ref $ref (object $hash)"
  fi
done

# 8. Submodule and nested-repo object databases
#    Submodules have their own .git/modules/<name>/objects/ databases
#    Nested repos have .git/ directories inside subdirectories
GIT_DIRS=$(find . -name '.git' -type d 2>/dev/null; find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||')
# Deduplicate and exclude the main .git (already searched above)
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')

for gitdir in $GIT_DIRS; do
  echo "--- Searching submodule/nested repo: $gitdir ---"
  # Use GIT_DIR to run git commands in the submodule
  SUB_HASHES=$(
    GIT_DIR="$gitdir" git rev-list --all --objects 2>/dev/null | awk '{print $1}'
    GIT_DIR="$gitdir" git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
      | grep -E '^(unreachable|dangling)' | awk '{print $3}'
  )
  for hash in $(echo "$SUB_HASHES" | sort -u); do
    content=$(GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      type=$(GIT_DIR="$gitdir" git cat-file -t "$hash" 2>/dev/null)
      echo "FOUND in submodule $gitdir $type $hash:"
      echo "$content" | grep 'secret\['
    fi
  done
  # Also check lost-found in submodule
  if [ -d "$gitdir/lost-found" ]; then
    find "$gitdir/lost-found" -type f | while read f; do
      if grep -q 'secret\[' "$f" 2>/dev/null; then
        echo "FOUND in $f:"
        grep 'secret\[' "$f"
      fi
    done
  fi
done

echo "=== Search complete ==="
```

### A.2 — Extract the secret

Once found, extract and save immediately:

```bash
# If found in a blob:
git cat-file -p BLOB_HASH | grep -oP 'secret\[[^\]]*\]' > /app/secret.txt

# If found via grep in a file:
grep -oP 'secret\[[^\]]*\]' FILEPATH > /app/secret.txt

# Verify:
cat /app/secret.txt
```

**Critical: Always save the secret BEFORE starting cleanup.** Cleanup operations
are destructive and irreversible.

---

## Section B: Ordered Cleanup

### B.1 — Cleanup Dependency Chain (MANDATORY ORDER)

When the secret exists in **multiple locations simultaneously**, cleanup steps have
hard dependencies. Applying them out of order leaves the secret recoverable.

```
Step 1: Drop explicit references
  → git stash drop stash@{N}    (if stash contains secret)
  → git tag -d TAG_NAME         (if tainted tags exist)
  → git update-ref -d refs/replace/...  (replace refs)
  → git update-ref -d refs/notes/...    (notes refs)

Step 2: Rewrite reachable history (if secret is in committed history)
  → git filter-branch ...
  This creates backup refs in refs/original/ — the OLD commits
  (still containing the secret) remain reachable through these backups.

Step 3: Delete backup refs created by filter-branch
  → rm -rf .git/refs/original/
  → git for-each-ref --format='delete %(refname)' refs/original/ | git update-ref --stdin

Step 4: Expire ALL reflogs
  → git reflog expire --expire=now --all
  Reflogs may reference any of the above objects.

Step 5: Clean auxiliary files/directories
  → rm -rf .git/lost-found/
  → Clean .git/COMMIT_EDITMSG, .git/MERGE_MSG, .git/SQUASH_MSG if tainted

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

**Skip steps that don't apply** (e.g., skip Step 2 if secret is only in
unreachable objects), but never reorder the steps you do execute.

### B.2 — Cleanup Techniques by Location

#### Secret in unreachable/dangling objects only (simplest case — v01 pattern)

The secret is not in any reachable commit, stash, or ref. Just prune.

```bash
git reflog expire --expire=now --all
rm -rf .git/lost-found/
git gc --prune=now --aggressive
```

#### Secret in reachable history — file removal

If the secret is in a **standalone file** that should be removed entirely:

```bash
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch PATH_TO_SECRET_FILE' \
  --prune-empty -- --all
```

#### Secret in reachable history — content replacement (text file)

If the secret is **embedded inside a legitimate file**:

```bash
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all
```

#### Secret in reachable history — content replacement (binary file)

```bash
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     perl -0777 -pi -e "s/secret\[.*?\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all
```

#### Secret in commit messages

```bash
git filter-branch --force --msg-filter '
  sed "s/secret\[[^]]*\]/REDACTED/g"
' -- --all
```

#### Secret in author/committer metadata

```bash
git filter-branch --force --env-filter '
  export GIT_AUTHOR_NAME=$(echo "$GIT_AUTHOR_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_AUTHOR_EMAIL=$(echo "$GIT_AUTHOR_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_NAME=$(echo "$GIT_COMMITTER_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_EMAIL=$(echo "$GIT_COMMITTER_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
' -- --all
```

#### Combining multiple filter-branch filters

If the secret is in both file content AND commit messages, combine in one pass:

```bash
git filter-branch --force \
  --tree-filter 'if [ -f PATH ]; then sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH; fi' \
  --msg-filter 'sed "s/secret\[[^]]*\]/REDACTED/g"' \
  --prune-empty -- --all
```

**Critical flags for all filter-branch commands:**
- `-- --all` is **mandatory**. Without it, filter-branch only rewrites the
  current branch. Secrets in other branches or tags survive.
- `--prune-empty` removes commits that become empty after file removal.
  Omit if you want to keep empty commits for message preservation.

**Note on hash changes:** Rewriting history changes ALL commit hashes downstream
of the first modified commit. The spec says "commit messages remain untouched" —
content rewriting preserves messages but changes hashes.

#### Secret in a stash

```bash
git stash drop stash@{N}
```

#### Secret in replace refs, notes, or backup refs

```bash
git for-each-ref --format='%(refname)' refs/replace/ refs/notes/ refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

#### Secret in a submodule or nested-repo object database

Submodules have their own object databases at `.git/modules/<name>/objects/`.
If the secret is in a submodule, you must clean it there using the same
procedure as the main repo. If the secret is in the submodule's reachable
history, you need filter-branch inside the submodule too.

```bash
# Find all submodule/nested-repo .git directories
GIT_DIRS=$(find . -name '.git' -type d 2>/dev/null; find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||')
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')

for gitdir in $GIT_DIRS; do
  echo "=== Cleaning submodule: $gitdir ==="
  # If secret is in reachable history within the submodule, rewrite it first
  # (use the same filter-branch techniques from B.2, with GIT_DIR="$gitdir")
  # Example for unreachable objects only:
  GIT_DIR="$gitdir" git reflog expire --expire=now --all
  GIT_DIR="$gitdir" git gc --prune=now --aggressive
  rm -rf "$gitdir/lost-found/"
done

# Then clean the main repo
git reflog expire --expire=now --all
git gc --prune=now --aggressive
rm -rf .git/lost-found/
```

### B.3 — Post-rewrite cleanup (always run after filter-branch)

```bash
# Remove backup refs
rm -rf .git/refs/original/
git for-each-ref --format='delete %(refname)' refs/original/ 2>/dev/null | git update-ref --stdin

# Expire all reflogs
git reflog expire --expire=now --all

# Clean lost-found (before gc)
rm -rf .git/lost-found/

# Prune unreachable objects (always last)
git gc --prune=now --aggressive
```

---

## Section C: Verification

After cleanup, **re-run the unified search from Section A.1** to confirm the
secret is gone from every location. Then verify legitimate content is intact.

```bash
cd /app/repo

# 1. Re-run unified discovery (Section A.1) — should find nothing
# [paste the same command from A.1]

# 2. Verify no secret in ANY object (brute-force, including submodules)
echo "=== Brute-force verification ==="
found=0

# Check main repo objects
for hash in $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'; \
              git fsck --full --no-reflogs --unreachable 2>&1 | awk '/^(unreachable|dangling)/ {print $3}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in main repo object $hash"
    found=1
  fi
done

# Check submodule/nested-repo objects
GIT_DIRS=$(find . -name '.git' -type d 2>/dev/null; find .git/modules -name 'objects' -type d 2>/dev/null | sed 's|/objects$||')
GIT_DIRS=$(echo "$GIT_DIRS" | sort -u | grep -v '^\.git$' | grep -v '^\./\.git$')
for gitdir in $GIT_DIRS; do
  for hash in $(GIT_DIR="$gitdir" git rev-list --all --objects 2>/dev/null | awk '{print $1}'; \
                GIT_DIR="$gitdir" git fsck --full --no-reflogs --unreachable 2>&1 | awk '/^(unreachable|dangling)/ {print $3}'); do
    if GIT_DIR="$gitdir" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
      echo "FAIL: secret still in submodule $gitdir object $hash"
      found=1
    fi
  done
done

[ "$found" = "0" ] && echo "PASS: secret not found in any object"

# 3. Verify no lost-found directory with secrets
if [ -d .git/lost-found ]; then
  if find .git/lost-found -type f -exec grep -l 'secret\[' {} \; 2>/dev/null | grep -q .; then
    echo "FAIL: secret found in .git/lost-found/"
  fi
fi

# 4. Verify legitimate content is intact
echo "=== Legitimate content ==="
git log --all --oneline
git branch -a
git tag -l
git status
```

---

## Section D: Decision Flowchart

```
Phase 1: DISCOVER
  → Run unified search (A.1) — covers ALL locations in one pass
  → Note WHERE the secret was found (location type)

Phase 2: EXTRACT
  → Save to /app/secret.txt BEFORE any cleanup

Phase 3: PURGE (strict order)
  → Step 1: Drop explicit refs (stash, tag, replace, notes)
  → Step 2: Rewrite history if needed (filter-branch -- --all)
  → Step 3: Delete backup refs (rm refs/original/)
  → Step 4: Expire reflogs
  → Step 5: Clean lost-found + metadata files
  → Step 6: gc --prune=now --aggressive
  [Skip non-applicable steps; never reorder]

Phase 4: VERIFY
  → Re-run unified search (A.1) — must find nothing
  → Check legitimate content intact
```

---

## Key Principles

1. **Unified search first** — one command covers all locations; don't run 7 separate scripts
2. **Recover before cleaning** — write to /app/secret.txt before any destructive operations
3. **Preserve legitimate content** — never delete branches, tags, or commits that don't contain the secret
4. **Cleanup order is a hard dependency** — follow the 6-step chain; never run gc before deleting backup refs
5. **Verify by re-running full discovery** — abbreviated checks miss edge cases
6. **Reflogs can resurrect** — always expire reflogs before gc
7. **Pack files count** — objects in pack files must also be checked and purged
8. **filter-branch leaves backups** — always remove refs/original/ after filter-branch
9. **`-- --all` is mandatory** — without it, filter-branch only rewrites the current branch
10. **Rewriting changes hashes** — commit messages are preserved but hashes change
11. **Secrets can be in metadata** — check commit messages, author/committer fields, tag annotations, COMMIT_EDITMSG, MERGE_MSG
12. **Clean lost-found** — `git fsck --lost-found` creates `.git/lost-found/` with copies of dangling objects; must be removed before gc
13. **Search submodules recursively** — submodules have separate object databases at `.git/modules/<name>/objects/`; the unified search must iterate over all `.git` directories in the repo tree

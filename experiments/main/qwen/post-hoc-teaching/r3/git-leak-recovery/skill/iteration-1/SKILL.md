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
messages, author/committer metadata, or submodule object databases. The task is to:

1. **Recover** the secret and write it to `/app/secret.txt`
2. **Purge** it from every location in the repo
3. **Preserve** all legitimate content (branches, files, tags, commit messages)

## General Strategy

### Phase 1: Comprehensive Secret Discovery

Search every possible Git storage location for the secret pattern `secret[...]`.
The secret can be in file content, commit messages, author/committer fields, or
annotated tag messages.

#### 1a. Search all reachable objects (blobs, commits, trees)

```bash
cd /app/repo
# List ALL objects reachable from any ref (branches, tags, stashes, etc.)
git rev-list --all --objects | while read hash rest; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    type=$(git cat-file -t "$hash" 2>/dev/null)
    echo "FOUND in reachable $type $hash ($rest)"
    echo "$content" | grep 'secret\['
  fi
done
```

#### 1b. Search unreachable/dangling objects

```bash
# Find all unreachable objects (blobs, commits, trees)
git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
  | grep -E '^(unreachable|dangling)' | awk '{print $3}' | while read hash; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    type=$(git cat-file -t "$hash" 2>/dev/null)
    echo "FOUND in unreachable $type $hash"
    echo "$content" | grep 'secret\['
  fi
done
```

#### 1c. Search stashes

```bash
git stash list 2>/dev/null
# If stashes exist, inspect each one's full tree
git stash list --format="%gd" | while read stash_ref; do
  git ls-tree -r "$stash_ref" 2>/dev/null | while read mode type hash name; do
    if [ "$type" = "blob" ]; then
      content=$(git cat-file -p "$hash" 2>/dev/null)
      if echo "$content" | grep -q 'secret\['; then
        echo "FOUND in stash $stash_ref blob $hash ($name)"
      fi
    fi
  done
done
```

#### 1d. Search all refs comprehensively

```bash
# List every ref in the repo (branches, tags, stashes, replace, notes, etc.)
git for-each-ref --format='%(refname)' | while read ref; do
  git ls-tree -r "$ref" 2>/dev/null | while read mode type hash name; do
    if [ "$type" = "blob" ]; then
      content=$(git cat-file -p "$hash" 2>/dev/null)
      if echo "$content" | grep -q 'secret\['; then
        echo "FOUND in $ref -> $name (blob $hash)"
      fi
    fi
  done
done
```

#### 1e. Search commit messages and metadata

```bash
# Check all commit messages for embedded secrets
git log --all --format="%H %s" | while read hash msg; do
  if echo "$msg" | grep -q 'secret\['; then
    echo "FOUND in commit message of $hash: $msg"
  fi
done
# Also check full commit body
git log --all --format="%H%n%B%n---END---" | awk '
  /^---END---/ { if (found) print "FOUND in commit " hash; found=0; next }
  /secret\[/ { found=1; hash=last_hash }
  /^[0-9a-f]{40}/ { last_hash=$0 }
'
# Check author/committer name and email
git log --all --format="%H | %an | %ae | %cn | %ce" | while IFS='|' read hash an ae cn ce; do
  for field in "$an" "$ae" "$cn" "$ce"; do
    if echo "$field" | grep -q 'secret\['; then
      echo "FOUND in metadata of $hash: $field"
    fi
  done
done
```

#### 1f. Check annotated tag messages

```bash
git tag -l | while read tag; do
  # Get the tag object itself (not just the commit it points to)
  tag_obj=$(git rev-parse "$tag^{tag}" 2>/dev/null)
  if [ -n "$tag_obj" ]; then
    content=$(git cat-file -p "$tag_obj" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      echo "FOUND in annotated tag object $tag_obj ($tag)"
    fi
  fi
done
```

#### 1g. Brute-force search of ALL objects in the object store

This is the ultimate fallback — it finds secrets in loose objects and pack files
regardless of reachability.

```bash
# Search loose objects
find .git/objects -type f | grep -v '/info/' | grep -v '/pack/' | while read f; do
  hash=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND in loose object $hash"
  fi
done

# Search pack files
for pack in .git/objects/pack/*.idx; do
  [ -f "$pack" ] || continue
  git verify-pack -v "$pack" 2>/dev/null | awk '/^[0-9a-f]{40}/ {print $1}' | while read hash; do
    content=$(git cat-file -p "$hash" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      echo "FOUND in pack object $hash"
    fi
  done
done
```

### Phase 2: Extract and Save the Secret

Once found, extract the exact secret string and write it **before** any cleanup:

```bash
# Extract precisely using grep
echo -n 'secret[THE_EXACT_VALUE]' > /app/secret.txt
# Or pipe from discovery output:
# git cat-file -p BLOB_HASH | grep -oP 'secret\[[^\]]*\]' > /app/secret.txt
```

**Critical: Always save the secret BEFORE starting cleanup.** Cleanup operations
are destructive and irreversible.

### Phase 3: Purge the Secret

#### 3.1 — Cleanup Ordering (MANDATORY)

When the secret exists in **multiple locations simultaneously**, cleanup steps have
hard dependencies. Applying them out of order leaves the secret recoverable.

**The 5-step dependency chain (execute in this exact order):**

```
Step 1: Drop explicit references
  → git stash drop stash@{N}    (if stash contains secret)
  → git tag -d TAG_NAME         (if tainted tags exist)
  → git update-ref -d refs/replace/...  (replace refs)

Step 2: Rewrite reachable history
  → git filter-branch ...       (if secret is in committed history)
  This creates backup refs in refs/original/ — the OLD commits
  (still containing the secret) remain reachable through these backups.

Step 3: Delete backup refs created by filter-branch
  → rm -rf .git/refs/original/
  → git for-each-ref --format='delete %(refname)' refs/original/ | git update-ref --stdin

Step 4: Expire ALL reflogs
  → git reflog expire --expire=now --all
  Reflogs may reference any of the above objects.

Step 5: Prune unreachable objects
  → git gc --prune=now --aggressive
  This is ALWAYS the last step.
```

**Why order matters:**
- If you run `git gc` before deleting `refs/original/`, gc sees old commits as
  reachable through backup refs and **keeps them**. You'd have to re-run gc.
- If you expire reflogs before rewriting history, you lose the reflog entries
  that identify which commits contained the secret — but the secret is still
  in the reachable history.
- If you run filter-branch before dropping stashes, the stash objects remain
  and can resurrect the secret.

**Skip steps that don't apply** (e.g., skip Step 2 if secret is only in
unreachable objects), but never reorder the steps you do execute.

#### 3.2 — Cleanup Techniques by Location

##### Secret in unreachable/dangling objects only (simplest case)

The secret is not in any reachable commit, stash, or ref. Just prune.

```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

##### Secret in reachable history (committed) — file content

If the secret is in a **standalone file** that should be removed entirely:

```bash
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch PATH_TO_SECRET_FILE' \
  --prune-empty -- --all
```

If the secret is **embedded inside a legitimate file** (content replacement):

```bash
# For text files — use --tree-filter (simpler but slower):
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all

# For text files in large repos — use --index-filter (faster):
git filter-branch --force --index-filter '
  git checkout-index -f -- PATH_TO_FILE 2>/dev/null
  if [ -f "PATH_TO_FILE" ]; then
    sed "s/secret\[[^]]*\]/REDACTED/g" "PATH_TO_FILE" > "PATH_TO_FILE.tmp"
    mv "PATH_TO_FILE.tmp" "PATH_TO_FILE"
    git update-index --add "PATH_TO_FILE"
  fi
' --prune-empty -- --all
```

**Critical flags:**
- `-- --all` is **mandatory**. Without it, filter-branch only rewrites the
  current branch. Secrets in other branches or tags survive.
- `--prune-empty` removes commits that become empty after the secret file
  is removed. Omit if you want to keep empty commits for message preservation.

**Binary files:** If the secret is embedded in a binary file, `sed` may corrupt
it. Use perl for binary-safe replacement:

```bash
git filter-branch --force --tree-filter \
  'if [ -f PATH_TO_FILE ]; then
     perl -0777 -pi -e "s/secret\[.*?\]/REDACTED/g" PATH_TO_FILE
   fi' \
  --prune-empty -- --all
```

##### Secret in commit messages

```bash
git filter-branch --force --msg-filter '
  sed "s/secret\[[^]]*\]/REDACTED/g"
' -- --all
```

##### Secret in author/committer metadata

```bash
git filter-branch --force --env-filter '
  export GIT_AUTHOR_NAME=$(echo "$GIT_AUTHOR_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_AUTHOR_EMAIL=$(echo "$GIT_AUTHOR_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_NAME=$(echo "$GIT_COMMITTER_NAME" | sed "s/secret\[[^]]*\]/REDACTED/g")
  export GIT_COMMITTER_EMAIL=$(echo "$GIT_COMMITTER_EMAIL" | sed "s/secret\[[^]]*\]/REDACTED/g")
' -- --all
```

**Note on hash changes:** Rewriting history changes ALL commit hashes downstream
of the first modified commit (because each commit's hash depends on its parent's
hash). The spec says "commit messages remain untouched" — content rewriting
preserves messages but changes hashes. Tests should verify by content, not by hash.

##### Combining multiple filter-branch filters

If the secret is in both file content AND commit messages, combine filters:

```bash
git filter-branch --force \
  --tree-filter 'if [ -f PATH ]; then sed -i "s/secret\[[^]]*\]/REDACTED/g" PATH; fi' \
  --msg-filter 'sed "s/secret\[[^]]*\]/REDACTED/g"' \
  --prune-empty -- --all
```

##### Secret in a stash

```bash
git stash drop stash@{N}
```

##### Secret in replace refs or backup refs

```bash
git for-each-ref --format='%(refname)' refs/replace/ | while read ref; do
  git update-ref -d "$ref"
done
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

##### Secret in a submodule object database

```bash
# Enter the submodule and perform cleanup there
cd PATH_TO_SUBMODULE
git reflog expire --expire=now --all
git gc --prune=now --aggressive
cd /app/repo
# Also clean up the parent repo
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

#### 3.3 — Complete Cleanup Procedure (after filter-branch or multi-location)

After any history rewrite or multi-location cleanup, always execute Steps 3-5:

```bash
# Step 3: Remove backup refs
rm -rf .git/refs/original/
git for-each-ref --format='delete %(refname)' refs/original/ 2>/dev/null | git update-ref --stdin

# Step 4: Expire all reflogs
git reflog expire --expire=now --all

# Step 5: Prune unreachable objects
git gc --prune=now --aggressive
```

### Phase 4: Verification (Re-run Full Discovery)

After cleanup, **re-run the complete Phase 1 discovery** to confirm the secret
is gone from every location. An abbreviated check can miss edge cases.

```bash
cd /app/repo

# 1. Check ALL reachable objects
echo "=== Checking reachable objects ==="
git rev-list --all --objects | while read hash rest; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in reachable object $hash ($rest)"
  fi
done

# 2. Check unreachable objects
echo "=== Checking unreachable objects ==="
git fsck --full --no-reflogs --unreachable --dangling 2>&1 \
  | grep -E '^(unreachable|dangling)' | awk '{print $3}' | while read hash; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in unreachable object $hash"
  fi
done

# 3. Check commit messages and metadata
echo "=== Checking commit messages/metadata ==="
git log --all --format="%H %s" | while read hash msg; do
  if echo "$msg" | grep -q 'secret\['; then
    echo "FAIL: secret still in commit message of $hash"
  fi
done

# 4. Check stashes
echo "=== Checking stashes ==="
git stash list 2>/dev/null | while read line; do
  echo "WARN: stash still exists: $line"
done

# 5. Check replace/backup refs
echo "=== Checking special refs ==="
git for-each-ref refs/replace/ refs/original/ 2>/dev/null | while read line; do
  echo "WARN: special ref still exists: $line"
done

# 6. Brute-force all objects in object store (ultimate check)
echo "=== Brute-force object store check ==="
found=0
for hash in $(git rev-list --all --objects | awk '{print $1}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in $hash"
    found=1
  fi
done
# Also check any remaining unreachable objects
for hash in $(git fsck --full --no-reflogs --unreachable 2>&1 | awk '/^(unreachable|dangling)/ {print $3}'); do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FAIL: secret still in unreachable $hash"
    found=1
  fi
done
[ "$found" = "0" ] && echo "PASS: secret not found in any object"

# 7. Verify legitimate content is intact
echo "=== Verifying legitimate content ==="
git log --all --oneline
git branch -a
git tag -l
git status
```

## Decision Flowchart

```
Phase 1: DISCOVER — Search ALL locations comprehensively
  ├─ Reachable objects (rev-list --all --objects)
  ├─ Unreachable objects (fsck --unreachable)
  ├─ Stashes (stash list + ls-tree)
  ├─ All refs (for-each-ref + ls-tree)
  ├─ Commit messages (log --format)
  ├─ Author/committer metadata (log --format)
  ├─ Annotated tag messages (cat-file on tag objects)
  └─ Brute-force object store (loose + pack)

Phase 2: EXTRACT — Save secret to /app/secret.txt BEFORE cleanup

Phase 3: PURGE — Execute in strict dependency order:
  Step 1: Drop explicit refs (stash drop, tag -d, update-ref -d)
  Step 2: Rewrite history (filter-branch with -- --all)
  Step 3: Delete backup refs (rm refs/original/)
  Step 4: Expire reflogs (reflog expire --expire=now --all)
  Step 5: Prune objects (gc --prune=now --aggressive)
  [Skip steps that don't apply; never reorder]

Phase 4: VERIFY — Re-run full Phase 1 discovery to confirm purge
```

## Key Principles

1. **Always search comprehensively first** — the secret may be in unexpected places
2. **Recover before cleaning** — write to /app/secret.txt before any destructive operations
3. **Preserve legitimate content** — never delete branches, tags, or commits that don't contain the secret
4. **Cleanup order is a hard dependency** — follow the 5-step chain; never run gc before deleting backup refs
5. **Verify by re-running full discovery** — abbreviated checks miss edge cases
6. **Reflogs can resurrect** — always expire reflogs before gc
7. **Pack files count** — objects in pack files must also be checked and purged
8. **filter-branch leaves backups** — always remove refs/original/ after filter-branch
9. **`-- --all` is mandatory** — without it, filter-branch only rewrites the current branch
10. **Rewriting changes hashes** — commit messages are preserved but hashes change; tests should verify content
11. **Secrets can be in metadata** — check commit messages, author/committer fields, and tag annotations, not just file content

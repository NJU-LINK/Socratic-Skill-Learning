---
name: git-leak-recovery
description: Recover leaked secrets from Git repositories and remove them from all storage locations while preserving legitimate content
---

# Git Leak Recovery Skill

## Purpose
Recover secrets that were accidentally committed, staged, stashed, or otherwise stored in Git repositories, then remove them from all Git storage locations while preserving legitimate branches, tags, commits, and files.

## Quick Start: Triage Workflow

**When you encounter a new variant, follow this prioritized workflow:**

1. **Find WHERE the secret is:**
   ```bash
   # Enumerate all objects and search each individually
   git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' > /tmp/all_objects.txt
   SECRET_PATTERN='secret\['
   while read hash type; do
     git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN" && echo "TAINTED: $hash ($type)"
   done < /tmp/all_objects.txt
   
   # Check additional locations
   git stash list  # Live stashes
   git for-each-ref --format='%(refname)' refs/replace/ refs/original/  # Special refs
   git notes list  # Git notes
   ```

2. **Classify the location and choose cleanup:**
   - **Unreachable blob/tree/commit** → `git reflog expire --expire=now --all && git gc --prune=now --aggressive`
   - **Reachable file in history** → `git filter-repo --invert-paths --path <file>` (or filter-branch if filter-repo unavailable)
   - **Commit message** → `git filter-repo --message-callback 'return message.replace(b"secret[xyz]", b"[REDACTED]")'`
   - **Live stash** → `git stash drop <stash>` (or `git stash clear` if all tainted)
   - **Replace/backup ref** → `git update-ref -d <ref>`
   - **Annotated tag message** → `git tag -d <tagname>`
   - **Multiple locations** → Apply ALL matching cleanups

3. **Execute cleanup and verify:**
   ```bash
   # After cleanup, always expire reflogs and gc
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   
   # Verify secret is gone from ALL objects
   while read hash type; do
     git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN" && echo "ERROR: Still in $hash"
   done < <(git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)')
   ```

**Note:** `git filter-repo` is preferred but may not be installed. Check with `which git-filter-repo`. If unavailable, use `git filter-branch` (see Phase 2 for examples).

---

## Core Methodology

This skill handles secrets in any Git storage location: unreachable objects, reachable history, stashes (live or dropped), replace refs, backup refs, annotated tags, deleted branches, submodules, commit messages, or any combination. Secrets may exist in **multiple locations simultaneously** — the workflow must find and clean ALL of them.

### Phase 1: Exhaustive Discovery

**Goal**: Find ALL objects containing the secret pattern, identify which objects hold them, and determine each object's reference status.

#### Step 1.1: Enumerate all objects in the repository

```bash
cd /path/to/repo

# Method 1: Using batch-all-objects (Git 2.19+)
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null > /tmp/all_objects.txt

# Method 2: Fallback for older Git
git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | \
  awk '/^[0-9a-f]{40}/ {print $1, $2}' > /tmp/all_objects.txt
# Add loose objects
find .git/objects -type f | grep -v '/pack/' | grep -v '/info/' | \
  sed 's|.git/objects/||;s|/||g' | while read hash; do
    type=$(git cat-file -t "$hash" 2>/dev/null)
    [ -n "$type" ] && echo "$hash $type"
  done >> /tmp/all_objects.txt
```

#### Step 1.2: Search each object individually (preserving identity)

```bash
SECRET_PATTERN='secret\['

# Check EVERY object individually — do NOT concatenate, which loses identity
> /tmp/tainted_objects.txt
while read hash type; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
    echo "TAINTED: $hash ($type)"
    echo "$hash $type" >> /tmp/tainted_objects.txt
  fi
done < /tmp/all_objects.txt

# Extract the actual secret values
> /tmp/found_secrets.txt
while read hash type; do
  git cat-file -p "$hash" 2>/dev/null | grep -oE "$SECRET_PATTERN[^]]*]"
done < /tmp/tainted_objects.txt | sort -u > /tmp/found_secrets.txt
```

#### Step 1.3: Determine reachability of each tainted object

**Important**: `git merge-base --is-ancestor` only works for commits, NOT blobs or trees. Use the correct method for each type:

```bash
# For commits: use merge-base
is_commit_reachable() {
  local hash="$1"
  git merge-base --is-ancestor "$hash" HEAD 2>/dev/null
}

# For blobs and trees: check if they appear in any reachable commit's tree
# IMPORTANT: Use process substitution < <(...) to avoid subshell issue with return
is_blob_or_tree_reachable() {
  local hash="$1"
  while read commit; do
    if git ls-tree -r "$commit" 2>/dev/null | grep -q "$hash"; then
      return 0
    fi
  done < <(git rev-list --all)
  return 1
}

# Classify each tainted object
> /tmp/tainted_classified.txt
while read hash type; do
  case "$type" in
    commit)
      if is_commit_reachable "$hash"; then
        echo "REACHABLE $hash $type"
      else
        echo "UNREACHABLE $hash $type"
      fi
      ;;
    blob|tree)
      if is_blob_or_tree_reachable "$hash"; then
        echo "REACHABLE $hash $type"
      else
        echo "UNREACHABLE $hash $type"
      fi
      ;;
    tag)
      # Tag objects: check if the tag ref still points to it
      git for-each-ref --format='%(objectname)' refs/tags/ | grep -q "$hash" && \
        echo "REACHABLE $hash $type" || echo "UNREACHABLE $hash $type"
      ;;
    *)
      echo "UNKNOWN $hash $type"
      ;;
  esac
done < /tmp/tainted_objects.txt > /tmp/tainted_classified.txt
```

#### Step 1.4: Check additional storage locations beyond the object database

```bash
# Stashes (live) — stash refs are reachable via refs/stash
git stash list 2>/dev/null
for stash in $(git stash list 2>/dev/null | cut -d: -f1); do
  git stash show -p "$stash" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
    echo "TAINTED STASH: $stash"
done

# All refs — check for replace refs, backup refs, and any ref containing the secret
git for-each-ref --format='%(refname) %(objectname)' | while read ref objhash; do
  # Check replace refs and backup refs specifically
  case "$ref" in
    refs/replace/*|refs/original/*)
      echo "SPECIAL REF: $ref -> $objhash"
      ;;
  esac
  # Check if any ref's log contains the secret pattern
  git log -p "$ref" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
    echo "SECRET IN REF HISTORY: $ref"
done

# Annotated tag messages (the tag object itself, not just the tagged commit)
git for-each-ref --format='%(refname) %(objectname)' refs/tags/ | while read ref tagobj; do
  objtype=$(git cat-file -t "$tagobj" 2>/dev/null)
  if [ "$objtype" = "tag" ]; then
    git cat-file -p "$tagobj" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
      echo "SECRET IN TAG MESSAGE: $ref ($tagobj)"
  fi
done

# Commit messages in reachable history
git log --all --format="%H %s" | while read hash msg; do
  echo "$msg" | grep -q "$SECRET_PATTERN" && \
    echo "SECRET IN COMMIT MESSAGE: $hash"
done

# Git notes (stored in refs/notes/, separate objects)
git notes list 2>/dev/null | while read note_ref; do
  git notes show "$note_ref" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
    echo "SECRET IN GIT NOTE: $note_ref"
done

# .git/lost+found/ (recovered objects from fsck)
if [ -d .git/lost+found ]; then
  find .git/lost+found -type f | while read objfile; do
    objhash=$(basename "$objfile")
    git cat-file -p "$objhash" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
      echo "SECRET IN LOST+FOUND: $objhash"
  done
fi

# Submodule object databases (handle both .git directories and gitfiles)
find . \( -name '.git' -type d -o -name '.git' -type f \) | while read gitentry; do
  if [ -f "$gitentry" ]; then
    # It's a gitfile — extract actual gitdir
    actual_dir=$(sed 's/gitdir: //' "$gitentry")
    submodule_dir=$(dirname "$gitentry")
    actual_dir=$(cd "$submodule_dir" && cd "$actual_dir" 2>/dev/null && pwd)
  else
    actual_dir=$(cd "$gitentry" && pwd)
  fi
  [ -d "$actual_dir" ] && echo "SUBMODULE GIT DIR: $actual_dir"
  # Must repeat full discovery inside each submodule
done
```

### Phase 2: Targeted Cleanup

**Goal**: Remove the secret from ALL locations where it was found, while preserving legitimate content. This is a **checklist**, not a decision tree — multiple cleanups may be needed.

#### Step 2.1: Apply ALL applicable cleanups

**A. Unreachable tainted objects (blobs, trees, commits not reachable from any ref):**
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**B. Reachable tainted objects in commit history (files containing secrets):**
```bash
# IMPORTANT: git filter-repo requires --force if the repo has remotes or is not a fresh clone
# Check availability: which git-filter-repo || echo "not installed, use filter-branch"

# Using git-filter-repo (preferred, faster, safer)
# Option 1: Remove the file entirely from all history
git filter-repo --force --invert-paths --path <file-with-secret>

# Option 2: Replace file content in all commits (preserves the file, removes secret)
git filter-repo --force --blob-callback '
  if b"secret[" in blob.data:
    blob.data = blob.data.replace(b"secret[xyz]", b"[REDACTED]")
'

# OR using git-filter-branch (older Git, slower, more error-prone)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <file-with-secret>' \
  --prune-empty --tag-name-filter cat -- --all

# Remove backup refs created by filter-branch
rm -rf .git/refs/original/
```

**After history rewriting:**
- All commit hashes change — verify branches still point to valid commits
- Tags are rewritten (filter-branch uses `--tag-name-filter cat` to preserve them)
- Remote tracking branches become invalid — may need to re-fetch
- Always follow with: `git reflog expire --expire=now --all && git gc --prune=now --aggressive`

**C. Secrets in commit messages:**
```bash
# Using git-filter-repo
git filter-repo --message-callback 'return message.replace(b"secret[xyz]", b"[REDACTED]")'

# OR using git-filter-branch
git filter-branch --msg-filter 'sed "s/secret\[.*\]/[REDACTED]/g"' \
  --tag-name-filter cat -- --all

rm -rf .git/refs/original/
```

**D. Live stashes containing secrets:**
```bash
# IMPORTANT: Drop stashes in reverse order (indices shift after each drop)
# Or just use 'git stash clear' if ALL stashes are tainted
git stash list 2>/dev/null | tac | cut -d: -f1 | while read stash; do
  git stash show -p "$stash" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
    git stash drop "$stash"
done
# Alternative: if all stashes are tainted, just clear them all:
# git stash clear
```

**E. Replace refs pointing to tainted objects:**
```bash
git for-each-ref --format='%(refname)' refs/replace/ | while read ref; do
  git update-ref -d "$ref"
done
```

**F. Backup refs (from filter-branch):**
```bash
rm -rf .git/refs/original/
# Or individually:
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

**G. Annotated tags containing secrets in their messages:**
```bash
git for-each-ref --format='%(refname) %(objectname)' refs/tags/ | while read ref tagobj; do
  objtype=$(git cat-file -t "$tagobj" 2>/dev/null)
  if [ "$objtype" = "tag" ]; then
    git cat-file -p "$tagobj" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
      git tag -d "$(echo "$ref" | sed 's|refs/tags/||')"
  fi
done
```

**H. Submodule object databases:**
```bash
# For each submodule found in Step 1.4, repeat the entire cleanup process
# inside that submodule's git directory
```

**I. Git notes containing secrets:**
```bash
git notes list 2>/dev/null | while read note_ref; do
  git notes show "$note_ref" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
    git notes remove "$note_ref"
done
```

**J. `.git/lost+found/` containing tainted recovered objects:**
```bash
if [ -d .git/lost+found ]; then
  find .git/lost+found -type f | while read objfile; do
    objhash=$(basename "$objfile")
    git cat-file -p "$objhash" 2>/dev/null | grep -q "$SECRET_PATTERN" && \
      rm -f "$objfile"
  done
fi
```

**K. Final sweep — always expire reflogs and gc after any cleanup:**
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### Phase 3: Verification

**Goal**: Confirm the secret is completely removed from ALL objects and legitimate content is preserved.

#### Step 3.1: Verify secret is gone from every object

```bash
FOUND=0
# Re-enumerate all objects
# IMPORTANT: Use process substitution < <(...) to avoid subshell issue with FOUND variable
while read hash type; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
    echo "ERROR: Secret still found in object $hash ($type)"
    FOUND=1
  fi
done < <(git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null)

# Also verify no tainted objects remain in pack files by checking content
# (verify-pack -v only shows metadata, not content — must cat-file each object)
for packidx in .git/objects/pack/*.idx; do
  [ -f "$packidx" ] || continue
  while read obj; do
    if git cat-file -p "$obj" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
      echo "ERROR: Secret found in packed object $obj"
      FOUND=1
    fi
  done < <(git verify-pack -v "$packidx" 2>/dev/null | awk '/^[0-9a-f]{40}/ {print $1}')
done

[ $FOUND -eq 0 ] && echo "✓ Secret completely removed from all objects"
```

#### Step 3.2: Verify legitimate content is preserved

```bash
# All branches still exist
git branch -a

# All tags still exist (that weren't tainted)
git tag

# Commit messages are intact
git log --all --oneline

# Files in working tree
git status
ls -la

# Verify specific legitimate files
git show HEAD:<legitimate-file>
```

#### Step 3.3: Check submodules if present

```bash
find . \( -name '.git' -type d -o -name '.git' -type f \) | while read gitentry; do
  if [ -f "$gitentry" ]; then
    actual_dir=$(sed 's/gitdir: //' "$gitentry")
    submodule_dir=$(dirname "$gitentry")
    actual_dir=$(cd "$submodule_dir" && cd "$actual_dir" 2>/dev/null && pwd)
  else
    actual_dir=$(cd "$gitentry" && pwd)
  fi
  echo "Verifying submodule at: $actual_dir"
  # Repeat verification inside submodule
done
```

## Common Pitfalls

1. **`git merge-base --is-ancestor` only works for commits**: For blobs and trees, use `git ls-tree -r` across all reachable commits to check if the object is referenced.

2. **`git verify-pack -v` shows metadata, not content**: To verify pack files are clean, you must `git cat-file -p` each packed object and grep the content.

3. **Concatenating objects loses identity**: Always iterate objects individually when searching, so you know exactly which hash contains the secret.

4. **`filter-repo --invert-paths` only removes files, not commit messages**: Use `--message-callback` for secrets in commit messages, or `filter-branch --msg-filter`.

5. **Secrets in multiple locations**: The spec allows secrets in several places simultaneously. Always check ALL locations and apply ALL needed cleanups — don't stop after finding the first one.

6. **Submodule `.git` may be a gitfile, not a directory**: Use `find . \( -name '.git' -type d -o -name '.git' -type f \)` and parse `gitdir:` from gitfiles.

7. **Forgetting reflogs**: Even after deleting branches or stashes, reflogs keep objects reachable. Always `git reflog expire --expire=now --all` before `git gc`.

8. **Not checking replace/backup refs**: These can keep tainted objects reachable. Always check `git for-each-ref` for `refs/replace/` and `refs/original/`.

9. **Bash subshell variable loss in pipes**: `cmd | while read; do VAR=1; done` runs the while loop in a subshell — `VAR` changes are lost. Always use process substitution: `while read; do VAR=1; done < <(cmd)`. This affects reachability checks and verification loops.

10. **Stash drop index shifting**: When dropping multiple stashes in a loop, indices shift after each drop. Drop in reverse order (`tac`) or use `git stash clear`.

11. **`git notes` can contain secrets**: Notes are stored in `refs/notes/` and are separate objects. Check them with `git notes list` and `git notes show`.

12. **`.git/lost+found/` may contain recovered objects**: After `git fsck`, recovered objects may be written here. Check and clean if tainted.

## Cleanup Checklist (apply all that match)

```
[ ] Unreachable tainted blobs/trees/commits → reflog expire + gc
[ ] Tainted files in reachable history → filter-repo --invert-paths or filter-branch
[ ] Secrets in commit messages → filter-repo --message-callback or filter-branch --msg-filter
[ ] Live tainted stashes → git stash drop (reverse order) or git stash clear
[ ] Replace refs → git update-ref -d
[ ] Backup refs → rm -rf .git/refs/original/
[ ] Tainted annotated tag messages → git tag -d
[ ] Submodule object databases → repeat full process in each submodule
[ ] Git notes containing secrets → git notes remove
[ ] .git/lost+found/ tainted objects → rm + re-gc
[ ] Final sweep → reflog expire + gc --prune=now --aggressive
```

## Recovery Workflow Summary

1. **Discover**: Enumerate ALL objects, search each individually (preserving hash identity), check stashes/refs/reflogs/tags/commit messages/submodules
2. **Classify**: For each tainted object, determine reachability (commits via merge-base, blobs/trees via ls-tree walk)
3. **Clean**: Apply ALL matching cleanups from the checklist — not just one
4. **Verify**: Re-enumerate and re-search every object's content, confirm legitimate branches/tags/files/messages preserved
5. **Write secret**: Save recovered secret to specified location (e.g., `/app/secret.txt`)

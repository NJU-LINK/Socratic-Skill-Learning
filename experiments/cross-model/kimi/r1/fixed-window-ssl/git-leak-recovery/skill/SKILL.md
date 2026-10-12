---
name: git-leak-recovery
description: Recover leaked secrets from Git repositories and clean them from all storage including unreachable objects, reflogs, stashes, and submodules.
---

# Git Leak Recovery Skill

## Overview

This skill addresses the recovery and cleanup of secrets accidentally leaked into Git storage. Secrets may exist in various locations: staged blobs, unreachable objects, stashes, reflogs, replace refs, annotated tags, or reachable history. The procedure handles all cases through a unified four-phase approach.

## Quick Path (common case: unreachable/dangling blob, simple repo)

**Use when**: survey shows hits only in unreachable objects and the repo has no tainted stash/history/tags. 
**If survey shows hits in a live stash, reachable history, tags, or submodules** — stop, use the full procedure below.

```bash
cd "$REPO"   # e.g. /app/repo

# 1. Find every object containing the pattern, reachable or not.
#    Do NOT substitute `git fsck --unreachable` here: it only sees unreachable
#    objects and misses staged blobs, reachable history, stashes, and tags.
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' \
  | awk '$1=="blob"||$1=="commit"||$1=="tag"{print $2}' \
  | while read sha; do
      git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN" && echo "HIT: $sha"
    done

# 2. Recover BEFORE cleanup: extract token(s), save OUTSIDE the repo
git cat-file -p <HIT_SHA> | grep -oE "$PATTERN" | sort -u > /app/secret.txt

# 3. Clean: expire all reflogs EXCEPT refs/stash (a stash list IS that reflog), then prune
git for-each-ref --format='%(refname)' | grep -v '^refs/stash$' \
  | while read -r ref; do git reflog expire --expire=now "$ref"; done
git reflog expire --expire=now HEAD
git gc --prune=now

# 4. Verify: re-run step 1 → zero hits; git fsck --full --unreachable → silence;
#    git log --oneline --all and worktree files → unchanged from before.
```

## Family Variation Dimensions

| Axis | Description | v01 Example |
|------|-------------|-------------|
| `secret_location` | Where secret persists in Git storage | Removed-from-index dangling blob |
| `repo_complexity` | Branches, tags, merges, submodules | Two commits, one branch |
| `cleanup_scope` | References and objects needing cleanup | Single unreachable blob |

## Four-Phase Procedure

### Phase 1: Survey (Discover All Hits)

Enumerate all Git objects and metadata to locate every occurrence of the secret pattern.

**Universal Object Scan** (catches all object locations regardless of reachability):
```bash
cd "$REPO"
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      git cat-file -p "$sha" 2>/dev/null \
        | grep -oE "$PATTERN" /dev/stdin \
        && echo "HIT: $sha"
    done
```

**Specific Location Checks** (run all; empty results are expected for many):

| Location | Command |
|----------|---------|
| Staged blobs | `git ls-files --stage` |
| Live stash | `git stash list` |
| Replace refs | `git replace -l` |
| All refs | `git for-each-ref` |
| Reflogs | `git reflog show --all` |
| Reachable history | `git log -S'secret[' --all` (literal) or `git log -G'secret\[' --all` (regex) |
| Annotated tags | `git for-each-ref refs/tags --format='%(objectname)'` |
| Submodules | Recurse into `.git/modules/*/` |
| Alternates | Check `.git/objects/info/alternates` |

**Important**: Continue after first hit - multiple staged blobs are possible.

**Warning**: `git fsck --unreachable` only finds unreachable objects. It will miss secrets in staged blobs, reachable commits, stashes, replace refs, or annotated tags. Always use the universal object scan for comprehensive survey.

### Phase 2: Recover (Before Any Destructive Step)

Extract the secret token(s) from hit objects and save outside the repository.

```bash
# Extract pattern matches from all hit objects, dedupe, save
cd "$REPO"
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' \
  | awk '$1=="blob" || $1=="commit" || $1=="tag" {print $2}' \
  | while read sha; do
      git cat-file -p "$sha" 2>/dev/null | grep -oE "$PATTERN"
    done \
  | sort -u > "$OUTPUT_FILE"
```

**Guardrail**: Verify output file exists and is non-empty before proceeding to cleanup.

### Phase 3: Cleanup (Least to Most Destructive)

Execute only the steps required based on survey findings:

1. **Drop tainted stashes only**: `git stash drop <stash>` for affected stashes
2. **Delete tainted refs/tags**: `git update-ref -d <ref>` (preserve untainted ones)
3. **Remove replace refs**: `git replace -d <sha>` for each tainted replace ref
4. **Rewrite reachable history** (only if secret in reachable commits):
   - Use `git filter-repo` or `git filter-branch --force --index-filter '...'`
   - Remove `.git/refs/original/` after filter-branch
5. **Expire reflogs** (preserve `refs/stash` when untainted stashes exist): 
   - `git for-each-ref --format='%(refname)' | grep -v '^refs/stash$' | while read ref; do git reflog expire --expire=now "$ref"; done`
   - `git reflog expire --expire=now HEAD`
   - *Why*: Stash list IS the reflog of `refs/stash`; `--all` expiry destroys surviving stashes
6. **Garbage collect**: `git gc --prune=now`
7. **Recurse**: Repeat in `.git/modules/*/` for each submodule

### Phase 4: Verify (Both Directions)

Verification aligns with evaluator checks:
- `test_no_secret_in_any_git_object` → universal object scan (step 1 below)
- `test_no_secrets_in_unreachable_objects` → `git fsck --full --unreachable`
- `test_no_secrets_in_commits` → commit messages: `git log --grep='secret\['`; commit diffs: `git log -S'secret['`
- `test_good_commits_preserved` → positive verification of refs/log/worktree
- `test_flag_file_exists_and_correct` → `/app/secret.txt` exists and contains secret

**Negative verification** (secret completely removed):
```bash
# Re-run universal object scan - must find zero hits
git cat-file --batch-all-objects --batch-check='%(objecttype) %(objectname)' ...

# Verify no unreachable objects remain
git fsck --full --unreachable

# Check metadata files (uncompressed text)
grep -rE "$PATTERN" .git --exclude-dir=objects || true
```

**Positive verification** (legitimate state preserved):
```bash
# Compare refs, log, worktree to before-cleanup snapshot
diff before_refs.txt after_refs.txt
diff before_log.txt after_log.txt  
diff before_worktree.txt after_worktree.txt
```

## Regex Tool Reference

| Tool | Pattern Syntax | Example |
|------|---------------|---------|
| `grep -E` | Regex | `secret\[` (escaped) |
| `git grep -E` | Regex | `secret\[` (escaped) |
| `git log -S` | Literal string | `secret[` (no escape) |
| `git log -G` | Regex | `secret\[` (escaped) |
| `grep -oE` | Regex | `secret\[[^]]*\]` |

## Scripts

- `scripts/survey.sh` - Phase 1: Enumerate all objects containing pattern
- `scripts/recover.sh` - Phase 2: Extract and save secret tokens  
- `scripts/cleanup.sh` - Phase 3: Remove tainted objects (parameterized by survey results)
- `scripts/verify.sh` - Phase 4: Both-direction verification

## Usage Example

```bash
export REPO=/app/repo
export OUTPUT_FILE=/app/secret.txt
export PATTERN='secret\[[^]]*\]'

# Phase 1: Survey
bash scripts/survey.sh > /tmp/survey_hits.txt

# Phase 2: Recover
bash scripts/recover.sh

# Phase 3: Cleanup (manual review of survey_hits.txt, then)
bash scripts/cleanup.sh

# Phase 4: Verify
bash scripts/verify.sh
```

## Failure Modes

| Symptom | Likely Cause | Remediation |
|----------|-------------|-------------|
| Secret found after cleanup | Reflog not expired or incomplete survey | Re-run `reflog expire` + `gc`; use universal scan not just `git fsck --unreachable` |
| Secret in pack file | GC didn't repack fully | `git repack -ad` then `gc --prune=now` |
| Secret in submodule | Cleanup not recursive | Re-run cleanup in `.git/modules/*/`<br>Iterate `.git/modules/*/` directly for uninitialized submodules |
| Legitimate refs changed | Over-agressive deletion | Use targeted `update-ref -d` not branch delete |
| All stashes vanished after cleanup | `--all` reflog expiry destroyed `refs/stash` reflog | Use selective per-ref expiry, exclude `refs/stash` |

## Key Invariants

1. **Recover before cleanup** - Unreachable objects are irrecoverable after prune
2. **Survey determines cleanup scope** - Only clean proven-tainted locations
3. **Verify both directions** - Absence of secret AND presence of legitimate state
4. **Recurse into submodules** - Each submodule has independent object database

## Taint Detection Rules

When checking if a specific ref/commit/stash is tainted:

| Object Type | Check Method | Why |
|-------------|--------------|-----|
| Blob | `git cat-file -p <sha> \| grep` | Blobs contain file content directly |
| Commit | `git grep <pattern> <sha>` | Must search the commit's tree, not headers |
| Tag | Check tag message (cat-file) AND pointed object (grep) | Tags have their own message + point to commits |
| Stash | `git grep <pattern> <sha> <sha>^2 <sha>^3` | Stash is 3 commits: worktree, index, untracked |

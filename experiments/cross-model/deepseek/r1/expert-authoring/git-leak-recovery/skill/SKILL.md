---
name: git-leak-recovery
description: >
  Recover a secret that leaked into a Git repository through any leak path
  (staged blob, dangling object, stash, replace ref, annotated tag, deleted
  branch, reset/amended commit, reachable history, submodule or nested object
  database), write it to the required output file, then purge every trace of it
  from the repository while keeping all legitimate branches, tags, files, and
  commit messages intact. Covers locate -> recover -> classify -> cleanup ->
  verify for the git-leak-recovery family.
---

# Git Leak Recovery

## Task contract (family invariants)

Read the instruction for three things: the repo path (typically `/app/repo`),
the recovery output path (typically `/app/secret.txt`), and the secret pattern
hint (typically `secret[...]`). The hint also guarantees **uniqueness**: only
one such string exists in the repository, which makes it a safe search key.

You must end in a state where:

1. The recovered secret is written (byte-accurate) to the output file the
   instruction names.
2. Neither the full `secret[...]` string nor the secret content is findable
   anywhere in the repo: not in the worktree, the index, refs, reflogs, stash,
   replace refs, tag objects, stashes, or any reachable/unreachable object in
   **every object database belonging to the repo** (main `.git/objects`,
   `.git/modules/*`, nested repos, alternates hosts).
3. All legitimate state is untouched: branch names + tips, untainted tags,
   tracked file contents, commit messages (and commit hashes whenever no
   history rewrite was needed), worktree status.

Recovery must happen **before** any destructive cleanup: once objects are
pruned, the secret is unrecoverable and the task fails.

## Evidence map (what is observed vs. extrapolated)

Observed in the v01 anchor: repo at `/app/repo`, one branch (`master`) with two
commits whose messages (`chore: init <uuid>`, `update readme`) must survive;
the leak is a single **dangling loose blob** whose entire content is
`secret[lost_and_found_in_git]\n` (trailing newline included) — the file was
staged, unstaged, then deleted from the worktree; index clean, no stashes,
tags, replace refs; repo-local git identity exists (`TerminalBench
<tb@example.com>`) while no global identity is configured; `git reflog expire
--expire-unreachable=now --expire=now --all && git gc --prune=now` removes the
leak and all preserved-state diffs remain equal. `git-filter-repo` is NOT
installed; `git filter-branch` is (git 2.39.5).

Extrapolated from spec.yaml and validated in lab repos here: leak may also sit
in several staged blobs, a live or dropped stash, an amended or reset-away
commit, a deleted branch, a replace ref, a submodule object database
(`.git/modules/<name>`), reachable history, an annotated tag's message, a tree
entry (the `secret[...]` string as a **filename**), or embedded inside a larger
file; repos may contain branches, tags, merges, nested repos, or dozens of
commits. Every variant below was exercised end-to-end in a throwaway repo:
recovery extraction, targeted removal, purge, and verification. Lab results
worth remembering: extraction must handle secrets with and without trailing
newlines and secrets embedded in larger sources (rule in Step 2);
`--tag-name-filter cat` *re-creates* a tainted annotated tag after a rewrite,
so delete tainted tags AFTER the rewrite, not before; graders check reachable
history with `git grep <pattern> $(git rev-list --all)` and
`git log --all -p` — verify with those same commands; test what keeps the
leak alive with `git rev-list --branches --tags --remotes HEAD --objects`
(real history), plus explicit `git rev-list refs/stash --objects` and
`git for-each-ref refs/original` — do NOT rely on `--exclude`
patterns, they silently misfire for `refs/original` even when placed before
`--all` (verified in lab); `git filter-branch --prune-empty` silently deletes
pre-existing legitimate empty commits, so omit it unless the pre.log truly
has none (see rewrite section).

## Workflow

### Step 0 — Recon: snapshot legitimate state and find every object database

Run in the repo named by the instruction. Save snapshots used later to prove
nothing legit changed:

```bash
cd /app/repo
git status --porcelain | tee /tmp/pre.status
git for-each-ref --format='%(refname) %(objectname)' | tee /tmp/pre.refs
git log --all --format='%H %s' | tee /tmp/pre.log
git ls-files -z | xargs -0 sha256sum | tee /tmp/pre.files
```

Find **all** object databases — the leak may live in any of them and the main
repo's `git gc` does NOT touch the others (verified):

```bash
find /app/repo -name .git                  # nested repos: .git may be a dir (DB on site)
                                          # or a gitdir: pointer file (DB in .git/modules/<name>)
ls /app/repo/.git/modules 2>/dev/null        # submodule DBs live in each dir here
cat /app/repo/.git/objects/info/alternates 2>/dev/null   # shared object stores
cat /app/repo/.git   # if this is a plain text `gitdir:` pointer, its target is another DB to cover
git -C /app/repo worktree list               # linked worktrees
```

Run Steps 1/4/5's sweeps with `-C <worktree-or-db>` for each of these — the
main repo's `git gc` does NOT prune other databases (verified).

### Step 1 — Locate the leak (read-only)

The universal locator enumerates **all objects** (loose and packed, any type)
and prints whichever contain the pattern. Use `secret[` as the key.

```bash
git -C /app/repo cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' |
while read sha type; do
  git -C /app/repo cat-file "$type" "$sha" 2>/dev/null | grep -aq 'secret\[' \
    && echo "LEAK type=$type sha=$sha"
done
```

Run it in every DB found in Step 0 (e.g. `git -C /app/repo/.git/modules/vendor ...`).
If zero hits, fall back, in order, to:

- staged/worktree content: `git diff --cached`, `grep -ran 'secret\[' --exclude-dir=.git .`
- other metadata: `grep -ra 'secret\[' .git --exclude-dir=objects` (logs, config,
  COMMIT_EDITMSG, hooks). If the leak was never committed or staged, it appears
  only here or in plain worktree files.

Record `type` and `sha` of every hit. A hit with `type=tree` means the string
is a **filename** (path entries, not content) — recover the same way, then
remove that path (rows 2 and 6 of Step 3). For blob hits that are historical
(committed), `git rev-list --branches --tags --remotes HEAD --objects | sort -u
| grep <sha>` shows the `path`(s) of the leak — needed later as the path
argument for rewrites. This classification drives Step 3.

### Step 2 — Recover and write out (before anything destructive)

Write the output file so it contains exactly the leaked value, whatever the
source shape — a blob, a tag/commit message, a tree entry, or (if the leak
never entered Git) a plain worktree file from the Step 1 fallback grep. Use
this file-based rule (validated for blobs with/without newline, embedded
strings, messages, and filename-only leaks):

```bash
TYPE=<type>; SHA=<sha>; git cat-file "$TYPE" "$SHA" > /tmp/leak_src
#   OR, if the source is a plain file:  cp <path> /tmp/leak_src
val=$(grep -aoE 'secret\[[^]]*\]' /tmp/leak_src | sort -u | head -n1)
n=$(wc -c < /tmp/leak_src); [ "$(tail -c 1 /tmp/leak_src | od -An -t x1 | tr -d ' \n')" = "0a" ] && n=$((n-1))
head -c $n /tmp/leak_src > /tmp/leak_body
if [ -n "$val" ] && [ "$(cat /tmp/leak_body)" = "$val" ] \
   && [ "$(grep -aoE 'secret\[[^]]*\]' /tmp/leak_body | wc -l)" -eq 1 ]; then
  cp /tmp/leak_src /app/secret.txt       # source IS the bare value(+optional \n): byte-exact copy
else
  printf '%s\n' "$val" > /app/secret.txt # value embedded in more text: extract just it + newline
fi
```

(Examples: a blob whose content is exactly `secret[x]\n` is copied byte-for-
byte; a blob `token=secret[x] extra` yields `secret[x]\n`; a tag message
`release secret[x]` yields `secret[x]\n`.) `sort -u` collapses identical copies
in several objects, matching the uniqueness hint.

Validate before touching anything:
`[ -s /app/secret.txt ] && grep -aq 'secret\[' /app/secret.txt`.

### Step 3 — Classify each leak and remove it (targeted)

Determine where the leak object sits, then act on the matching rows only.
First discriminate what keeps it alive:

```bash
# 1: reachable from real history (branches + tags + remotes + detached HEAD)?
git rev-list --branches --tags --remotes HEAD --objects | sort -u | grep -w <sha>
# 2: reachable only through the stash?
git rev-list refs/stash --objects 2>/dev/null | grep -w <sha>
# 3: pinned by leftover filter-branch backup refs?
git for-each-ref refs/original   # non-empty + only listed here -> backup-pinned
```
Hit on 1 -> true reachable history (row 1 rewrite). Hit only on 2 -> stash
leak (row 3; no rewrite). The leak appears only in 3 -> delete `refs/original/*`
then Step 4 (no rewrite). No hits at all while the locator found the leak ->
staged-only (row 2 via `git ls-files --stage | grep -w <sha>`) or unreachable-
only (row 7). After any rewrite or removal, re-run this discrimination before
gc: rewritten pre-images are often still pinned by refs/stash entries or
backup refs until those are cleaned.

1. **Reachable from refs** (committed history): discrimination 1 above hits
   -> the object survives pruning, so **history rewrite required** (below).
   The same listing reveals the leak's `path`(s) at the end of the matching
   line — collect them and pass each to the rewrite's `git rm` (quote paths
   that contain spaces). After any rewrite, re-run the discrimination: tainted
   commits get new hashes (e.g. a leak on a shared merge base may persist on
   every branch and needs the full `--all` rewrite).
2. **Index (staged)**: `git ls-files --stage | grep -w <sha>` -> `git reset -q -- <paths>`
   then handle the worktree copy per row 6. If the hit was `type=tree` the
   string is the **filename itself**: unstage/remove that path exactly the same
   way (rows 2, 6, and the rewrite all operate on paths).
3. **Stash**: discrimination 2 above (or `git stash list` + `git stash show -p stash@{n}`)
   -> drop only tainted entries with `git stash drop stash@{n}` (delete from
   the largest `n` downward — indexes shift as you drop). Use `git stash clear`
   only when no stash is legitimate; dropping also removes the stash reflog.
   Do NOT rewrite history for a stash-only leak; the drop + Step 4 suffice.
4. **Replace refs**: `git replace -l`; `git replace -d <sha>` for each listed
   ref. IMPORTANT: deleting a replace ref can put the previously hidden
   tainted commit back into visible history — re-run discrimination 1
   afterwards and apply the rewrite if it now hits. If it does not hit, the
   orphaned objects are simply collected by Step 4.
5. **Tainted annotated tags** (the tag *object's message* contains the secret):
   `git tag -d <tag>`. Delete only tainted tags; untainted tags must survive.
   Do this AFTER any rewrite: `--tag-name-filter cat` re-creates tainted tag
   objects with the same tainted message, so pre-rewrite deletion is undone by
   the remap (observed in lab).
6. **Worktree files containing the pattern** (`grep -rl 'secret\[' --exclude-dir=.git .`):
   tracked -> `git checkout HEAD -- <path>`; untracked -> `rm -f <path>`.
   IMPORTANT: first confirm HEAD's own copy of a tracked file does NOT contain
   the secret; if it does, this is really row 1 — rewrite history instead.
7. **Unreachable-only** (dangling blob/commit/tree, reset-away or amended
   original commits, deleted-branch history, dropped-stash leftovers, and all
   pre-rewrite objects): no targeted action; Step 4 collects them.

**History rewrite** (row 1 — must preserve all legitimate content and commit
messages; commit hashes of the tainted line WILL change, untainted branches and
tags should be remapped, not deleted):

```bash
# secret confined to whole file(s): remove by path (paths from Step 1/row 1 discovery;
# use -r for directories, quote whitespace in paths, several paths allowed):
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --index-filter 'git rm -r -q --cached --ignore-unmatch <path> [<path2> ...]' \
  --tag-name-filter cat -- --all
# secret is a string embedded in a file that must survive (slower tree-filter):
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --tree-filter 'grep -rlI "secret\[" . 2>/dev/null | xargs -r sed -i "s/secret\[[^]]*\]/REDACTED/g"' \
  --tag-name-filter cat -- --all
# if both cases coexist (a file to delete AND a file to scrub), run the two
# filter-branch passes one after the other; tidy backup refs after EACH pass:
git for-each-ref --format='%(refname)' refs/original | xargs -r -n1 git update-ref -d
# after the rewrite, re-run the Step 3 discrimination: filter-branch remaps
# refs/stash onto the rewritten base but keeps its stored WIP content, so
# tainted stash entries still pin the old objects — stash-drop tainted
# entries and re-sweep until clean. Only then delete tainted tags (row 5)
# and go to Step 4.
```

DELIBERATELY OMITTED: `--prune-empty`. It deletes commits whose tree equals
their parent's — including pre-existing legitimate empty commits (verified in
lab: it silently erased an intentional empty commit). Emptied tainted commits
left behind are harmless (their content is scrubbed). Use `--prune-empty` only
when /tmp/pre.log proves the repo has no legitimate empty commits and the
task asks for minimal history.

Run rewrites in a real worktree: for submodule leaks use the submodule's
worktree path (e.g. `cd /app/repo/vendor`), not the bare `/app/repo/.git/modules/...`
dir; the same filter-branch commands then apply there. After sanitizing a
submodule/nested repo, its commit hash changes, so the parent's recorded
gitlink is stale (parent `git status` shows e.g. ` M vendor`). Sync it to
restore a clean parent state: `git -C <parent> add <submodule-path> && git -C
<parent> commit -m ...` — a single sync commit keeps every prior parent commit
and message intact. Take fresh Step 0 snapshots for the inner repo before
rewriting it, and verify the inner repo's log/files/status diffs in Step 5.

If `git filter-repo` exists (`git filter-repo --version`), it is the faster
replacement (`--invert-paths --path <file>` or `--replace-text`); it was not
installed in the reference env, so filter-branch is the default. Rewriting
creates commits: ensure a local identity first with
`git config user.name X && git config user.email x@y` (some repos lack even the
repo-local identity). After rewriting, verify with
`git log --all --format='%s'` that message text and order match the pre-snapshot.

### Step 4 — Global purge sweep (every object database)

After all targeted deletions (including post-rewrite deletion of tainted
tags), run in the main repo **and in every DB from Step 0** (submodules via
`git -C /app/repo/.git/modules/<name> ...`, nested repos via their own paths,
alternates hosts likewise):

```bash
git -C <dir> reflog expire --expire-unreachable=now --expire=now --all
git -C <dir> gc --prune=now
```

Order matters: targeted ref/index/stash/tag deletions FIRST, then reflog
expiry, then gc. `--prune=now` is essential — plain `git gc` keeps unreachable
objects for ~2 weeks, and reflogs keep them referenced until expired.

### Step 5 — Verify (grader-shaped checks; re-iterate Steps 3-4 if anything fails)

```bash
cd /app/repo
# 1. repo-wide binary grep, including .git metadata (index, logs, config):
grep -ra 'secret\[' . && echo "FAIL: visible hits" || echo "OK: no visible hits"
# 2. object-level sweep per DB (authoritative; catches packed/compressed objects):
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' |
while read sha type; do
  git cat-file "$type" "$sha" 2>/dev/null | grep -aq 'secret\[' && echo "HIT $type $sha"
done
# 3. dangling/unreachable objects gone:
git fsck --full --no-reflogs
# 4. reachable-history purity (grader-style checks; expect no output / exit 1):
git grep -an 'secret\[' $(git rev-list --all)
git log --all -p | grep -an 'secret\['
# 5. nothing legit changed (hash-compare only when no rewrite happened):
diff /tmp/pre.status <(git status --porcelain)
diff /tmp/pre.refs   <(git for-each-ref --format='%(refname) %(objectname)')  # equal only if no rewrite
#   after a rewrite, compare tags separately: untainted ones must still exist
#   pre: git tag -l > /tmp/pre.tags; post: diff /tmp/pre.tags <(git tag -l)
diff /tmp/pre.log    <(git log --all --format='%H %s')      # rewritten line: compare '%s' only
diff /tmp/pre.files  <(git ls-files -z | xargs -0 sha256sum)  # secret files legitimately differ post-purge
# 6. leak refs gone:
git stash list; git replace -l; git tag -l   # tainted tags must be absent, untainted present
```

Re-run the sweep for each DB. If the object sweep still hits, re-classify what
keeps the object alive (forgotten ref/original backup, stash, tag, another DB)
and repeat Steps 3-4 until clean.

## Hard rules and pitfalls

- **Sequence**: locate -> recover/write -> snapshot-driven cleanup -> verify.
  Never run `gc`/`prune`/`stash drop`/rewrite before `/app/secret.txt` is
  written and non-empty. Apply Step 2's rule for every source shape (byte
  copy when the object IS the bare value, extract otherwise) — do not retype
  or edit the value by hand.
- Never `rm -rf .git`, never `git reset --hard` blindly, never `git clean -fdx`:
  these destroy legitimate history, worktree state, or untracked files the
  grader checks. Remove only objects/files demonstrably connected to the leak.
- Do not commit new work or create new tags/branches unless it compensates for
  a rewrite's side effects (e.g. the parent's stale submodule/nested gitlink
  after sanitizing the inner repo) — the grader compares messages, refs, and
  file contents, and every pre-existing message must survive.
- `git filter-branch --prune-empty` deletes legitimate empty commits; omit it
  by default (emptied tainted commits are harmless) and only use it when
  /tmp/pre.log proves there are none.
- For reachability discrimination prefer explicit enumerations
  (`--branches --tags --remotes HEAD`, `refs/stash`, `for-each-ref refs/original`);
  `git rev-list --exclude=... --all` silently misfires for `refs/original`
  (verified) and misclassifies stash-only leaks as history.
- Staged-secret cleanup leaves the index matching HEAD and the worktree free of
  the secret file; README-style neutral files must remain byte-identical.
- Submodule/nested DBs are invisible to the main repo's gc (verified): sweep,
  rewrite, and gc each DB explicitly. Check `objects/info/alternates` — shared
  objects physically live in the alternate host and must be pruned there.
- filter-branch leaves `refs/original/*` backup refs that pin tainted history;
  delete them before gc or Step 5's item 2 will keep hitting.
- If a tracked file's committed content contains the secret, restoring from
  HEAD is not enough — that is reachable history; rewrite it.
- Deleting a replace ref can resurrect a tainted commit into visible history;
  always re-run the reachability check (Step 3 row 1) after `git replace -d`.
- Delete tainted tags only AFTER the rewrite pass — `--tag-name-filter cat`
  re-creates tainted tag objects, undoing any earlier deletion.
- The recovered value may lack a trailing newline or sit inside a larger
  text; always apply Step 2's byte-exact/extract rule instead of typing the
  value by hand.
- Keep recovery confined to `/app/repo`; never move, delete, or overwrite the
  output file (e.g. `/app/secret.txt`) after verification.
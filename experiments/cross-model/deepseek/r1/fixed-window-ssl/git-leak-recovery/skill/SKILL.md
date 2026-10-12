---
name: git-leak-recovery
description: >-
  Recover a leaked secret from a Git repository (history, object database,
  stash, tags, replace refs, index, or nested/submodule object databases),
  then expunge every copy so the secret cannot be found anywhere in the repo,
  while preserving all legitimate branches, files, tags, and commit messages.
  Use when a task says a secret was accidentally committed/staged/stashed in a
  repo and asks you to recover it and then clean it up.
---

# Git Leak Recovery

Recover-then-purge for secrets (e.g. `secret[...]`) inside Git repositories.
The family spec varies along three axes:
`secret_location` (unreachable blob, staged blobs, stash, amended/reset-away
commit, deleted branch, replace ref, submodule ODB, reachable history,
annotated tag, commit/tag message), `repo_complexity` (branches, merges, tags,
nested repos, many legitimate commits), and `cleanup_scope` (which refs /
objects keep the leak recoverable).

## First laws (invariants for every variant)

1. **Recover before any destructive command.** At some point the copy you
   hold is the only survivable one. Write the recovered value to the task's
   destination (`/app/secret.txt` in this environment) *first*.
2. **Never destroy legitimate content.** Legitimate branches, files, tags,
   and commit messages must survive byte-identical. Take a preservation
   snapshot up front and diff at the end.
3. **Verify by re-inventory, never by belief.** The only authority is
   re-running the full enumeration and seeing zero matches. A filesystem
   `grep -r` is **not** valid verification: loose blobs are zlib-compressed
   and packed blobs are delta-compressed, so plaintext is invisible to raw
   grep even while present. You must inflate objects.
4. **`git fsck` exits 0 even when it reports dangling/unreachable objects.**
   The correctness criterion is **empty output**, not the exit code.

## Phase 0 — Orient & snapshot

```sh
# Locate every object database (the family can hide a leak in any of them):
#   - main repo:            repo/.git
#   - registered submodule: repo/.git/modules/<name>/   (gitdir for the sub)
#   - embedded repo:        repo/sub/.git/              (gitlink only in parent)
#   - any `gitdir:` file pointing elsewhere
#   - alternates (shared ODBs from `clone --shared` / `--reference`):
#       cat repo/.git/objects/info/alternates    # one path per line
#     `git cat-file --batch-all-objects` ENUMERATES alternate objects too
#     (verified) so detection is safe — but pruning happens where the object
#     physically lives, so cleanup must run in the OWNING repo (see failure
#     modes).
find /app -name objects -type d -path '*/.git/*' 2>/dev/null   # first sweep
git -C /app/repo submodule status 2>/dev/null
cat /app/repo/.git/objects/info/alternates 2>/dev/null || echo "(no alternates)"

# Preservation snapshot (diff at the end):
git -C /app/repo rev-parse HEAD
git -C /app/repo for-each-ref
git -C /app/repo log --format='%s'
git -C /app/repo status --porcelain
```

## Phase 1 — Inventory & detect (per object database)

Run this inside each ODB found in Phase 0 (`GIT_DIR=<gitdir>` for
submodule/embedded repos). The signature below is `secret[`; substitute the
task's format.

```sh
# THE authoritative scan: every object in the ODB (loose + packed), of every
# content-bearing type. Trees are excluded (they hold only paths+SHAs).
# PATTERN DISCIPLINE: secret formats contain regex metacharacters ('[' ']'),
# and an unescaped '[' is an INVALID regex on GNU grep ("Invalid regular
# expression", exit 2). ALWAYS use fixed-string mode: grep -F. Exit codes are
# semantic: 0 = match found, 1 = no match, 2 = grep ERROR (bad pattern/missing
# file) — never certify "clean" from exit 2; re-run with -F.
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' |
  while read h t; do case $t in blob|commit|tag) git cat-file -p "$h";; esac; done |
  grep -aF 'secret['        # blob content, commit messages, TAG MESSAGES

# Fast paths (reachable content):
git grep -aF 'secret[' $(git rev-list --all)          # reachable file blobs
git log --all --format='%B' | grep -aF 'secret['      # commit messages
git stash list; git stash show -p 'stash@{0}'        # stash
git for-each-ref refs/tags                           # tags (then cat-file -p each)
git replace -l; git for-each-ref refs/replace        # replace refs
git ls-files -s                                      # index/staged blobs
git fsck --unreachable                               # dangling objects (report, not exit code)
```

**See through replace veils.** Replace refs change what *reachability-based*
tools (`rev-list`, `log`, `fsck`) show: a replacement object can impersonate
a tainted commit so the secret looks absent while it is anchored underneath.
The full-object scan above is **already veil-proof** — `cat-file
--batch-all-objects` enumerates the object store directly and never consults
refs. Only the reachability tools need replacements disabled:
`GIT_NO_REPLACE_OBJECTS=1 git rev-list --objects --all` (or the global
`git --no-replace-objects <cmd>`), then cat-file those blobs. A secret found
only there means a replace ref is veiling it.

**Complete inventory = union of two passes** (this pair covers every
location regardless of tool behavior): (1) the full-object inflation scan
above — every ODB byte, refs-independent; (2) the plaintext surface sweep
below — worktree files, the real index, and all `.git` text files. Reachability
tools are used only to *classify* the anchor, never to certify absence.

**Non-ODB copies.** Check plaintext text files that can carry the leak
outside the ODB: `.git/lost-found/**` (written by `git fsck --lost-found` —
a *salvage* step whose copies no prune touches; versions differ on whether
it writes, so `ls .git/lost-found` and delete if present), `.git/logs/**`
(reflog lines embed commit subjects in plaintext), `.git/COMMIT_EDITMSG`,
`.git/ORIG_HEAD`, `.git/refs/original/**` (filter-branch backups),
`.git/filter-repo/**`.

## Phase 2 — Recover

```sh
git cat-file -p <tainted-object-sha> > /app/secret.txt   # exact bytes; don't retype
# or, for worktree/index content: cp the file / git show :<path>
cat /app/secret.txt    # confirm
```

## Phase 3 — Classify the anchor, then clean

What *holds* the secret decides the cleanup. Diagnose with the scan:
is the tainted object listed by `git rev-list --objects --all` (reachable)?
Which ref reaches it (`git log --all --oneline`; `git for-each-ref`)?

| Anchor (secret lives in) | Detect | Cleanup |
|---|---|---|
| **Unreachable object** (v01: staged, unstaged, file deleted; also deleted branch / reset-away / amended-away, packed or loose) | `git fsck --unreachable` reports it; `git cat-file -e <sha>` works; NOT in rev-list | `git reflog expire --expire=now --all && git gc --prune=now`; if `git cat-file -e <sha>` still succeeds (older gits keep packed unreachable objects), escalate: `git repack -ad && git prune --expire=now`; re-check `cat-file -e` |
| **Stash** | `git stash list` (stash is a commit under `refs/stash`, so it looks reachable) | `git stash drop <only-tainted>` (or `git stash clear` if all tainted), then expire+prune |
| **Replace ref, anchor direction** (tainted object is only the *target* of `refs/replace/<sha>`) | `git replace -l`; target visible via rev-list with replacements on | `git replace -d <sha>`, then expire+prune |
| **Replace ref, veil direction** (clean replacement object impersonates a tainted commit) | default enumeration shows clean; `GIT_NO_REPLACE_OBJECTS=1` enumeration finds the leak | `git replace -d <sha>` will *reveal* the leak as reachable again — proceed to **reachable history** rewrite below; `replace -d` alone is never the end for a veil |
| **Annotated tag** (message or pointed-to commit) | `git for-each-ref refs/tags` + `git cat-file -p <tag>` | `git tag -d <only-tainted-tag>`, then expire+prune so its objects fall free; keep legitimate tags |
| **Reachable history** (a commit tree or message) | rev-list enumeration shows the blob; `git log --all` shows the commit | Rewrite: `FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --index-filter 'git rm --cached --ignore-unmatch <path>' --tag-name-filter cat -- --all` (add `--tag-name-filter cat` only if tags exist so legitimate tags survive — VERIFIED incl. MERGED history, git 2.39.5: merge commits keep BOTH parents, untouched commits keep their shas, only tainted commits are rewritten, tag names survive; tags on rewritten targets get re-pointed (new tag object, message/tagger preserved); tags on untouched commits keep identical shas (`v1 -> v1 same-sha` = identity-preserving PASS, not a bug); the rewrite NEVER scrubs annotated tag *messages* — if the tag object itself is tainted, `git tag -d` it instead). For message-only leaks: `--msg-filter 'sed -e "/secret\\[/d"'` (line-drop; VERIFIED, sed always exits 0; a `grep -v` filter that emits nothing exits 1 and aborts the whole rewrite with 'msg filter failed', so if you use grep append `|| true`). Then `rm -rf .git/refs/original`, expire+prune. (Prefer `git filter-repo` when installed: `git filter-repo --path <path> --invert-paths`, then remove `.git/filter-repo`.) **Then the universal completion step below** — rewrite tools differ on whether the post-rewrite checkout is synchronized (filter-branch's epilogue `git read-tree -u -m HEAD` updated index+worktree on git 2.39.5; filter-repo leaves the original checkout stale with the plaintext file on disk), so never certify from the tool's documented behavior — let `git status --porcelain` and the surface sweep decide |
| **Index/staged blobs** | `git ls-files -s`; blob also appears in the full-object scan | `git rm --cached <path>` / `git reset` to unstage, then apply the row above for the resulting object state |
| **Submodule / nested ODB** | parent scan finds nothing — the leak is inside the sub's own ODB | Run Phases 1–4 *inside each submodule/embedded repo* (`GIT_DIR=...` or `git -C sub ...`); the parent cannot see or prune it |

**Always finish every row with (universal completion step):**
```sh
git reflog expire --expire=now --all
git gc --prune=now
```
Reflogs and backup refs (`refs/original`) *protect* objects from pruning and
can themselves hold plaintext subjects — they must expire before gc. The
default prune grace period is ~2 weeks, so the explicit `--prune=now` /
`--expire=now` flags are what actually delete a fresh leak.

**Then make the checkout surface clean — do not trust the rewrite tool's
epilogue.**
```sh
git status --porcelain          # must be clean
# Post-rewrite stale-surface states, all three VERIFIED with unlabeled raw
# output (iteration-3 labs, no rewrite tool involved):
#   A <path>   realistic no-epilogue leftover: index has the path, rewritten
#              HEAD lacks it -> remedy clears FULLY (status becomes empty)
#   ?? <path>  untracked file on disk only -> remedy's rm -f clears it
#   D <path>   index lacks a path HEAD still HAS -> the remedy clears the
#              index+disk surfaces but D PERSISTS, because D is an
#              index-vs-HEAD relationship the remedy cannot touch. A
#              surviving D is NOT a remedy failure: it means the path is
#              still in HEAD, i.e. that ref's history was never rewritten —
#              go back to Phase 3 and rewrite, do not dig deeper here.
# NOTE: an earlier iteration of this Skill claimed the stale-checkout
# leftover shows as `D <path>`; the A-state lab supersedes that, retain the
# diagnosis above.
git rm --cached --ignore-unmatch <path> && rm -f <path>
# re-run `git status --porcelain`: if `D <path>` remains, return to Phase 3.
```
Different tools behave differently (filter-branch synchronized index+worktree
in the lab on git 2.39.5; filter-repo is expected to leave the old checkout
stale), so the status check + surface sweep are the arbiter either way.

## Phase 4 — Verify (the arbiter)

```sh
# 1. Full-object inflation scan, per ODB: expect exit 1 (no match), ZERO output.
#    (cat-file --batch-all-objects never consults refs, so it is already
#    veil-proof; GIT_NO_REPLACE_OBJECTS is needed only for rev-list/log/fsck.)
# Mirror-image exit facts: fsck exits 0 WHILE reporting objects; grep exits 1
# while saying CLEAN and 2 when the scan itself ERRORS. Consume the code
# explicitly — a bare grep in a `set -e` script terminates the script on a
# clean result and silently skips every later check (observed in lab):
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' |
  while read h t; do case $t in blob|commit|tag) git cat-file -p "$h";; esac; done |
  grep -aFq 'secret['
case $? in
  0) echo "LEAK PRESENT (must clean)"; exit 1;;
  1) echo "CLEAN";;
  2) echo "SCAN BROKEN (grep error)"; exit 1;;
esac

# 2. Integrity: expect NO output (do not trust exit codes)
git fsck --full; git fsck --unreachable
GIT_NO_REPLACE_OBJECTS=1 git fsck --full

# 3. Preservation: diff against Phase-0 snapshot
git status --porcelain                   # clean (no D/?? leftovers)
git log --format='%s'                    # messages identical
git for-each-ref                         # only legitimate refs/tags remain
git show HEAD:<legit-file>               # contents identical

# 4. Non-ODB stragglers (object scans cannot cover these)
ls -R .git/lost-found 2>/dev/null && rm -rf .git/lost-found
grep -raIF 'secret[' .git/logs/ 2>/dev/null # empty after reflog expire
ls .git/refs/original 2>/dev/null        # absent after filter-branch cleanup

# 5. Plaintext surface sweep: worktree, real index, all .git text files.
#    -r recursive; -a treat binary as text BUT -I skip binary files, so
#    zlib-compressed loose/pack files are ignored and only real plaintext
#    surfaces are checked. Expect exit 1 (no match).
grep -raIF 'secret[' /app/repo
```
Items 1 + 5 together are the complete every-location inventory: every ODB
byte (refs-independent) plus every plaintext surface — whichever tool moved
which files, the pair catches it.

## Evidence ledger

The falsification ledger (four confidence levels: v01-direct, scratch-lab
direct, teacher-taught, reasoned extrapolation) moved to
`references/evidence.md` to keep this file load-efficient. It records every
claim, its experiment, and its git version, including the merge-topology
lab, the stale-index remedy labs, the alternates probe, and both
fresh-solver evals. Failure modes below remain operational (they read
observables, they are not narratives). Audit rule: a command block is
either verbatim-executed (ledger entry) or explicitly labeled unexecuted —
never ship command text that has not run or been flagged.

## Failure modes to remember

- **Unexecuted command text is a bug class, not a typo class.** Command
  blocks carry the same evidence levels as claims: every verbatim command in
  this Skill was executed in v01, a lab, or the fresh-solver eval — anything
  not yet executed must be labeled as such. Iteration-2 caught two live
  offenders this way: `--msg-filter 'grep -avF "secret["'` aborted the
  rewrite ('msg filter failed' — a `grep -v` with an all-matching input
  outputs nothing and exits 1, which filter-branch treats as failure), and
  tag-name-filter semantics were over-claimed until the tagged labs ran.
- **A clean scan under `set -e` (or `&&` chains) silently kills the rest of
  the script**: grep exit 1 = clean means "pipeline failed" to the shell.
  Always consume scan exit codes explicitly (`case $?` form above); never
  chain a clean scan into further verification steps with `&&`.
- **Unescaped `[`/`]` in grep patterns → "Invalid regular expression", exit
  2** — an exit code that is a *tool error*, never a no-match result; a scan
  that errors can silently certify a leaking repo. Always `grep -F` (fixed
  string) when the secret format contains metacharacters, and treat exit 2
  as failure, exit 1 as clean, exit 0 as found. (Found by the iteration-1
  fresh-solver eval: the frozen skill's `grep -a 'secret['` failed twice.)
- Trusting `fsck`'s exit code (it is 0 even with a report) → use empty output.
- `grep -r` on the repo → certifies a leaking repo; only inflated objects count.
- Certifying a rewrite from the tool's documented epilogue → filter-branch
  and filter-repo differ on checkout synchronization; always end with
  `git status --porcelain` clean + surface sweep zero, applying
  `git rm --cached --ignore-unmatch <p> && rm -f <p>` for `A`/`??` leftovers
  (verified); a surviving `D <p>` after the remedy is NOT a leftover — it
  means the path is still in HEAD and that ref was never rewritten (return
  to Phase 3).
- `git gc --prune=now` without `reflog expire` → reflog-referenced objects
  survive and reflog plaintext survives.
- `git replace -d` alone → can *resurrect* the leak (veil direction); always
  re-scan after removing replace refs.
- Deleting `--lost-found` copy missed → prune proof copy outside the ODB.
- Cleaning the parent only → submodule/nested ODB leak survives.
- **A commit message printed TWICE by `git log --all` (or a scan that finds
  the leak right after a rewrite) is the visible signature that the
  completion step has not run** — `refs/original` and reflogs still anchor
  the old tainted history. Finish the row (remove `refs/original`, expire
  reflogs, prune), then re-scan: post-completion CLEAN is the definitive
  observation (merge lab, iteration 3).
- **Pruning inside a repo with alternates never touches objects physically
  housed in another ODB** — a `clone --shared`/`--reference` clone cannot
  remove the origin's objects from inside the clone (verified: clone-side
  `prune --expire=now` left the alternate-owned blob intact). `fsck` in the
  clone still reports them; the cleanup must run in the owning repo, or the
  alternates link must be removed first.
---
name: git-leak-recovery
description: >
  Recover a secret that was accidentally committed, staged, or stashed in a Git
  repository (from history, reflogs, stashes, replace refs, tags, worktrees,
  submodule object databases, unreachable objects, or alternate stores), then
  remove every remaining trace while preserving legitimate branches, files,
  tags, and commit messages. Enforces a strict recover -> inventory -> cleanup
  -> verify gate: cleanup is never allowed before the secret is extracted to a
  path outside the repository and format-checked, and final verification uses
  an object-complete scan (git cat-file --batch-all-objects --batch over every
  object database) plus a filesystem sweep of gitdirs and every worktree root,
  because plain grep cannot see into compressed loose objects or packfiles and
  object cleanup alone never proves the value is gone from working-tree files.
---

# Git Leak Recovery

## 1. Family definition and when to use

A task in this family presents a Git repository containing a leaked secret value
(flag/credential/token string, typically a recognizable format like
`secret[...]`). The task always has the same three requirements:

1. **Recover** the secret (write it to a file outside the repo).
2. **Clean up** the secret so it cannot be found anywhere in the repo.
3. **Preserve** irrelevant files, branches, tags, and commit messages.

Variation axes from spec.yaml:

| axis | v01 anchor (simplest cell) | family variations to expect |
|---|---|---|
| secret_location | blob added to index, removed from index, worktree-deleted -> unreachable dangling blob | several staged blobs, live/dropped stash, amended or reset-away commit, deleted branch, replace ref, submodule object DB, **reachable history**, annotated tag |
| repo_complexity | 2 commits on 1 branch | independent branches, tags, merges, nested Git repo, dozens of commits, both reachable and unreachable history |
| cleanup_scope | expire reflogs + prune unreachable objects | drop stash, remove replace/backup refs, delete only-tainted tags, expire reflogs, rewrite reachable history while preserving legitimate content, prune, check every object database |

The v01 surface procedure ("find the dangling blob, delete it") generalizes to
only one cell of the family. The reusable method is the ordered pipeline below
plus a holder -> cleanup mapping; the pipeline is the invariant.

## 2. Invariant pipeline — hard-ordered gate

```
RECOVER  ->  (gate: secret outside repo + format-checked)  ->  CLEANUP  ->  VERIFY
```

* **Never run any destructive command before recovery passes.** After
  `git gc --prune=now` the only copy of the secret has been deleted from disk
  and the task is unrecoverable. This is an invariant stated by the task family
  definition itself ("Recovery must happen before destructive cleanup").
* **Gate check:** extracted file exists, is **outside the repo**, is non-empty,
  and matches the expected secret format (e.g. `grep -a -o -E 'secret\[[^]]*\]'`).
  Refuse cleanup and verification when the gate has not passed.
* INVENTORY is read-only and may run at any time (it is what locates the leak);
  only destructive actions are gated behind RECOVER.
* Never write the recovered value back inside the repository before verification
  passes.

The companion script `scripts/leak-recovery.sh` mechanizes the gate: `recover`
exits non-zero unless the extraction validates; `cleanup` and `verify` refuse to
run unless the gate marker is valid.

**Where the skill resources live inside the task container (verified in a
fresh-solver run):** the package is mounted read-only at `/skill` — SKILL.md at
`/skill/SKILL.md` and the script at `/skill/scripts/leak-recovery.sh`.
Host-workspace paths (e.g. `.../train-solvers/.../workspace/skill/...`) are
**not** visible inside the container; attempting to run the script at such a
path fails with `exit 127`. If the mount point is unknown:
`find / -name 'leak-recovery.sh' -not -path '/proc/*' 2>/dev/null`.

## 3. Phase 0 — INVENTORY (read-only)

Run in the main repo **and in every object database in scope** (see below):

| holder | command |
|---|---|
| all refs (heads, tags, remotes, stash, replace, original, backup) | `git for-each-ref` |
| stash entries | `git stash list` |
| reflogs (head + every branch; branch reflogs survive branch deletion as files under `<gd>/logs/refs/heads/` until expired) | `git reflog --all`; `ls <gd>/logs` |
| linked worktrees (each has its own gitdir/index/reflogs) | `git worktree list --porcelain` |
| submodule object DBs (`<gd>/modules/<name>` — a separate object database the superproject's scans do NOT cover) | `ls <gd>/modules/` |
| alternate object stores | `cat <gd>/objects/info/alternates` |
| unreachable objects (dangling blobs/commits/trees) | `git fsck --full --no-reflogs --unreachable` |
| reachable content + current index | `git rev-list --all --objects`; `git ls-files -s` |
| **index entries of EVERY gitdir** (main + worktrees: staged blobs are gc roots and survive `gc --prune=now` — verified) | `git --git-dir=<gd> -c core.worktree=<gd> ls-files -s` |
| **working-tree files of EVERY worktree** (tracked + untracked; a value can sit on disk while all Git storage is clean) | `git worktree list --porcelain` (`worktree <path>` lines) + `grep -r -a -E '<pattern>' <path> --exclude-dir=.git` |

Scope discovery (also implemented in the script): main gitdir via
`git -C <repo> rev-parse --absolute-git-dir`, linked-worktree admin dirs via
`ls <gd>/worktrees/*/` (**`git worktree list --porcelain` prints no `gitdir`
lines on git 2.39 — observed; enumerate the admin dirs directly**, they are
real gitdirs with their own index/logs), and submodule gitdirs under
`<main>/modules/`.

**Never use `git fsck --lost-found` during investigation.** For dangling
*blobs* it materializes the blob's content as a **plaintext file** at
`<gd>/lost-found/other/<sha>` — a second cleartext copy of the secret that
survives `git gc --prune=now`. Verified in v01: running it once created
`.git/lost-found/other/52d18a…` containing the secret; after pruning the
object the plaintext copy was still there. If `--lost-found` was ever used,
cleanup must delete the directory and VERIFY must sweep it.

## 4. Phase 1 — RECOVER (the gate)

**Locate** every object whose raw content matches the secret format:

```sh
git -C <repo> cat-file --batch-all-objects --batch | grep -a -E '<pattern>'
```

* `--batch-all-objects` enumerates **all** objects: loose + packed +
  alternate-store (verified: with an alternates link, repo B's scan found the
  leak living in repo A's object store). It also covers commit/tag messages.
* Use the **full-format pattern** (`secret\[[^]]*\]`), never a bare substring:
  a bare `secret` matched my own commit message "addsecret" (verified false
  positive). The task hint often states the exact format and that only one
  string matches it.
* Get the `<sha> <type> <size>` header of each hit with `grep -a -B1`, or run
  the script's `locate`, which pairs every hit with its object identity
  (`<gitdir> | <sha> <type> <size> | <matching line>`) after per-object
  confirmation — directly actionable for cleanup decisions.
* Repeat for every object DB in scope (worktree gitdirs, submodule gitdirs).
  For a submodule gitdir whose worktree was removed, `git --git-dir=<gd>`
  operations fail with `fatal: cannot chdir to '../../sub'` (verified). Fix
  without mutating config: `git --git-dir=<gd> -c core.worktree=<gd> <cmd>`.

**Extract:**

* blob hit -> `git cat-file blob <sha> > <outfile>` (outfile OUTSIDE the repo)
* commit/tag hit -> the leak is in the message; record it (holder is history)
* stash holder -> `git stash show -p stash@{N}` or cat-file the stash commit's
  matching blob (verified)
* multiple blob hits (several staged versions, variants of the value) -> write
  each to `<outfile>.1`, `<outfile>.2`, ... — do not stop at the first hit

**Gate validation:** at least one extracted file is non-empty and matches the
pattern, and (when the hint/instance defines uniqueness) the total match count
across the repo equals the expected value. Only then may CLEANUP start. The
script records a gate marker (`<outfile>.gate` containing the pattern) and
refuses `cleanup`/`verify` without it.

**Content fidelity:** extraction keeps the blob's exact bytes, including a
trailing newline when the blob has one (v01's secret blob was 30 bytes =
29-char value + `\n`); the external grader accepted the file as written
(iteration-1 eval, `test_flag_file_exists_and_correct` passed). If a grader is
expected to compare exact content without the newline, write only the matched
value: `printf '%s' "$(grep -a -o -E '<pattern>' <outfile> | head -1)" > <outfile>`
before finishing.

## 5. Phase 2 — CLEANUP: holder -> least-destructive action

Evidence key: **[E]** = directly exercised on synthetic repos during skill
development, **[L]** = Teacher domain knowledge, **[R]** = reasoned
extrapolation (mechanism known, local environment lacked the tool; future
verification procedure in §9).

| holder found in inventory | action | evidence |
|---|---|---|
| unreachable blob/tree/commit (staged-but-never-committed, deleted branch, reset-away, amend-away) | expire reflogs, then prune (below); confirm `git cat-file -e <sha>` fails after | E |
| stash | `git stash drop <stash>` for tainted entries **before** expiring reflogs, then expire + prune (a live stash stays pinned by `refs/stash` — gc will not remove it; conversely, once your reflogs are expired, `git stash list` reads 0 and `git stash drop` may need `git update-ref -d refs/stash` instead — verified) | E |
| index (main **or** linked worktree) | staged-but-uncommitted blobs are GC ROOTS: they survive `reflog expire` + `gc --prune=now` (verified: blob survived main-repo and worktree gc; fsck even reports it unreachable while it exists). Unstage first: `git rm --cached <file>` (or `git reset`); for a linked worktree run `git -C <worktree> rm --cached <file>` (its index lives at `<gd>/worktrees/<id>/index`). Then rerun the mechanical steps; **`git rm --cached` leaves the file itself in the worktree (git semantics — verified: the staged-secret synth still had `s.txt` on disk after unstaging) — delete the leak-carrier file (`rm <file>`) or scrub the value out of legitimate files (edit; cf. inline `--replace-text` row) BEFORE rerunning cleanup/verify.** The script reports both the still-pinned object and the still-present worktree copy until removed — verified | E |
| replace ref | `git replace -d <sha>`; refs/replace removed; the tainted object then becomes unreachable and is pruned | E |
| reflog-only commit (reset/amend) | `git reflog expire --expire=now --all` (covers branch reflogs of deleted branches kept under `logs/refs/heads/`), then prune | E |
| deleted branch | branch reflog keeps commits reachable; expire `--all` clears it (verified: `logs/refs/heads/<name>` removed), then prune | E |
| submodule object DB | re-run the whole pipeline with the submodule gitdir; the superproject's scans never see the sub DB (verified: superproject batch scan = 0 hits while sub-DB scan = 1) | E |
| reachable history (secret committed; tags/branches point at tainted commits) | history rewrite — VERIFIED with filter-branch: `git filter-branch --index-filter 'git rm --cached --ignore-unmatch <file>' -- --all` (ran cleanly on a 2-branch repo; both refs rewritten, commit messages preserved, legit files untouched), then `rm -rf <gd>/refs/original` (filter-branch backup — verified present after rewrite, removal required), expire reflogs, prune; re-point tainted annotated tags onto rewritten commits. **After the rewrite, check the worktree: the rewritten-away file is gone from the new tip, but a leftover copy may remain on disk (delete it if it is the leak carrier), and `git status` will show it as deleted/untracked until then.** Note: avoid bare `-q` combined with `--prune-empty` (git 2.39 dumps usage — observed); plain form works. `git filter-repo --invert-paths --path <file>` is the preferred tool when installed (**not installed in this environment**) and preserves messages/other branches by default | E (filter-branch) / R (filter-repo) |
| tainted annotated tag (message leaks, tag must survive) | recreate the tag with a clean message (`git tag -a <tag> <sha> -m 'clean message'` after `git tag -d`; the tag object is a gc root while its ref exists — verified: cleanup exits non-zero until `git tag -d`, then prune removes it, other tags untouched); if the tag itself is expendable, `git tag -d <tag>` is enough | E |
| inline value in many files (no clean file boundary) | filter-repo `--replace-text` (or manual rewrite), then prune | R |
| alternates | the leak physically lives in another repo's object DB; cleanup must run there (`git --git-dir=<owning-gd>`), though the batch scan of the linked repo sees it | E |

**Universal post-step, regardless of holder:**

```sh
git -C <repo> reflog expire --expire=now --all
git -C <repo> gc --prune=now
rm -rf <gd>/lost-found            # if --lost-found was ever used (or prophylactically)
```

* Order matters: **expire reflogs BEFORE pruning** — reflog entries keep old
  commits reachable for 90 days (gc.reflogExpire) and protected objects survive
  pruning.
* **Stash caveat (verified):** `git stash list` reads the stash *reflog*; after
  `reflog expire --expire=now --all` it reports 0 while `refs/stash` still pins
  the stash commit (and its leaked blobs) — gc will NOT prune them. Drop
  tainted stashes **before** expiring reflogs; once expired, remove the ref with
  `git update-ref -d refs/stash`. Count stashes with `git for-each-ref refs/stash`,
  not `git stash list`, after expiry.
* **Index caveat (verified):** any staged-but-uncommitted secret is pinned by
  the index (main or linked-worktree) and survives `gc --prune=now` even
  though fsck lists the object as unreachable. Unstage (`git rm --cached` /
  `git reset`, per worktree if needed) BEFORE expecting pruning to remove it;
  the script's cleanup reports the object as "STILL present" so the unstage
  step is unmissable.
* `--prune=now` is essential: plain `git gc` only prunes objects older than
  `gc.pruneExpire` (default 2 weeks); a freshly-created dangling blob would
  survive it.
* Repeat expire+gc+lost-found removal in **every** gitdir in scope (worktrees,
  submodules); `rm -rf` the lost-found directory in each.
* Container note: `git gc --prune=now` may refuse if a stale gc lock exists
  (`<gd>/gc.pid`); remove the stale lock file and retry.
* **Cleanup exit semantics (revised after iteration-1 evaluation):** the
  script's `cleanup` runs the mechanical steps, then re-locates and reports
  two lists — "matches found BEFORE cleanup" (informational; includes
  objects the mechanical steps were expected to remove) and "matches STILL
  present AFTER cleanup" (a discriminating signal: it lists exactly the
  holder-pinned matches that need `stash drop` / `tag -d` / `replace -d` /
  `refs/original` removal / history rewrite). If anything still matches,
  `cleanup` **exits non-zero** and prints the ADVICE block; run the
  holder-specific action and rerun `cleanup` until it exits 0, then `verify`.

## 6. Phase 3 — VERIFY (object-complete)

"Found nowhere in the repo" spans THREE disjoint storage spaces; verify closes
all three (plus preservation):

1. **Object databases** (loose + packed + alternates; every gitdir in scope)
   -> checks 1-2 below.
2. **Gitdir non-object files** (`logs/`, `refs/`, `index`, `COMMIT_EDITMSG`,
   `lost-found/`, worktree admin dirs) -> check 3 below.
3. **Working-tree files, tracked and untracked, of every worktree in scope**
   -> check 3b below. This is the space object-level cleanup alone never
   touches: `git rm --cached` deliberately leaves the file on disk (git
   semantics, not a bug), history rewrites can leave a stale checkout copy,
   and an untracked leftover file matches the pattern while every object scan
   is clean. The family contract "cannot be found anywhere in that repo"
   fails in that state.

Run every check in **every object DB in scope**; the whole verify is
meaningless if a submodule DB was skipped — verified: v01-style superproject
scan missed a secret whose only copy sat in `.git/modules/sub`.

**1. Object graph:** `git --git-dir=<gd> fsck --full --no-reflogs --unreachable`
must produce **no output**. Do not trust the exit code: fsck exits 0 while
listing unreachable objects (verified). `--no-reflogs` keeps expired reflog
files from re-marking objects reachable.

**2. Object content (the airtight check):**

```sh
git --git-dir=<gd> cat-file --batch-all-objects --batch | grep -a -E '<pattern>'
```

must match **nothing**. Required because:

* `grep -r` over `.git` cannot decompress zlib loose objects and cannot read
  packfiles at all (verified: v01's secret was invisible to a plain
  `grep -r secret .git` while sitting in a loose object).
* `git grep` only searches tracked worktree files.
* `--batch` emits raw object content including commit and tag messages; this
  is the only way to assert "nowhere" over *every* object.
* Use `--batch` (emits content), not `--batch-check` (metadata only).
* `grep -a` treats the stream as text (binary blobs included).
* After `git gc --prune=now` all remaining objects may be packed; the same
  command still enumerates them all (verified: pack-only repo, 6/6 objects
  listed after gc).

**3. Filesystem sweep of gitdirs (belt-and-braces for plaintext materializations):**

```sh
grep -r -a -l -E '<pattern>' <gd>
```

must match nothing. This covers non-object files a batch scan never reads:
`lost-found/`, `logs/`, `refs/` (e.g. stash ref files), `index`, `COMMIT_EDITMSG`,
`MERGE_MSG`, `worktrees/<id>/`, `modules/**`. Use the precise format pattern
(§4) to avoid false positives like "addsecret". Also sweep nested/embedded
repos: `find <repo> -name .git` and run the checks against each discovered
gitdir.

**3b. Filesystem sweep of every worktree root (the plaintext-on-disk space):**

```sh
for wt in $(git -C <repo> worktree list --porcelain | sed -n 's/^worktree //p'); do
  grep -r -a -l -E '<pattern>' "$wt" --exclude-dir=.git
done
```

must match nothing (and when it does match, verify exits non-zero naming the
file). `--exclude-dir=.git` keeps gitdirs out (content there is covered by
checks 2-3), and the recovered outfile lives outside the repo so it cannot
self-trigger. This check is what makes "several staged blobs" / "reachable
history" cells pass honestly: after `git rm --cached` or a history rewrite,
the value may still sit in a worktree file — verified: iteration-3 staged-
secret tests exited 0 from verify while `s.txt`/`w.txt` still held the secret
on disk; the revised verify fails (exit 1) until the file is removed, then
passes.

**4. Preservation:** `git status --porcelain` clean (or only intended changes);
`git log --oneline --all` matches the legitimate history; README/flag files
byte-identical to before; `git for-each-ref` equals the pre-cleanup inventory
minus the tainted holders; recovered outfile outside the repo still intact and
matching.

## 7. Traps and failure modes (each observed unless marked [R])

1. **lost-found plaintext trap** — `git fsck --lost-found` writes blob contents
   to `<gd>/lost-found/other/<sha>`; survives pruning. Remove the dir; never
   use `--lost-found`. [E]
2. **Plain `git gc` without `--prune=now`** — default expire 2 weeks; young
   unreachable objects survive. [E/L]
3. **Pruning before expiring reflogs** — reflog-reachable objects are not
   removed. Expire first. [E/L]
4. **`grep -r` on `.git`** misses compressed loose objects and packs; only
   `cat-file --batch-all-objects --batch` sees them. [E]
5. **Bare-substring patterns** cause false positives and can mask a real leak
   location; use the full format. [E]
6. **fsck exit code** is 0 even when it prints dangling objects — parse
   output. [E]
7. **Submodule/worktree DBs invisible from the main repo** — scan each gitdir;
   use `-c core.worktree=<gd>` when the linked worktree is absent. [E]
8. **Replace refs** do not remove objects — the tainted object stays in the DB
   (batch scan still sees it) until `git replace -d` + prune. [E]
9. **filter-branch leaves `refs/original/` backups** that keep rewritten-away
   objects reachable; delete them, then expire + prune. [L/R]
10. **Recovered file written inside the repo** — the secret then lives in the
    worktree/`.git`; always extract outside the repo. [invariant]
11. **Alternates** — the leak may physically live in another repo's DB; batch
    scan sees it, but prune must run in the owning repo. [E]
12. **Stash hidden after reflog expiry** — `git stash list` shows 0 while
    `refs/stash` still pins the leaked stash; drop the stash before expiring
    reflogs (or `git update-ref -d refs/stash`). [E]
13. **Index pins staged blobs against pruning** — a staged-but-uncommitted
    secret survives `reflog expire` + `gc --prune=now` in both the main repo
    and linked worktrees (fsck may still call it unreachable — it exists!
    batch scan finds it). Unstage before pruning. [E]
14. **`git worktree list --porcelain` prints no `gitdir` lines on git 2.39**
    — linked-worktree gitdirs would silently drop out of scope; enumerate
    `<gd>/worktrees/*/` directly (each admin dir is a real gitdir with its own
    index/logs). [E]
15. **`git filter-branch -q` + `--prune-empty` dumps usage on git 2.39** —
    use the plain invocation; the gotchas warning on stderr is benign. [E]
16. **Object cleanup ≠ worktree cleanup** — `git rm --cached` leaves the file
    on disk (git semantics), and history rewrites can leave a stale copy in a
    worktree; the value can sit in a working-tree file while every object DB
    and gitdir is clean. Verify sweeps every worktree root (tracked +
    untracked) and exits non-zero naming the file; cleanup reports
    "worktree plaintext copies STILL present" until removed/scrubbed. [E]

## 8. Worked example — v01 (anchor member; instance facts bracketed are NOT general method)

Instance: repo at [/app/repo], two commits [d3185d4, 1764fff] on master, a
secret was `git add`-ed, removed from the index, worktree-deleted -> dangling
blob [52d18a091cd9755bacb8eaccab2882a24b080dc7]. Secret format `secret[...]`,
exactly one such string.

1. **Inventory (read-only):** `git fsck --full --no-reflogs --unreachable`
   -> `unreachable blob 52d18a0…`. No stashes, no extra refs, one worktree.
2. **Recover (gate):** `git cat-file blob 52d18a0… > /app/secret.txt` ->
   `secret[lost_and_found_in_git]`; `grep -a -o -E 'secret\[[^]]*\]'` matches
   once; repo-wide match count = 1. Gate passes.
3. **Cleanup:** `git reflog expire --expire=now --all && git gc --prune=now
   && rm -rf .git/lost-found` (the `rm` because investigation had run
   `--lost-found`, which materialized the secret at
   `.git/lost-found/other/52d18a0…`).
4. **Verify:** fsck lists nothing; batch scan `git cat-file --batch-all-objects
   --batch | grep -a -E 'secret\[[^]]*\]'` = 0 hits (post-gc, all 6 remaining
   objects live in one pack — the scan reads them); `grep -r -a -l` over
   `.git` = no hits; `git status --porcelain` empty; `git log --oneline --all`
   unchanged (2 commits); README bytes unchanged; `/app/secret.txt` intact.

## 9. Evidence ledger (epistemic status of key claims)

* **[E] v01 direct:** dangling-blob recovery, lost-found plaintext
  materialization, expire+prune removal, pack-aware batch scan, fsck exit-code
  behavior, substring false positive.
* **[E] synthetic variants (built and cleaned during development):** live
  stash; reset-away commit kept alive only by reflog; deleted branch with
  surviving branch reflog; replace ref (object persists until `replace -d` +
  prune); submodule object DB invisible to superproject scans (plus
  `core.worktree` override when the submodule worktree is gone); alternates
  store visible to `--batch-all-objects`.
* **[L] Teacher domain knowledge:** reflog/gc expire semantics, filter-repo
  as the history-rewrite tool, `refs/original` cleanup, stash-stack handling,
  multi-DB verification requirement.
* **[R] Reasoned extrapolation (not locally executable):** filter-repo
  rewrite flow (tool absent from this environment), annotated-tag message
  cleanup, inline `--replace-text` rewrites, worktree-gitdir variant.
  Future verification procedures below.
* **[E] Fresh-solver evaluation (iteration-1 feedback):** a fresh session
  using the frozen Skill solved a reset v01 in 11 tool calls / one attempt;
  the external grader's six checks passed: flag file exists and correct; no
  secrets in commits; good commits preserved; no secrets in unreachable
  objects; lost-found cleaned; no secret in any git object — i.e. the grader
  normalizes exactly the pipeline's verification model. The trajectory also
  exposed three frictions, all fixed in iteration 2: (1) the solver tried the
  host skill path inside the container (exit 127) before finding the `/skill`
  mount — now documented in §2; (2) the cleanup message "objects still
  matching" was a pre-cleanup locate printed after cleanup and read as a
  post-cleanup failure — cleanup now labels pre/post lists explicitly and
  exits non-zero only when matches genuinely remain; (3) `locate` output
  lacked the object SHA/type — now each hit is confirmed per-object and
  printed as `<gd> | <sha> <type> <size> | <line>`.
* **[E] Fresh-solver evaluation (iteration-2 feedback):** the revised Skill
  produced a friction-free one-shot solve (11 tool calls, 6/6 grader tests):
  /skill found immediately, locate with sha/type, cleanup pre/post lists
  understood correctly, verify exit 0. Validates the iteration-2 fixes.
* **[E] Variant mechanism tests (iteration-3, synthetic repos T1-T6):**
  reachable-history rewrite via filter-branch on a 2-branch repo (both refs
  rewritten, `refs/original` present then removed, messages preserved,
  legit files untouched, final batch scan 0 — and a bare-substring grep
  re-demonstrated the "addsecret"-class false positive on a legitimate commit
  message "add feature with secret"; cleanup exits 1 while the tainted
  commit remains reachable, 0 after rewrite+prune); annotated tag with leaky
  message (locate reports the `tag` object; cleanup exits 1 while
  `refs/tags/<name>` exists; `tag -d` + prune removes it, sibling tags
  preserved); multiple staged blobs (recover emits numbered outfiles
  `<outfile>` + `<outfile>.2`, gate passes on 2 candidates, prune removes
  both); linked worktree (dangling blob created from a worktree is found via
  the SHARED object store — but the worktree's own gitdir was NOT discovered
  because porcelain lacks `gitdir` lines: scope fixed to enumerate
  `<gd>/worktrees/*/`; index pinning: a blob staged in the main or worktree
  index survives `reflog expire` + `gc --prune=now` while fsck reports it
  unreachable — unstage (`git rm --cached`) is required before pruning).
* **[E] Worktree-file verification gap (iteration-3 follow-up, issue-3):**
  the staged-secret synthetics above ended verify exit 0 while the unstaged
  file still carried the secret inside the repo directory (`/tmp/I1/s.txt`,
  `/tmp/W1wt/w.txt` were found by plain grep after "verify PASSED") — an
  object-complete verification that ignores working-tree files is not
  "anywhere in the repo". verify now adds a failing worktree-root sweep
  (`grep -r -a -E '<pattern>' <worktree> --exclude-dir=.git`, roots from
  `worktree list --porcelain` `worktree` lines) and cleanup reports worktree
  plaintext copies with delete/scrub advice; discriminating runs: staged-
  secret synth with file present -> verify exit 1 naming the file, after
  `rm` -> exit 0; linked-worktree repeat behaves identically; v01 regression
  unchanged (recover/cleanup/verify 0/0/0, README sha f7488e6…, log intact).

## 10. Future verification procedures for unexercised variants

Build a synthetic repo, run the pipeline, assert via §6 checks. Status: the
reachable-history (filter-branch), annotated-tag, multiple-staged-blobs, and
linked-worktree procedures below were all EXECUTED in iteration-3 testing
(marked verified); still unexercised locally:

* **filter-repo rewrite (tool absent here):** when installed, run
  `git filter-repo --invert-paths --path <file>` and assert the same
  properties as the filter-branch flow above (batch scan empty; messages via
  `git log --format=%s` unchanged; refs/original absent — filter-repo does
  not create it; other branches preserved).
* **Inline `--replace-text` rewrite:** filter-repo `--replace-text` for a
  secret embedded in many files with no clean file boundary; assert the value
  is gone from `git log -p --all` and the batch scan, and file content is
  otherwise unchanged.
* **Worktree-local ref leak:** commit a secret on a branch created from a
  linked worktree and delete it without merging; assert `refs/heads/<name>`
  gone, reflogs of both gitdirs expired, batch scan empty.
* **Nested repo:** a `.git` directory inside the worktree; discover via
  `find <repo> -name .git`; run the full pipeline per nested gitdir (script
  verify already sweeps nested gitdirs).

Verified procedures (keep as reference):

## 11. Companion script

`scripts/leak-recovery.sh <repo> <command> …` (mounted at
`/skill/scripts/leak-recovery.sh` inside the task container) implements the
gate: `inventory`, `locate`, `recover <outfile> <pattern>`, `cleanup <outfile>
<pattern>`, `verify <outfile> <pattern>`. It hardcodes no instance facts —
repo, outfile, and pattern are always parameters. `cleanup` refuses to run
unless `recover` produced a valid outfile + gate marker, and exits non-zero
when matches still exist after the mechanical steps (the printed list shows
which holders need deliberate action). `verify` exits 0 only when all three
checks pass in every discovered object DB **and** no worktree file matches
(the worktree-root sweep is a hard failure, naming the offending file).
Holder-specific decisions that
affect legit content (stash drop, tag delete, history rewrite) are never made
by the script — they are printed as advice for the agent to execute
deliberately, since only the agent can judge what is "tainted" vs
"legitimate" in a given instance.
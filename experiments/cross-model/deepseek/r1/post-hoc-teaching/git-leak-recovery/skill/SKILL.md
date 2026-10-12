---
name: git-leak-recovery
description: >-
  Recover a leaked secret[...] token from anywhere inside a Git repository —
  dangling staged blobs, stashes (live or dropped), amended/reset-away commits,
  deleted branches, replace refs, reachable history, annotated tags, commit
  messages, alternate object stores, or nested/submodule object databases —
  write it to /app/secret.txt, then purge every trace of it from all object
  databases, refs, reflogs, and worktree files while preserving all legitimate
  branches, files, tags, and commit messages. Mechanical phases are executed by
  the packaged script; Phase 2 (classification and history rewriting) is a
  human decision layer.
---

# Git Leak Recovery

## When to use
A task states that a secret (format `secret[...]`) was accidentally added/staged/committed
in a repository and must be (1) recovered to a file (typically `/app/secret.txt`) and
(2) removed so it "cannot be found anywhere in that repo", while (3) irrelevant files,
branches, tags, and commit messages stay untouched. The repo is usually `/app/repo`.

The leak may live in *any* Git storage or metadata location. **Never assume the leak is
only a dangling blob.** The script handles every case; follow the full loop below.

## Package
- `scripts/git-leak-recovery.sh` — executable Phase 0 (discovery/snapshot/baselines),
  Phase 1 (guarded union scan + recovery), Phase 3 (per-DB reflog expiry + prune),
  Phase 4 (guarded verification). This is the validated, shipped artifact — run it;
  do not re-type bash from memory.
- This file — the decision layer: Phase 2 classification, history rewriting, and the
  contracts the script enforces.

## Quick start (the loop)

**Where the package lives**: in the task container the skill package is mounted
read-only at `/skill` (i.e. `/skill/scripts/git-leak-recovery.sh` and `/skill/SKILL.md`).
The metadata file path on the host is NOT reachable from `task_shell` — do not waste
calls trying it. Prefer the package-relative `bash scripts/git-leak-recovery.sh` when a
shell already runs from the package dir; otherwise use the absolute mount path; as a
last resort `find / -name git-leak-recovery.sh 2>/dev/null`.

```bash
# 0. (optional) detector sanity check — scratch space ONLY, never touches the repo:
bash /skill/scripts/git-leak-recovery.sh --probe

# 0b. (recommended) read-only reconnaissance BEFORE any cleanup:
bash /skill/scripts/git-leak-recovery.sh /app/repo diag
#     prints: object DBs, the token (no writes), holders per DB, and the pinning
#     state (refs beyond heads/tags, tags, replace refs, detached HEAD, holder
#     reachability with paths, status). Exit 0 = token found, 2 = none (already clean).

# 1. Run the script on the repo (snapshots to /tmp/repo.pristine automatically,
#    recovers the token to $SECRET_FILE=/app/secret.txt, expires reflogs, prunes):
bash /skill/scripts/git-leak-recovery.sh /app/repo      # write=yes (default)
#    exit 0  -> task state VERIFIED GOOD: recovered+clean, OR (re-run on an already-
#               clean repo whose deliverable exists) re-verified against the existing
#               /app/secret.txt. Script then removes its working files + snapshot.
#    exit 2  -> cannot proceed: no token in ANY object DB AND no existing deliverable
#               to re-verify (nothing to recover, nothing to verify). Re-check the
#               task hint and object-DB discovery. Nothing was written or destroyed.
#    exit 3  -> do Phase 2, then re-run: the token is still pinned by a ref/stash/tag/
#               replace ref, or verification failed. The script prints a pinning-state
#               diagnostic (see below) and KEEPS its working files/snapshot for Phase 2.

# 2. (only on exit 3) Phase 2 — classify and break pinning references, rewrite
#    reachable history. See the table below. Then re-run step 1 until exit 0.

# 3. Verification-only mode (never writes /app/secret.txt): same verifier; on a clean
#    repo it exits 0 (exact-token check if the deliverable exists, absence check
#    otherwise). Useful on the self-test copy:
bash /skill/scripts/git-leak-recovery.sh /tmp/repo.selfcheck no

# 4. The script self-cleans on exit 0 (working files + its snapshot) and creates
#    nothing on exit 2. Only manually-created copies remain — remove them so no copy
#    of the secret stays anywhere outside the repo:
rm -rf /tmp/repo.selfcheck
```

Env overrides: `SECRET_FILE=<path>` (default `/app/secret.txt`), `SNAPSHOT=no` (skip
snapshot), `SNAP=<path>` (snapshot destination). The script accepts `yes|no|diag` (or
`write=yes|write=no`) as its second argument. Run it via `bash` (the mounted copy is
not executable).

## What the script does (mechanical phases — contracts you rely on)

**Phase 0** — snapshots `$REPO` to `/tmp/repo.pristine`; discovers EVERY object database:
main `.git`, nested `.git` dirs and submodule `.git` gitfiles (normalized to the dir
they point at), `.git/modules/*`, and every path listed in any `objects/info/alternates`
(relative entries resolved against the object dir; an `objects`-suffixed entry is mapped
to its owning gitdir). Dedupes; records baselines (status, messages, paths, tags).

**Phase 1** — guarded union scan over all DBs: `git cat-file --batch-all-objects` +
content grep with `-a` (binary blobs!) for `secret[...]`, `LC_ALL=C sort -u`. If a
**token is found**: WARNs on multiple distinct tokens (generator promises exactly one —
re-read the hint); writes the exact token (no trailing newline) to `$SECRET_FILE` and
verifies the write. If **no token is found anywhere**, the script is self-certifying
instead of dying: with an existing deliverable it re-verifies the repo against the
 token read back from it; in `no` mode it performs an absence check; only when there
is no token AND no deliverable does it fail closed (exit 2 — nothing to recover,
nothing to verify). Uses `GIT_NO_REPLACE_OBJECTS=1` so replace refs cannot hide content.

**Phase 3** — per-DB, in order: `git reflog expire --expire=now --all` then
`git gc --prune=now` (`--prune=now` is required; the default ~2-week grace would keep
the leak). Main-repo gc does NOT prune alternates — each discovered store is pruned.

**Phase 4** — guarded verification (all greps use `PAT="${SECRET:-secret[}"` so an
unset variable degrades to a real pattern, never a match-everything one):
1. Every object DB scanned for the token → must be 0.
2. `git fsck --full --no-reflogs --unreachable` per DB → no dangling/unreachable/error
   lines (`notice:`/`warning:` lines are benign, e.g. unborn HEAD in an empty
   alternate-owner store).
3. Plaintext sweep of the whole tree (`grep -raF`). On hits: removes regenerable
   metadata files (`.git/COMMIT_EDITMSG`, `.git/MERGE_MSG`, reflog logs) in **every**
   gitdir — msg-filter rewrites commits but not these files — then re-checks. Worktree
   hits are leftover leaky files: delete them and re-run.
4. **Strict status-delta contract**: every `git status --porcelain` line must be
   ` M <submodule-path>` for a real gitlink (mode `160000` in `git ls-files --stage`);
   anything else (staged deletions, modified legit files, untracked files, ` M` on a
   non-gitlink) is a FATAL. This permits the single expected delta after a nested-repo
   rewrite — exactly one ` M vendor/tool` line — and rejects any other change.
5. Message/path/tag diffs vs baselines are reported; differences are expected **only**
   after Phase 2 rewrites (redacted messages, removed leaky path, deleted tainted tags).
6. Deliverable check: `$SECRET_FILE` exists, non-empty, and equals the token in play
   (the freshly recovered one, or — on the already-clean re-run — the one read back
   from the deliverable itself, so 4e is a real comparison).

## Exit-3 diagnostics (the pinning-state hint)

When Phase 4 finds the token still present, the script prints — before dying with exit
3 — a `pinning state` block that tells you exactly what to do in Phase 2:
- `[refs beyond heads/tags ...]` — refs like `refs/stash`, `refs/notes/*`,
  `refs/bisect/*`, `refs/original/*`, `refs/replace/*` with their SHAs. **This is the
  authoritative stash/notes check**: do NOT rely on `git stash list` at this point —
  the script's own reflog expiry wipes `logs/refs/stash`, so the list would lie and
  report a live stash as absent (verified).
- `[tags]` / `[replace refs]` / `[HEAD is DETACHED]` — quick state facts.
- `[holder reachability ...]` — for every holder object: `REACHABLE -> <path>` (it is
  in some ref's history; that ref is the pin — rewrite, or delete the ref) or
  `NOT in refs -> check index (ls-files --stage), notes, refs/replace, alternate-owner
  refs` (the pin is a non-branch ref or the index).
- `[status]` lines — current working-tree state.

Worked example — the most common exit-3 variant (leak file committed on a branch):
```bash
bash /skill/scripts/git-leak-recovery.sh /app/repo      # -> exit 3, hint shows
#   ... REACHABLE -> <sha> <leaky-path> ...
# Phase 2 (in the repo, AFTER recovery):
export FILTER_BRANCH_SQUELCH_WARNING=1
git reset --hard HEAD
R=$(git replace -l); [ -z "$R" ] || git replace -d $R
git tag -d <tainted-tag>   # only tags whose OBJECT message contains the token
git stash clear            # if refs/stash was listed in the hint
git filter-branch --force --tag-name-filter cat \
  --index-filter 'git rm --cached --ignore-unmatch -- <leaky/path>' -- --all
git for-each-ref --format='%(refname)' refs/original | xargs -r -n1 git update-ref -d
# re-run:
bash /skill/scripts/git-leak-recovery.sh /app/repo      # -> exit 0
```

## Phase 2 — the decision layer (run ONLY when the script exits 3 / token is pinned)

Classify from the script's exit-3 pinning-state hint and `/tmp/leak-objects.txt` (DB+
object type per holder) — run each command in the repo/worktree that owns the DB:

| Leak location | Detection | Cleanup |
|---|---|---|
| Staged in index | `git ls-files --stage \| grep <blobsha>` | `git rm --cached -f --ignore-unmatch <path>`; `rm -f <path>` if worktree copy exists. NOTE: if a history rewrite also follows, `git reset --hard HEAD` first (filter-branch REFUSES on a dirty index) |
| Untracked worktree file | Phase-4 plaintext sweep | `rm -f <path>` |
| Live stash | `git stash list`; `git stash show -p` | `git stash drop <n>` (all: `git stash clear`) |
| Dropped stash / deleted branch / reset-away / amended-away commit (only reflog or nothing keeps it) | `git fsck --full --no-reflogs --unreachable`; object scan | no ref to delete — re-running the script (Phase 3) removes it |
| Leak reachable from a live branch or tag | `git rev-list --objects --all \| grep -F <blobsha>` | rewrite history (below) |
| Detached HEAD sitting on a leaky commit | `git symbolic-ref -q HEAD` fails | attach a temp branch first, rewrite (below), then delete it after verification — filter-branch does NOT rewire detached HEAD |
| Leaky file NAME (token inside a tree entry, e.g. `secret[x].txt`) | scan hits come from tree objects | same rewrite, removing that path (quote it for the index-filter) |
| Replace ref (hides objects from fsck/rev-list/cat-file!) | `git replace -l` | `R=$(git replace -l); [ -z "$R" ] || git replace -d $R` (bare `git replace -d $(git replace -l)` errors with no args when none exist); all scans run with `GIT_NO_REPLACE_OBJECTS=1` |
| Annotated tag whose TAG OBJECT message contains the token | `git cat-file -p <tag>^{object}` | delete ONLY that tag: `git tag -d <tag>` (spec: delete only tainted tags) |
| Tag pointing at a rewritten commit | after rewrite, tag still old | `--tag-name-filter cat` during rewrite keeps tags clean |
| Secret in a commit message | object scan shows a commit containing token | rewrite with `--msg-filter` (below) |
| notes/bisect/original/other refs holding it | `git for-each-ref` | `git update-ref -d refs/notes/...` etc. |
| Object only in an alternate store | script's Phase-1 scan lists it under the alternate dir | the script prunes it (per-DB Phase 3); if it exits 3, check the alternate-owner store's own refs |

**Rewrite reachable history** (when a live ref's history contains the leak). Prefer
`git filter-repo` if installed, else built-in filter-branch:
```bash
# ORDER MATTERS INSIDE PHASE 2 (do all of this AFTER Phase 1 recovery):
# 1) delete replace refs:   R=$(git replace -l); [ -z "$R" ] || git replace -d $R
# 2) delete TAINTED tags:   git tag -d <tainted>  — filter-branch --tag-name-filter cat
#                           would re-create the tag object with the SAME message,
#                           re-planting the token, so delete tainted tags BEFORE rewrite
# 3) drop tainted stashes:  git stash clear
# 4) hygiene BEFORE filter-branch (filter-branch REFUSES on a dirty index and does
#    NOT rewire a detached HEAD):
#      git reset --hard HEAD    # discard staged/worktree residue (safe: recovery is
#                               # done and task worktrees are scripted/clean otherwise)
#      git symbolic-ref -q HEAD >/dev/null || git checkout -q -B __leakfix HEAD
# 5) rewrite (below), 6) remove refs/original (below)

# file leak — remove the file from ALL commits, keep every commit message:
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch --force --tag-name-filter cat \
  --index-filter 'git rm --cached --ignore-unmatch -- <leaky/path>' \
  -- --all
# message leak — scrub the token from every message:
git filter-branch --force --tag-name-filter cat \
  --msg-filter 'sed "s/secret\[[^]]*\]/[REDACTED]/g"' \
  -- --all
# filter-repo alternative (if available):
git filter-repo --invert-paths --path <leaky/path> --force
```
Deliberately do **NOT** pass `--prune-empty`: the leak commit becomes empty but its
message survives, which best satisfies "commit messages remain untouched".

Remove filter-branch backups (they keep the old leaky commits reachable!):
```bash
git for-each-ref --format='%(refname)' refs/original | xargs -r -n1 git update-ref -d
```

If a `__leakfix` temp branch was created: after the script passes, delete it
(`git checkout -q --detach HEAD && git branch -D __leakfix` — git refuses to delete a
checked-out branch, so detach first; HEAD then rests detached on the clean rewritten
commit and the original ref set is restored).

Then **re-run the script** (`bash scripts/git-leak-recovery.sh /app/repo`) — exit 0 is
the gate. If it exits 3 again, inspect Phase 4's diagnostics (which DB still holds the
token, fsck output, plaintext lines, status delta) and repeat.

## Self-check and probes (never mutate the graded repo)

- **Detector probe**: `bash scripts/git-leak-recovery.sh --probe` — builds a scratch
  repo in `mktemp -d`, writes a probe blob there, and runs the exact Phase-1 pipeline;
  expects ≥1 token. Validates the detector in scratch space only; an interruption
  leaves only harmless /tmp litter.
- **Procedure self-test**: run the script on a copy of the snapshot before (or in
  parallel with) the live run:
  `cp -a /tmp/repo.pristine /tmp/repo.selfcheck && bash scripts/git-leak-recovery.sh /tmp/repo.selfcheck`
  It must exit 0. (The live run then exits 0 too.) Note the script snapshots only on
  recovery runs and self-cleans on success — `/tmp/repo.pristine` exists only while a
  recovery run needs it; if you need a pristine copy for later review, make it
  yourself (e.g. `cp -a /app/repo /tmp/repo.preview`) before cleanup.
- **Exit code is the decision function**: 0 = task state verified good (recovery
  passed, or clean repo re-verified/absence-checked); 2 = no token AND no deliverable
  (cannot proceed); 3 = do Phase 2 and re-run. Re-running the script on the live repo
  after a successful cleanup exits 0 — the victory condition is not encoded as a
  failure code.
- **Rule**: probes, snapshots, self-test copies, and baseline files are scratch-space
  citizens. `/app/repo` is touched by nothing except recovery-reads and the cleanup
  itself. Never `git hash-object -w` into the graded repo as a "positive control" —
  a timeout mid-run would freeze that probe in the graded object DB.

## Non-negotiables (learned the hard way)
1. **The token declaration must fail CLOSED.** `grep -oE ... | sort -u | head -1` yields
   the empty string when nothing matches — and an empty `SECRET` silently poisons
   everything downstream: `printf '%s' "" > /app/secret.txt` writes an empty file, and
   `grep -cF ""` matches *every line of every file*, so a "clean" verification reports
   garbage like 16/813/2. Guard with a hard FATAL **before** writing the secret file or
   destroying anything.
2. **Never declare `SECRET` from the main repo scan alone.** If the leak lives only in a
   submodule/nested/alternate object DB, the main scan legitimately returns 0. Scan the
   **union of all object databases** first, then declare.
3. **`grep -cF "nonempty"` == 0 proves absence of that string; `grep -cF ""` == anything
   proves nothing.** Always verify with `PAT="${SECRET:-secret[}"`.
4. **Snapshot before you destroy.** The script snapshots recovery runs automatically
   and self-cleans on success; keep manual preview copies in scratch space and remove
   them at the end.
5. **No self-check may mutate the artifact under test.** Probes live in scratch space.

## Family invariants (from spec/v01) vs. what varies

**Invariants (grounded by v01 + spec language):**
- Secret token format: `secret[...]`; v01's hint promises exactly ONE such string in
  the whole repo (multiple blob copies may repeat the SAME token).
- Deliverables: recovered secret file (`/app/secret.txt`) + purged repo.
- Legitimate refs/files/commit messages must survive cleanup.
- Recovery must happen BEFORE any destructive cleanup.

**Variation dimensions (spec.yaml axes):**
- `secret_location`: several staged blobs, live/dropped stash, amended/reset-away
  commit, deleted branch, replace ref, submodule object database, reachable history,
  annotated tag, commit/tag message text.
- `repo_complexity`: multiple branches, tags, merges, nested repos/submodules, dozens
  of commits, reachable AND unreachable leak copies at once.
- `cleanup_scope`: may require dropping stashes, deleting replace refs, deleting only
  tainted tags, expiring reflogs, rewriting reachable history, pruning unreachable
  objects, and running the same cleanup in every object database (including alternates)
  under the repo.

## Mechanism notes (evidence)

- **v01 verified directly** (real task, twice — original and fresh reset): dangling blob
  `52d18a09…` (file staged, unstaged, deleted). Script run: recover, expire, prune,
  verify; fsck clean; messages/README intact; `secret[lost_and_found_in_git]`.
- **Packaged script validated by executing the shipped bytes** (S1–S8 battery +
  iteration-3 axes): v01-style dangling blob → 0; binary dangling blob → 0 (without
  `-a` the token is missed); binary committed leak → exit 3, after Phase-2 rewrite → 0;
  msg leak with `.git/COMMIT_EDITMSG` residue → exit 0 (Phase 4 auto-removes the
  metadata file); detached HEAD → temp-branch flow → 0 with master untouched; dirty
  index → hygiene step → 0; nested-only leak → union discovery → 0; alternate-store
  leak → per-DB pruning → 0; nested reachable leak → exit 3, nested rewrite → exit 0
  with the ` M vendor/tool` gitlink delta allowed; **two nested repos rewritten → both
  gitlink lines allowed**; **reset-away commit (reflog-only pin) → exit 0 in a single
  pass**; **live stash → exit 3 with the hint listing `refs/stash` → stash clear →
  exit 0**; tainted annotated tag → exit 3 → `git tag -d` → exit 0; merge +
  multi-branch rewrite → merge keeps 2 parents, unaffected commits keep their SHAs;
  **clean-repo re-run (write mode, deliverable present) → exit 0 self-certifying
  verify; `no` mode without deliverable → exit 0 absence check; genuinely broken
  (no token AND no deliverable) → exit 2**; **success paths leave no snapshot and no
  baseline/holder files behind; exit-3 keeps them for Phase 2; diag leaves nothing**;
  `--probe` → OK with no residue in the graded repo; `diag` → read-only.
- **Empty-pattern fail-open (verified)**: `grep -oE ... | head -1` on no matches yields
  `""` with exit 0; `grep -cF ""` then matches every line + counts each binary file —
  the earlier "16/813/2" re-run numbers were this cascade, not a leak.
- **Alternates (verified)**: `git cat-file --batch-all-objects` lists alternate-store
  objects (detection works from the main repo), but `git gc --prune=now` in the main
  repo does NOT prune them (cleanup misses) — the worst detect-but-not-clean combo.
  Hence: alternate paths join `GITDIRS` and each store gets its own expire/gc.
- **Default `git fsck --full` does NOT report reflog-referenced leaks**; use
  `--no-reflogs --unreachable`. The all-objects content scan is the only detector that
  works in every case (replace-ref-hidden, reflog-only, stash, submodule, alternate).
- **Replace refs hide objects from fsck, rev-list AND cat-file** (git applies them during
  traversal). `git replace -l` + the all-objects scan see through; export
  `GIT_NO_REPLACE_OBJECTS=1` so every read ignores replacements. git 2.39 has no
  `--no-replace-objects` flag on `git cat-file` or `git fsck` (verified: "unknown
  option") — the env var is the only way to make them replacement-proof.
- **`git gc` without `--prune=now` retains unreachable objects ~2 weeks** (and reflog
  entries ~90 days) — always expire reflogs first, then `gc --prune=now`.
- **filter-branch rewrites branches and lightweight tags but NOT annotated tags**
  unless `--tag-name-filter cat` is given, and it leaves `refs/original/*` backups;
  it REFUSES on a dirty index; it does NOT rewire a detached HEAD; `--msg-filter` does
  not touch `.git/COMMIT_EDITMSG` — all verified; the Phase-2 ordering handles each.
- **Binary blobs**: `grep -oE` without `-a` silently misses tokens in binary blobs
  (verified) — every content scan/classification/verification grep uses `-a`.
- **`git --git-dir=` accepts a submodule `.git` gitfile** and resolves it (verified);
  discovery normalizes it anyway for dedupe.
- **`git stash list` lies after the script's reflog expiry** (verified: the stash
  reflog is wiped by Phase 3, so the list reads empty while `refs/stash` still pins
  the token). The exit-3 hint and `diag` therefore enumerate refs beyond heads/tags
  (`refs/stash`, `refs/notes/*`, `refs/bisect/*`, `refs/original/*`, `refs/replace/*`)
  directly via `git for-each-ref`.
- Reflog log files are plain text: a leaky commit subject survives object pruning until
  reflogs are expired — hence the reflog expiry + plaintext sweep.

## Failure modes & remedies
- Script exit 2 (no token anywhere AND no deliverable to re-verify) → re-check
  discovery (nested `.git` dirs/files, `.git/modules/*`, alternates paths) and re-read
  the task hint; if the repo is already clean but `/app/secret.txt` was lost, nothing
  can be re-derived — the deliverable is the only ground truth left (avoid this by
  keeping write=yes runs until exit 0).
- Script exit 3 "token still present" → read the pinning-state hint printed by the
  script (refs beyond heads/tags, tags, replace refs, detached HEAD, holder
  reachability with paths), run Phase 2 (delete the pinning ref / rewrite reachable
  history), then re-run the script. Use `... /app/repo diag` anytime you want the same
  picture read-only.
- Multiple distinct `secret[...]` tokens (contradicts the v01 hint) → STOP, re-read the
  task instructions; only then, if still ambiguous, recover the most frequent token and
  report all of them.
- Doubt the detector? `bash scripts/git-leak-recovery.sh --probe` (scratch space only —
  never `git hash-object -w` into the graded repo).
- `git filter-repo` unavailable → use the filter-branch commands; both preserve messages
  when run without `--prune-empty`.
- Warning "You said to rewrite tagged commits..." → you forgot `--tag-name-filter cat`.
- filter-branch says "Your index contains uncommitted changes" → `git reset --hard HEAD`
  (recovery is already done) and retry.
- filter-branch leaves the leak reachable with a detached HEAD → attach a temp branch
  (`git checkout -q -B __leakfix HEAD`), rewrite, then delete `__leakfix` after the
  script passes.
- Phase 4 status FATAL with a non-gitlink line → inspect `git status --porcelain`;
  revert accidental damage from the snapshot (`cp -a /tmp/repo.pristine ...`) and redo.
- Plaintext hits remain in `.git/COMMIT_EDITMSG` / `MERGE_MSG` → the script removes
  regenerable metadata in every gitdir automatically; if hits persist they are real
  worktree files — delete them and re-run.
- `git stash list` shows nothing while the hint lists `refs/stash` → the script's
  reflog expiry emptied the stash reflog; the stash is still live — `git stash clear`
  it and re-run.
- If the live cleanup breaks irreversibly mid-way: recovery is always re-derivable from
  `/tmp/repo.pristine` (re-run the script on a copy with `no` mode to see the token),
  then finish the live cleanup from the Phase 2 table.
# Evidence ledger — git-leak-recovery

Every claim in SKILL.md carries one of four levels. This file is the
falsification ledger: when a future variant contradicts an entry, patch the
entry (and only the entry) — the procedure's backbone is designed to read
observables, not beliefs. Last updated: iteration 3 (git 2.39.5 everywhere).

## Level 1 — Direct on the actual v01 task (each iteration's fresh reset)

- Unreachable loose blob found via `git fsck --unreachable` after the secret
  was staged, unstaged, and the file deleted from the worktree.
- Recovery by `git cat-file -p <sha> > /app/secret.txt` (exact bytes).
- `git reflog expire --expire=now --all && git gc --prune=now` removed it;
  `git cat-file -e <sha>` then fails.
- Post-cleanup: inflation scan clean, fsck empty, status clean, commit
  messages and README byte-identical, `.git/lost-found` absent (and
  `git fsck --lost-found` wrote no lost-found copy on git 2.39.5).
- Iterations 2 and 3 reran v01 with `grep -aF` patterns: clean on first
  pass, canonical `case $?` form consumed correctly.

## Level 2 — Scratch-lab direct (git 2.39.5)

### Detection & exit-code semantics
- `git fsck` exits 0 while reporting dangling/unreachable objects — the
  criterion is EMPTY OUTPUT, not the exit code.
- Blob-only scans MISS secrets in commit messages and annotated tag
  messages; the blob|commit|tag inflation scan catches them.
- Raw `grep -r` cannot see compressed loose/pack object content.
- Unescaped `[` in a grep pattern → `grep: Invalid regular expression`,
  exit 2 (a tool error, never a no-match result).
- A clean scan (grep exit 1) under `set -e` terminates the script and
  silently skips later checks — observed live in the iteration-2 tag lab.

### The expire+gc recipe
- Removes an unreachable object even when it is PACKED after branch
  deletion (`git repack -a -d` then `git update-ref -d`), still on git
  2.39.5 — the single recipe covers loose and packed unreachable cases.

### Stash
- A stash is a commit under `refs/stash`; `git rev-list --all` covers it;
  detected via `git stash list` / `git stash show -p 'stash@{0}'`;
  removed by `git stash drop` + expire+prune.

### Replace refs
- ANCHOR direction (tainted object is only the target of
  `refs/replace/<sha>`): `git replace -d` + expire+prune cleans.
- VEIL direction (clean replacement impersonates a tainted commit):
  `git replace -d` makes the leak REACHABLE again (observed: scan found
  `secret[veiled]` right after removal) → the reachable-history rewrite
  path is required. `replace -d` is never the end for a veil.
- `GIT_NO_REPLACE_OBJECTS=1` / `git --no-replace-objects` see through veils
  for reachability tools (`rev-list`, `log`, `fsck`); `git cat-file
  --batch-all-objects` is refs-independent and needs no flag (verified by
  finding a veiled secret with a live replace ref installed).

### Reachable-history rewrite (filter-branch, git 2.39.5)
- `--index-filter 'git rm --cached --ignore-unmatch <f>'` preserves commit
  messages and legitimate files; `refs/original` + reflogs must be purged
  afterwards or the old tainted history stays reachable (visible signature:
  `git log --all` prints the same message TWICE while `refs/original`
  exists; duplication disappears after the completion step).
- Filter-branch's epilogue `git read-tree -u -m HEAD` synchronized the real
  index and worktree to the rewritten HEAD (post-rewrite `git status
  --porcelain` clean, secret file absent from disk) — VERBATIM, git 2.39.5.
  `git filter-repo` is expected to behave differently (see Level 3).
- `--tag-name-filter cat` with REAL annotated tags:
  - tag on an UNTOUCHED commit → identity-preserving rewrite: tag name
    kept, tag object sha UNCHANGED (`v1 -> v1 same-sha`), `git show v1:...`
    dereference intact. This falsified the prediction "tag object always
    rewritten": identical sha on an untouched target is a PASS.
  - tag on a TAINTED commit → name kept, tag object REWRITTEN to point at
    the new commit (message/tagger preserved), old commit pruned after
    refs/original removal + expire+prune.
  - a secret inside an annotated tag MESSAGE survives tag-name-filter
    (verified); remedy is `git tag -d <tag>` + expire+prune.
- `--msg-filter 'grep -avF "secret["'` FAILED end-to-end: `grep -v` with an
  all-matching input emits nothing, exits 1, and filter-branch aborts the
  whole rewrite ("msg filter failed"). Verified replacements:
  `--msg-filter 'sed -e "/secret\[/d"'` (sed always exits 0) and
  `--msg-filter 'grep -avF "secret[" || true'` — both rewrite successfully,
  scan clean, legitimate messages/files preserved.
- MERGES (non-linear history): the row runs verbatim on a repo with a real
  merge (feature branch with tainted file merged into master):
  - rewritten merge commit keeps BOTH parents (topology preserved);
  - untouched commits keep their shas (master's clean commit unchanged);
  - only the tainted feature commit and the merge commit were rewritten;
  - pre-completion scan still finds the leak (refs/original + reflog
    anchor old history — expected, not a failure); post-completion
    (refs/original removal + expire + prune) scan = CLEAN, surface CLEAN,
    fsck quiet, `git log --all --oneline -- <path>` empty, every message
    exactly once.

### Completion-step checkout remedies (stale index / worktree)
Manufactured WITHOUT any rewrite tool (so the remedy lines actually fired):
- `A  <path>` state (stale index: path in index, rewritten HEAD lacks it)
  — manufactured via `git commit-tree` + `git update-ref HEAD <new>` —
  cleared verbatim by `git rm --cached --ignore-unmatch <path> && rm -f
  <path>`.
- `D  <path>` + `?? <path>` simultaneous state (index lacks path, HEAD still
  has it, file on disk) — manufactured via `git rm --cached`: the remedy
  cleared the INDEX and DISK surfaces (file gone, no `??`), but `D`
  PERSISTED with unlabeled raw output (S3) because `D` is an index-vs-HEAD
  relationship: the path is still in a HEAD tree (`git ls-tree HEAD`
  verified). A surviving `D` after the remedy means that ref's history was
  never rewritten — redirect to Phase 3. This supersedes an earlier claim
  (iteration 1) that the stale-checkout leftover shows as `D`; the
  realistic no-epilogue leftover is `A  <path>` (index has the path,
  rewritten HEAD lacks it), which the remedy clears FULLY to an empty
  status.
- `?? <path>` untracked-file state — `rm -f <path>` clears (no git command
  removes untracked files).

### Submodules / nested ODBs
- Embedded repo (`git add sub`): objects live in `sub/.git/objects`,
  invisible to the parent scan.
- Registered submodule (`git submodule add`): ODB at
  `parent/.git/modules/<name>/objects`; hidden from parent scans in the
  same way. Per-ODB loop with `GIT_DIR=...` finds them.

### Alternates (`objects/info/alternates`)
- `git clone --shared r clone` writes `clone/.git/objects/info/alternates`
  → origin ODB path.
- `git cat-file --batch-all-objects` ENUMERATES alternate objects: a scan
  run inside the clone found `secret[grep_fast]` living in the origin's
  ODB — detection is safe across shared ODBs.
- `git prune --expire=now` run in the clone did NOT delete a dangling blob
  physically owned by the alternate (origin blob still readable) while
  `git fsck --unreachable` in the clone reported it — cleanup must run at
  the physical owner or after unsharing.

### Fast paths (all executed verbatim)
- `git show :<path>` recovers the INDEX version of a staged file.
- `git stash show -p 'stash@{0}'` exposes stashed content.
- `git grep -aF 'secret[' $(git rev-list --all)` finds reachable file
  blobs.
- `git log --all --format='%B' | grep -aF 'secret['` finds commit-message
  leaks (verified with the secret actually placed in a message).

## Level 3 — Teacher-taught domain knowledge (adopted, not locally re-verified)

- `git fsck --lost-found` is a SALVAGE step that may write copies into
  `.git/lost-found/` outside the ODB (check-list rule, version-dependent —
  on this git it wrote nothing; always `ls .git/lost-found` and delete if
  present).
- `git filter-repo` is expected to leave the original checkout stale
  (plaintext file still on disk after refs are rewritten) — the opposite
  of the filter-branch epilogue observed in the lab, hence the completion
  step must not depend on either tool's behavior.
- Prefer `git filter-repo` when installed (`--path <p> --invert-paths`,
  then remove `.git/filter-repo/`).
- `grep -raI` (plus `-F`) as the plaintext surface sweep: skips binary
  (zlib/pack) files, covers worktree + index + `.git` text files; combined
  with the inflation scan it forms the complete every-location inventory.

## Level 4 — Reasoned extrapolation (mechanism follows from evidence)

- On gits older than ~2.37, expire+gc may not repack existing packs, so a
  packed unreachable object could survive; the `git repack -ad && git
  prune --expire=now` escalation plus `git cat-file -e` re-check is the
  safety net (verified as harmless no-op on 2.39.5).
- Per-ODB procedure loop for every submodule/nested repo (mechanism proven
  per-ODB; the loop itself is a composition).
- `--msg-filter 'sed -e "/secret\[/d"'` for message-only leaks (verified
  in one shape; message shapes may vary but line-drop semantics are
  stable).
- Alternates cleanup rule generalizes to `--reference` clones and any ODB
  sharing arrangement (verified for `clone --shared`).

## External eval evidence (fresh-solver runs of frozen skill snapshots)

- Iteration-1 frozen skill: fresh agent passed all 6 hidden tests
  (`test_flag_file_exists_and_correct`, `test_no_secrets_in_commits`,
  `test_good_commits_preserved`, `test_no_secrets_in_unreachable_objects`,
  `test_lost_found_cleaned`, `test_no_secret_in_any_git_object`) in 14
  tool calls; its run exposed the unescaped-`secret[` pattern bug twice.
- Iteration-2 frozen skill: fresh agent passed 6/6 in 7 tool calls with
  zero errors — the `-F` patterns, canonical `case $?` consumption, and
  phase flow held verbatim.
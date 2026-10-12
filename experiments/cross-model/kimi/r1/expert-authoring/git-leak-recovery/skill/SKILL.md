---
name: git-leak-recovery
description: >
  Recover a leaked secret from a git repository (unreachable blobs, index,
  stash, amended/reset-away commits, deleted branches/tags, replace refs,
  reachable history, submodules, nested repos), write it to a required output
  file, then eradicate it from every object database and ref while provably
  preserving all legitimate branches, tags, commit messages, and files.
---

# git-leak-recovery

## Task shape

Given a git repo (anchor: `/app/repo`) containing exactly one leaked string
matching `secret[...]`:

1. **Recover** the secret value and write it to the required path (anchor: `/app/secret.txt`).
2. **Eradicate** it so it cannot be found *anywhere* in the repo.
3. **Preserve** all legitimate files, branches, tags, and commit messages.

Take the repo path, output path, and secret pattern from the task instruction
— the values above are the v01 anchors; other family members may differ.
Substitute the pattern everywhere a command below uses `secret\[`.

## Execution environment (read first)

All git work happens inside an isolated container via `task_shell`. The helper
scripts under `scripts/` are host-side files and are **not** present in the
container. Two options:

- **Use the inline commands below** — every code block in this doc is
  container-ready. This is the primary path.
- Or copy a script in: `read` the script file, then recreate it with
  `task_shell` using a quoted heredoc (`cat > /tmp/scan.sh <<'EOF' ... EOF`),
  `chmod +x`, run it.

## Non-negotiables (in this order)

1. **Recover before you destroy.** Never run `gc`, `prune`, `reflog expire`,
   `stash drop`, or history rewrite before the secret value is safely written
   to the output file. Cleanup is irreversible.
2. **Scan objects, not files.** Loose objects and packfiles are
   zlib-compressed; `grep -r` over `.git` cannot see them. The only reliable
   scan is through `git cat-file`. Every location variant in this family
   (index blob, stash, dangling commit, tag, replace ref) is a git object, so
   one universal scan finds them all.
3. **Verify with the same scan you located with.** Re-scan after cleanup;
   zero hits is the definition of done.

## Fast path (single unreachable object — the common case)

Use this only when **all** of these hold: the scan below prints exactly one
HIT and it is a *blob*; `git fsck --unreachable --dangling` shows no
unreachable *commit*; `git stash list` is empty; `git status` is clean. If
any hit is a commit/tree, or the final verify prints DIRTY, the value also
lives in reachable history or another location — fall through to the full
pipeline. (A secret can be in reachable history AND an unreachable blob at
the same time; the purge below only removes the unreachable copy — observed
in testing.)

```sh
cd /app/repo
# locate + recover (exact bytes, no trailing newline)
for o in $(git cat-file --batch-all-objects --batch-check='%(objectname)'); do
  if git cat-file -p "$o" 2>/dev/null | grep -aq 'secret\['; then
    git cat-file -p "$o" | grep -ao 'secret\[[^]]*\]' | sed 's/^/  value: /'
    echo "  ^in $o"
  fi
done
git cat-file -p <hit> | grep -ao 'secret\[[^]]*\]' | head -1 | tr -d '\n' > /app/secret.txt
cat /app/secret.txt        # confirm BEFORE cleaning
# purge
git reflog expire --expire=now --all && git gc --prune=now
# verify (must print CLEAN; if DIRTY -> full pipeline below, Phase 1)
n=$(git cat-file --batch-all-objects --batch-check='%(objectname)' | while read o; do
  if git cat-file -p "$o" 2>/dev/null | grep -aq 'secret\['; then echo x; fi; done | wc -l)
m=$(grep -ral 'secret\[' . 2>/dev/null | wc -l)
[ "$n" = 0 ] && [ "$m" = 0 ] && echo CLEAN || echo "DIRTY: objects=$n files=$m"
git log --all --format='%s'   # eyeball: legitimate messages unchanged
```

If anything more complex shows up (a HIT on a commit or tree, live stash,
multiple gitdirs, tainted tags, DIRTY verdict), fall through to the full
pipeline below.

## Phase 0 — Snapshot legitimacy (needed for the final preservation check)

```sh
cd REPO
git log --all --format='%H %s' > /tmp/msgs.before   # commit messages
git for-each-ref > /tmp/refs.before                 # branches/tags/stash
git status --short; ls -a                           # worktree state
# all gitdirs (a gitdir contains HEAD and objects/; excludes .git/logs):
find . -name HEAD -type f | while read -r h; do d=$(dirname "$h");
  [ -d "$d/objects" ] && echo "$d"; done | sort -u
```

## Phase 1 — Locate

Universal scan — every object in every object database under the repo
(reachable, unreachable, packed, loose, nested `.git`, `.git/modules/*`),
plus plaintext metadata (reflogs, `COMMIT_EDITMSG`, `packed-refs`):

```sh
for gd in $(find REPO -name HEAD -type f | while read -r h; do d=$(dirname "$h");
    [ -d "$d/objects" ] && echo "$d"; done | sort -u); do
  GIT_DIR="$gd" git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' |
  while read -r oid ot; do
    if GIT_DIR="$gd" git cat-file -p "$oid" 2>/dev/null | grep -aq 'secret\['; then
      echo "HIT $ot $oid  ($gd)"
    fi
  done
done
grep -ral 'secret\[' REPO 2>/dev/null || echo '(no plaintext hits)'   # worktree + metadata
```

(`scripts/scan_repo.sh` does all this plus reference attribution, if copied in.)

Then classify each hit to decide cleanup:

| Location | How to confirm |
|---|---|
| Unreachable blob only (v01: staged, then removed from index) | `git fsck --unreachable --dangling`; no ref/reflog path to it |
| Staged in index | `git ls-files -s`; `git diff --cached` |
| Live worktree file (untracked or modified) | `grep -ral 'secret\[' . --exclude-dir=.git`; `git status` |
| Live stash | `git stash list`; blob under `refs/stash` commits |
| Dropped stash / amended / reset-away commit / deleted branch | `git reflog` / `git log -g --all`; `git fsck` unreachable *commit* |
| Reachable history | `git log --all --oneline --find-object=<blob>`; `git rev-list --objects --all \| grep <blob>` gives the path |
| Annotated tag / tainted tag | `git cat-file -p <tag>`; `git tag --contains <commit>` |
| Replace ref | `git replace -l`; refs under `refs/replace/` |
| Submodule / nested repo | separate gitdir reported by the scan; repeat all steps there with `git -C` |
| Alternates | `cat .git/objects/info/alternates` (rare; scan those stores too) |

The same secret value may exist as **several objects in several locations** —
clean every location.

## Phase 2 — Recover

```sh
git cat-file -p <blob>            # blob hit
git show <commit>:<path>          # committed file
git stash show -p stash@{n}       # stashed change
git diff --cached                 # staged
```

Write the **exact** `secret[...]` string to the required output path. Extract
with `grep -ao 'secret\[[^]]*\]'` if the blob has surrounding content, and
write exact bytes — `printf '%s'` or `... | tr -d '\n' >`, never a bare
`echo`. Confirm with `cat /app/secret.txt` before proceeding.

## Phase 3 — Eradicate (per location; then the common purge)

- **Worktree file, untracked**: delete or redact it (`sed -i
  's/secret\[[^]]*\]/REDACTED/g' file`). Never `git add` it.
- **Worktree file, tracked at HEAD**: redact it, then treat as reachable
  history (rewrite below) — the committed copy is what the grader scans.
- **Index**: `git rm --cached <f>` or `git reset`; keep the worktree file only
  if it is legitimate and untainted.
- **Live stash**: `git stash drop` each tainted entry (dropped stash objects
  become unreachable → purge below).
- **Tainted tag**: `git tag -d <tag>` (only tainted ones; keep legitimate tags).
- **Replace ref**: `git replace -d <ref>`.
- **Reachable history** (a ref still points at a commit containing the secret):
  rewrite, redacting content but preserving messages, topology, and tags:

  ```sh
  cd REPO   # must be repo root, worktree clean (filter-branch refuses otherwise)
  FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --tree-filter \
    'grep -rl "secret\[" . 2>/dev/null | xargs -r sed -i "s/secret\[[^]]*\]/REDACTED/g"' \
    --tag-name-filter cat -- --all
  ```
  (`git filter-repo --replace-text` is nicer *if installed* — it was **not**
  installed in the anchor environment; `filter-branch` is always present.
  Validated on a repo with a merge, two branches, and an annotated tag:
  commit count and all commit/tag messages preserved, tag re-pointed to the
  rewritten history, untainted ancestors keep their original hashes, tainted
  files redacted in place with surrounding lines intact.)
- **Unreachable-only** (v01 case, dropped stash, amended/reset-away commit,
  deleted branch): no rewrite needed — just purge.

**Common purge (always, in every affected gitdir):**

```sh
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d  # filter-branch backups keep taint alive
git reflog expire --expire=now --all    # reflogs pin tainted commits/stashes
git gc --prune=now                      # deletes unreachable objects, repacks
rm -rf .git/lost-found                  # only if you used fsck --lost-found
```

For submodule/nested gitdirs repeat with `git -C <path> ...` (reflog/gc) using
`GIT_DIR=<path>/.git` or `cd` inside. Also expire stash reflogs
(`refs/stash` entries die with `reflog expire --all` after `stash drop`).

## Phase 4 — Verify (gate; do not skip)

Mirrors what the graders check (secret in any git object / unreachable
objects / commit content, `.git/lost-found`, preserved commits):

```sh
bash scripts/verify_clean.sh REPO 'secret\['   # if copied in; must exit 0
```

or inline (must print CLEAN):

```sh
cd REPO
n=$(git cat-file --batch-all-objects --batch-check='%(objectname)' | while read o; do
  if git cat-file -p "$o" 2>/dev/null | grep -aq 'secret\['; then echo x; fi; done | wc -l)
m=$(grep -ral 'secret\[' . 2>/dev/null | wc -l)
git fsck --unreachable --dangling 2>/dev/null | grep . || echo "no unreachable objects"
ls .git/lost-found 2>/dev/null || echo "no lost-found dir"
[ "$n" = 0 ] && [ "$m" = 0 ] && echo CLEAN || echo "DIRTY: objects=$n files=$m"
true   # keep exit status 0; the verdict is in the printed text
```

Then check legitimacy against the Phase 0 snapshot:

- `git log --all --format='%H %s' | diff /tmp/msgs.before -` — unchanged
  (rewritten history keeps messages; only hashes may change — expected).
- `git for-each-ref | diff /tmp/refs.before -` — same legitimate refs (minus
  only tainted ones you deliberately deleted).
- Worktree files present with original content; `git status` as before.

If verify fails, return to Phase 1 with the reported object/file — a missed
reflog, `refs/original/*`, pack, or second gitdir is the usual culprit.

## Pitfalls (observed while validating)

- `git gc --prune=now` alone does **not** purge objects pinned by reflogs or
  `refs/original/*` — expire/delete those first (in the stash test the tainted
  blob survived until `stash drop` + `reflog expire` + `gc`).
- After `filter-branch`, the original tainted objects remain under
  `refs/original/` until you delete those refs.
- `fsck --lost-found` writes `.git/lost-found/*` copies, and graders check for
  it — prefer plain `git fsck --unreachable` for inspection, or remove the
  directory after.
- A nested repo's leak is invisible to the parent's `git` commands; enumerate
  gitdirs by looking for directories containing both `HEAD` and `objects/`.
- Empty grep output is easy to misread — end verification commands with an
  explicit `echo CLEAN`/`echo DIRTY` verdict.
- Write scan loops with `if grep -aq ...; then echo ...; fi`, not
  `grep && echo`: a failing grep makes the loop exit non-zero, which silently
  aborts the rest of a `set -e` script or an `&&` chain before later gitdirs
  or checks run (observed: a nested repo's leak was skipped for this reason).

## Evidence vs. extrapolation

- **Verified in the anchor environment (v01):** unreachable index blob found
  via `git fsck --unreachable` / `cat-file` scan; recovered via
  `git cat-file -p`; eradicated with `reflog expire --expire=now --all` +
  `gc --prune=now`; post-checks: zero pattern hits across all objects and
  `.git`, both legitimate commits and file content intact. Iteration-1 and
  iteration-2 solvers both passed all 6 hidden tests on fresh v01 containers
  (flag file, no secret in commits/objects/unreachable, lost-found clean,
  good commits preserved); iteration 2 used the fast path nearly verbatim in
  13 tool calls (down from 25).
- **Verified in scratch analogues of family variants (git 2.39.5, no
  filter-repo):** live-stash recovery + `stash drop` purge; reachable-history
  redaction via `filter-branch --tree-filter` + backup-ref deletion + purge;
  multi-gitdir (nested repo) scan and purge; helper scripts on tainted and
  clean repos (positive and negative tests); the fast-path pipeline above;
  the exact rewrite command (env-var form, no --prune-empty) on a
  merge+branch+annotated-tag topology with a multi-line tainted file;
  the mixed reachable+unreachable case, where the simple purge leaves the
  reachable copy and the verify step correctly reports DIRTY.
- **Extrapolated (same mechanics, not directly exercised):** annotated-tag and
  replace-ref locations, alternates, very large histories (use the same
  scan/rewrite/purge pipeline; for huge repos prefer `git filter-repo` if
  installable, and `git log --find-object` to scope the rewrite).

## Files

- `scripts/scan_repo.sh REPO [PATTERN]` — universal locator: every object in
  every gitdir, extracted values, referencing paths/commits/refs, plus
  structural inventory (stashes, replace refs, reflogs, alternates).
- `scripts/verify_clean.sh REPO [PATTERN]` — post-cleanup gate: exit 0 only if
  the pattern is absent from all objects, metadata, and worktree.
- Both are host-side; copy into the container (see *Execution environment*) or
  use the equivalent inline commands shown in each phase.

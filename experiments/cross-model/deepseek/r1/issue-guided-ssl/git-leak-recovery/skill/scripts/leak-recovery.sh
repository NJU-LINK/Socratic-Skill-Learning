#!/usr/bin/env bash
# leak-recovery.sh — gated RECOVER -> CLEANUP -> VERIFY pipeline for Git leak recovery.
#
# Hard gate: no destructive cleanup runs until the secret has been extracted to
# a path OUTSIDE the repository and format-checked.  Nothing task-specific is
# hardcoded: repo, outfile, and pattern are always parameters.
#
# Inside the task container this package is mounted READ-ONLY at /skill
# (SKILL.md at /skill/SKILL.md; this script at /skill/scripts/leak-recovery.sh).
# Host-workspace paths (e.g. .../workspace/skill/...) are NOT visible inside
# the container; if the mount point is unknown, run:
#   find / -name 'leak-recovery.sh' -not -path '/proc/*' 2>/dev/null
#
# Usage:
#   leak-recovery.sh <repo> inventory
#   leak-recovery.sh <repo> locate '<pattern>'
#   leak-recovery.sh <repo> recover <outfile> '<pattern>'
#   leak-recovery.sh <repo> cleanup <outfile> '<pattern>'
#   leak-recovery.sh <repo> verify   <outfile> '<pattern>'
#
# <pattern> is an extended regex (grep -E) for the secret FORMAT, e.g.
#   'secret\[[^]]*\]'   or a quoted literal value.
# Never use a bare substring ('secret'): it false-positives on words like
# "addsecret" (observed).
#
# Exit semantics: recover exits 0 only when the gate passes (candidate(s)
# extracted outside the repo and format-checked).  cleanup exits 0 only when
# the mechanical steps (expire reflogs, gc --prune=now, remove lost-found)
# removed every matching object; if matches survive, it exits 1 and prints
# which matches are still present so the agent can run holder-specific actions
# (stash drop / tag -d / replace -d / history rewrite) and rerun cleanup.
# verify exits 0 only when all object-DB checks pass after cleanup.
set -u

REPO="${1:-}"; CMD="${2:-}"
if [ -z "$REPO" ] || [ -z "$CMD" ]; then
  echo "usage: leak-recovery.sh <repo> <inventory|locate|recover|cleanup|verify> [args...]" >&2
  exit 2
fi
shift 2

die() { echo "ERROR: $*" >&2; exit 1; }
out() { echo "[leak-recovery] $*"; }

# ---------------------------------------------------------------------------
# Object-DB scope: main gitdir, linked-worktree gitdirs, submodule gitdirs.
# ---------------------------------------------------------------------------
scope_gitdirs() {
  local main
  main="$(git -C "$REPO" rev-parse --absolute-git-dir 2>/dev/null)" || die "not a git repository: $REPO"
  echo "$main"
  # Linked-worktree admin dirs.  NOTE: on git 2.39 `git worktree list --porcelain`
  # prints NO `gitdir` lines (observed), so enumerate <main>/worktrees/*/ directly;
  # keeping the porcelain parse below covers newer git versions that do print them.
  git -C "$REPO" worktree list --porcelain 2>/dev/null | sed -n 's/^gitdir //p'
  ls -d "$main"/worktrees/*/ 2>/dev/null | sed 's:/$::'
  ls -d "$main"/modules/*/ 2>/dev/null | sed 's:/$::'
}

# Worktree roots in scope (main + linked).  `worktree list --porcelain`
# prints these as `worktree <path>` lines on every git version.
worktree_roots() {
  git -C "$REPO" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p'
}

# Plaintext matches inside any worktree root (tracked or untracked),
# excluding gitdirs (their non-object files are swept per-gitdir; their
# objects are scanned via batch-all-objects).  One file per line.
worktree_file_hits() { # pattern
  local pat="$1" wt
  for wt in $(worktree_roots); do
    grep -r -a -l -E "$pat" "$wt" --exclude-dir=.git 2>/dev/null
  done
}

# Run an object-DB command against a gitdir, insulating against a broken
# (e.g. removed/renamed) linked worktree by overriding core.worktree to an
# existing directory.  Observed failure without it: "fatal: cannot chdir ...".
gdgit() { local gd="$1"; shift; git --git-dir="$gd" -c core.worktree="$gd" "$@"; }

# ---------------------------------------------------------------------------
# inventory — read-only sweep of every holder.  Never uses `--lost-found`
# (it materializes blob contents as plaintext under <gd>/lost-found/other/).
# ---------------------------------------------------------------------------
cmd_inventory() {
  out "repo: $REPO"
  local gd
  for gd in $(scope_gitdirs); do
    out "== gitdir: $gd"
    gdgit "$gd" for-each-ref 2>/dev/null
    gdgit "$gd" stash list 2>/dev/null
    gdgit "$gd" reflog --all 2>/dev/null
    echo "   reflog files: $(find "$gd/logs" -type f 2>/dev/null | tr '\n' ' ')"
    echo "   alternates: $(cat "$gd/objects/info/alternates" 2>/dev/null | tr '\n' ' ')"
    echo "   index entries (staged blobs are GC ROOTS and survive prune):"
    gdgit "$gd" ls-files -s 2>/dev/null
    echo "   unreachable (fsck):"
    gdgit "$gd" fsck --full --no-reflogs --unreachable 2>/dev/null
  done
  out "worktrees:"
  git -C "$REPO" worktree list --porcelain 2>/dev/null
  out "inventory done (read-only)."
}

# ---------------------------------------------------------------------------
# locate — every object whose raw content matches the pattern, with the
# object identity attached (actionable output):
#   "<gd> | <sha> <type> <size> | <first matching content line>"
# Each object is confirmed individually (cat-file + grep), so the SHA/type
# is always paired with the hit — the streamed-grep header association is
# not relied upon.
# ---------------------------------------------------------------------------
cmd_locate() {
  local pat="$1" gd sha type size line
  for gd in $(scope_gitdirs); do
    while read -r sha type size; do
      line="$(gdgit "$gd" cat-file "$type" "$sha" 2>/dev/null | grep -a -m1 -E "$pat" || true)"
      if [ -n "$line" ]; then
        echo "$gd | $sha $type $size | $line"
      fi
    done < <(gdgit "$gd" cat-file --batch-all-objects --batch-check 2>/dev/null)
  done
}

# ---------------------------------------------------------------------------
# recover — gate: extract every matching blob to numbered files OUTSIDE the
# repo, validate format, write a gate marker.  Exit 0 only if the gate passes.
# ---------------------------------------------------------------------------
cmd_recover() {
  local outfile="$1" pat="$2" gd n=0 good=0 f sha type size
  # refuse an outfile inside the repository
  case "$outfile" in
    "$REPO"/*) die "outfile must be OUTSIDE the repository: $outfile";;
  esac
  rm -f "$outfile" "${outfile}".* "${outfile}.gate" 2>/dev/null
  for gd in $(scope_gitdirs); do
    while read -r sha type size; do
      if ! gdgit "$gd" cat-file "$type" "$sha" 2>/dev/null | grep -qa -E "$pat"; then
        continue
      fi
      n=$((n+1))
      if [ "$n" -eq 1 ]; then f="$outfile"; else f="${outfile}.${n}"; fi
      if [ "$type" = "blob" ]; then
        gdgit "$gd" cat-file blob "$sha" > "$f" 2>/dev/null
      else
        gdgit "$gd" cat-file "$type" "$sha" > "$f" 2>/dev/null   # commit/tag: message is the leak
      fi
      if [ -s "$f" ] && grep -qa -E "$pat" "$f"; then
        out "recovered #$n from $gd $type $sha -> $f"
        good=$((good+1))
      else
        rm -f "$f"
      fi
    done < <(gdgit "$gd" cat-file --batch-all-objects --batch-check 2>/dev/null)
  done
  if [ "$good" -eq 0 ]; then
    die "no object matched the pattern; nothing recovered (pattern=$pat)"
  fi
  # gate marker: pattern + candidate files
  { echo "$pat"; echo "candidates: $(ls "${outfile}"* 2>/dev/null | tr '\n' ' ')"; } > "${outfile}.gate"
  out "GATE PASSED: $good candidate(s) extracted outside repo and format-checked."
  out "verify uniqueness of the leaked value across candidates before cleanup."
}

# ---------------------------------------------------------------------------
# gate check used by cleanup and verify.
# ---------------------------------------------------------------------------
gate_ok() { # outfile pattern
  local outfile="$1" pat="$2"
  [ -f "$outfile" ] || { out "GATE BLOCKED: $outfile missing (run recover first)"; return 1; }
  [ -s "$outfile" ] || { out "GATE BLOCKED: $outfile empty"; return 1; }
  grep -qa -E "$pat" "$outfile" || { out "GATE BLOCKED: $outfile does not match pattern"; return 1; }
  [ -f "${outfile}.gate" ] || { out "GATE BLOCKED: no gate marker ${outfile}.gate (run recover first)"; return 1; }
  return 0
}

# ---------------------------------------------------------------------------
# cleanup — refuses unless the recovery gate passed.  Mechanical steps that
# are safe for every holder: expire all reflogs, gc --prune=now, remove any
# lost-found materialization, in every gitdir in scope.  Holder-specific
# decisions that could destroy legitimate content (stash drop, tag -d,
# replace -d, history rewrite) are printed as advice; the agent runs them,
# then reruns cleanup.  Exits 0 only when NO match remains after cleanup.
# ---------------------------------------------------------------------------
cmd_cleanup() {
  local outfile="$1" pat="$2" gd pre post
  gate_ok "$outfile" "$pat" || die "recovery gate not satisfied; cleanup refused"
  out "gate OK -> proceeding with cleanup"
  pre="$(cmd_locate "$pat")"
  for gd in $(scope_gitdirs); do
    out "== gitdir $gd"
    gdgit "$gd" reflog expire --expire=now --all 2>/dev/null
    rm -f "$gd/gc.pid"                       # stale gc lock guard
    gdgit "$gd" gc --prune=now -q 2>/dev/null
    rm -rf "$gd/lost-found"                  # plaintext materializations
    out "   reflogs expired; gc --prune=now done; lost-found removed"
  done
  if [ -n "$pre" ]; then
    out "matches found BEFORE cleanup (objects the mechanical steps were expected to remove, or holders needing action):"
    echo "$pre"
  fi
  out "refs/replace: $(git -C "$REPO" for-each-ref refs/replace 2>/dev/null | wc -l)  refs/original: $(git -C "$REPO" for-each-ref refs/original 2>/dev/null | wc -l)"
  out "stash ref (refs/stash): $(git -C "$REPO" for-each-ref refs/stash 2>/dev/null | wc -l)  (git stash list can read 0 after reflog expiry; count the ref)"
  post="$(cmd_locate "$pat")"
  local wt_hits
  wt_hits="$(worktree_file_hits "$pat")"
  if [ -n "$post" ]; then
    out "matches STILL present AFTER cleanup (holder-specific cleanup still required):"
    echo "$post"
    out "ADVICE: unstage tainted files still staged in an index — the index is a GC ROOT and"
    out "       survives reflog-expire + gc --prune=now (verified for main and worktree indexes):"
    out "       git rm --cached <file>   (or git reset; for a linked worktree run it with git -C <worktree>);"
    out "       for live stashes drop them BEFORE expiring reflogs (git stash drop) so the stash is not left pinned by refs/stash;"
    out "       if the reflog is already expired, use 'git update-ref -d refs/stash' instead of 'git stash drop';"
    out "       delete only-tainted tags (git tag -d),"
    out "       remove replace refs (git replace -d <sha>) and backup refs (refs/original),"
    out "       rewrite reachable history (git filter-repo / filter-branch) — then rerun"
    out "       cleanup to prune the now-unreachable objects, and finally verify."
  fi
  if [ -n "$wt_hits" ]; then
    out "worktree plaintext copies STILL present (Git object storage is clean but the value still"
    out "sits in files inside a worktree — the family contract forbids this):"
    echo "$wt_hits" | sed 's/^/    /'
    out "ADVICE: delete the file if it is the leak carrier (rm <file>); if it is legitimate"
    out "       content that merely contains the value, scrub the value out (edit the file);"
    out "       cf. the inline --replace-text rewrite for many files."
  fi
  if [ -n "$post" ] || [ -n "$wt_hits" ]; then
    die "cleanup incomplete: matches still present after mechanical cleanup (see above)"
  fi
  out "cleanup complete: no object matches the pattern in any object DB, and no plaintext copy in any worktree."
}

# ---------------------------------------------------------------------------
# verify — object-complete: fsck graph, batch-all-objects content scan,
# filesystem sweep, preservation summary.  Exit 0 only when all clean.
# ---------------------------------------------------------------------------
cmd_verify() {
  local outfile="$1" pat="$2" gd clean=1
  gate_ok "$outfile" "$pat" || die "recovery gate not satisfied; verify refused"
  for gd in $(scope_gitdirs); do
    out "== gitdir $gd"
    local fsck_out
    fsck_out="$(gdgit "$gd" fsck --full --no-reflogs --unreachable 2>/dev/null)"
    if [ -n "$fsck_out" ]; then out "  FAIL fsck lists: $fsck_out"; clean=0; else out "  OK  fsck: no unreachable"; fi
    local hits
    hits="$(gdgit "$gd" cat-file --batch-all-objects --batch 2>/dev/null | grep -a -E "$pat" || true)"
    if [ -n "$hits" ]; then out "  FAIL batch scan: $hits"; clean=0; else out "  OK  batch-all-objects: no matches (loose+packed+alternates)"; fi
    local fhits
    fhits="$(grep -r -a -l -E "$pat" "$gd" 2>/dev/null || true)"
    if [ -n "$fhits" ]; then out "  FAIL fs sweep: $fhits"; clean=0; else out "  OK  fs sweep of gitdir: no matches (logs/refs/lost-found/index/modules)"; fi
  done
  # Plaintext copies inside worktree roots (tracked or untracked files).
  # git rm --cached / history rewrites remove Git storage but leave the file
  # on disk; the family contract forbids the value ANYWHERE in the repo.
  local wt_hits
  wt_hits="$(worktree_file_hits "$pat")"
  if [ -n "$wt_hits" ]; then
    out "  FAIL worktree sweep: plaintext copies inside worktree roots:"
    echo "$wt_hits" | sed 's/^/    /'
    clean=0
  else
    out "  OK  worktree sweep: no plaintext matches in any worktree root (tracked or untracked)"
  fi
  # nested repos inside the worktree (skip the main gitdir, already checked)
  local ng main_gd
  main_gd="$(git -C "$REPO" rev-parse --absolute-git-dir 2>/dev/null)"
  while IFS= read -r ng; do
    [ -n "$ng" ] || continue
    local ngd="$ng"; [ -f "$ng" ] && ngd="$(sed -n 's/^gitdir: //p' "$ng")"
    [ "$ngd" = "$main_gd" ] && continue
    out "== nested gitdir: $ngd"
    git --git-dir="$ngd" -c core.worktree="$ngd" cat-file --batch-all-objects --batch 2>/dev/null | grep -a -q -E "$pat" \
      && { out "  FAIL nested batch scan"; clean=0; } || out "  OK  nested repo scan"
  done < <(find "$REPO" -name .git 2>/dev/null | grep -v '/modules/' || true)
  out "== preservation summary (eyeball vs pre-cleanup inventory) =="
  out "status: $(git -C "$REPO" status --porcelain 2>/dev/null | tr '\n' ';')"
  git -C "$REPO" log --oneline --all 2>/dev/null | sed 's/^/  log: /'
  out "tags: $(git -C "$REPO" tag 2>/dev/null | tr '\n' ' ')"
  out "recovered value still intact: $(grep -a -o -E "$pat" "$outfile" 2>/dev/null | head -1)"
  [ "$clean" -eq 1 ] || die "verification FAILED"
  out "VERIFY PASSED: no trace of the pattern in any object DB or gitdir file."
}

case "$CMD" in
  inventory) cmd_inventory ;;
  locate)    [ $# -ge 1 ] || die "locate needs <pattern>"; cmd_locate "$1" ;;
  recover)   [ $# -ge 2 ] || die "recover needs <outfile> <pattern>"; cmd_recover "$1" "$2" ;;
  cleanup)   [ $# -ge 2 ] || die "cleanup needs <outfile> <pattern>"; cmd_cleanup "$1" "$2" ;;
  verify)    [ $# -ge 2 ] || die "verify needs <outfile> <pattern>"; cmd_verify "$1" "$2" ;;
  *) die "unknown command: $CMD (inventory|locate|recover|cleanup|verify)" ;;
esac
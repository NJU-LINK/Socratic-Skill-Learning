#!/usr/bin/env bash
# git-leak-recovery — recover a secret[...] token from EVERY object database under
# REPO and purge it; verify zero occurrence + preserved legitimate state.
#
# Usage:
#   bash scripts/git-leak-recovery.sh REPO [yes|no | write=yes|write=no]
#   bash scripts/git-leak-recovery.sh REPO diag
#   bash scripts/git-leak-recovery.sh --probe
#
# REPO        path to the repository (default deliverable: /app/secret.txt)
# write=yes   (default) write the recovered token to $SECRET_FILE (/app/secret.txt)
# write=no    verification-only mode: never touches $SECRET_FILE (safe re-run/self-check)
# diag        READ-ONLY reconnaissance: discovery + union scan + holders + pinning
#             state summary; no snapshot, no writes, no prune. Exit 0 = token found,
#             2 = none found.
# --probe     detector sanity check in SCRATCH SPACE only (never the graded repo)
#
# Env overrides:
#   SECRET_FILE=<path>   output file (default /app/secret.txt)
#   SNAPSHOT=no          skip the /tmp/repo.pristine snapshot
#   SNAP=<path>          snapshot destination (default /tmp/repo.pristine)
#
# Exit codes (a decision function — trust the code, not the message text):
#   0  task state VERIFIED GOOD. Either: token recovered + repo clean (recovery run),
#      OR repo already clean with an existing deliverable re-verified against it, OR a
#      clean verification-only ('no') pass with no deliverable (absence check). The
#      success path removes its working files and this run's snapshot before returning.
#   2  cannot proceed: not a repo / no object DB / no token in ANY object DB AND no
#      existing deliverable to re-verify (nothing to recover, nothing to verify).
#      Nothing was written or destroyed.
#   3  do Phase 2 and re-run: token still pinned by a ref/stash/tag/replace ref, fsck
#      not clean, plaintext remains, or unexpected working-tree delta. A pinning-state
#      hint is printed; leak-objects.txt / baselines / snapshot are KEPT for Phase 2.
set -u

# ------------------------------ probe mode ------------------------------
if [ "${1:-}" = "--probe" ]; then
  tmp=$(mktemp -d) || { echo "FATAL: mktemp failed" >&2; exit 2; }
  git -C "$tmp" init -q || { rm -rf "$tmp"; exit 2; }
  printf 'secret[probe_scratch]' | git -C "$tmp" hash-object -w --stdin >/dev/null || { rm -rf "$tmp"; exit 2; }
  n=$(git -C "$tmp" cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null \
      | while read oid t; do git -C "$tmp" cat-file -p "$oid" 2>/dev/null; done \
      | grep -aoE 'secret\[[^]]*\]' | LC_ALL=C sort -u | wc -l)
  rm -rf "$tmp"
  if [ "$n" -lt 1 ]; then
    echo "PROBE FAILED: detector found 0 tokens in a known-leaky scratch repo" >&2
    exit 2
  fi
  echo "probe OK: detector finds $n token(s) in a scratch repo (graded repo untouched)"
  exit 0
fi

REPO="${1:-}"
[ -n "$REPO" ] || { echo "usage: bash $0 REPO [yes|no|diag] | $0 --probe" >&2; exit 2; }
MODE="${2:-yes}"
case "$MODE" in yes|no|write=yes|write=no|diag) MODE=${MODE#write=} ;; *) echo "FATAL: mode must be yes, no, or diag (got '$MODE')" >&2; exit 2;; esac
OUT="${SECRET_FILE:-/app/secret.txt}"
export GIT_NO_REPLACE_OBJECTS=1   # every git read ignores replace refs

die2() { echo "FATAL: $*" >&2; exit 2; }
die3() { echo "FATAL: $*" >&2; exit 3; }

# ------------------------------ discovery ------------------------------
discover_dbs() {
  GITDIRS=( "$REPO/.git" )
  while IFS= read -r d; do                         # nested .git dirs / submodule .git files
    [ -f "$d" ] && d=$(sed -n 's/^gitdir: //p' "$d")
    [ -n "$d" ] && GITDIRS+=( "$d" )
  done < <(find "$REPO" -name .git ! -path "$REPO/.git" 2>/dev/null)
  GITDIRS+=( "$REPO"/.git/modules/* )              # real submodule object DBs (literal glob filtered below)
  for d in "${GITDIRS[@]}"; do                     # alternates are object DBs too
    [ -f "$d/objects/info/alternates" ] || continue
    while IFS= read -r alt; do
      [ -n "$alt" ] || continue
      case "$alt" in /*) ;; *) alt="$(cd "$d/objects" 2>/dev/null && pwd)/$alt" ;; esac
      [ "${alt##*/}" = "objects" ] && alt=$(dirname "$alt")   # OBJECT dir -> owning gitdir
      GITDIRS+=( "$alt" )
    done < "$d/objects/info/alternates"
  done
  seen=(); GITDIRS2=()
  for d in "${GITDIRS[@]}"; do
    [ -d "$d/objects" ] || continue
    case " ${seen[*]} " in *" $d "*) continue ;; esac
    seen+=( "$d" ); GITDIRS2+=( "$d" )
  done
  GITDIRS=( "${GITDIRS2[@]}" )
}

union_scan() {   # echoes unique secret[...] candidates from ALL DBs
  for d in "${GITDIRS[@]}"; do
    git --git-dir="$d" cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null \
      | while read oid t; do git --git-dir="$d" cat-file -p "$oid" 2>/dev/null; done
  done | grep -aoE 'secret\[[^]]*\]' | LC_ALL=C sort -u     # -a: binary blobs too
}

holders_list() {   # writes /tmp/leak-objects.txt: "DB OID TYPE" per holder
  : > /tmp/leak-objects.txt
  for d in "${GITDIRS[@]}"; do
    git --git-dir="$d" cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null \
      | while read oid t; do git --git-dir="$d" cat-file -p "$oid" 2>/dev/null | grep -aqF "$SECRET" && echo "$d $oid $t"; done
  done | sort -u >> /tmp/leak-objects.txt
}

state_summary() {   # who pins the token — printed by diag and on exit 3
  echo "--- pinning state ---"
  # NOTE: do NOT use `git stash list` here — the script's own reflog expiry wipes
  # logs/refs/stash, so the list would misreport a live stash as absent. Read refs.
  echo "[refs beyond heads/tags (stash / notes / bisect / original / replace...)]"
  nonstd=$(git -C "$REPO" for-each-ref --format='  %(refname) -> %(objectname:short)' 2>/dev/null | grep -vE 'refs/(heads|tags)/' || true)
  [ -n "$nonstd" ] && echo "$nonstd" || echo "  (none)"
  echo "[tags]";        git -C "$REPO" tag -l 2>/dev/null || true
  echo "[replace refs]"; git -C "$REPO" replace -l 2>/dev/null || true
  git -C "$REPO" symbolic-ref -q HEAD >/dev/null 2>&1 || echo "[HEAD is DETACHED]"
  echo "[holder reachability (DB OID TYPE -> path in refs)]"
  if [ -s /tmp/leak-objects.txt ]; then
    while read -r db oid typ; do
      [ -n "$oid" ] || continue
      hit=$(git --git-dir="$db" rev-list --objects --all 2>/dev/null | grep -F "$oid" | head -2)
      if [ -n "$hit" ]; then
        echo "  $db $oid ($typ): REACHABLE -> $hit"
      else
        echo "  $db $oid ($typ): NOT in refs -> check index (ls-files --stage), notes, refs/replace, alternate-owner refs"
      fi
    done < /tmp/leak-objects.txt
  fi
  git -C "$REPO" status --porcelain 2>/dev/null | sed 's/^/  [status] /' || true
}

# ------------------------------ identity ------------------------------
[ -d "$REPO/.git" ] || die2 "$REPO is not a git repo"
REPO=$(cd "$REPO" && pwd) || die2 "cannot resolve $REPO"
discover_dbs
[ "${#GITDIRS[@]}" -ge 1 ] || die2 "no object DB discovered under $REPO"
echo "object DBs: ${GITDIRS[*]}"

# ------------------------------ diag mode ------------------------------
if [ "$MODE" = "diag" ]; then
  CANDIDATES=$(union_scan)
  if [ -z "$CANDIDATES" ]; then
    echo "no secret[...] found in ANY object DB (repo may already be clean)"
    exit 2
  fi
  SECRET=$(printf '%s\n' "$CANDIDATES" | head -1)
  echo "recovered-from-scan (diag, no writes): $SECRET"
  [ "$(printf '%s\n' "$CANDIDATES" | wc -l)" -gt 1 ] && { echo "WARN: multiple distinct tokens:" >&2; printf '%s\n' "$CANDIDATES" >&2; }
  holders_list
  echo "holders: $(wc -l < /tmp/leak-objects.txt) object(s) — see /tmp/leak-objects.txt"
  state_summary
  rm -f /tmp/leak-objects.txt   # diag is read-only reconnaissance: leave nothing behind
  exit 0
fi

# ------------------------------ Phase 1: guarded union scan ------------------------------
frm_scan=0
CANDIDATES=$(union_scan)
if [ -z "$CANDIDATES" ]; then
  # No token anywhere. Terminal state is either "success to re-verify" (a deliverable
  # exists) or "unrecoverable" (nothing to recover AND nothing to verify). Exit 0 must
  # mean "task state verified good", so fall through to baselines + Phase 3 + Phase 4.
  if [ -s "$OUT" ]; then
    SECRET=$(cat "$OUT" 2>/dev/null || true)   # ground truth from the earlier write=yes run
    if [ -n "$SECRET" ]; then
      echo "no token in object DBs — repo already clean; re-verifying against deliverable $OUT"
    else
      [ "$MODE" = "no" ] || die2 "no secret[...] in any object DB and $OUT is empty — nothing to recover or verify"
    fi
  elif [ "$MODE" = "no" ]; then
    SECRET=
    echo "no token in object DBs — verification-only pass (PAT falls back to 'secret[')"
  else
    die2 "no secret[...] found in ANY object DB and $OUT missing — nothing to recover (or the repo was already cleaned and the deliverable removed); re-check the task hint"
  fi
else
  frm_scan=1
  NTOK=$(printf '%s\n' "$CANDIDATES" | wc -l)
  if [ "$NTOK" -gt 1 ]; then
    echo "WARN: $NTOK distinct tokens (generator promises exactly one; RE-READ the task hint):" >&2
    printf '%s\n' "$CANDIDATES" >&2
  fi
  SECRET=$(printf '%s\n' "$CANDIDATES" | head -1)
  [ -n "$SECRET" ] || die2 "empty token"
  if [ "$MODE" = "yes" ]; then
    printf '%s' "$SECRET" > "$OUT" || die2 "cannot write $OUT"
    [ "$(cat "$OUT")" = "$SECRET" ] || die2 "write verification failed for $OUT"
  fi
  echo "recovered: $SECRET"
fi

# ------------------------------ snapshot + baselines ------------------------------
# Snapshot only on a real recovery run (frm_scan=1): the verify branch is
# non-destructive and needs no insurance copy. Scan/baselines are read-only, so
# pristine-ness is preserved.
if [ "${SNAPSHOT:-yes}" = "yes" ] && [ "$frm_scan" = 1 ]; then
  SNAP="${SNAP:-/tmp/repo.pristine}"
  rm -rf "$SNAP"
  cp -a "$REPO" "$SNAP" || die2 "snapshot to $SNAP failed"
  snap_taken=1
  echo "snapshot: $SNAP"
fi

cd "$REPO" || die2 "cannot cd $REPO"
git status --porcelain | sort > /tmp/baseline.status
git log --format='%s' --all | sort > /tmp/baseline.msgs
git rev-list --objects --all 2>/dev/null | awk '{print $2}' | grep -v '^$' | sort -u > /tmp/baseline.paths
git tag -l | sort > /tmp/baseline.tags

if [ "$frm_scan" = 1 ]; then
  holders_list
  echo "holders: $(wc -l < /tmp/leak-objects.txt) object(s) — see /tmp/leak-objects.txt"
fi

# ------------------------------ Phase 3: expire reflogs + prune in EVERY DB ------------------------------
for d in "${GITDIRS[@]}"; do
  git --git-dir="$d" reflog expire --expire=now --all 2>/dev/null
  git --git-dir="$d" gc --prune=now 2>/dev/null        # --prune=now REQUIRED (default ~2 weeks)
done

# ------------------------------ Phase 4: guarded verification ------------------------------
PAT="${SECRET:-secret[}"   # non-empty even if SECRET is somehow unset ("" would match everything)

total=0                                                   # 4a: every object DB
for d in "${GITDIRS[@]}"; do
  n=$(git --git-dir="$d" cat-file --batch-all-objects --batch-check='%(objectname)' 2>/dev/null \
      | while read oid; do git --git-dir="$d" cat-file -p "$oid" 2>/dev/null; done \
      | grep -acF "$PAT" || true)
  echo "  scan $d: $n"; total=$((total+n))
done
if [ "$total" -ne 0 ]; then
  holders_list   # refresh: Phase 3 may already have pruned some holders; list only what remains
  state_summary
  die3 "token still present in objects ($total) — run SKILL.md Phase 2 (classification, delete pinning refs like stash/tag/replace/notes, rewrite reachable history), then re-run this script"
fi

for d in "${GITDIRS[@]}"; do                              # 4b: fsck per DB
  out=$(git --git-dir="$d" fsck --full --no-reflogs --unreachable 2>&1 | grep -vE '^(notice|warning):' || true)
  [ -z "$out" ] || die3 "fsck $d: $out"
done

hits=$(grep -raF "$PAT" "$REPO" 2>/dev/null | wc -l)      # 4c: plaintext sweep (whole tree)
echo "plaintext hits: $hits"
if [ "$hits" -ne 0 ]; then
  grep -raF "$PAT" "$REPO" 2>/dev/null | head -20 >&2
  for d in "${GITDIRS[@]}"; do                            # regenerable metadata in EVERY gitdir
    rm -f "$d"/COMMIT_EDITMSG "$d"/MERGE_MSG "$d"/logs/HEAD "$d"/logs/refs/heads/* "$d"/logs/refs/stash 2>/dev/null || true
  done
  hits=$(grep -raF "$PAT" "$REPO" 2>/dev/null | wc -l)
  [ "$hits" -eq 0 ] || die3 "plaintext leak remains (see lines above) — worktree hits must be removed by hand"
fi

cd "$REPO" || die2 "cannot cd $REPO"                       # 4d: strict status-delta contract:
git status --porcelain | sort > /tmp/after.status         # every line must be ' M <gitlink-path>'
bad=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  case "$line" in
    " M "*)
      p=${line#" M "}
      git ls-files --stage | awk '$1=="160000"{print $4}' | grep -qxF "$p" \
        || { echo "UNEXPECTED ' M' on non-gitlink path: [$line]" >&2; bad=1; }
      ;;
    *)
      echo "UNEXPECTED status line: [$line]" >&2; bad=1;;
  esac
done < /tmp/after.status
[ "$bad" -eq 0 ] || die3 "working-tree delta not explained by submodule gitlink updates"

git log --format='%s' --all | sort | diff /tmp/baseline.msgs - >/dev/null \
  && echo "messages: unchanged" || echo "messages: DIFFER (expected only if Phase 2 rewrote/redacted)"
git rev-list --objects --all 2>/dev/null | awk '{print $2}' | grep -v '^$' | sort -u | diff /tmp/baseline.paths - >/dev/null \
  && echo "paths: unchanged" || echo "paths: DIFFER (expected only if Phase 2 removed a leaky path)"
git tag -l | sort | diff /tmp/baseline.tags - >/dev/null \
  && echo "tags: unchanged" || echo "tags: DIFFER (expected only if Phase 2 deleted tainted tags)"

if [ "$MODE" = "yes" ]; then                              # 4e: deliverable
  [ -s "$OUT" ] || die3 "$OUT missing or empty"
  [ "$(cat "$OUT")" = "$SECRET" ] || die3 "$OUT content mismatch"
  echo "secret.txt: [$(cat "$OUT")]"
fi

if [ "$frm_scan" = 1 ]; then
  echo "PASS: recovered=$SECRET objects=$total"
else
  echo "PASS: clean-repo verified (token=${SECRET:-absent} objects=$total)"
fi
# Success path leaves nothing behind: remove working files (baseline.msgs can carry a
# leaked commit subject; after PASS their data is stale) and this run's snapshot.
# Exit-2/-3 paths keep them (Phase 2 needs leak-objects.txt; at exit 3 the repo still
# legitimately contains the token).
rm -f /tmp/baseline.status /tmp/baseline.msgs /tmp/baseline.paths /tmp/baseline.tags \
      /tmp/after.status /tmp/leak-objects.txt 2>/dev/null || true
if [ "${snap_taken:-0}" = "1" ]; then
  rm -rf "${SNAP:-/tmp/repo.pristine}" 2>/dev/null || true
fi
exit 0
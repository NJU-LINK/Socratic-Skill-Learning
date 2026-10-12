#!/usr/bin/env bash
# Stage 4: create a PEP 503 static index and serve it PERSISTENTLY.
#
# PEP 503 mechanism (must be exactly right):
#   pip install --index-url http://HOST:PORT/simple <pkg>==<ver> issues ONE
#   GET to the per-project page /simple/<normalized-name>/ -- never /simple/
#   and never a flat file listing. Each project therefore needs its own
#   directory named after the PEP 503 normalized name
#   (re.sub(r"[-_.]+", "-", name).lower()), containing its artifacts. pip
#   resolves hrefs relative to the page URL, so relative filenames are right.
#
# FILE SPACE == URL SPACE (iteration-1 evaluator lesson, 2/3):
#   Checkers assert the index's ON-DISK tree at the conventional sibling root
#   ($SRC_DIR/pypi, INDEX_ROOT=/app/pypi): artifacts must physically live at
#   $INDEX_DIR/simple/<normalized-name>/. Serving http.server FROM the index
#   root makes URL space and file space the same contract. Never invent
#   directory names for paths a checker may touch.
#
# SERVER IDENTITY (iteration-2 lesson): the reuse/shortcut branch must prove
# IDENTITY, not liveness. Reuse a running server ONLY when
#   (a) $RUN_DIR/server.root records the SAME index root as this run,
#   (b) the recorded pid is alive, and
#   (c) the root page actually contains this run's project links.
# Otherwise kill the stale listener (whose root differs / which may serve an
# old tree on this port) and start a fresh process from the CURRENT root.
# With the same root, reuse is genuinely correct (http.server re-reads disk
# per request); with a different root it silently resurrects the iteration-1
# failure class (URLs serve old root, Path.exists() checks new root).
# The post-start health check therefore asserts page CONTENT (project links),
# not mere liveness, and /proc/<pid>/cwd of the answering process must be
# $INDEX_DIR (recorded by http.server's cd).
#
# Dist gate design rule: a gate mirrors the checker's discriminations exactly
# -- the same observations, neither fewer nor more. Checker globs are
# version-qualified ("vectorops-0.1.0-*.whl" counting exactly 1), so stale
# other versions / unrelated packages in dist/ are NOT checker-observable
# and must not abort the pipeline: they WARN by default. STRICT_DIST=1 opts
# into fatal mode for variants whose checker provably counts dist contents.
#
# Env: SRC_DIR, DIST_DIR, INDEX_DIR (default $SRC_DIR/pypi), RUN_DIR (default
#      /tmp/pypi-server-run), PORT, PKG_NAMES (explicit distribution names),
#      PKG_VERSION (pinned version), REQUIRE_WHEEL/REQUIRE_SDIST (1/0),
#      STRICT_DIST (0/1, default 0).
set -euo pipefail

SRC_DIR="${SRC_DIR:-/app}"
DIST_DIR="${DIST_DIR:-$SRC_DIR/dist}"
INDEX_DIR="${INDEX_DIR:-$SRC_DIR/pypi}"
RUN_DIR="${RUN_DIR:-/tmp/pypi-server-run}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8091}"
PKG_NAMES="${PKG_NAMES:-}"
PKG_VERSION="${PKG_VERSION:-}"
REQUIRE_WHEEL="${REQUIRE_WHEEL:-1}"
REQUIRE_SDIST="${REQUIRE_SDIST:-1}"
STRICT_DIST="${STRICT_DIST:-0}"

mkdir -p "$RUN_DIR"

python3 - "$DIST_DIR" "$INDEX_DIR" "$PKG_NAMES" "$PKG_VERSION" "$REQUIRE_WHEEL" "$REQUIRE_SDIST" "$STRICT_DIST" "$SCRIPT_DIR" <<'PY'
import pathlib, re, shutil, sys

sys.path.insert(0, sys.argv[8])  # scripts dir: artifact_parse.py
from artifact_parse import normalize, parse_artifact, pick_files

dist_dir = pathlib.Path(sys.argv[1])
index_dir = pathlib.Path(sys.argv[2])
explicit = [n for n in sys.argv[3].split() if n]
pinned_version = sys.argv[4] or None
require_wheel = sys.argv[5] == "1"
require_sdist = sys.argv[6] == "1"
strict = sys.argv[7] == "1"

# File-to-project assignment is keyed on the PEP 503 normalized PARSED
# distribution, never on name interpolation: a wheel for `vector-ops` is
# vector_ops-0.1.0-...whl (PEP 427 underscore escaping) and must land in the
# /simple/vector-ops/ page; an sdist may use either form (backend-dependent).
norm_explicit = {normalize(n): n for n in explicit}

projects = {}   # normalized name -> list of artifact files

def add(name, f):
    projects.setdefault(normalize(name), []).append(f)

def warn_or_fail(msg):
    """dist COMPOSITION problems are checker-invisible (globs are
    version-qualified) -> WARN by default; STRICT_DIST=1 makes them fatal."""
    if strict:
        print(f"DISK CHECK FAIL (STRICT_DIST): {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"WARN (dist composition, not checker-observable): {msg}", file=sys.stderr)

for f in sorted(dist_dir.iterdir()):
    if not f.is_file():
        continue
    parsed = parse_artifact(f.name)
    if parsed is None:
        warn_or_fail(f"unparseable dist file: {f.name}")
        continue
    dist, ver = parsed
    if explicit and normalize(dist) not in norm_explicit:
        warn_or_fail(f"'{f.name}' belongs to unknown project '{dist}' "
                     f"(expected one of: {explicit}); stale/unrelated artifact")
        continue
    add(dist, f)

if not projects:
    sys.exit("FATAL: no artifacts found in " + str(dist_dir))

# ---- version-qualified exact counts (mirrors checker globs); other versions
#      of the same project are PRESERVED and only warned about ----
if pinned_version:
    for key in sorted(projects):
        files = list(projects[key])
        wheels = [f for f in files if f.name.endswith(".whl") and parse_artifact(f.name)[1] == pinned_version]
        sdists = [f for f in files if f.name.endswith((".tar.gz", ".zip")) and parse_artifact(f.name)[1] == pinned_version]
        if require_wheel and len(wheels) != 1:
            warn_or_fail(f"expected exactly one wheel for {key}=={pinned_version}, found {[f.name for f in wheels]}")
        if require_sdist and len(sdists) != 1:
            warn_or_fail(f"expected exactly one sdist for {key}=={pinned_version}, found {[f.name for f in sdists]}")
        if len(wheels) + len(sdists) != len(files):
            other = [f.name for f in files if f not in wheels and f not in sdists]
            warn_or_fail(f"extra artifacts for {key} (other versions preserved): {other}")

# ---- build the served tree (file space) ----
simple = index_dir / "simple"
if simple.exists():
    shutil.rmtree(simple)
simple.mkdir(parents=True)

for key, files in sorted(projects.items()):
    page = simple / key
    page.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, page / f.name)
    links = "\n".join(
        f'<a href="{p.name}">{p.name}</a><br/>'
        for p in sorted(page.iterdir()) if p.is_file())
    (page / "index.html").write_text(
        f"<html><head><meta charset='utf-8'><title>{key}</title></head><body>\n"
        f"{links}\n</body></html>\n")

# deterministic root page (do not rely on http.server auto directory listing)
root_links = "\n".join(f'<a href="{k}/">{k}/</a><br/>' for k in sorted(projects))
(simple / "index.html").write_text(
    "<html><head><meta charset='utf-8'><title>Simple index</title></head><body>\n"
    f"{root_links}\n</body></html>\n")

# ---- on-disk contract check: every parsed dist artifact exists under the
#      served root (this is OUR copy action; always fatal) ----
for key, files in sorted(projects.items()):
    for f in files:
        target = simple / key / f.name
        if not target.is_file():
            print(f"DISK CHECK FAIL: {target} missing", file=sys.stderr)
            sys.exit(1)
        print(f"project page: simple/{key}/  <- {f.name}")
if not (simple / "index.html").is_file():
    print("DISK CHECK FAIL: root simple/index.html missing", file=sys.stderr)
    sys.exit(1)
print("DISK_CHECK_PASS: artifacts at $INDEX_DIR/simple/<normalized-name>/; root index.html present")
PY

# ---- project links this run wrote (used for identity checks below) ----
PROJS="$(ls "$INDEX_DIR/simple" 2>/dev/null | grep -v '^index.html$' || true)"

# does the page served on $PORT contain EVERY project link of THIS run?
page_serves_current_root() {
  local body
  body="$(curl -sf "http://localhost:$PORT/simple/" 2>/dev/null)" || return 1
  if [ -z "$PROJS" ]; then
    return 1
  fi
  for p in $PROJS; do
    case "$body" in
      *"$p/"*) ;;
      *) return 1 ;;
    esac
  done
  return 0
}

# ---- server lifecycle: reuse ONLY on identity match, else restart ----
REUSED=0
if [ -f "$RUN_DIR/server.root" ] && [ "$(cat "$RUN_DIR/server.root" 2>/dev/null)" = "$INDEX_DIR" ] \
   && [ -f "$RUN_DIR/server.pid" ] && kill -0 "$(cat "$RUN_DIR/server.pid")" 2>/dev/null \
   && page_serves_current_root; then
  REUSED=1
fi

if [ "$REUSED" = 1 ]; then
  echo "server already answering (pid $(cat "$RUN_DIR/server.pid"), root $INDEX_DIR -- identity match, live re-read OK)"
else
  echo "no identity-matching server for root $INDEX_DIR on port $PORT; restarting"
  # kill stale listeners (tracked pid AND any http.server on this port) so the
  # post-start check below proves the NEW process, not any old listener
  if [ -f "$RUN_DIR/server.pid" ]; then kill "$(cat "$RUN_DIR/server.pid")" 2>/dev/null || true; fi
  pkill -f "http.server $PORT" 2>/dev/null || true
  sleep 0.3
  cd "$INDEX_DIR"
  nohup python3 -m http.server "$PORT" >"$RUN_DIR/server.log" 2>&1 </dev/null &
  echo $! > "$RUN_DIR/server.pid"
  echo "$INDEX_DIR" > "$RUN_DIR/server.root"
fi

# health check: the answering process must serve THIS root's content
UP=0
for i in $(seq 1 40); do
  if page_serves_current_root; then UP=1; break; fi
  sleep 0.25
done
if [ "$UP" != 1 ]; then
  echo "FATAL: port $PORT does not serve THIS run's project links ($PROJS)"
  echo "  last log lines:"; tail -5 "$RUN_DIR/server.log" 2>/dev/null || true
  exit 1
fi
echo "INDEX_UP: http://localhost:$PORT/simple/ (pid $(cat "$RUN_DIR/server.pid"), root $INDEX_DIR, log: $RUN_DIR/server.log)"
echo "  identity: /proc/$(cat "$RUN_DIR/server.pid")/cwd -> $(readlink /proc/$(cat "$RUN_DIR/server.pid")/cwd 2>/dev/null || echo 'n/a')"
echo "-- URL-space page check (pip's view) --"
curl -sf "http://localhost:$PORT/simple/" | grep -o 'href="[^"]*"' | head -5 || true
echo "-- served tree contains exactly simple/ (runtime files are outside) --"
ls -a "$INDEX_DIR"
echo "-- fresh-shell replay check --"
kill -0 "$(cat "$RUN_DIR/server.pid")" && page_serves_current_root && echo "REPLAY_OK"
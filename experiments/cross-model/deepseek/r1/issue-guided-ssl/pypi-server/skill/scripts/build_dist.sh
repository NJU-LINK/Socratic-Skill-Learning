#!/usr/bin/env bash
# Stage 3: build the artifacts. Default requirement: BOTH sdist and wheel.
# Env: SRC_DIR, DIST_DIR.
#
# Route chain:
#   1. `python3 -m build` (isolated; downloads build deps -- needs NET_OK)
#   2. install `build` via pip, then (1)
#   3. `python3 -m build --no-isolation` using locally installed setuptools/wheel (offline)
set -euo pipefail

SRC_DIR="${SRC_DIR:-/app}"
DIST_DIR="${DIST_DIR:-$SRC_DIR/dist}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SRC_DIR/pyproject.toml" ] && [ ! -f "$SRC_DIR/setup.py" ]; then
  echo "FATAL: no build metadata (pyproject.toml or setup.py) in $SRC_DIR" >&2
  exit 1
fi

rm -rf "$DIST_DIR"; mkdir -p "$DIST_DIR"

if python3 -m build --version >/dev/null 2>&1; then
  (cd "$SRC_DIR" && python3 -m build --outdir "$DIST_DIR" .)
elif python3 -m pip install -q build 2>/dev/null && python3 -m build --version >/dev/null 2>&1; then
  (cd "$SRC_DIR" && python3 -m build --outdir "$DIST_DIR" .)
else
  echo "build module unavailable; trying --no-isolation with local setuptools/wheel"
  (cd "$SRC_DIR" && python3 -m build --no-isolation --outdir "$DIST_DIR" .) \
    || { echo "FATAL: cannot build (no build module, no network, or missing setuptools/wheel)" >&2; exit 1; }
fi

echo "== BUILD artifacts in $DIST_DIR =="
ls -la "$DIST_DIR"

if ls "$DIST_DIR"/*.whl >/dev/null 2>&1 && { ls "$DIST_DIR"/*.tar.gz >/dev/null 2>&1 || ls "$DIST_DIR"/*.zip >/dev/null 2>&1; }; then
  echo "BUILD_PASS: sdist + wheel present"
else
  echo "WARNING: not both sdist and wheel present -- check task spec (wheel-only / source-only variants exist)" >&2
fi

# ---- artifact-content gate (mirrors the checker, which OPENS the archives) ----
# The v01 checker inspects the wheel zip (package __init__.py present;
# .dist-info/METADATA contains 'Name: <pkg>' and 'Version: <ver>') and the
# sdist tar (pyproject.toml present; src/<imp>/__init__.py present). A build
# can install fine yet fail these; since the checker discriminates them, this
# gate is fatal (mirror exactly, neither fewer nor more observations).
echo "== artifact-content gate =="
REQUIRE_WHEEL="${REQUIRE_WHEEL:-1}"
REQUIRE_SDIST="${REQUIRE_SDIST:-1}"
IMPORT_NAME="${IMPORT_NAME:-$(printf '%s' "${PKG_NAME:-}" | tr '-' '_')}"
python3 - "$DIST_DIR" "${PKG_NAME:-}" "${PKG_VERSION:-}" "$IMPORT_NAME" "$REQUIRE_WHEEL" "$REQUIRE_SDIST" "$SCRIPT_DIR" <<'PY'
import pathlib, re, sys, zipfile, tarfile

sys.path.insert(0, sys.argv[7])  # scripts dir: artifact_parse.py
from artifact_parse import normalize, parse_artifact, pick_files, parse_meta_name

dist_dir = pathlib.Path(sys.argv[1]); pkg = sys.argv[2]; ver = sys.argv[3]
imp = sys.argv[4]; rw = sys.argv[5] == "1"; rs = sys.argv[6] == "1"
if not pkg or not ver:
    print("artifact-content gate skipped (PKG_NAME/PKG_VERSION unset)")
    sys.exit(0)
norm = normalize(pkg)

def fail(msg):
    print("ARTIFACT CONTENT FAIL:", msg, file=sys.stderr); sys.exit(1)

# PARSE, never reconstruct: the wheel filename may escape the name with
# underscores (PEP 427: vector-ops -> vector_ops-...whl); the sdist may use
# either form depending on backend. pick_files matches on the normalized
# PARSED distribution, so all forms land here.
if rw:
    wheels = pick_files(dist_dir, norm, ver, "wheel")
    if len(wheels) != 1:
        fail(f"expected exactly one wheel for {pkg}=={ver}, found {[w.name for w in wheels]}")
    with zipfile.ZipFile(wheels[0]) as z:
        names = z.namelist()
        if f"{imp}/__init__.py" not in names:
            fail(f"wheel lacks {imp}/__init__.py; has: {names[:8]}")
        meta = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
        if meta is None:
            fail("wheel lacks .dist-info/METADATA")
        text = z.read(meta).decode()
        # METADATA 'Name:' is the AUTHORED spelling; compare normalized
        meta_name = parse_meta_name(text)
        if meta_name is None or normalize(meta_name) != norm:
            fail(f"METADATA Name {meta_name!r} does not normalize to {norm!r}")
        if f"Version: {ver}" not in text:
            fail(f"METADATA lacks 'Version: {ver}'")
    print("wheel content OK:", wheels[0].name)

if rs:
    sdists = pick_files(dist_dir, norm, ver, "sdist")
    if len(sdists) != 1:
        fail(f"expected exactly one sdist for {pkg}=={ver}, found {[s.name for s in sdists]}")
    names = []
    if sdists[0].name.endswith(".zip"):
        with zipfile.ZipFile(sdists[0]) as z: names = z.namelist()
    else:
        with tarfile.open(sdists[0]) as t: names = t.getnames()
    if not any(n.endswith("/pyproject.toml") for n in names):
        fail("sdist lacks pyproject.toml")
    if not any(n.endswith(f"/src/{imp}/__init__.py") for n in names):
        fail(f"sdist lacks /src/{imp}/__init__.py")
    print("sdist content OK:", sdists[0].name)

print("ARTIFACT_CONTENT_PASS")
PY
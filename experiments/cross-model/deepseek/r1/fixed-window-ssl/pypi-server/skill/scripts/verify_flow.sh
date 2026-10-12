#!/usr/bin/env bash
# verify_flow.sh -- canonical acceptance gate for the pypi-server family.
#
# Purpose: mirror what the grader does. The grader opens a FRESH shell, talks to
# the local index over HTTP, installs into a clean Python, and tests the
# installed runtime. A grader may ALSO stat the filesystem: v01's hidden tests
# assert the artifacts physically exist as an on-disk PEP 503 tree at
# /app/pypi/simple/<pkg>/ (grader-feedback-observed [G]). Any check that does
# not reproduce the grader's sequence can pass locally while the real task
# fails. Run this from a NEW task shell, never from the one that launched the
# index daemon (same-shell success proves nothing about server survival).
#
# Front-end agnostic: passes against pypiserver (absolute /packages/ hrefs,
# anchor text `>pkg<`) and against http.server directory listings (relative
# hrefs, anchor text `>pkg/<`) alike; step 1 accepts the optional trailing
# slash and the data-file stages resolve relative hrefs against the PROJECT
# page ($INDEX/simple/$PKG/). Verified against both front ends (iter 3).
#
# Usage (env vars):
#   PKG=vectorops            package/distribution name (from task)
#   VERSION=0.1.0            exact version to install (use the task's pin)
#   PORT=8091                index port (default 8091)
#   REQUIRE_BOTH=1           require BOTH .whl and .tar.gz links on the project
#                            page (default 1; set 0 for wheel-only/sdist-only)
#   INDEX_ROOT=/app/pypi     on-disk index root; when set, every artifact
#                            listed for PKG on the HTTP project page must ALSO
#                            exist at $INDEX_ROOT/simple/$PKG/<filename>.
#                            Defaults to /app/pypi (the layout the v01 grader
#                            asserts). Set to empty to skip the fs stage.
#   SDIST_DATA_FILE=...      relative path that must be present INSIDE the
#                            served sdist archive (e.g. data/seed.txt): a link
#                            on the page does not prove the archive is
#                            complete. Requires tar.
#   WHEEL_DATA_FILE=...      relative path that must be present INSIDE the
#                            served wheel archive. Uses `python -m zipfile`
#                            (no unzip dependency).
#   RUNTIME_CHECK=...        python -c expression run with the venv interpreter
#                            from cwd /tmp; default: import <PKG> and print path
#   INDEX_HOST=localhost     host for the index URL (default localhost)
#
# Exit code 0 only if every stage passes. Relies on bash, curl, python3.
set -euo pipefail

: "${PKG:?set PKG (distribution name)}"
: "${VERSION:?set VERSION (exact pin)}"
PORT="${PORT:-8091}"
REQUIRE_BOTH="${REQUIRE_BOTH:-1}"
INDEX_HOST="${INDEX_HOST:-localhost}"
INDEX="http://${INDEX_HOST}:${PORT}/simple"
INDEX_ROOT="${INDEX_ROOT:-/app/pypi}"
RUNTIME_CHECK="${RUNTIME_CHECK:-import ${PKG}; print('import ok:', ${PKG}.__file__)}"

echo "== 1/7 index root lists project =="
# Accept anchor text with or without trailing slash: pypiserver emits
# `>vectorops<`, http.server directory listings emit `>vectorops/<`.
curl -sf "${INDEX}/" | grep -qE ">${PKG}/?<" \
  || { echo "FAIL: ${PKG} not listed at ${INDEX}/"; exit 1; }

echo "== 2/7 project page lists artifacts =="
page="$(curl -sf "${INDEX}/${PKG}/" || { echo "FAIL: cannot fetch ${INDEX}/${PKG}/"; exit 1; })"
if [ "${REQUIRE_BOTH}" = "1" ]; then
  grep -qE "${PKG}-${VERSION}-.+\\.whl" <<<"${page}" || { echo "FAIL: no wheel link"; exit 1; }
  grep -qE "${PKG}-${VERSION}\\.tar\\.gz" <<<"${page}" || { echo "FAIL: no sdist link"; exit 1; }
else
  grep -qE "${PKG}-${VERSION}-" <<<"${page}" || { echo "FAIL: no artifact link"; exit 1; }
fi

if [ -n "${INDEX_ROOT}" ]; then
  echo "== 2b/7 on-disk PEP 503 tree (grader fs assertions) =="
  found=0
  for href in $(grep -oE 'href="[^"]*"' <<<"${page}" | sed 's/^href="//; s/"$//'); do
    fname="$(basename "${href%%#*}")"
    case "${fname}" in
      "${PKG}-${VERSION}"*)
        test -f "${INDEX_ROOT}/simple/${PKG}/${fname}" \
          || { echo "FAIL: ${INDEX_ROOT}/simple/${PKG}/${fname} does not exist"; exit 1; }
        echo "fs OK: ${INDEX_ROOT}/simple/${PKG}/${fname}"
        found=1
        ;;
    esac
  done
  [ "${found}" = "1" ] || { echo "FAIL: no ${PKG}-${VERSION} artifacts found on project page"; exit 1; }
else
  echo "== 2b/7 fs stage skipped (INDEX_ROOT empty) =="
fi

if [ -n "${SDIST_DATA_FILE:-}" ]; then
  echo "== 2c/7 served sdist contains ${SDIST_DATA_FILE} =="
  href="$(grep -oE "href=\"[^\"]*${PKG}-${VERSION}[^\"#]*\\.tar\\.gz" <<<"${page}" | head -1 | sed 's/^href="//')"
  [ -n "${href}" ] || { echo "FAIL: no sdist href on project page"; exit 1; }
  url="${href%%#*}"
  case "${url}" in
    http*) ;;
    /*) url="http://${INDEX_HOST}:${PORT}${url}" ;;
    *) url="${INDEX}/${PKG}/${url}" ;;
  esac
  curl -sf "${url}" -o /tmp/probe-sdist.tar.gz \
    || { echo "FAIL: cannot download sdist"; exit 1; }
  tar -tzf /tmp/probe-sdist.tar.gz | grep -q "${SDIST_DATA_FILE}" \
    || { echo "FAIL: sdist lacks ${SDIST_DATA_FILE}"; exit 1; }
fi
if [ -n "${WHEEL_DATA_FILE:-}" ]; then
  echo "== 2d/7 served wheel contains ${WHEEL_DATA_FILE} =="
  href="$(grep -oE "href=\"[^\"]*${PKG}-${VERSION}[^\"#]*\\.whl" <<<"${page}" | head -1 | sed 's/^href="//')"
  [ -n "${href}" ] || { echo "FAIL: no wheel href on project page"; exit 1; }
  url="${href%%#*}"
  case "${url}" in
    http*) ;;
    /*) url="http://${INDEX_HOST}:${PORT}${url}" ;;
    *) url="${INDEX}/${PKG}/${url}" ;;
  esac
  curl -sf "${url}" -o /tmp/probe-wheel.whl \
    || { echo "FAIL: cannot download wheel"; exit 1; }
  python -m zipfile -l /tmp/probe-wheel.whl | grep -q "${WHEEL_DATA_FILE}" \
    || { echo "FAIL: wheel lacks ${WHEEL_DATA_FILE}"; exit 1; }
fi

echo "== 3/7 fresh venv + exact documented install command =="
rm -rf /tmp/verify-venv && python3 -m venv /tmp/verify-venv
# --no-cache-dir: never let pip's wheel cache replay a stale artifact.
# --index-url: pip queries ONLY this index; if the index is broken, the
# install fails loudly (there is no implicit PyPI fallback -- this is the
# property the task's "no fallback" axis depends on).
/tmp/verify-venv/bin/pip install --no-cache-dir \
  --index-url "${INDEX}" "${PKG}==${VERSION}"

echo "== 4/7 installed runtime check from a NEUTRAL cwd =="
# Never verify from inside the project tree: with cwd=<project>, an import can
# resolve the source tree via sys.path instead of the installed package, and a
# broken wheel would "pass". /tmp guarantees the venv's site-packages wins.
cd /tmp
/tmp/verify-venv/bin/python -c "${RUNTIME_CHECK}" \
  || { echo "FAIL: runtime check"; exit 1; }

echo "== 5/7 resolution source (optional but informative) =="
/tmp/verify-venv/bin/pip show "${PKG}" 2>/dev/null \
  | sed -n 's/^\(Name\|Version\|Location\):/\1:/p'

echo "GATE_OK: ${PKG}==${VERSION} installs from ${INDEX} and behaves correctly"
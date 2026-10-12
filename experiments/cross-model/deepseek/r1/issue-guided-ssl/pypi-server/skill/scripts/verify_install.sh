#!/usr/bin/env bash
# Stage 5: verify with the EXACT client command the spec promises, defeating
# the two classic self-deceptions:
#   1. pip's HTTP cache  -> --no-cache-dir
#   2. importing the source tree instead of the installed artifact
#      -> clean venv + neutral CWD + assert __file__ lives in site-packages
#
# Then install into the SYSTEM interpreter too, because the evaluation shell
# may import the package directly (run_tests_in_same_shell is false, so we
# cannot rely on venv state from an earlier shell).
#
# Env: PKG_NAME (distribution name), PKG_VERSION, INDEX_URL,
#      IMPORT_NAME (default: PKG_NAME with '-'->'_'), VERIFY_SNIPPET (a python
#      program run with the venv interpreter from a neutral CWD; default: import
#      + site-packages assertion), VERIFY_SNIPPET_FILE (path to a file
#      containing the program -- easier for multi-line snippets than env
#      quoting).
set -euo pipefail

PKG_NAME="${PKG_NAME:?PKG_NAME required}"
PKG_VERSION="${PKG_VERSION:-}"
IMPORT_NAME="${IMPORT_NAME:-$(printf '%s' "$PKG_NAME" | tr '-' '_')}"
INDEX_URL="${INDEX_URL:-http://localhost:8091/simple}"
PIN="${PKG_NAME}==${PKG_VERSION}"; [ -n "$PKG_VERSION" ] || PIN="$PKG_NAME"

if [ -n "${VERIFY_SNIPPET_FILE:-}" ] && [ -f "$VERIFY_SNIPPET_FILE" ]; then
  VERIFY_SNIPPET="$(cat "$VERIFY_SNIPPET_FILE")"
fi

if [ -z "${VERIFY_SNIPPET:-}" ]; then
  VERIFY_SNIPPET=$(printf 'import %s\nprint("installed at:", %s.__file__)\nassert "site-packages" in %s.__file__, "NOT imported from site-packages"\n' "$IMPORT_NAME" "$IMPORT_NAME" "$IMPORT_NAME")
fi

VENV_DIR="$(mktemp -d /tmp/vcheck.XXXXXX)/venv"
python3 -m venv "$VENV_DIR"

echo "== installing into clean venv: pip install --no-cache-dir --index-url $INDEX_URL $PIN =="
"$VENV_DIR/bin/pip" install --no-cache-dir --index-url "$INDEX_URL" "$PIN" 2>&1 | tail -n 4

echo "== running behavior check from neutral CWD (/tmp) =="
( cd /tmp && "$VENV_DIR/bin/python" -c "$VERIFY_SNIPPET" )

echo "== installing into system interpreter (eval shell may import directly) =="
python3 -m pip install --no-cache-dir --index-url "$INDEX_URL" "$PIN" 2>&1 | tail -n 2

echo "VERIFY_PASS"
if [ -n "${SERVER_LOG:-}" ] && [ -f "$SERVER_LOG" ]; then
  echo "-- server log: pip artifact GETs --"
  grep -E "GET /simple/.*/" "$SERVER_LOG" | tail -3 || true
else
  echo "-- (optional) confirm the artifact GETs in $RUN_DIR/server.log --"
fi
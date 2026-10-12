#!/bin/bash
# verify_artifacts.sh — prove that the stored artifacts reproduce the output.
#
# Rebuilds the jq command from jq_args.yaml EXACTLY the way the grader does:
#   jq $(yq -r '.args[]' ARGS) "$(yq -r '.filter' ARGS)" INPUT > tmp
# then byte-compares the result with the produced output file.
# Optionally also re-runs cmd.sh into a temp file and byte-compares that too.
#
# Usage:
#   verify_artifacts.sh INPUT_JSON OUTPUT_JSON [JQ_ARGS_YAML] [CMD_SH]
# Defaults: JQ_ARGS_YAML=/app/jq_args.yaml  (CMD_SH skipped unless given)
set -uo pipefail

IN="${1:?usage: verify_artifacts.sh INPUT_JSON OUTPUT_JSON [JQ_ARGS_YAML] [CMD_SH]}"
OUT="${2:?usage: verify_artifacts.sh INPUT_JSON OUTPUT_JSON [JQ_ARGS_YAML] [CMD_SH]}"
ARGS="${3:-/app/jq_args.yaml}"
CMD="${4:-}"

fail=0

# --- Lint the artifact shape (mirrors the grader's structural asserts) ---
KEYS="$(yq -r 'keys | join(",")' "$ARGS" 2>/dev/null)"
if [ "$KEYS" != "args,filter" ] && [ "$KEYS" != "filter,args" ]; then
  echo "FAIL: $ARGS keys must be exactly {filter, args}, got: $KEYS"
  fail=1
fi
# filter must be a string, args a list of strings each starting with '-'
# portable type checks (works with both python-yq and mikefarah yq)
if [ "$(yq -r '.filter | type' "$ARGS" 2>/dev/null)" != "string" ]; then
  echo "FAIL: .filter is not a string"; fail=1
fi
if [ "$(yq -r '.args | type' "$ARGS" 2>/dev/null)" != "array" ]; then
  echo "FAIL: .args is not a list"; fail=1
fi
BAD="$(yq -r '.args[]' "$ARGS" 2>/dev/null | grep -v '^-')"
if [ -n "$BAD" ]; then
  echo "FAIL: every .args[] item must start with '-' (flag+value = ONE item)."
  echo "      Offending item(s): $(echo "$BAD" | tr '\n' ' ')"
  echo "      e.g. write [\"--indent 2\"], not [\"--indent\", \"2\"]"
  fail=1
fi
[ $fail -eq 0 ] && echo "OK:   jq_args.yaml shape lint (keys, types, args items)"

TMP_RECON="$(mktemp)"
# NOTE: the unquoted $(...) word-splitting below is intentional — it mirrors
# the grader's reconstruction template verbatim.
# shellcheck disable=SC2046
jq $(yq -r '.args[]' "$ARGS") "$(yq -r '.filter' "$ARGS")" "$IN" > "$TMP_RECON"
rc=$?
if [ $rc -ne 0 ]; then
  echo "FAIL: reconstruction from $ARGS exited $rc"
  fail=1
elif cmp -s "$TMP_RECON" "$OUT"; then
  echo "OK:   jq_args.yaml reconstruction matches $OUT ($(jq 'if type=="array" then length else "object" end' "$OUT" 2>/dev/null) top-level items)"
else
  echo "FAIL: reconstruction from $ARGS differs from $OUT"
  diff <(head -20 "$TMP_RECON") <(head -20 "$OUT") | head -30
  fail=1
fi
rm -f "$TMP_RECON"

if [ -n "$CMD" ]; then
  # Do NOT rewrite cmd.sh's redirection with sed — filters legitimately
  # contain '>' (e.g. "user <email>"). Instead: back up OUT, run cmd.sh
  # verbatim (it regenerates OUT), compare against the backup, restore backup.
  TMP_BAK="$(mktemp)"
  cp "$OUT" "$TMP_BAK"
  bash "$CMD"
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FAIL: cmd.sh exited $rc"
    cp "$TMP_BAK" "$OUT"   # restore clobbered output
    fail=1
  elif cmp -s "$TMP_BAK" "$OUT"; then
    echo "OK:   cmd.sh reproduces $OUT"
  else
    echo "FAIL: cmd.sh output differs from $OUT"
    cp "$TMP_BAK" "$OUT"   # never leave a clobbered output behind
    fail=1
  fi
  rm -f "$TMP_BAK"
fi

# Cheap structural spot checks on the output itself.
jq -e . "$OUT" > /dev/null || { echo "FAIL: $OUT is not valid JSON"; fail=1; }

if [ $fail -eq 0 ]; then
  echo "ALL CHECKS PASSED"
else
  echo "CHECKS FAILED"
fi
exit $fail

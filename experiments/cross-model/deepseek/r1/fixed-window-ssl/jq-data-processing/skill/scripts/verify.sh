#!/usr/bin/env bash
# verify.sh - acceptance test for the jq-data-processing packaging contract.
#
# Usage:
#   verify.sh JQ_ARGS_YAML INPUT OUTPUT [--expected N] [--direct "FILTER"] [--cmd PATH]
#
#   --expected N   assert the produced array has exactly N rows
#   --direct F     also run the same filter typed as a direct single-quoted
#                  argument (same args as the yaml, so flags are fair) and
#                  require byte-identical output to the wrapper run
#   --cmd PATH     check the saved cmd.sh: exists, non-empty, EXECUTABLE
#                  (chmod +x only - no shebang, content must stay exactly the
#                  reconstruction line), and references the output path
#
# Steps (all exit nonzero on failure - fail loudly, distinguishable lines):
#   0. jq_args.yaml has exactly the keys: args, filter
#   1. EVERY args item starts with "-"  (grader contract [iteration-1]: the
#      item '2' in ["--indent","2"] failed the grader's startswith("-")
#      assertion). Flag+value travel in ONE item; the reconstruction's
#      unquoted $(yq -r '.args[]' ...) expansion word-splits it.
#   2. byte-level escape audit: no 4+-backslash runs in the filter
#      (over-escaped "\\\\s" compiles to a literal-backslash regex that
#      silently matches nothing - the #1 silent failure in this family)
#   3. run the VERBATIM reconstruction line
#      `jq $(yq -r '.args[]' YAML) "$(yq -r '.filter' YAML)" INPUT > OUTPUT`
#      (executed inline - never rebuilt through a variable, which would add
#      re-parsing layers); optional byte-compare against a direct run
#   4. output is valid JSON (type reported); when --expected N is given,
#      output must be an ARRAY of length N; ALWAYS-ON indent check: reads
#      `--indent N` from args when present, else asserts jq's default 2
#      spaces; skipped only for compact output (-c/--compact-output) or
#      single-line output
#   5. cmd.sh metadata/content (with --cmd PATH)
#
# Operating note: inside the task container the skill package may be mounted
# read-only at /skill (root = the family dir). Host-workspace paths are NOT
# visible to the container - invoking a host path fails with exit 127. If this
# script cannot be reached, copy it to /app or run SKILL.md §5's inline
# acceptance commands.
set -euo pipefail

YAML="${1:?usage: verify.sh JQ_ARGS_YAML INPUT OUTPUT [--expected N] [--direct \"FILTER\"] [--cmd PATH]}"
INPUT="${2:?}"; OUTPUT="${3:?}"; shift 3

EXPECTED=""; DIRECT=""; CMDFILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --expected) EXPECTED="${2:?--expected needs a value}"; shift 2 ;;
    --direct)   DIRECT="${2:?--direct needs a filter}"; shift 2 ;;
    --cmd)      CMDFILE="${2:?--cmd needs a path}"; shift 2 ;;
    *) echo "FAIL: unknown option '$1'"; exit 2 ;;
  esac
done

command -v jq >/dev/null 2>&1 || { echo "FAIL: jq not found (PATH=${PATH})"; exit 1; }
command -v yq >/dev/null 2>&1 || { echo "FAIL: yq not found (PATH=${PATH})"; exit 1; }
[ -f "$YAML" ]  || { echo "FAIL: $YAML missing"; exit 1; }
[ -f "$INPUT" ] || { echo "FAIL: $INPUT missing"; exit 1; }

# --- Step 0: contract keys -------------------------------------------------
KEYS="$(yq -r 'keys | sort | join(",")' "$YAML")"
[ "$KEYS" = "args,filter" ] || { echo "FAIL: keys are '$KEYS', want exactly 'args,filter'"; exit 1; }
echo "PASS: yaml keys are exactly args,filter"

# --- Step 1: args item contract (grader-evidenced) -------------------------
# Grader asserts arg.startswith("-") for every item. ["--indent","2"] fails
# on the item '2'; ["--indent 2"] passes (word-split by the reconstruction);
# [] passes vacuously. --indent=2 is rejected by jq 1.6 ("Unknown option").
BAD="$(yq -r '.args[]' "$YAML" | grep -v '^-' || true)"
if [ -n "$BAD" ]; then
  echo "FAIL: every args item must start with '-' (grader contract, iteration-1 evidence);"
  echo "      offending item(s):"
  printf '%s\n' "$BAD" | sed 's/^/        /'
  echo "      Flag and value must travel in ONE item (e.g. \"--indent 2\"), never separate items."
  exit 1
fi
echo "PASS: every args item starts with '-' (grader contract)"

# --- Step 2: escape audit --------------------------------------------------
echo "--- Step 2: filter escape audit ---"
yq -r '.filter' "$YAML" | od -c | sed -n '1,12p'
# sed reads to EOF (no SIGPIPE on the producer); grep reads all input too
# (no -q early exit) so pipefail cannot kill a producer
if yq -r '.filter' "$YAML" | grep -F '\\\\' >/dev/null; then
  echo "FAIL: 4+-backslash run found in filter (over-escaped regex -> silent no-match)."
  echo "      Only acceptable if the task must match a literal backslash."
  exit 1
fi
echo "PASS: no 4+-backslash runs in filter"

# --- Step 3: verbatim reconstruction + optional direct cmp -----------------
echo "--- Step 3: run the verbatim reconstruction line ---"
# The grader runs exactly this shape; execute it inline, do NOT reassemble it
# in a variable (a second parsing layer changes word-splitting/escaping).
jq $(yq -r '.args[]' "$YAML") "$(yq -r '.filter' "$YAML")" "$INPUT" > "$OUTPUT" \
  || { echo "FAIL: reconstruction command exited nonzero"; exit 1; }
echo "PASS: reconstruction produced $OUTPUT"

if [ -n "$DIRECT" ]; then
  TMP="$(mktemp)"
  # Fair comparison: same args as stored in the yaml, filter given literally.
  jq $(yq -r '.args[]' "$YAML") "$DIRECT" "$INPUT" > "$TMP" \
    || { echo "FAIL: direct single-quoted run exited nonzero"; rm -f "$TMP"; exit 1; }
  if cmp -s "$OUTPUT" "$TMP"; then
    echo "PASS: wrapper output byte-identical to direct run"
  else
    echo "FAIL: wrapper output differs from direct run"
    diff <(head -c 2000 "$OUTPUT") <(head -c 2000 "$TMP") || true
    rm -f "$TMP"; exit 1
  fi
  rm -f "$TMP"
else
  echo "SKIP: no --direct filter given (byte-cmp mode off)"
fi

# --- Step 4: output sanity -------------------------------------------------
echo "--- Step 4: output sanity ---"
jq -e 'true' "$OUTPUT" >/dev/null 2>&1 \
  || { echo "FAIL: output is not valid JSON"; exit 1; }
OTYPE="$(jq -r 'type' "$OUTPUT")"
echo "PASS: output is valid JSON (type: $OTYPE)"

if [ -n "$EXPECTED" ]; then
  if [ "$OTYPE" != "array" ]; then
    echo "FAIL: --expected $EXPECTED requires an array output, got type $OTYPE"; exit 1
  fi
  ROWS="$(jq 'length' "$OUTPUT")"
  jq -e --argjson n "$EXPECTED" 'length == $n' "$OUTPUT" >/dev/null 2>&1 \
    || { echo "FAIL: row count $ROWS != expected $EXPECTED"; exit 1; }
  echo "PASS: row count == $EXPECTED ($OTYPE of $ROWS)"
fi

# Always-on indent check. Read --indent N from args (default: jq's own 2),
# so it stays honest for any N; awk reads its input to EOF (no SIGPIPE traps;
# never use `| head -1` inside a pipefail pipeline).
INDENT="$(yq -r '.args[]' "$YAML" | awk '$1=="--indent"{n=$2} END{print (n=="" ? 2 : n)}')"
COMPACT="$(yq -r '.args[]' "$YAML" | awk '$1=="-c"||$1=="--compact-output"{c=1} END{print (c=="" ? "" : "yes")}')"
if [ "$COMPACT" = "yes" ]; then
  echo "SKIP: compact output requested (-c/--compact-output), indent check skipped"
else
  SECOND="$(sed -n '2p' "$OUTPUT")"
  if [ -z "$SECOND" ]; then
    echo "SKIP: output is empty/single-line; indent check n/a"
  else
    LEAD="$(printf '%s\n' "$SECOND" | awk '{ match($0, /^ */); print RLENGTH }')"
    if [ "$LEAD" = "$INDENT" ]; then
      echo "PASS: ${INDENT}-space indentation"
    else
      echo "FAIL: expected ${INDENT}-space indent (from args or default), got $LEAD leading spaces on line 2"
      exit 1
    fi
  fi
fi

# --- Step 5: cmd.sh metadata + content (mode bits are part of the contract) -
if [ -n "$CMDFILE" ]; then
  echo "--- Step 5: cmd.sh check ---"
  [ -f "$CMDFILE" ] || { echo "FAIL: $CMDFILE missing"; exit 1; }
  [ -s "$CMDFILE" ] || { echo "FAIL: $CMDFILE is empty"; exit 1; }
  [ -x "$CMDFILE" ] || { echo "FAIL: $CMDFILE not executable - chmod +x it (no shebang; content must stay exactly the reconstruction line)"; exit 1; }
  grep -Fq -- "$OUTPUT" "$CMDFILE" || { echo "FAIL: $CMDFILE does not reference output path '$OUTPUT'"; exit 1; }
  grep -Fq "yq -r '.args[]'" "$CMDFILE" || { echo "FAIL: $CMDFILE lacks the args reconstruction (yq -r '.args[]')"; exit 1; }
  grep -Fq "yq -r '.filter'" "$CMDFILE" || { echo "FAIL: $CMDFILE lacks the filter reconstruction (yq -r '.filter')"; exit 1; }
  echo "PASS: cmd.sh exists, non-empty, executable, references output + reconstruction line"
fi

echo "ALL CHECKS PASSED"
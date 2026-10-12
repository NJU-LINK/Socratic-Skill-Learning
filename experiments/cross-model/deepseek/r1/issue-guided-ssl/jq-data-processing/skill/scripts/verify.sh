#!/usr/bin/env bash
# Rebuild-and-verify loop for jq-data-processing tasks.
#
# Usage:
#   IN=/app/users.json OUT=/app/verified_admin_contacts.json \
#   YAML=/app/jq_args.yaml CMD=/app/cmd.sh bash scripts/verify.sh
#
# Defaults match the v01 evaluator contract. The script has TWO LAYERS:
#   REUSABLE CORE (above the "TASK-SHAPED CHECKS" marker): rebuild from
#   jq_args.yaml via the evaluator command form, byte-identity cmp,
#   cmd.sh textual startswith + replay, ID-set diff machinery.
#   TASK-SHAPED CHECKS (below the marker): v01 literals/predicates
#   (exact yaml keys, field invariants, uniformity assumption). On ANY
#   other task these must be re-derived from the current instruction.
#   1. rebuilds output from jq_args.yaml using the EXACT evaluator command form,
#   2. cmp-checks the rebuilt file against the existing OUT (rebuild identity),
#   2b. checks cmd.sh's TEXTUAL contract (stripped content starts with 'jq ')
#       and replays it via `sh $CMD` from IN's directory, cmp vs REBUILT,
#   3. (below marker) runs v01-shaped semantic invariants,
#   4. (below marker) optionally cross-checks the ID set when IDSEL_JQ.
set -u

IN="${IN:-/app/users.json}"
OUT="${OUT:-/app/verified_admin_contacts.json}"
YAML="${YAML:-/app/jq_args.yaml}"
CMD="${CMD:-/app/cmd.sh}"
REBUILT="${REBUILT:-/tmp/jq_rebuilt.json}"

fail() { echo "FAIL: $1" >&2; exit 1; }

command -v jq >/dev/null || fail "jq not found"
command -v yq >/dev/null || fail "yq not found (fallback: run sh \$CMD and cmp manually)"
[ -f "$YAML" ] || fail "no $YAML"
[ -f "$IN" ] || fail "no $IN"

# --- 1. rebuild with the evaluator's exact command form --------------------
jq $(yq -r '.args[]' "$YAML") "$(yq -r '.filter' "$YAML")" "$IN" > "$REBUILT" \
  || fail "rebuild failed (jq error)"
echo "rebuild OK"

# args must be empty (self-contained filter) — otherwise the unquoted
# word-splitting makes the artifact fragile; warn but don't hard-fail.
NARGS=$(yq -r '.args | length' "$YAML" 2>/dev/null || echo 0)
if [ "$NARGS" != "0" ] && [ "$NARGS" != "null" ]; then
  echo "WARN: args is non-empty ($NARGS items) — rebuild is at risk of word-splitting"
fi

# --- 2. rebuild identity ----------------------------------------------------
if [ -f "$OUT" ]; then
  cmp -s "$OUT" "$REBUILT" && echo "rebuild-identical OK" \
    || { echo "DIFF between $OUT and rebuilt:"; diff "$OUT" "$REBUILT" | head -40; fail "rebuild identity"; }
else
  echo "note: $OUT does not exist; using rebuilt as reference"
  cp "$REBUILT" "$OUT"
fi

# --- 2b. cmd.sh textual contract + replay (grader simulation) -----------------
# v01 lesson: the grader asserts open(CMD_PATH).read().strip().startswith("jq ")
# — cmd.sh is TEXT, not a launchable script: no shebang/comments/cd. The local
# oracle previously validated only the yaml-rebuild path and never read cmd.sh,
# which is how a shebang-headed artifact passed locally and failed the grader.
[ -f "$CMD" ] || fail "no $CMD (instruction requires a command file)"
if command -v python3 >/dev/null 2>&1; then
  # exact replication of the grader predicate
  python3 -c "import sys; sys.exit(0 if open('$CMD', encoding='utf-8').read().strip().startswith('jq ') else 1)" \
    && echo "cmd contract: stripped content starts with 'jq ' OK" \
    || fail "cmd.sh does not start with 'jq ' after strip (grader does startswith check); write the bare command: no shebang/comments/cd"
else
  CMD_TEXT=$(sed -e 's/^[[:space:]]*//; s/[[:space:]]*$//' "$CMD")
  case "$CMD_TEXT" in
    jq\ *) echo "cmd contract: starts with 'jq ' OK" ;;
    *) fail "cmd.sh does not start with 'jq ' (grader does startswith check); remove any shebang/comments/cd" ;;
  esac
fi
# replay exactly as the grader would, from the input's directory
( cd "$(dirname "$IN")" && sh "$CMD" ) || fail "cmd.sh replay failed"
cmp -s "$OUT" "$REBUILT" && echo "cmd replay: output identical to yaml rebuild OK" \
  || { echo "DIFF between cmd.sh replay and yaml rebuild:"; diff "$OUT" "$REBUILT" | head -40; fail "cmd.sh replay differs from yaml rebuild"; }

# =============================================================================
# === TASK-SHAPED CHECKS BELOW (v01 literals/predicates).                   ===
# === THE REUSABLE VERIFICATION CORE ENDS ABOVE THIS LINE.                  ===
# =============================================================================
# Everything below is written against v01's instruction wording and output
# schema. On ANY other task, re-derive these predicates from the new
# instruction — NEVER inherit field names, exact yaml key literals, or the
# uniformity assumption. Why (jq mechanism): indexing a missing field yields
# null WITHOUT error. Equality/sort invariants on wrong field names then pass
# VACUOUSLY — probe: printf '[{"a":1},{"b":2}]' | jq -e
# '[.[].email_domain] == ([.[].email_domain] | sort)' -> true, exit 0,
# nothing checked — while string ops on the same nulls fail LOUDLY: probe:
# printf '[{"a":1},{"b":2}]' | jq -e 'all(.[]; (.phone | sub("^[[:space:]]+";
# "")) == .phone)' -> 'null (null) cannot be matched, as it is not a string',
# exit 5. The silent half mimics "ALL CHECKS PASSED" — exactly what must not
# be inherited across tasks.

# yaml textual contract (v01-shaped): the exact key set and args-item types
# come from v01's instruction wording ("exactly these keys: filter, args").
# On another task compare against the keys/args the CURRENT instruction
# names — do not copy these literals.
YKEYS=$(yq -r 'keys | sort | join(",")' "$YAML" 2>/dev/null)
[ "$YKEYS" = "args,filter" ] || fail "jq_args.yaml keys are [$YKEYS], expected exactly args,filter (v01 wording — re-derive per task)"
echo "yaml contract: keys exactly {args, filter} OK"
ARG_TYPES=$(yq -r '.args | map(type) | unique | join(",")' "$YAML" 2>/dev/null)
case "$ARG_TYPES" in
  ""|string) : ;;   # empty args (no items) or all items strings
  *) fail "jq_args.yaml args items are not all strings (types: $ARG_TYPES)" ;;
esac
[ "$NARGS" = "0" ] && echo "yaml contract: args is an empty list OK" \
  || echo "yaml contract: args has $NARGS string items (non-empty is allowed but word-splitting-risky)"

# --- 3. semantic invariants (v01-shaped; re-derive every predicate per task) -
# NOTE on jq scoping: inside all(.[]; E), `.` is the item. To inspect a field
# of the item you must write .field on the left; a bare `sort`/`unique` on the
# right side would sort the whole item. Write `.field | sort`, never `sort`
# alone, inside a per-item all().

jq -e '[.[].email_domain] == ([.[].email_domain] | sort)' "$REBUILT" >/dev/null \
  || fail "global order: email_domain not ascending"
echo "invariant: email_domain ascending OK"

jq -e 'all(group_by(.email_domain)[]; . == (sort_by(.username) | reverse))' "$REBUILT" >/dev/null \
  || fail "within-domain order: username not descending"
echo "invariant: username descending within domain OK"

# roles: each record's roles sorted+unique, and count matches — per-item, so
# reference the field on the left side of the pipe.
jq -e 'all(.[]; (.account_summary.roles == (.account_summary.roles | sort | unique)) and
                (.account_summary.role_count == (.account_summary.roles | length)))' "$REBUILT" >/dev/null \
  || fail "roles not sorted/unique or count mismatch"
echo "invariant: roles sorted+unique, role_count == length OK"

jq -e 'all(.[]; .phone == "unknown" or
                 ((.phone | sub("^[[:space:]]+"; "") | sub("[[:space:]]+$"; "")) == .phone))' "$REBUILT" >/dev/null \
  || fail "phone not trimmed or not 'unknown' fallback"
echo "invariant: phone trimmed-or-unknown OK"

jq -e 'all(.[]; (.last_login | type) == "string" and (.last_login | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}$")))' "$REBUILT" >/dev/null \
  || fail "last_login not YYYY-MM-DD"
echo "invariant: last_login date shape OK"

jq -e '[.[].contact] == [.[] | "\(.username) <\(.email)>"]' "$REBUILT" >/dev/null \
  || fail "contact not 'username <email>'"
echo "invariant: contact format OK"

jq -e 'all(.[]; .email_domain == (.email | sub("^[^@]*@"; "") | ascii_downcase))' "$REBUILT" >/dev/null \
  || fail "email_domain not derived from email"
echo "invariant: email_domain derivation OK"

# binding pitfall: inside index(f), `.` is the ARRAY, not the record — bind the
# record's fields to variables before use.
jq -e 'all(.[]; .account_summary as $s |
                 (((($s.roles | length) == 0) and ($s.primary_role == null)) or
                  ($s.roles[0] == $s.primary_role)))' "$REBUILT" >/dev/null \
  || fail "primary_role not first element of roles (or null when empty)"
echo "invariant: primary_role == roles[0] (or null) OK"

# Uniform top-level key set: TRUE ONLY for v01's contract (its grader asserts
# schema/shape uniformity). NOT family-true — a field_derivation variant may
# legitimately emit heterogeneous records, and this check would then fail on
# correct output (probe: printf '[{"a":1},{"b":2}]' | jq -e '(map(keys) |
# unique | length) == 1' -> false, exit 1). Enable only when the current
# instruction implies a uniform schema. Note: uniform keys do NOT make the
# field invariants above sound — '[{"x":1},{"x":2}]' passes this check
# while every email_domain/phone check stays vacuous.
jq -e '(map(keys) | unique | length) == 1' "$REBUILT" >/dev/null \
  || fail "output records do not share a uniform top-level key set"
echo "invariant: uniform top-level key set OK"

# --- 4. optional ID-set cross-check (machinery reusable; IDSEL_JQ task-shaped) -
# Set IDSEL_JQ to a filter RE-DERIVED FROM THE CURRENT INSTRUCTION that,
# applied to IN, prints the JSON array of eligible IDs computed INDEPENDENTLY
# (different expression style is best). The diff machinery is reusable; the
# filter itself is task-shaped like everything below the boundary.
# After step 2b, OUT has been regenerated by the cmd.sh replay; the ID set is
# computed from REBUILT, which cmp-verified equals OUT.
if [ -n "${IDSEL_JQ:-}" ]; then
  jq -c "$IDSEL_JQ" "$IN" > /tmp/jq_idsel_expected.txt || fail "IDSEL_JQ failed"
  jq -c '[.[].user_id] | sort' "$REBUILT" > /tmp/jq_idsel_actual.txt
  cmp -s /tmp/jq_idsel_expected.txt /tmp/jq_idsel_actual.txt \
    && echo "ID-set cross-check OK" \
    || { echo "ID-set mismatch:"; diff /tmp/jq_idsel_expected.txt /tmp/jq_idsel_actual.txt | head; fail "selection logic"; }
fi

echo "ALL CHECKS PASSED"
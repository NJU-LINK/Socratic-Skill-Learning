#!/usr/bin/env bash
# Regression harness for the html-finance-verify checker.
#
# Usage: bash selftest.sh [path-to-checker.py]
#   checker path defaults to ../checker.py relative to this script.
#
# Every fixture below pins either an expected answer (line,shown-wrong-value)
# or an expected abort (exit code 2, nothing written). Run after any checker
# change to detect regressions.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="${1:-$HERE/../checker.py}"
FIX="$HERE/fixtures"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
failed=0

# expect_answer <fixture> <line,value>
expect_answer() {
  local f="$1" want="$2" out code got
  out="$(python3 "$CHECKER" "$FIX/$f" --out "$TMP/ans.txt" 2>&1)"; code=$?
  got="$(cat "$TMP/ans.txt" 2>/dev/null || true)"
  if [ "$code" -eq 0 ] && [ "$got" = "$want" ]; then
    echo "PASS  $f -> $got"
  else
    echo "FAIL  $f: want '$want', exit=$code file='$got'"; failed=1
  fi
}

# expect_abort <fixture> <reason-substring>
expect_abort() {
  local f="$1" want="$2" out code
  rm -f "$TMP/ans.txt"   # checker never writes on abort; remove stale answer
  out="$(python3 "$CHECKER" "$FIX/$f" --out "$TMP/ans.txt" 2>&1)"; code=$?
  if [ "$code" -eq 2 ] && [ ! -s "$TMP/ans.txt" ] && grep -q "$want" <<<"$out"; then
    echo "PASS  $f (abort: $want)"
  else
    echo "FAIL  $f: want exit2 + '$want', exit=$code"; failed=1
  fi
}
# expect_exit3 <fixture> <wrong-pin> <then-answer>
# Documents the exit-3 path: pinning --expect with the seed's example answer
# on a variant whose answer differs must exit 3, print REGRESSION MISMATCH,
# and write nothing; re-running without --expect must write <then-answer>.
expect_exit3() {
  local f="$1" pin="$2" want="$3" out code got
  rm -f "$TMP/ans.txt"
  out="$(python3 "$CHECKER" "$FIX/$f" --out "$TMP/ans.txt" --expect "$pin" 2>&1)"; code=$?
  if [ "$code" -ne 3 ]; then echo "FAIL  $f: want exit 3 with --expect $pin, got exit=$code"; failed=1; return; fi
  if [ -s "$TMP/ans.txt" ]; then echo "FAIL  $f: exit 3 must not write a file"; failed=1; return; fi
  grep -q "REGRESSION MISMATCH" <<<"$out" || { echo "FAIL  $f: missing REGRESSION MISMATCH"; failed=1; return; }
  out="$(python3 "$CHECKER" "$FIX/$f" --out "$TMP/ans.txt" 2>&1)"; code=$?
  got="$(cat "$TMP/ans.txt" 2>/dev/null || true)"
  if [ "$code" -eq 0 ] && [ "$got" = "$want" ]; then
    echo "PASS  $f (exit3 with pin '$pin'; recovery -> $got)"
  else
    echo "FAIL  $f recovery: exit=$code file='$got'"; failed=1
  fi
}


echo "== resolved/regression answers =="
expect_answer v01_minimal.html    "210,60.8"
expect_answer subtotal_error.html "70,250.7"
expect_answer growth_error.html   "340,10.1"
expect_answer eps_error.html      "3,4.80"
expect_answer noheader.html       "70,19.5"
expect_answer root_gp_error.html  "130,521.4"   # resolver: dollar root of the fan
expect_answer unit_conversion.html "20,2,310"   # label-anchored unit conversion
expect_answer year_header.html    "340,10.1"    # year-only period headers
expect_answer conv_margin_error.html "210,60.8" # conversion row present; margin error emits, no dup-base refusal
expect_answer conv_row_error.html   "215,862,000" # margin consistent; wrong annotated row emits verbatim

echo "== abort rails =="
expect_abort consistent.html    "found 0"
expect_abort two_errors.html    "no unique root"
expect_abort dup_revenue.html   "duplicate base candidates"

echo "== exit-3 rail (--expect is a dev pin, not a runtime aid) =="
expect_exit3 subtotal_error.html "210,60.8" "70,250.7"

# Optional: real v01 report regression when present
if [ -f /app/q2_earnings_report.html ]; then
  echo "== live v01 =="
  expect_answer1() {
    local want="210,60.8" out code got
    out="$(python3 "$CHECKER" /app/q2_earnings_report.html --out "$TMP/ans.txt" --expect "$want" 2>&1)"; code=$?
    got="$(cat "$TMP/ans.txt" 2>/dev/null || true)"
    if [ "$code" -eq 0 ] && [ "$got" = "$want" ]; then
      echo "PASS  /app/q2_earnings_report.html -> $got"
    else
      echo "FAIL  live v01: exit=$code file='$got'"; failed=1
    fi
  }
  expect_answer1
fi

echo
if [ "$failed" -eq 0 ]; then echo "ALL SELFTESTS PASSED"; else echo "SELFTEST FAILURES"; fi
exit $failed
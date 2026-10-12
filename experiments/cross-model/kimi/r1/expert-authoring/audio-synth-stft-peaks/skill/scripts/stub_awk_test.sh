#!/usr/bin/env bash
# Rehearse the grader's awk-stub test (observed on v01, iteration 2):
#   * a fake `awk` is placed first on PATH; it logs every invocation and
#     prints fixed peaks content, ignoring its input entirely.
#   * After a full pipeline run AND after a peaks-only run:
#       - peaks.csv must equal the stub's stdout BYTE-FOR-BYTE
#         (no shell-added header, no post-processing of awk output), and
#       - awk must have been invoked EXACTLY ONCE per run.
# Usage: bash stub_awk_test.sh [path-to-run_audio_pipeline.sh]
set -euo pipefail
PIPELINE="${1:-/app/run_audio_pipeline.sh}"
PEAKS="${PEAKS_CSV:-/app/data/peaks.csv}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/awk" <<EOF
#!/bin/bash
printf 'invoked\n' >> "$tmp/awk.log"
printf 'frame,f1_bin,f2_bin,f3_bin\n'
printf '0,501,401,301\n'
printf '1,502,402,302\n'
EOF
chmod +x "$tmp/bin/awk"

printf 'frame,f1_bin,f2_bin,f3_bin\n0,501,401,301\n1,502,402,302\n' > "$tmp/expected"
fail=0

check() {  # $1=label
  if diff -q "$tmp/expected" "$PEAKS" >/dev/null; then
    echo "[PASS] $1: peaks.csv is byte-exactly the stub's stdout"
  else
    echo "[FAIL] $1: peaks.csv differs from stub stdout:"; diff "$tmp/expected" "$PEAKS" || true
    fail=1
  fi
  n="$(wc -l < "$tmp/awk.log")"
  if [ "$n" = "1" ]; then
    echo "[PASS] $1: awk invoked exactly once"
  else
    echo "[FAIL] $1: awk invoked $n times (expected 1)"; fail=1
  fi
}

: > "$tmp/awk.log"
env PATH="$tmp/bin:$PATH" bash "$PIPELINE" >/dev/null
check "full-pipeline"

: > "$tmp/awk.log"
env PATH="$tmp/bin:$PATH" PEAKS_ONLY=1 bash "$PIPELINE" >/dev/null
check "peaks-only"

echo "RESULT: $([ "$fail" = 0 ] && echo ALL PASS || echo FAILURES PRESENT)"
exit "$fail"

#!/usr/bin/env bash
# Orchestrates the audio-synth-stft-peaks pipeline:
#   python3 audioproc.py  -> data/clip.wav + data/mag.csv
#   awk                   -> data/peaks.csv (top-3 magnitude bins per frame)
# PEAKS_ONLY=1: only regenerate data/peaks.csv from an existing data/mag.csv.
#
# Variant knobs: top-k, output columns, CSV schema, and the awk program itself
# live in the awk block below. awk must be invoked by bare `awk` (PATH), never
# by absolute path; mawk and gawk both work (no asort/length(array)).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data

run_peaks_awk() {
  # Portable mawk/gawk top-3 extraction.
  # Rows arrive frame-major with ascending bin; strict '>' comparisons make
  # exact ties resolve to the lower bin index (first arrival).
  # NOTE the sentinel: cur is initialized to -1 in BEGIN. Unset cur would be
  # numerically ""==0 and frame 0 would never be emitted.
  awk '
    function emit() { print cur, b1, b2, b3 }
    BEGIN { FS=","; OFS=","; print "frame,f1_bin,f2_bin,f3_bin"; cur = -1 }
    NR == 1 { next }                     # skip mag.csv header
    { fid = $1 + 0; b = $2 + 0; v = $3 + 0   # numeric, never stringified
      if (fid != cur) {                  # cur=-1 sentinel: first row always inits
        if (cur >= 0) emit()
        cur = fid; m1 = m2 = m3 = -1e300; b1 = b2 = b3 = -1
      }
      if (v > m1)      { m3 = m2; b3 = b2; m2 = m1; b2 = b1; m1 = v; b1 = b }
      else if (v > m2) { m3 = m2; b3 = b2; m2 = v;  b2 = b }
      else if (v > m3) { m3 = v;  b3 = b }
    }
    END { if (cur >= 0) emit() }
  ' "$@"
}

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
  run_peaks_awk data/mag.csv > data/peaks.csv   # awk only, skip other steps
  exit 0
fi

python3 audioproc.py
run_peaks_awk data/mag.csv > data/peaks.csv
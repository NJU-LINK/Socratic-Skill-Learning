# extract_peaks.awk -- per-frame top-3 spectral peaks from mag.csv
# Usage:   awk -f extract_peaks.awk data/mag.csv > data/peaks.csv
# (identical logic to the inline block inside run_audio_pipeline.sh)
#
# Input schema (v01):  frame,bin,val  -- one row per bin per frame,
# frame-major with ascending bin, header line optional (first line skipped).
# Output schema:       frame,f1_bin,f2_bin,f3_bin  (0-indexed, header row)
#
# Portability: mawk + gawk only (no asort, no length(array), no %f traps).
# Numbers are compared purely as numerics ($x+0); only integer columns print.

function emit() { print cur, b1, b2, b3 }

BEGIN {
  FS = ","; OFS = ","
  print "frame,f1_bin,f2_bin,f3_bin"
  cur = -1                       # sentinel; unset cur == "" == 0 loses frame 0
}

NR == 1 { next }                 # skip input header

{
  fid = $1 + 0; b = $2 + 0; v = $3 + 0     # force numeric (mawk OFMT trap)
  if (fid != cur) {
    if (cur >= 0) emit()
    cur = fid
    m1 = m2 = m3 = -1e300; b1 = b2 = b3 = -1
  }
  # streaming insertion, descending magnitude; strict '>' => exact ties keep
  # the lower bin index (rows arrive in ascending bin order)
  if      (v > m1) { m3 = m2; b3 = b2; m2 = m1; b2 = b1; m1 = v; b1 = b }
  else if (v > m2) { m3 = m2; b3 = b2; m2 = v;  b2 = b }
  else if (v > m3) { m3 = v;  b3 = b }
}

END { if (cur >= 0) emit() }
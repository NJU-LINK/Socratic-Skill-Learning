#!/usr/bin/env bash
# Reference implementation: Pipeline orchestrator
# Supports PEAKS_ONLY=1 to skip synthesis/STFT and only run awk peak extraction.
#
# Architecture:
#   - Python (audioproc.py) produces clip.wav + mag.csv
#   - This script invokes awk for peaks.csv
#   - PEAKS_ONLY=1 skips Python, reads existing mag.csv
set -euo pipefail
cd /app
mkdir -p data

if [ "${PEAKS_ONLY:-0}" != "1" ]; then
    # Stages 1+2: WAV synthesis and STFT magnitude computation
    python3 audioproc.py
fi

# Stage 3: awk peak extraction (ALWAYS runs)
# Reads frame-major mag.csv, finds top-3 magnitude bins per frame.
# Uses streaming insertion sort — O(1) per bin, O(n_bins) per frame.
awk -F, '
BEGIN {
    OFS = ","
    cur_frame = -1
    print "frame,f1_bin,f2_bin,f3_bin"
}
NR == 1 { next }
{
    fr = $1 + 0
    bi = $2 + 0
    va = $3 + 0

    if (fr != cur_frame) {
        if (cur_frame >= 0) {
            print cur_frame, v1b, v2b, v3b
        }
        cur_frame = fr
        v1 = -1; v2 = -1; v3 = -1
        v1b = 0; v2b = 0; v3b = 0
    }

    # Insertion into top-3 slots (descending by magnitude)
    if (va > v1) {
        v3 = v2; v3b = v2b
        v2 = v1; v2b = v1b
        v1 = va; v1b = bi
    } else if (va > v2) {
        v3 = v2; v3b = v2b
        v2 = va; v2b = bi
    } else if (va > v3) {
        v3 = va; v3b = bi
    }
}
END {
    if (cur_frame >= 0) print cur_frame, v1b, v2b, v3b
}
' data/mag.csv > data/peaks.csv

echo "[pipeline] peaks.csv generated ($(wc -l < data/peaks.csv) lines including header)"

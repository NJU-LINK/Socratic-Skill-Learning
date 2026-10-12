#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="/app/data"
MAG_CSV="${DATA_DIR}/mag.csv"
PEAKS_CSV="${DATA_DIR}/peaks.csv"

# Configurable top-k (default 3)
TOP_K="${TOP_K:-3}"

mkdir -p "${DATA_DIR}"

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    echo "PEAKS_ONLY mode: extracting peaks from ${MAG_CSV}"
else
    echo "Running audioproc.py..."
    python3 /app/audioproc.py
fi

echo "Extracting top-${TOP_K} peaks with awk..."

awk -v TOP_K="${TOP_K}" -F, '
BEGIN {
    OFS = ","
    nbins = 0
    cur_frame = -1

    header = "frame"
    for (j = 1; j <= TOP_K; j++) {
        header = header ",f" j "_bin"
    }
    print header
}

NR == 1 { next }

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0

    if (cur_frame >= 0 && frame != cur_frame) {
        process_frame()
        delete bins
        delete vals
        nbins = 0
    }
    cur_frame = frame
    bins[nbins] = bin
    vals[nbins] = val
    nbins++
}

END {
    if (nbins > 0) process_frame()
}

function process_frame(    j, i, max_idx, max_val, line) {
    delete used
    line = cur_frame
    for (j = 1; j <= TOP_K; j++) {
        max_val = -1
        max_idx = -1
        for (i = 0; i < nbins; i++) {
            if (!(i in used) && vals[i] > max_val) {
                max_val = vals[i]
                max_idx = i
            }
        }
        if (max_idx >= 0) {
            used[max_idx] = 1
            line = line "," bins[max_idx]
        } else {
            line = line ",0"
        }
    }
    print line
}
' "${MAG_CSV}" > "${PEAKS_CSV}"

echo "Peaks written: ${PEAKS_CSV}"
echo "Pipeline complete."

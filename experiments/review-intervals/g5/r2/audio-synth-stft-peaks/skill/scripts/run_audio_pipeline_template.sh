#!/usr/bin/env bash
# Audio pipeline orchestration template
# Parameterized for variant adaptation
#
# CRITICAL FIX (from iteration-1 failure):
# The shell script must NOT use 'awk' for any purpose other than peak extraction.
# Tests may replace 'awk' in PATH with a stub that counts invocations.
# Do NOT use 'awk' for text processing, file size reporting, etc.

set -euo pipefail

cd /app
mkdir -p data

# === VARIANT CONFIGURATION ===
TOP_K=${TOP_K:-3}  # Number of peaks per frame; override with env var
# === END VARIANT CONFIGURATION ===

# ---------------------------------------------------------------------------
# AWK SCRIPT: General top-k peak extraction
# ---------------------------------------------------------------------------
# This awk program:
#   1. Skips the CSV header (NR==1)
#   2. Accumulates (bin, val) pairs per frame
#   3. On frame transition, selects top-k bins by magnitude (descending)
#   4. Outputs header + one row per frame
#
# Critical implementation details:
#   - cur_frame initialized to -1 so frame 0 triggers the transition
#   - got_frame flag prevents printing before first frame is complete
#   - END block outputs the last frame
#   - Function uses local variables (declared as extra parameters) to avoid
#     conflicts with global scope
# ---------------------------------------------------------------------------
read -r -d '' AWK_SCRIPT << 'AWKEOF' || true
function select_top_k(    i, j, max_idx, max_val) {
    for (i = 1; i <= top_k; i++) {
        max_idx = -1
        max_val = -1
        for (j = 0; j < n_bins; j++) {
            if (frame_vals[j] > max_val) {
                max_val = frame_vals[j]
                max_idx = j
            }
        }
        if (max_idx >= 0) {
            top_bins[i] = frame_bins[max_idx]
            frame_vals[max_idx] = -1  # Mark as used (magnitudes are >= 0)
        } else {
            top_bins[i] = 0  # Fallback if fewer bins than top_k
        }
    }
}

function emit_frame(    i) {
    select_top_k()
    printf "%d", cur_frame
    for (i = 1; i <= top_k; i++) {
        printf ",%d", top_bins[i]
    }
    printf "\n"
}

BEGIN {
    FS = ","
    OFS = ","
    cur_frame = -1
    got_frame = 0
    n_bins = 0

    # Build header dynamically based on top_k
    header = "frame"
    for (i = 1; i <= top_k; i++) {
        header = header ",f" i "_bin"
    }
    print header
}

NR == 1 { next }

{
    frame = $1 + 0
    bin_val = $2 + 0
    mag = $3 + 0

    if (frame != cur_frame) {
        # Transition: output previous frame if we have one
        if (got_frame) {
            emit_frame()
        }
        # Start new frame
        cur_frame = frame
        got_frame = 1
        delete frame_bins
        delete frame_vals
        delete top_bins
        n_bins = 0
    }

    frame_bins[n_bins] = bin_val
    frame_vals[n_bins] = mag
    n_bins++
}

END {
    if (got_frame) {
        emit_frame()
    }
}
AWKEOF

# ---------------------------------------------------------------------------
# PEAKS_ONLY mode
# ---------------------------------------------------------------------------
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk -v top_k="${TOP_K}" "${AWK_SCRIPT}" data/mag.csv > data/peaks.csv
    exit 0
fi

# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
python3 audioproc.py

# Peak extraction with awk - THE ONLY awk INVOCATION IN THIS SCRIPT
awk -v top_k="${TOP_K}" "${AWK_SCRIPT}" data/mag.csv > data/peaks.csv

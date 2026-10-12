#!/usr/bin/env bash
# Template: Audio pipeline orchestrator with PEAKS_ONLY mode
# Adapt TOP_K and file paths per variant.
set -euo pipefail

cd /app

TOP_K=${TOP_K:-3}  # Number of peaks per frame (default: 3)
MAG_CSV="/app/data/mag.csv"
PEAKS_CSV="/app/data/peaks.csv"

# Portable awk peak extraction (works with mawk and gawk)
# Reads: frame,bin,val (header + data rows)
# Writes: frame,f1_bin,f2_bin,...,fk_bin (header + data rows)
# Tie-breaking: lower bin index wins on equal magnitude
extract_peaks() {
    local k="$1"
    local input="$2"
    awk -F',' -v K="$k" '
    BEGIN {
        OFS = ","
        # Initialize top-k slots
        for (i = 1; i <= K; i++) {
            tv[i] = -1
            tb[i] = -1
        }
        prev_frame = -1
    }

    function flush_frame() {
        if (prev_frame < 0) return
        printf "%d", prev_frame
        for (i = 1; i <= K; i++) {
            printf ",%d", tb[i]
        }
        printf "\n"
    }

    function reset_topk() {
        for (i = 1; i <= K; i++) {
            tv[i] = -1
            tb[i] = -1
        }
    }

    function try_insert(bin, val,    j) {
        for (j = 1; j <= K; j++) {
            if (val > tv[j] || (val == tv[j] && tb[j] >= 0 && bin < tb[j])) {
                # Shift down from j to K
                for (s = K; s > j; s--) {
                    tv[s] = tv[s-1]; tb[s] = tb[s-1]
                }
                tv[j] = val; tb[j] = bin
                return
            }
        }
    }

    NR == 1 { next }
    {
        frame = $1 + 0
        bin   = $2 + 0
        val   = $3 + 0

        if (prev_frame >= 0 && frame != prev_frame) {
            flush_frame()
            reset_topk()
        }
        prev_frame = frame
        try_insert(bin, val)
    }
    END {
        flush_frame()
    }
    ' "$input"
}

# === PEAKS_ONLY MODE ===
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    echo "PEAKS_ONLY: extracting top-${TOP_K} peaks from ${MAG_CSV}"
    {
        # Build header dynamically
        header="frame"
        for i in $(seq 1 "$TOP_K"); do
            header="${header},f${i}_bin"
        done
        echo "$header"
        extract_peaks "$TOP_K" "$MAG_CSV"
    } > "$PEAKS_CSV"
    echo "Done: $PEAKS_CSV"
    exit 0
fi

# === FULL PIPELINE ===
echo "=== Step 1: Synthesize WAV + STFT ==="
python3 /app/audioproc.py

echo "=== Step 2: Extract top-${TOP_K} peaks via awk ==="
{
    header="frame"
    for i in $(seq 1 "$TOP_K"); do
        header="${header},f${i}_bin"
    done
    echo "$header"
    extract_peaks "$TOP_K" "$MAG_CSV"
} > "$PEAKS_CSV"

echo "=== Pipeline complete ==="
ls -la /app/data/

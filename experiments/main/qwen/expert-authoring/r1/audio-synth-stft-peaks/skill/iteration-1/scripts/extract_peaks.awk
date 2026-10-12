# extract_peaks.awk
# Extracts the top-K magnitude bins per frame from a frame/bin/value CSV.
#
# Usage:
#   echo "frame,f1_bin,f2_bin,f3_bin" > data/peaks.csv
#   awk -v K=3 -f extract_peaks.awk data/mag.csv >> data/peaks.csv
#
# Input CSV schema (from audioproc.py): frame,bin,val
#   - Rows must be sorted by frame (frame-major order from Python).
#   - Header row is skipped automatically.
#
# Output: one row per frame with the top-K bin indices in descending magnitude order.
#   The shell script is responsible for writing the output header before this script runs.
#
# Parameters:
#   K (int): number of top bins to extract (default: 3)

BEGIN {
    if (K == "") K = 3
    FS = ","
    cur = -1
    cnt = 0
}

NR == 1 { next }

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0

    if (frame != cur) {
        if (cur >= 0) flush()
        cur = frame
        cnt = 0
    }
    cnt++
    bins[cnt] = bin
    vals[cnt] = val
}

END {
    if (cur >= 0) flush()
}

function flush(    i, j, mx, tb, tv) {
    # Partial selection sort: extract top-K in descending order
    for (i = 1; i <= K && i <= cnt; i++) {
        mx = i
        for (j = i + 1; j <= cnt; j++) {
            if (vals[j] > vals[mx]) mx = j
        }
        if (mx != i) {
            tv = vals[i]; vals[i] = vals[mx]; vals[mx] = tv
            tb = bins[i]; bins[i] = bins[mx]; bins[mx] = tb
        }
    }
    # Emit: frame,bin1,bin2,...,binK
    printf "%d", cur
    for (i = 1; i <= K && i <= cnt; i++) printf ",%d", bins[i]
    printf "\n"
}

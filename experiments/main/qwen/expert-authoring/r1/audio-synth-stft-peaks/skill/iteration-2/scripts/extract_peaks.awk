# extract_peaks.awk
# Extracts the top-K magnitude bins per frame from a frame/bin/value CSV.
# Writes the complete output file including header (use > to redirect).
#
# Usage:
#   awk -v K=3 -f extract_peaks.awk data/mag.csv > data/peaks.csv
#
# Input:  frame,bin,val  CSV (frame-major order, header skipped)
# Output: frame,f1_bin,...,fk_bin  CSV (complete file with header)
#
# CRITICAL: This script writes the header itself in BEGIN. The shell script
# must NOT write a separate header, or stub-awk tests will produce duplicates.

BEGIN {
    if (K == "") K = 3
    FS = ","
    # Generate header dynamically
    hdr = "frame"
    for (i = 1; i <= K; i++) hdr = hdr ",f" i "_bin"
    print hdr
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

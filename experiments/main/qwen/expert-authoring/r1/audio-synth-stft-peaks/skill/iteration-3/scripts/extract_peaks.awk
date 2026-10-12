# extract_peaks.awk — Streaming top-K peak extraction from STFT magnitude CSV.
#
# Writes the COMPLETE output file (header + data). Use with > (overwrite):
#   awk -v K=3 -f extract_peaks.awk data/mag.csv > data/peaks.csv
#
# CRITICAL: The shell script must NOT write a separate header, or stub-awk
# tests will produce duplicate headers.
#
# Parameters:
#   K (int): number of top bins per frame (default: 3)

BEGIN {
    if (K == "") K = 3
    FS = ","
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
    printf "%d", cur
    for (i = 1; i <= K && i <= cnt; i++) printf ",%d", bins[i]
    printf "\n"
}

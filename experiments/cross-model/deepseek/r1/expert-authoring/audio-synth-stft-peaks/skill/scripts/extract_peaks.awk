# Top-k spectral-peak extractor for a "frame,bin,val" CSV (header row optional
# on input; tolerates blank lines and Python csv CRLF endings). Portable across
# gawk and mawk: POSIX subset only.
#
# Usage: awk -F, [-v k=3] [-v tie=first|last] [-v header="frame,f1_bin,f2_bin,f3_bin"] \
#             -f extract_peaks.awk mag.csv
#   k         : top magnitude bins reported per frame (default 3)
#   tie=first : equal magnitudes -> earlier row wins (smaller bin when bins
#               arrive in ascending order)
#   tie=last  : equal magnitudes -> later row wins (larger bin)
#   header    : if non-empty, printed as the output CSV's first line; pass the
#               exact column names the task requires (omit for no header)
#
# Input rows must be grouped by frame in ascending order (write the CSV
# frames-outer, bins-inner). Output: header (optional) + one row per frame.
BEGIN {
    if (k == 0) k = 3
    pf = -999999
    use_last = (tie == "last")
    if (header != "") print header
}
$1 !~ /^[-+0-9]/ || NF < 3 { next }      # skip header / blank lines
{
    f = $1 + 0; b = $2 + 0; v = $3 + 0
    if (f != pf && pf != -999999) { emit() }
    if (f != pf) {
        pf = f
        for (i = 1; i <= k; i++) { va[i] = -1; ba[i] = -1 }
    }
    for (i = 1; i <= k; i++)
        if (v > va[i] || (use_last && v == va[i])) {
            for (j = k; j > i; j--) { va[j] = va[j - 1]; ba[j] = ba[j - 1] }
            va[i] = v; ba[i] = b
            break
        }
}
function emit() {
    printf "%d", pf
    for (i = 1; i <= k; i++) printf ",%d", ba[i]
    printf "\n"
}
END { if (pf != -999999) emit() }
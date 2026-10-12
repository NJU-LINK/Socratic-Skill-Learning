# Portable streaming top-k awk script
# Usage: awk -F',' -v k=3 -f topk.awk mag.csv > peaks.csv
#
# Assumes mag.csv has schema: frame,bin,val
# Assumes rows for a frame are contiguous (frame-major order)
# Works with mawk, gawk, BusyBox awk (POSIX subset)

BEGIN {
    if (k < 1) k = 3
    hdr = "frame"
    for (i = 1; i <= k; i++) hdr = hdr ",f" i "_bin"
    print hdr
}
NR == 1 { next }                      # skip header
{
    frame = $1
    b = $2 + 0                          # +0 forces numeric, strips stray \r/space
    v = $3 + 0
    if (have && frame != prev) emit(prev)
    prev = frame; have = 1
    if (cnt < k)        pos = ++cnt     # insertion into descending top-k
    else if (v > val[k]) pos = k
    else next
    while (pos > 1 && val[pos-1] < v) { # strict <: ties keep earlier (lower) bin first
        val[pos] = val[pos-1]; bin[pos] = bin[pos-1]; pos--
    }
    val[pos] = v; bin[pos] = b
}
END { if (have) emit(prev) }
function emit(f,   i, line) {
    line = f
    for (i = 1; i <= k; i++) line = line "," bin[i]
    print line
    cnt = 0                             # val[]/bin[] slots 1..cnt get overwritten next frame
}

# peaks_buffered.awk -- buffered top-K spectral bins per frame.
#
# Use when the input CSV is NOT frame-major (bin-major or arbitrary row
# order) and the streaming peaks.awk contract cannot apply.  Same tie-break
# contract as peaks.awk (strict '>' insertion => first-seen wins; bins
# ascending within a frame => exact ties go to the SMALLEST bin index).
#
# CRITICAL: emission must be a NUMERIC SWEEP over tracked fmin..fmax with a
# membership guard -- NEVER `for (k in arr)`:
#   * for (k in arr) iterates in HASH order in both mawk and gawk; small
#     arrays frequently look ascending by coincidence (gawk often does),
#     so a local test proves nothing.
#   * PROCINFO["sorted_in"]="@ind_num_asc" is gawk-only and SILENTLY INERT
#     under mawk (PROCINFO is an ordinary array there) -- not a portable
#     knob.  On Debian, plain `awk` IS mawk.
# Membership tests use `key in arr` (no side effects), never `arr[key]==""`
# (which assigns the element on every check).
#
# Usage: awk -v K=3 -v FR=1 -v BI=2 -v VA=3 -f peaks_buffered.awk mag.csv
function emit(fr,   i, line) {
    line = fr
    for (i = 1; i <= K; i++) line = line "," bins[i]
    print line
}
BEGIN {
    FS = ","
    if (K == "") K = 3
    if (FR == "") FR = 1
    if (BI == "") BI = 2
    if (VA == "") VA = 3
    header = "frame"
    for (i = 1; i <= K; i++) header = header sprintf(",f%d_bin", i)
    print header
}
$FR !~ /^[-+]?[0-9]/ { next }
{
    fr = $FR + 0; b = $BI + 0; v = $VA + 0
    if (!(fr in has)) {
        has[fr] = 1
        if (n == 0 || fr < fmin) fmin = fr
        if (n == 0 || fr > fmax) fmax = fr
        n++
    }
    for (i = 1; i <= K; i++) {
        key = fr SUBSEP i
        if (!(key in vkey) || v > vkey[key] + 0) {
            for (j = K; j > i; j--) {
                jk = fr SUBSEP j; pk = fr SUBSEP (j - 1)
                vkey[jk] = vkey[pk]; bkey[jk] = bkey[pk]
            }
            vkey[fr SUBSEP i] = v; bkey[fr SUBSEP i] = b
            break
        }
    }
}
END {
    for (fr = fmin; fr <= fmax; fr++) {
        if (!(fr in has)) continue
        for (i = 1; i <= K; i++) bins[i] = bkey[fr SUBSEP i]
        emit(fr)
    }
}
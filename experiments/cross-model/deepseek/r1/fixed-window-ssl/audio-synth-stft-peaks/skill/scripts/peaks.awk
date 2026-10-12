# peaks.awk -- streaming top-K spectral bins per frame from a frame-major CSV.
#
# Input contract: mag.csv is frame-major (all bins of frame f precede frame
# f+1), rows are "frame,bin,val", first row may be a header.
# Field positions are parameterized (-v FR/BI/VA) so CSV-schema variants
# (different column order) work without editing the program.
# Tie-break rule: strict '>' insertion => first-seen wins.  Because bins
# ascend within a frame, exact float ties resolve deterministically to the
# SMALLEST bin index.  (Change > to < only if the variant specifies a
# different tie-break.)
# Portable across mawk and gawk: no asort/asorti, no SUBSEP key tricks.
#
# Usage: awk -v K=3 -v FR=1 -v BI=2 -v VA=3 -f peaks.awk mag.csv > peaks.csv
# (K = top-K count; header is built as frame,f1_bin..fK_bin)
function emit(fr,   i, line) {
    line = fr
    for (i = 1; i <= K; i++) line = line "," bins[i]
    print line
}
BEGIN {
    FS = ","
    if (K == "") K = 3
    if (FR == "") FR = 1     # field holding the frame index
    if (BI == "") BI = 2     # field holding the bin index
    if (VA == "") VA = 3     # field holding the magnitude value
    header = "frame"
    for (i = 1; i <= K; i++) header = header sprintf(",f%d_bin", i)
    print header
}
$FR !~ /^[-+]?[0-9]/ { next }   # header guard (harmless if header absent)
{
    fr = $FR + 0; b = $BI + 0; v = $VA + 0
    # NOTE: gate on an explicit 'seen' flag, never on fr != curframe alone:
    # an uninitialized awk variable compares equal to numeric 0, which would
    # silently drop frame 0 (observed v01 failure).
    if (!seen || fr != curframe) {
        if (seen) emit(curframe)
        curframe = fr; seen = 1
        for (i = 1; i <= K; i++) { val[i] = ""; bins[i] = 0 }
    }
    for (i = 1; i <= K; i++) {
        if (val[i] == "" || v > val[i] + 0) {
            for (j = K; j > i; j--) { val[j] = val[j - 1]; bins[j] = bins[j - 1] }
            val[i] = v; bins[i] = b
            break
        }
    }
}
END { if (seen) emit(curframe) }
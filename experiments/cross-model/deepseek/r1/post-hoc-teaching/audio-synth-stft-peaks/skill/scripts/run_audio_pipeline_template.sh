#!/usr/bin/env bash
# Family orchestrator: audioproc.py (WAV + mag.csv) -> awk (peaks.csv)
#
# Contract (family invariants):
#   * runs the python stage, then performs peak selection *in shell/awk*
#   * invokes `awk` via PATH (never an absolute awk path)
#   * PEAKS_ONLY=1 : regenerate peaks.csv from existing mag.csv and exit
#     without running any other step
#   * TOP_K (default 3) selects how many peaks per frame are emitted
#   * OUTPUT_MODE (default bins) selects what the peak columns CONTAIN:
#       bins        -> f1_bin..fK_bin        (integer bin indices; v01)
#       freq        -> f1_hz..fK_hz          (bin * FREQ_PER_BIN, %.12g)
#       val         -> f1_val..fK_val        (magnitudes, %.17g repr-round-trip)
#       interleaved -> f1_bin,f1_val,...     (or f1_hz,f1_val for Hz identity)
#   * FREQ_PER_BIN = fs / nfft (Hz per bin): pass the NUMERIC value, or pass
#     FS_RATE + NFFT and let awk divide (awk -v never evaluates expressions:
#     `-v FREQ_PER_BIN=12000/1024` becomes the string '12000/1024' -> 12000!)
#   * header "frame,..." + one row per frame, frames 0-indexed ascending;
#     within a frame peaks ordered by magnitude descending, ties broken by
#     smaller identity (bin index, or Hz value for a Hz-schema mag.csv) --
#     deterministic, equals a stable sort of (val desc, identity asc)
#   * RULE: bins are identity, everything else is display. The awk ranks by
#     val and ties by the identity column AS READ FROM mag.csv; bin->Hz
#     conversion happens ONLY at emission (bin * FREQ_PER_BIN). NEVER invert
#     a Hz column back to bins for ranking -- rounded Hz values would move
#     peaks at half-bin boundaries and change the top-k.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$BASE/data"
MAG="$DATA/mag.csv"
PEAKS="$DATA/peaks.csv"
TOP_K="${TOP_K:-3}"
OUTPUT_MODE="${OUTPUT_MODE:-bins}"
FREQ_PER_BIN="${FREQ_PER_BIN:-}"   # numeric bin width (Hz); OR set FS_RATE+NFFT
FS_RATE="${FS_RATE:-}"              # sample rate (int), e.g. 12000
NFFT="${NFFT:-}"                    # FFT size (int), e.g. 1024

# Portable POSIX awk (verified identical output under mawk and gawk):
#   - HEADER-AWARE column mapping: the first line is parsed and the columns
#     named frame / bin(ish) / val(ish) are located BY NAME, case-insensitive,
#     quotes/whitespace trimmed:
#       identity: bin, bins, index, idx            -> integer bins (v01)
#                 freq, frequency, hz              -> Hz identity (isfreq=1)
#       value:    val, mag, magnitude, value, amplitude, amp, power, db
#     No recognizable header -> positional fallback (frame=1, identity=2,
#     val=3).
#   - keeps per-frame top-K (identity,val) ordered by (val desc, identity asc)
#   - accepts rows in ANY order: frames are recorded in first-seen order,
#     then a numeric insertion sort in END reorders them ascending
#     (awk has no ordered containers/builtin sort; +0 forces numeric compare
#     so '10' does not sort before '9')
#   - END emission follows OUTPUT_MODE (bins|freq|val|interleaved); float
#     columns use %.12g (Hz) / %.17g (magnitudes, repr-round-trip) -- never
#     %d, which truncates floats to integers
#   - no arrays-of-arrays / no length(arr) / no gawk-only sort functions
PEAKS_AWK='
BEGIN {
    FS = ","
    K = (TOP_K + 0 > 0) ? TOP_K + 0 : 3
    MODE = (OUTPUT_MODE == "") ? "bins" : OUTPUT_MODE
    # bin width: prefer explicit numeric FREQ_PER_BIN; else compute FS_RATE/NFFT
    # HERE inside awk (plain ints pass cleanly through -v; arithmetic
    # expressions like 12000/1024 passed from the shell are NOT evaluated)
    FPB = FREQ_PER_BIN + 0
    if (FPB <= 0 && NFFT + 0 > 0) FPB = (FS_RATE + 0) / (NFFT + 0)
}
NR == 1 {
    nh = split($0, h, FS)
    for (i = 1; i <= nh; i++) {
        gsub(/^[ \t"]+|[ \t"]+$/, "", h[i])
        t = tolower(h[i])
        if (t == "frame") cf = i
        else if (t == "bin" || t == "bins" || t == "index" || t == "idx") { cb = i; isfreq = 0 }
        # BIN names take priority over FREQ names: when a schema carries both
        # a bin and a freq column (e.g. frame,bin,freq,val), the integer bin
        # is the identity -- otherwise bins-mode output would %d-truncate the
        # Hz values (203.125 -> 203)
        else if (t == "freq" || t == "frequency" || t == "hz") { if (cb == 0) { cb = i; isfreq = 1 } }
        else if (t == "val" || t == "mag" || t == "magnitude" || t == "value" \
                 || t == "amplitude" || t == "amp" || t == "power" || t == "db") cv = i
    }
    if (cf && cb && cv) next          # recognized header: skip it
    cf = 1; cb = 2; cv = 3            # headerless / unrecognized: positional
    if ($1 == "frame") next          # bare "frame,..." header without names
}
{
    f = $cf; b = $cb
    gsub(/^[ \t"]+|[ \t"]+$/, "", f)
    gsub(/^[ \t"]+|[ \t"]+$/, "", b)
    v = $cv + 0
    if (!(f in seen)) { seen[f] = 1; flist[++nf] = f }
    n = cnt[f] + 0
    pos = n + 1
    for (i = 1; i <= n; i++) {
        if (v > vk[f, i] || (v == vk[f, i] && b < bk[f, i])) { pos = i; break }
    }
    if (pos <= K) {
        for (i = (n < K ? n : K); i >= pos; i--) {
            bk[f, i + 1] = bk[f, i]
            vk[f, i + 1] = vk[f, i]
        }
        bk[f, pos] = b
        vk[f, pos] = v
        cnt[f] = (n < K) ? n + 1 : K
    }
}
END {
    # sort frames ascending (numeric). seen[] dedupe guarantees each frame
    # appears exactly once; bin/val tables are keyed by frame, not position,
    # so sorting flist alone is sufficient.
    for (i = 2; i <= nf; i++) {
        fi = flist[i]; j = i
        while (j > 1 && flist[j - 1] + 0 > fi + 0) { flist[j] = flist[j - 1]; j-- }
        flist[j] = fi
    }
    if (MODE == "bins") {
        printf "frame"
        for (i = 1; i <= K; i++) printf ",f%d_bin", i
        print ""
        for (i = 1; i <= nf; i++) {
            f = flist[i]
            printf "%d", f
            for (j = 1; j <= K; j++) printf ",%d", bk[f, j]
            print ""
        }
    } else if (MODE == "freq") {
        # identity * FREQ_PER_BIN at emission time; a Hz-identity file emits
        # its own Hz values (already in Hz, no multiply)
        printf "frame"
        for (i = 1; i <= K; i++) printf ",f%d_hz", i
        print ""
        for (i = 1; i <= nf; i++) {
            f = flist[i]
            printf "%d", f
            for (j = 1; j <= K; j++) printf ",%.12g", (isfreq ? bk[f, j] : bk[f, j] * FPB)
            print ""
        }
    } else if (MODE == "val") {
        printf "frame"
        for (i = 1; i <= K; i++) printf ",f%d_val", i
        print ""
        for (i = 1; i <= nf; i++) {
            f = flist[i]
            printf "%d", f
            for (j = 1; j <= K; j++) printf ",%.17g", vk[f, j]
            print ""
        }
    } else {  # interleaved: identity,value pairs (f%d_bin / f%d_hz + f%d_val)
        if (isfreq) {
            printf "frame"
            for (i = 1; i <= K; i++) printf ",f%d_hz,f%d_val", i, i
            print ""
            for (i = 1; i <= nf; i++) {
                f = flist[i]
                printf "%d", f
                for (j = 1; j <= K; j++) printf ",%.12g,%.17g", bk[f, j], vk[f, j]
                print ""
            }
        } else {
            printf "frame"
            for (i = 1; i <= K; i++) printf ",f%d_bin,f%d_val", i, i
            print ""
            for (i = 1; i <= nf; i++) {
                f = flist[i]
                printf "%d", f
                for (j = 1; j <= K; j++) printf ",%d,%.17g", bk[f, j], vk[f, j]
                print ""
            }
        }
    }
}
'

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    [ -f "$MAG" ] || { echo "missing $MAG (run the pipeline first)" >&2; exit 1; }
    # pass variables explicitly with -v: awk does NOT see exported shell vars
    # as bare variables (only via ENVIRON[]); -v works the same in mawk/gawk
    awk -v TOP_K="$TOP_K" -v OUTPUT_MODE="$OUTPUT_MODE" -v FREQ_PER_BIN="$FREQ_PER_BIN" \
        -v FS_RATE="$FS_RATE" -v NFFT="$NFFT" "$PEAKS_AWK" "$MAG" > "$PEAKS"
    exit 0
fi

python3 "$BASE/audioproc.py"
awk -v TOP_K="$TOP_K" -v OUTPUT_MODE="$OUTPUT_MODE" -v FREQ_PER_BIN="$FREQ_PER_BIN" \
    -v FS_RATE="$FS_RATE" -v NFFT="$NFFT" "$PEAKS_AWK" "$MAG" > "$PEAKS"
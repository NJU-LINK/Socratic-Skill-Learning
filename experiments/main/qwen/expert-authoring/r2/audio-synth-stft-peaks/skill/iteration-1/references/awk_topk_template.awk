# awk_topk_template.awk
# Template for extracting top-K spectral peaks per frame from mag.csv.
#
# Usage:
#   awk -v K=3 -f awk_topk_template.awk data/mag.csv > data/peaks.csv
#
# Input:  CSV with columns frame,bin,val (header row skipped).
# Output: CSV with columns frame,f1_bin,f2_bin,...,fK_bin (header + one row/frame).
#
# Tie-breaking: higher magnitude wins; on equal magnitude, lower bin index wins.
# Adjust the comparison in the insertion logic if the task spec requires different rules.
#
# This template uses K=3 by default. Override with -v K=<number>.

BEGIN {
    FS = ","
    if (K == "") K = 3
    nframes = 0
}

NR == 1 { next }

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0.0

    # Track frame ordering
    if (!(frame in frame_seen)) {
        frame_seen[frame] = 1
        nframes++
        frame_order[nframes] = frame
    }

    # Count entries per frame
    if (!(frame in cnt)) cnt[frame] = 0
    cnt[frame]++
    idx = cnt[frame]
    frame_val[frame, idx] = val
    frame_bin[frame, idx] = bin
}

END {
    # Build header
    hdr = "frame"
    for (k = 1; k <= K; k++) hdr = hdr ",f" k "_bin"
    print hdr

    for (fi = 1; fi <= nframes; fi++) {
        fr = frame_order[fi]
        n = cnt[fr]

        # Initialize top-K slots
        for (k = 1; k <= K; k++) {
            top_v[k] = -1
            top_b[k] = -1
        }

        # Insertion: for each bin entry, try to insert into top-K
        for (i = 1; i <= n; i++) {
            v = frame_val[fr, i]
            b = frame_bin[fr, i]

            # Find insertion position
            pos = 0
            for (k = 1; k <= K; k++) {
                if (v > top_v[k] || (v == top_v[k] && b < top_b[k])) {
                    pos = k
                    break
                }
            }

            if (pos > 0) {
                # Shift down from K to pos+1
                for (k = K; k > pos; k--) {
                    top_v[k] = top_v[k-1]
                    top_b[k] = top_b[k-1]
                }
                top_v[pos] = v
                top_b[pos] = b
            }
        }

        # Output row
        row = fr
        for (k = 1; k <= K; k++) row = row "," top_b[k]
        print row
    }
}

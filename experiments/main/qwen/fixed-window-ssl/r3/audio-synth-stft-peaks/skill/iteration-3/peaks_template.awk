#!/usr/bin/awk -f
# Top-k peak extraction from STFT magnitude CSV
# Usage: awk -F',' -v TOP_K=3 -f peaks.awk mag.csv > peaks.csv
#
# Input schema: frame,bin,val (header row skipped)
# Output schema: frame,f1_bin,f2_bin,...,fk_bin (descending magnitude order)
#
# NOTE: This implementation assumes non-negative magnitude values.
# For variants with negative values, use the store-all-then-sort approach.

BEGIN {
    FS = ","
    OFS = ","
    if (TOP_K == "") TOP_K = 3
}

NR == 1 { next }  # skip header

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0.0

    # Incremental top-k tracker
    # Uses existence check (!(frame in nX)) to avoid 0-initialization trap
    if (!(frame in n1) || val > top1[frame]) {
        # Shift down: top_k <- top_{k-1} <- ... <- top_1 <- new
        for (k = TOP_K; k > 1; k--) {
            prev = k - 1
            if (prev == 1) { tv = top1[frame]; tb = top1_bin[frame] }
            else if (prev == 2) { tv = top2[frame]; tb = top2_bin[frame] }
            else if (prev == 3) { tv = top3[frame]; tb = top3_bin[frame] }
            if (k == 2) { top2[frame] = tv; top2_bin[frame] = tb }
            else if (k == 3) { top3[frame] = tv; top3_bin[frame] = tb }
        }
        top1[frame] = val; top1_bin[frame] = bin; n1[frame] = 1
    } else if (TOP_K >= 2 && (!(frame in n2) || val > top2[frame])) {
        for (k = TOP_K; k > 2; k--) {
            if (k == 3) { top3[frame] = top2[frame]; top3_bin[frame] = top2_bin[frame] }
        }
        top2[frame] = val; top2_bin[frame] = bin; n2[frame] = 1
    } else if (TOP_K >= 3 && (!(frame in n3) || val > top3[frame])) {
        top3[frame] = val; top3_bin[frame] = bin; n3[frame] = 1
    }
    
    if (!(frame in seen)) {
        seen[frame] = 1
        frames[++nf] = frame
    }
}

END {
    # Sort frames numerically
    for (i = 1; i <= nf; i++) {
        for (j = i+1; j <= nf; j++) {
            if (frames[i]+0 > frames[j]+0) {
                tmp = frames[i]; frames[i] = frames[j]; frames[j] = tmp
            }
        }
    }
    
    # Build header
    hdr = "frame"
    for (k = 1; k <= TOP_K; k++) hdr = hdr ",f" k "_bin"
    print hdr
    
    # Output rows
    for (i = 1; i <= nf; i++) {
        f = frames[i]
        line = f
        if (TOP_K >= 1) line = line "," (f in n1 ? top1_bin[f] : 0)
        if (TOP_K >= 2) line = line "," (f in n2 ? top2_bin[f] : 0)
        if (TOP_K >= 3) line = line "," (f in n3 ? top3_bin[f] : 0)
        print line
    }
}

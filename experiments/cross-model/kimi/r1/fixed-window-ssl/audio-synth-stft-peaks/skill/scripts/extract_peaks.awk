#!/usr/bin/awk -f
# Extract top-k spectral peaks per frame from magnitude CSV
# Usage: awk -f extract_peaks.awk -v k=3 mag.csv > peaks.csv
#
# Input schema: frame,bin,val (one row per bin per frame)
# Output schema: frame,f1_bin,f2_bin,...,fk_bin
#
# Tie-breaking: Lower bin index wins when magnitudes are equal (stable sort)
# Requirements: Coerce $1 and $3 to numeric with +0 to avoid string comparison

BEGIN {
    FS = ","
    if (k == "") k = 3  # Default to top-3
}

NR == 1 { next }  # Skip header

{
    frame = $1 + 0   # Force numeric to avoid string comparison bug
    bin = $2
    val = $3 + 0     # Force numeric
    
    if (frame > max_frame) max_frame = frame
    
    # Insert-sort into top-k (maintains descending order by value)
    inserted = 0
    for (i = 1; i <= k && !inserted; i++) {
        idx = frame "," i
        if (!(idx in top_val) || val > top_val[idx]) {
            # Shift existing entries down
            for (j = k; j > i; j--) {
                from_idx = frame "," (j-1)
                to_idx = frame "," j
                if (from_idx in top_bin) {
                    top_bin[to_idx] = top_bin[from_idx]
                    top_val[to_idx] = top_val[from_idx]
                }
            }
            # Insert new value
            insert_idx = frame "," i
            top_bin[insert_idx] = bin
            top_val[insert_idx] = val
            inserted = 1
        }
    }
}

END {
    # Output header
    printf "frame"
    for (i = 1; i <= k; i++) printf ",f%d_bin", i
    printf "\n"
    
    # Output in frame order
    for (fr = 0; fr <= max_frame; fr++) {
        printf "%d", fr
        for (i = 1; i <= k; i++) {
            idx = fr "," i
            val = (idx in top_bin) ? top_bin[idx] : ""
            printf ",%s", val
        }
        printf "\n"
    }
}

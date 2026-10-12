# extract_peaks.awk — Find top-k magnitude bins per STFT frame
# Input: CSV with header "frame,bin,val"
# Output: CSV with header "frame,f1_bin,f2_bin,...,fk_bin"
# Compatible with both mawk and gawk (no asorti/asort)
BEGIN {
    FS = ","
    OFS = ","
    k = 3  # Adjust for different top-k requirements
    # Build header dynamically
    hdr = "frame"
    for (i = 1; i <= k; i++) hdr = hdr ",f" i "_bin"
    print hdr
    n = 0
    prev_frame = -1
}

NR == 1 { next }  # skip header

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0.0  # +0 handles scientific notation

    if (frame != prev_frame) {
        # Process previous frame if we have data
        if (n > 0) {
            emit_topk(prev_frame)
        }
        # Reset for new frame
        delete bins
        delete vals
        n = 0
        prev_frame = frame
    }
    bins[n] = bin
    vals[n] = val
    n++
}

END {
    if (n > 0) {
        emit_topk(prev_frame)
    }
}

# Repeated-max selection for top-k (mawk-compatible)
function emit_topk(fr,    i, j, best_idx, best_val, used) {
    for (i = 0; i < n; i++) used[i] = 0

    printf "%d", fr
    for (i = 0; i < k; i++) {
        best_idx = -1
        best_val = -1
        for (j = 0; j < n; j++) {
            if (!used[j] && vals[j] > best_val) {
                best_val = vals[j]
                best_idx = j
            }
        }
        if (best_idx >= 0) {
            printf ",%d", bins[best_idx]
            used[best_idx] = 1
        } else {
            printf ",0"
        }
    }
    printf "\n"
}

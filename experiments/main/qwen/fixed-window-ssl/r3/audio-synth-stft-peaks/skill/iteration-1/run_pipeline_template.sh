#!/usr/bin/env bash
# Template for audio pipeline shell script
# Parameterize DATA_DIR, MAG_CSV, PEAKS_CSV paths from task.yaml
set -euo pipefail

DATA_DIR="/app/data"
MAG_CSV="${DATA_DIR}/mag.csv"
PEAKS_CSV="${DATA_DIR}/peaks.csv"
TOP_K="${TOP_K:-3}"

# === PEAKS_ONLY mode ===
if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    echo "PEAKS_ONLY mode: extracting top-${TOP_K} peaks from ${MAG_CSV}"
    if [[ ! -f "${MAG_CSV}" ]]; then
        echo "ERROR: ${MAG_CSV} not found. Run full pipeline first." >&2
        exit 1
    fi
    
    awk -F',' -v TOP_K="${TOP_K}" '
    NR == 1 { next }
    {
        frame = $1 + 0; bin = $2 + 0; val = $3 + 0.0
        if (!(frame in n1) || val > top1[frame]) {
            top3[frame]=top2[frame]; top3_bin[frame]=top2_bin[frame]
            top2[frame]=top1[frame]; top2_bin[frame]=top1_bin[frame]
            top1[frame]=val; top1_bin[frame]=bin; n1[frame]=1
        } else if (TOP_K>=2 && (!(frame in n2) || val > top2[frame])) {
            if (TOP_K>=3) { top3[frame]=top2[frame]; top3_bin[frame]=top2_bin[frame] }
            top2[frame]=val; top2_bin[frame]=bin; n2[frame]=1
        } else if (TOP_K>=3 && (!(frame in n3) || val > top3[frame])) {
            top3[frame]=val; top3_bin[frame]=bin; n3[frame]=1
        }
        if (!(frame in seen)) { seen[frame]=1; frames[++nf]=frame }
    }
    END {
        for (i=1;i<=nf;i++) for (j=i+1;j<=nf;j++) if (frames[i]+0>frames[j]+0) { t=frames[i];frames[i]=frames[j];frames[j]=t }
        hdr="frame"; for(k=1;k<=TOP_K;k++) hdr=hdr",f"k"_bin"; print hdr
        for (i=1;i<=nf;i++) {
            f=frames[i]; line=f
            if(TOP_K>=1) line=line","(f in n1?top1_bin[f]:0)
            if(TOP_K>=2) line=line","(f in n2?top2_bin[f]:0)
            if(TOP_K>=3) line=line","(f in n3?top3_bin[f]:0)
            print line
        }
    }
    ' "${MAG_CSV}" > "${PEAKS_CSV}"
    
    echo "Peaks written to ${PEAKS_CSV}"
    exit 0
fi

# === Full pipeline ===
echo "=== Full audio pipeline ==="

# Step 1 & 2: Python does synthesis + STFT
python3 /app/audioproc.py

# Step 3: Awk does peak extraction
echo "Extracting top-${TOP_K} peaks..."
awk -F',' -v TOP_K="${TOP_K}" '
NR == 1 { next }
{
    frame = $1 + 0; bin = $2 + 0; val = $3 + 0.0
    if (!(frame in n1) || val > top1[frame]) {
        top3[frame]=top2[frame]; top3_bin[frame]=top2_bin[frame]
        top2[frame]=top1[frame]; top2_bin[frame]=top1_bin[frame]
        top1[frame]=val; top1_bin[frame]=bin; n1[frame]=1
    } else if (TOP_K>=2 && (!(frame in n2) || val > top2[frame])) {
        if (TOP_K>=3) { top3[frame]=top2[frame]; top3_bin[frame]=top2_bin[frame] }
        top2[frame]=val; top2_bin[frame]=bin; n2[frame]=1
    } else if (TOP_K>=3 && (!(frame in n3) || val > top3[frame])) {
        top3[frame]=val; top3_bin[frame]=bin; n3[frame]=1
    }
    if (!(frame in seen)) { seen[frame]=1; frames[++nf]=frame }
}
END {
    for (i=1;i<=nf;i++) for (j=i+1;j<=nf;j++) if (frames[i]+0>frames[j]+0) { t=frames[i];frames[i]=frames[j];frames[j]=t }
    hdr="frame"; for(k=1;k<=TOP_K;k++) hdr=hdr",f"k"_bin"; print hdr
    for (i=1;i<=nf;i++) {
        f=frames[i]; line=f
        if(TOP_K>=1) line=line","(f in n1?top1_bin[f]:0)
        if(TOP_K>=2) line=line","(f in n2?top2_bin[f]:0)
        if(TOP_K>=3) line=line","(f in n3?top3_bin[f]:0)
        print line
    }
}
' "${MAG_CSV}" > "${PEAKS_CSV}"

echo "Peaks written to ${PEAKS_CSV}"
echo "=== Pipeline complete ==="

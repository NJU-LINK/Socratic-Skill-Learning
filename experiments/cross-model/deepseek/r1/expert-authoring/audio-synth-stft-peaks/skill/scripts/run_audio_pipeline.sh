#!/usr/bin/env bash
# Orchestrator template: python synthesizes WAV + STFT CSV; awk does the final
# peak selection. This script is the only thing allowed to create peaks.csv.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data

# Output schema: the exact peak-column names the task requires (header row).
HDR='frame,f1_bin,f2_bin,f3_bin'

# Peaks-only mode (env var name/values per task instructions): regenerate
# data/peaks.csv from the existing data/mag.csv using awk, then stop WITHOUT
# rerunning the python stages.
if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    awk -F, -v k=3 -v header="$HDR" -f extract_peaks.awk data/mag.csv > data/peaks.csv
    exit 0
fi

# Full pipeline. Invoke awk by bare name (PATH), never an absolute path.
python3 audioproc.py
awk -F, -v k=3 -v header="$HDR" -f extract_peaks.awk data/mag.csv > data/peaks.csv
echo "pipeline complete: data/clip.wav, data/mag.csv, data/peaks.csv"
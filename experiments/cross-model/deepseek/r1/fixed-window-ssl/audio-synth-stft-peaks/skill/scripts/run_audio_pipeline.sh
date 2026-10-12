#!/usr/bin/env bash
# Template orchestrator: synthesis+STFT (audioproc.py) -> awk peak extraction.
# The <FLAG> env var (v01: PEAKS_ONLY) must match the variant's name:
#   <FLAG>=1 : regenerate peaks.csv from the existing mag.csv via awk,
#              then exit WITHOUT running the other steps.
set -euo pipefail
DATA_DIR=/app/data
K=${TOP_K:-3}                       # top-K count (awk -v)
FLAG_NAME=PEAKS_ONLY                # ← rename per task spec

if [ "${!FLAG_NAME:-0}" = "1" ]; then
    awk -v K="$K" -f /app/peaks.awk "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
    exit 0
fi

python3 /app/audioproc.py
awk -v K="$K" -f /app/peaks.awk "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
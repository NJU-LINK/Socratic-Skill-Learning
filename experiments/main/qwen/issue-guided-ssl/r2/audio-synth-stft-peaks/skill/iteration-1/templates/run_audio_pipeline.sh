#!/usr/bin/env bash
# run_audio_pipeline.sh template — Orchestrate audio synthesis, STFT, and peak extraction
# Supports PEAKS_ONLY=1 to skip synthesis/STFT and only regenerate peaks.csv
#
# Usage:
#   bash run_audio_pipeline.sh              # Full pipeline
#   PEAKS_ONLY=1 bash run_audio_pipeline.sh # Only regenerate peaks.csv from mag.csv
set -euo pipefail

cd /app

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    # Peaks-only mode: read existing mag.csv, produce peaks.csv via awk
    echo "PEAKS_ONLY mode: extracting peaks from data/mag.csv"
    awk -f /app/extract_peaks.awk /app/data/mag.csv > /app/data/peaks.csv
    echo "Wrote data/peaks.csv"
    exit 0
fi

# Full pipeline
echo "Running full audio pipeline..."

# Stage 1 & 2: Synthesize WAV and compute STFT magnitude
# Adjust these arguments for different variants
python3 /app/audioproc.py \
    --sample-rate 12000 \
    --duration 2.5 \
    --frequencies "180,360,540,720" \
    --noise-std 0.01 \
    --rms-target 0.15 \
    --seed 42 \
    --window blackman \
    --nperseg 768 \
    --noverlap 576 \
    --nfft 1024 \
    --boundary None \
    --padded False \
    --return-onesided True \
    --data-dir data

# Stage 3: Extract top-k peaks per frame using awk
echo "Extracting peaks from data/mag.csv..."
awk -f /app/extract_peaks.awk /app/data/mag.csv > /app/data/peaks.csv
echo "Wrote data/peaks.csv"

echo "Pipeline complete."

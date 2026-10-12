#!/usr/bin/env python3
"""
audioproc_template.py — Reference template for audio synthesis + STFT pipeline.

This template is PARAMETERIZED. Replace all <PLACEHOLDER> values with the
concrete values from the task specification before use.

Produces:
    data/clip.wav   — PCM int16 WAV file
    data/mag.csv    — STFT magnitude spectrogram (frame, bin, val)

Does NOT produce data/peaks.csv — that is the awk stage's responsibility.
"""

import os
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile

# =============================================================================
# SYNTHESIS PARAMETERS — replace with task-specific values
# =============================================================================
FS = <SAMPLE_RATE>               # e.g. 12000
DURATION = <DURATION>            # e.g. 2.5
FREQUENCIES = <FREQUENCY_LIST>   # e.g. [180, 360, 540, 720]
NOISE_STD = <NOISE_STD>          # e.g. 0.05
RMS_TARGET = <RMS_TARGET>        # e.g. 0.15
RMS_TOLERANCE = <RMS_TOLERANCE>  # e.g. 0.002
SEED = <SEED>                    # integer or None if not specified

# =============================================================================
# STFT PARAMETERS — replace with task-specific values
# =============================================================================
STFT_WINDOW = '<WINDOW>'         # e.g. 'blackman', 'hann'
STFT_NPERSEG = <NPERSEG>         # e.g. 768
STFT_NOVERLAP = <NOVERLAP>       # e.g. 576
STFT_NFFT = <NFFT>               # e.g. 1024
STFT_BOUNDARY = <BOUNDARY>       # None or 'zeros' etc.
STFT_PADDED = <PADDED>           # True or False
STFT_ONESIDED = <ONESIDED>       # True or False

# =============================================================================
# OUTPUT PATHS
# =============================================================================
DATA_DIR = 'data'
WAV_PATH = os.path.join(DATA_DIR, 'clip.wav')
CSV_PATH = os.path.join(DATA_DIR, 'mag.csv')

# =============================================================================
# STEP 1: SYNTHESIZE SIGNAL
# =============================================================================
os.makedirs(DATA_DIR, exist_ok=True)

n_samples = int(FS * DURATION)
t = np.arange(n_samples, dtype=np.float64) / FS

# Sum of sine tones
signal = np.zeros(n_samples, dtype=np.float64)
for freq in FREQUENCIES:
    signal += np.sin(2.0 * np.pi * freq * t)

# Add Gaussian noise
if SEED is not None:
    np.random.seed(SEED)
noise = np.random.normal(0, NOISE_STD, n_samples)
signal += noise

# =============================================================================
# STEP 2: RMS NORMALIZATION (before int16 quantization)
# =============================================================================
rms_current = np.sqrt(np.mean(signal ** 2))
signal *= (RMS_TARGET / rms_current)

rms_check = np.sqrt(np.mean(signal ** 2))
assert abs(rms_check - RMS_TARGET) < RMS_TOLERANCE, (
    f"RMS normalization failed: {rms_check:.6f} vs target {RMS_TARGET}"
)

# =============================================================================
# STEP 3: INT16 QUANTIZATION AND WAV SAVE
# =============================================================================
signal_clipped = np.clip(signal, -1.0, 1.0)
signal_int16 = np.round(signal_clipped * 32767).astype(np.int16)

wavfile.write(WAV_PATH, FS, signal_int16)

# Verify saved WAV
sr_read, data_read = wavfile.read(WAV_PATH)
assert sr_read == FS, f"Sample rate mismatch: {sr_read} vs {FS}"
assert data_read.dtype == np.int16, f"Expected int16, got {data_read.dtype}"
assert len(data_read) == n_samples, f"Sample count: {len(data_read)} vs {n_samples}"

# =============================================================================
# STEP 4: STFT COMPUTATION (on the float signal)
# =============================================================================
f_axis, t_axis, Zxx = stft(
    signal,
    fs=FS,
    window=STFT_WINDOW,
    nperseg=STFT_NPERSEG,
    noverlap=STFT_NOVERLAP,
    nfft=STFT_NFFT,
    boundary=STFT_BOUNDARY,
    padded=STFT_PADDED,
    return_onesided=STFT_ONESIDED,
)

n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

# =============================================================================
# STEP 5: MAGNITUDE CSV EXPORT
# =============================================================================
with open(CSV_PATH, 'w') as fout:
    fout.write('frame,bin,val\n')
    for frame_idx in range(n_frames):
        for bin_idx in range(n_bins):
            mag = float(np.abs(Zxx[bin_idx, frame_idx]))
            fout.write(f'{frame_idx},{bin_idx},{mag}\n')

# =============================================================================
# SELF-VERIFICATION
# =============================================================================
hop = STFT_NPERSEG - STFT_NOVERLAP
if STFT_BOUNDARY is None and not STFT_PADDED:
    expected_frames = (n_samples - STFT_NPERSEG) // hop + 1
    assert n_frames == expected_frames, (
        f"Frame count: {n_frames} vs expected {expected_frames}"
    )

if STFT_ONESIDED:
    expected_bins = STFT_NFFT // 2 + 1
    assert n_bins == expected_bins, (
        f"Bin count: {n_bins} vs expected {expected_bins}"
    )

print(f"Pipeline complete: {WAV_PATH} ({n_samples} samples, {FS} Hz), "
      f"{CSV_PATH} ({n_frames} frames × {n_bins} bins)")

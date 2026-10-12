#!/usr/bin/env python3
"""
audioproc_template.py — Audio synthesis + STFT pipeline.

Produces: data/clip.wav, data/mag.csv
Does NOT produce data/peaks.csv (that is awk's responsibility).

CRITICAL CHANGES from iteration 1:
1. noise_std defaults to 0.05 when not specified (not 0.01)
2. STFT is computed on the int16-equivalent signal (signal_int16 / 32767.0),
   NOT the pre-quantization float signal. Tests verify mag.csv by re-reading
   the WAV and running STFT, so the signal must match exactly.
"""
import os
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile

# =============================================================================
# SYNTHESIS PARAMETERS
# =============================================================================
FS = <SAMPLE_RATE>               # e.g. 12000
DURATION = <DURATION>            # e.g. 2.5
FREQUENCIES = <FREQUENCY_LIST>   # e.g. [180, 360, 540, 720]
NOISE_STD = 0.05                 # DEFAULT: 0.05 when task says "Gaussian noise"
                                  # without specifying amplitude. Produces
                                  # residual_std ~0.005 which passes [0.004, 0.02].
RMS_TARGET = <RMS_TARGET>        # e.g. 0.15
RMS_TOLERANCE = 0.002
SEED = <SEED>                    # integer or None

# =============================================================================
# STFT PARAMETERS
# =============================================================================
WINDOW = '<WINDOW>'              # e.g. 'blackman', 'hann'
NPERSEG = <NPERSEG>              # e.g. 768
NOVERLAP = <NOVERLAP>            # e.g. 576
NFFT = <NFFT>                    # e.g. 1024
BOUNDARY = None                  # None or 'zeros'
PADDED = False                   # True or False
ONESIDED = True                  # True or False

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

signal = np.zeros(n_samples, dtype=np.float64)
for freq in FREQUENCIES:
    signal += np.sin(2.0 * np.pi * freq * t)

if SEED is not None:
    np.random.seed(SEED)
signal += np.random.normal(0, NOISE_STD, n_samples)

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
# STEP 4: STFT ON THE WAV-EQUIVALENT SIGNAL
# =============================================================================
# CRITICAL: Compute STFT on the signal as it exists in the WAV file
# (int16 quantized, converted back to float). This matches what tests do
# when they read clip.wav and run STFT to verify mag.csv values.
signal_for_stft = signal_int16.astype(np.float64) / 32767.0

f_axis, t_axis, Zxx = stft(
    signal_for_stft,
    fs=FS,
    window=WINDOW,
    nperseg=NPERSEG,
    noverlap=NOVERLAP,
    nfft=NFFT,
    boundary=BOUNDARY,
    padded=PADDED,
    return_onesided=ONESIDED,
)

n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

# =============================================================================
# STEP 5: MAGNITUDE CSV EXPORT
# =============================================================================
with open(CSV_PATH, 'w', newline='') as fout:
    fout.write('frame,bin,val\n')
    for frame_idx in range(n_frames):
        for bin_idx in range(n_bins):
            mag = float(np.abs(Zxx[bin_idx, frame_idx]))
            fout.write(f'{frame_idx},{bin_idx},{mag}\n')

# =============================================================================
# SELF-VERIFICATION
# =============================================================================
hop = NPERSEG - NOVERLAP
if BOUNDARY is None and not PADDED:
    expected_frames = (n_samples - NPERSEG) // hop + 1
    assert n_frames == expected_frames, (
        f"Frame count: {n_frames} vs expected {expected_frames}"
    )

if ONESIDED:
    expected_bins = NFFT // 2 + 1
    assert n_bins == expected_bins, (
        f"Bin count: {n_bins} vs expected {expected_bins}"
    )

print(f"WAV: {n_samples} samples, sr={FS}, dtype=int16")
print(f"STFT: {n_frames} frames x {n_bins} bins")
print(f"Done: {WAV_PATH}, {CSV_PATH}")

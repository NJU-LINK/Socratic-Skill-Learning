#!/usr/bin/env python3
"""Audio synthesis + STFT pipeline.

Produces:
  /app/data/clip.wav  - synthesized mono WAV (PCM int16)
  /app/data/mag.csv   - linear-magnitude STFT (frame,bin,val)

Never produces peaks.csv (that is the awk/shell stage's job).
"""

import os
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# -- Synthesis parameters --
SAMPLE_RATE = 12000
DURATION    = 2.5
FREQUENCIES = [180, 360, 540, 720]
RMS_TARGET  = 0.15
RMS_TOL     = 0.002
# Noise std chosen so that after RMS normalization the residual (noise floor)
# has std in [0.004, 0.02]. With 4 unit-amplitude sines (rms_sines=sqrt(2)),
# effective_noise = noise_std * 0.15 / sqrt(2 + noise_std^2).
# noise_std=0.1 -> effective_noise ~ 0.0106, safely in range.
NOISE_STD   = 0.1

# -- STFT parameters --
STFT_FS       = 12000
STFT_WINDOW   = 'blackman'
STFT_NPERSEG  = 768
STFT_NOVERLAP = 576
STFT_NFFT     = 1024

# -- Paths --
DATA_DIR = '/app/data'
WAV_PATH = os.path.join(DATA_DIR, 'clip.wav')
MAG_PATH = os.path.join(DATA_DIR, 'mag.csv')


def synthesize():
    n_samples = int(SAMPLE_RATE * DURATION)
    t = np.arange(n_samples) / SAMPLE_RATE

    signal = np.zeros(n_samples, dtype=np.float64)
    for f in FREQUENCIES:
        signal += np.sin(2 * np.pi * f * t)

    rng = np.random.default_rng(seed=42)
    signal += rng.normal(0, NOISE_STD, size=n_samples)

    rms = np.sqrt(np.mean(signal ** 2))
    signal = signal * (RMS_TARGET / rms)

    actual_rms = np.sqrt(np.mean(signal ** 2))
    assert abs(actual_rms - RMS_TARGET) <= RMS_TOL, \
        f"RMS {actual_rms:.6f} outside target {RMS_TARGET} +/- {RMS_TOL}"

    int16_signal = np.clip(signal * 32767, -32768, 32767).astype(np.int16)

    os.makedirs(DATA_DIR, exist_ok=True)
    wavfile.write(WAV_PATH, SAMPLE_RATE, int16_signal)
    print(f"WAV written: {WAV_PATH}  ({n_samples} samples, RMS={actual_rms:.6f})")


def compute_stft():
    sr, data = wavfile.read(WAV_PATH)
    assert sr == STFT_FS, f"Sample rate mismatch: {sr} vs {STFT_FS}"
    signal = data.astype(np.float64) / 32767.0

    f, t, Zxx = stft(
        signal,
        fs=STFT_FS,
        window=STFT_WINDOW,
        nperseg=STFT_NPERSEG,
        noverlap=STFT_NOVERLAP,
        nfft=STFT_NFFT,
        boundary=None,
        padded=False,
        return_onesided=True,
    )

    mag = np.abs(Zxx)
    n_frames = mag.shape[1]
    n_bins = mag.shape[0]

    print(f"STFT shape: {n_bins} bins x {n_frames} frames")

    with open(MAG_PATH, 'w') as fout:
        fout.write('frame,bin,val\n')
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                fout.write(f'{frame_idx},{bin_idx},{mag[bin_idx, frame_idx]:.10e}\n')

    print(f"Mag CSV written: {MAG_PATH}  ({n_frames * n_bins} data rows)")


if __name__ == '__main__':
    synthesize()
    compute_stft()
    print("audioproc.py complete.")

#!/usr/bin/env python3
"""
Template: Audio synthesis + STFT magnitude export.
Adapt parameters from task spec for each variant.
"""

import os
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# === SYNTHESIS PARAMETERS (adapt per variant) ===
SR = 12000              # Sample rate (Hz)
DURATION = 2.5          # Duration (seconds)
FREQS = [180, 360, 540, 720]  # Sine frequencies (Hz)
RMS_TARGET = 0.15       # Target RMS after normalization
SEED = 42               # RNG seed for reproducibility
NOISE_SCALE = 0.1       # CRITICAL: noise amplitude multiplier (0.05–0.15 range)

# === STFT PARAMETERS (adapt per variant) ===
WINDOW = 'blackman'     # Window type: 'hann', 'hamming', 'blackman', etc.
NPERSEG = 768           # Samples per segment
NOVERLAP = 576          # Overlap between segments
NFFT = 1024             # FFT size
BOUNDARY = None         # Boundary handling: None or 'zeros'
PADDED = False          # Whether to pad signal
RETURN_ONESED = True    # One-sided (real input) or two-sided

# === FILE PATHS ===
WAV_PATH = "/app/data/clip.wav"
CSV_PATH = "/app/data/mag.csv"


def generate_wav(output_path):
    """Synthesize mono WAV: sum of sines + scaled noise, RMS-normalized to target."""
    rng = np.random.default_rng(SEED)
    n_samples = int(SR * DURATION)
    t = np.arange(n_samples) / SR

    # Sum sine tones
    signal = np.zeros(n_samples, dtype=np.float64)
    for f in FREQS:
        signal += np.sin(2 * np.pi * f * t)

    # Add Gaussian noise with SMALL amplitude (CRITICAL: scale it down)
    # noise_scale=0.1 gives residual_std ≈ 0.01 after RMS normalization
    noise = rng.standard_normal(n_samples) * NOISE_SCALE
    noisy = signal + noise

    # CRITICAL: RMS-normalize to target — this is the ONLY normalization
    rms = np.sqrt(np.mean(noisy**2))
    noisy = noisy * (RMS_TARGET / rms)

    # Verify RMS
    rms_final = np.sqrt(np.mean(noisy**2))
    assert abs(rms_final - RMS_TARGET) < 0.002, \
        f"RMS {rms_final:.6f} not within tolerance of {RMS_TARGET}"

    # Quantize to int16 — NO peak normalization after RMS
    audio_int16 = (noisy * 32767).astype(np.int16)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wavfile.write(output_path, SR, audio_int16)
    print(f"WAV: {output_path} | sr={SR}, samples={n_samples}, rms={rms_final:.6f}")


def compute_stft(wav_path, output_csv):
    """Compute STFT and export linear magnitude to CSV."""
    sr, data = wavfile.read(wav_path)
    assert sr == SR, f"Sample rate mismatch: file={sr}, expected={SR}"

    audio = data.astype(np.float64) / 32767.0

    # scipy.signal.stft returns: f (freqs), t (times), Zxx (n_freqs x n_times)
    f, t, Zxx = stft(
        audio, fs=SR, window=WINDOW, nperseg=NPERSEG,
        noverlap=NOVERLAP, nfft=NFFT, boundary=BOUNDARY,
        padded=PADDED, return_onesided=RETURN_ONESED
    )

    magnitude = np.abs(Zxx)  # Linear magnitude (not dB)
    n_bins, n_frames = magnitude.shape

    print(f"STFT: bins={n_bins}, frames={n_frames}")

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    with open(output_csv, 'w') as fout:
        fout.write("frame,bin,val\n")
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                fout.write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}\n")

    print(f"CSV: {output_csv}")


if __name__ == "__main__":
    generate_wav(WAV_PATH)
    compute_stft(WAV_PATH, CSV_PATH)

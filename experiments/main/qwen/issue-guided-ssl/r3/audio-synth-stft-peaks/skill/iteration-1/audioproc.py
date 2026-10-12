#!/usr/bin/env python3
"""
Reference implementation: Audio synthesis + STFT pipeline.
Produces /app/data/clip.wav and /app/data/mag.csv.
Does NOT produce peaks.csv (that's the shell/awk stage's job).

Parameterize the constants below to adapt to different family variants.
"""
import os
import csv
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# ── Synthesis parameters ────────────────────────────────────────────────
FS = 12000                  # sample rate (Hz)
DURATION = 2.5              # seconds
FREQS = [180, 360, 540, 720]  # sine tone frequencies (Hz)
RMS_TARGET = 0.15           # RMS normalization target
NOISE_SEED = 42             # random seed for reproducible noise

# ── STFT parameters ─────────────────────────────────────────────────────
STFT_WINDOW = 'blackman'    # window type
STFT_NPERSEG = 768          # samples per segment
STFT_NOVERLAP = 576         # overlap between segments
STFT_NFFT = 1024            # FFT size

# ── File paths ──────────────────────────────────────────────────────────
WAV_PATH = '/app/data/clip.wav'
MAG_CSV_PATH = '/app/data/mag.csv'


def synthesize_wav():
    """Stage 1: Generate mono WAV from sum of sines + noise, RMS-normalized."""
    n_samples = int(FS * DURATION)
    t = np.arange(n_samples) / FS

    # Sum of sine tones
    signal = np.zeros(n_samples, dtype=np.float64)
    for freq in FREQS:
        signal += np.sin(2.0 * np.pi * freq * t)

    # Add Gaussian noise (fixed seed for reproducibility)
    rng = np.random.RandomState(NOISE_SEED)
    noise = rng.randn(n_samples)
    signal += noise

    # RMS-normalize BEFORE quantization
    rms = np.sqrt(np.mean(signal ** 2))
    signal = signal * (RMS_TARGET / rms)

    # Quantize to int16
    audio_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
    wavfile.write(WAV_PATH, FS, audio_int16)
    return signal, n_samples


def compute_stft(signal):
    """Stage 2: Compute STFT and export linear magnitude to CSV."""
    f_bins, t_frames, Zxx = stft(
        signal,
        fs=FS,
        window=STFT_WINDOW,
        nperseg=STFT_NPERSEG,
        noverlap=STFT_NOVERLAP,
        nfft=STFT_NFFT,
        boundary=None,
        padded=False,
        return_onesided=True,
    )

    mag = np.abs(Zxx)  # linear magnitude, shape: (n_bins, n_frames)
    n_bins, n_frames = mag.shape

    # Write frame-major CSV: frame,bin,val
    with open(MAG_CSV_PATH, 'w', newline='') as fout:
        writer = csv.writer(fout)
        writer.writerow(['frame', 'bin', 'val'])
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                writer.writerow([frame_idx, bin_idx, mag[bin_idx, frame_idx]])

    return n_bins, n_frames


def main():
    os.makedirs('/app/data', exist_ok=True)

    signal, n_samples = synthesize_wav()
    print(f"[audioproc] Wrote {WAV_PATH}: fs={FS}, samples={n_samples}, "
          f"RMS={np.sqrt(np.mean(signal**2)):.6f}")

    n_bins, n_frames = compute_stft(signal)
    print(f"[audioproc] STFT: {n_bins} bins x {n_frames} frames")
    print(f"[audioproc] Wrote {MAG_CSV_PATH}: {n_frames * n_bins} data rows")


if __name__ == '__main__':
    main()

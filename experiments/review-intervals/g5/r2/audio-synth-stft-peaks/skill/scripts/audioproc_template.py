#!/usr/bin/env python3
"""
Audio processing pipeline template.
Parameterized for variant adaptation.

CRITICAL FIXES (from iteration-1 failures):
1. NOISE_STD must be ~0.1 (not 0.01) to get residual_std in [0.004, 0.02]
2. STFT must be computed on the QUANTIZED signal (int16 → float), not pre-quantization
"""

# === VARIANT CONFIGURATION ===
SAMPLE_RATE = 12000          # Hz - affects duration calculation and STFT bin frequencies
DURATION = 2.5               # seconds - determines num_samples
FREQUENCIES = [180, 360, 540, 720]  # Hz - sine tone frequencies
NOISE_STD = 0.1              # CRITICAL: Must be ~0.1 to get residual_std in [0.004, 0.02]
TARGET_RMS = 0.15            # RMS normalization target
RMS_TOLERANCE = 0.002        # Acceptable deviation from TARGET_RMS

# STFT parameters
STFT_FS = 12000              # Must match SAMPLE_RATE
STFT_WINDOW = 'blackman'     # Window type: 'hann', 'blackman', 'hamming', etc.
STFT_NPERSEG = 768           # Samples per segment
STFT_NOVERLAP = 576          # Overlap between segments
STFT_NFFT = 1024             # FFT size
STFT_BOUNDARY = None         # Boundary handling: None, 'even', 'odd', 'constant', 'zeros'
STFT_PADDED = False          # Whether to pad signal
STFT_RETURN_ONESIDED = True  # One-sided (True) vs two-sided (False) STFT

# Output paths
OUTPUT_DIR = '/app/data'
WAV_PATH = f'{OUTPUT_DIR}/clip.wav'
MAG_CSV_PATH = f'{OUTPUT_DIR}/mag.csv'
# === END VARIANT CONFIGURATION ===

import os
import numpy as np
from scipy.signal import stft
import scipy.io.wavfile as wavfile

def main():
    # Calculate derived parameters
    num_samples = int(SAMPLE_RATE * DURATION)
    hop = STFT_NPERSEG - STFT_NOVERLAP
    
    # Expected dimensions (for verification)
    expected_frames = (num_samples - STFT_NPERSEG) // hop + 1 if STFT_BOUNDARY is None and not STFT_PADDED else None
    expected_bins = STFT_NFFT // 2 + 1 if STFT_RETURN_ONESIDED else STFT_NFFT
    
    print(f"Configuration:")
    print(f"  Sample rate: {SAMPLE_RATE} Hz")
    print(f"  Duration: {DURATION} s")
    print(f"  Num samples: {num_samples}")
    print(f"  Frequencies: {FREQUENCIES}")
    print(f"  Noise std: {NOISE_STD}")
    print(f"  Target RMS: {TARGET_RMS} ± {RMS_TOLERANCE}")
    print(f"  STFT: window={STFT_WINDOW}, nperseg={STFT_NPERSEG}, noverlap={STFT_NOVERLAP}, nfft={STFT_NFFT}")
    if expected_frames:
        print(f"  Expected: {expected_frames} frames × {expected_bins} bins")
    
    # === Stage 1: Generate signal ===
    t = np.arange(num_samples) / SAMPLE_RATE
    
    # Sum of sines
    signal = np.zeros(num_samples, dtype=np.float64)
    for freq in FREQUENCIES:
        signal += np.sin(2 * np.pi * freq * t)
    
    # Add Gaussian noise
    rng = np.random.default_rng(seed=42)
    noise = rng.normal(0, NOISE_STD, num_samples)
    signal += noise
    
    # CRITICAL: RMS normalize BEFORE int16 quantization
    rms = np.sqrt(np.mean(signal ** 2))
    signal = signal * (TARGET_RMS / rms)
    
    # Verify RMS
    actual_rms = np.sqrt(np.mean(signal ** 2))
    print(f"\nRMS after normalization: {actual_rms:.6f} (target: {TARGET_RMS})")
    if abs(actual_rms - TARGET_RMS) > RMS_TOLERANCE:
        raise ValueError(f"RMS {actual_rms:.6f} outside tolerance ±{RMS_TOLERANCE}")
    
    # Quantize to int16
    signal_int16 = np.int16(signal * 32767)
    
    # Save WAV
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    wavfile.write(WAV_PATH, SAMPLE_RATE, signal_int16)
    print(f"Saved {WAV_PATH}")
    
    # === Stage 2: Compute STFT ===
    # CRITICAL: Compute STFT on the QUANTIZED signal (int16 → float)
    # This matches what the test does: read WAV → convert to float → compute STFT
    signal_for_stft = signal_int16.astype(np.float64) / 32767.0
    
    f, t_stft, Zxx = stft(
        signal_for_stft,
        fs=STFT_FS,
        window=STFT_WINDOW,
        nperseg=STFT_NPERSEG,
        noverlap=STFT_NOVERLAP,
        nfft=STFT_NFFT,
        boundary=STFT_BOUNDARY,
        padded=STFT_PADDED,
        return_onesided=STFT_RETURN_ONESIDED
    )
    
    # CRITICAL: Export LINEAR magnitude, NOT dB
    magnitude = np.abs(Zxx)
    n_frames = magnitude.shape[1]
    n_bins = magnitude.shape[0]
    print(f"STFT shape: {n_bins} bins × {n_frames} frames")
    
    # Verify dimensions
    if expected_frames and n_frames != expected_frames:
        print(f"WARNING: Expected {expected_frames} frames, got {n_frames}")
    if expected_bins and n_bins != expected_bins:
        print(f"WARNING: Expected {expected_bins} bins, got {n_bins}")
    
    # Export mag.csv
    with open(MAG_CSV_PATH, 'w') as csvf:
        csvf.write('frame,bin,val\n')
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                csvf.write(f'{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]}\n')
    
    print(f"Saved {MAG_CSV_PATH}")
    
    # Frequency-to-bin mapping (for verification)
    print(f"\nFrequency-to-bin mapping:")
    for freq in FREQUENCIES:
        bin_idx = freq * STFT_NFFT / STFT_FS
        print(f"  {freq} Hz → bin {bin_idx:.2f}")

if __name__ == '__main__':
    main()

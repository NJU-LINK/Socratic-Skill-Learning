#!/usr/bin/env python3
"""
Reference template for audio synthesis + STFT pipeline.
Parameterize based on task.yaml values.
"""

import numpy as np
import scipy.signal as sps
import os
import wave

def generate_wav(output_path, sr, duration, freqs, target_rms, rms_tol, noise_std=0.01, seed=42):
    """
    Generate mono WAV: sum of sines + Gaussian noise, RMS-normalized.
    
    KEY: RMS normalize ONCE, then quantize directly to int16.
    Do NOT peak-normalize after RMS normalization.
    """
    n_samples = int(sr * duration)
    t = np.arange(n_samples) / sr
    
    # Sum of sines
    signal = np.zeros(n_samples)
    for f in freqs:
        signal += np.sin(2 * np.pi * f * t)
    
    # Add Gaussian noise
    rng = np.random.default_rng(seed=seed)
    noise = rng.normal(0, noise_std, n_samples)
    signal += noise
    
    # RMS normalize (ONE normalization)
    current_rms = np.sqrt(np.mean(signal**2))
    signal = signal * (target_rms / current_rms)
    
    # Verify
    actual_rms = np.sqrt(np.mean(signal**2))
    assert abs(actual_rms - target_rms) < rms_tol
    
    # Quantize directly — no additional normalization
    signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(signal_int16.tobytes())
    
    return signal, sr  # Return float signal for STFT


def compute_stft(signal, sr, output_path, window, nperseg, noverlap, nfft, 
                 boundary=None, padded=False, return_onesided=True):
    """
    Compute STFT and write magnitude CSV.
    
    Output schema: frame,bin,val (one row per bin per frame)
    """
    f, t_stft, Zxx = sps.stft(
        signal, fs=sr, window=window,
        nperseg=nperseg, noverlap=noverlap, nfft=nfft,
        boundary=boundary, padded=padded, return_onesided=return_onesided
    )
    
    magnitude = np.abs(Zxx)
    n_frames = magnitude.shape[1]
    n_bins = magnitude.shape[0]
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as csvf:
        csvf.write("frame,bin,val\n")
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                csvf.write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10g}\n")
    
    return magnitude, f, t_stft


if __name__ == "__main__":
    # === PARAMETERIZE FROM task.yaml ===
    SR = 12000
    DURATION = 2.5
    FREQS = [180, 360, 540, 720]
    TARGET_RMS = 0.15
    RMS_TOL = 0.002
    
    WINDOW = 'blackman'
    NPERSEG = 768
    NOVERLAP = 576
    NFFT = 1024
    
    WAV_PATH = "/app/data/clip.wav"
    MAG_CSV_PATH = "/app/data/mag.csv"
    # === END PARAMETERS ===
    
    signal, sr = generate_wav(WAV_PATH, sr=SR, duration=DURATION, freqs=FREQS,
                               target_rms=TARGET_RMS, rms_tol=RMS_TOL)
    
    magnitude, freqs_axis, times_axis = compute_stft(
        signal, sr, MAG_CSV_PATH,
        window=WINDOW, nperseg=NPERSEG, noverlap=NOVERLAP, nfft=NFFT
    )
    
    print(f"Pipeline complete: {magnitude.shape[1]} frames x {magnitude.shape[0]} bins")

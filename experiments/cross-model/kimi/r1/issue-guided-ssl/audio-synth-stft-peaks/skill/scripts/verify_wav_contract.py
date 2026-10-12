#!/usr/bin/env python3
"""
Grader-view verifier: reconstructs everything from clip.wav.
Checks RMS, tone-fit residual dither band, tone amplitudes, 
and mag.csv-vs-STFT(clip.wav) max relative error.
"""
import csv
import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

def main():
    # v01 parameters
    FS = 12000
    DURATION = 2.5
    SAMPLES = int(FS * DURATION)
    FREQS = [180, 360, 540, 720]
    TARGET_RMS = 0.15
    RMS_TOL = 0.002
    WIN = 'blackman'
    NPS = 768
    NOV = 576
    NFFT = 1024
    
    # Read clip.wav
    fs, x16 = wavfile.read('/app/data/clip.wav')
    assert fs == FS, f"Sample rate mismatch: {fs} != {FS}"
    assert len(x16) == SAMPLES, f"Sample count mismatch: {len(x16)} != {SAMPLES}"
    assert x16.dtype == np.int16, f"Dtype mismatch: {x16.dtype} != int16"
    
    # Dequantize: v01 confirmed convention /32767.0
    # Evidence: iteration-2 failure showed uniform rel error 3.0519e-5 = 1/32767
    x = x16.astype(np.float64) / 32767.0
    
    # Check RMS
    rms = np.sqrt(np.mean(x ** 2))
    print(f"RMS: {rms:.6f} (target: {TARGET_RMS} ± {RMS_TOL})")
    assert abs(rms - TARGET_RMS) <= RMS_TOL, f"RMS {rms} out of tolerance"
    
    # Tone-fit residual dither band
    t = np.arange(len(x)) / fs
    # Build design matrix with sin/cos for each frequency
    A_cols = []
    for f0 in FREQS:
        A_cols.append(np.sin(2 * np.pi * f0 * t))
        A_cols.append(np.cos(2 * np.pi * f0 * t))
    A = np.column_stack(A_cols)
    
    # Least squares fit
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    
    # Residual std (noise floor after normalization)
    residual = x - A @ coef
    rstd = residual.std()
    print(f"Residual std: {rstd:.6f} (required: [0.004, 0.02])")
    assert 0.004 <= rstd <= 0.02, f"Residual std {rstd} outside dither band"
    
    # Tone amplitudes
    amps = np.hypot(coef[0::2], coef[1::2])  # sqrt(sin² + cos²) for each freq
    print(f"Tone amplitudes: {amps}")
    assert np.all(amps > 0.08), f"Amplitudes too low: min={amps.min()}"
    assert amps.max() / amps.min() < 1.15, f"Amplitude ratio too high: {amps.max()/amps.min()}"
    
    # Compute STFT from saved waveform
    _, _, Zxx = stft(x, fs=fs, window=WIN, nperseg=NPS, noverlap=NOV, nfft=NFFT,
                     boundary=None, padded=False, return_onesided=True)
    mag_expected = np.abs(Zxx)
    
    # Compare with mag.csv
    worst_rel_err = 0.0
    with open('/app/data/mag.csv') as f:
        r = csv.reader(f)
        next(r)  # skip header
        for row in r:
            frame = int(row[0])
            bin_idx = int(row[1])
            val = float(row[2])
            expected = mag_expected[bin_idx, frame]
            rel_err = abs(val - expected) / abs(expected)
            if rel_err > worst_rel_err:
                worst_rel_err = rel_err
    
    print(f"Max relative error vs STFT(clip.wav): {worst_rel_err:.2e}")
    assert worst_rel_err < 1e-6, f"Relative error {worst_rel_err} exceeds 1e-6"
    
    print("\nAll WAV contract checks PASSED")
    print(f"  RMS: {rms:.6f} ✓")
    print(f"  Residual std: {rstd:.6f} ✓")
    print(f"  Tone amplitudes: min={amps.min():.6f}, ratio={amps.max()/amps.min():.4f} ✓")
    print(f"  Max rel error: {worst_rel_err:.2e} ✓")
    return 0

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Verification script for audio-synth-stft-peaks pipeline.
Checks:
1. Synthesis quality (tone amplitudes, residual std in band)
2. mag.csv matches recomputation from clip.wav
3. peaks.csv matches independent argsort reference
4. PEAKS_ONLY mode produces identical output
"""

import sys
import subprocess
import os
import numpy as np
from scipy.io import wavfile
from scipy import signal as sps


def verify_synthesis(wav_path, frequencies, target_rms, residual_band=(0.004, 0.02)):
    """Verify synthesized WAV meets tone quality constraints.
    
    Fits sin/cos at required frequencies, checks:
    - All fitted amplitudes > 0.08
    - max/min amplitude ratio < 1.15
    - Residual std within band (default [0.004, 0.02] for v01)
    """
    print(f"Verifying synthesis quality from {wav_path}...")
    
    fs, samples = wavfile.read(wav_path)
    
    # Normalize (use 32767 to match write-side)
    if samples.dtype == np.int16:
        sig = samples.astype(np.float64) / 32767.0
    elif samples.dtype == np.int32:
        sig = samples.astype(np.float64) / 2147483647.0
    else:
        sig = samples.astype(np.float64)
    
    t = np.arange(len(sig)) / fs
    
    # Build least-squares design matrix (sin and cos for each frequency)
    A = np.column_stack([f(2*np.pi*fr*t) for fr in frequencies for f in (np.sin, np.cos)])
    
    # Fit
    coef, *_ = np.linalg.lstsq(A, sig, rcond=None)
    resid = sig - A @ coef
    
    # Extract amplitudes (hypotenuse of sin/cos pairs)
    amps = [np.hypot(coef[i], coef[i+1]) for i in range(0, len(coef), 2)]
    
    # Checks
    min_amp, max_amp = min(amps), max(amps)
    ratio = max_amp / min_amp
    resid_std = resid.std()
    rms = np.sqrt(np.mean(sig**2))
    
    ok = True
    
    if not all(a > 0.08 for a in amps):
        print(f"  FAIL: Not all amplitudes > 0.08 (min={min_amp:.4f})")
        ok = False
    
    if ratio >= 1.15:
        print(f"  FAIL: Amplitude ratio {ratio:.4f} >= 1.15")
        ok = False
    
    if not (residual_band[0] <= resid_std <= residual_band[1]):
        print(f"  FAIL: Residual std {resid_std:.6f} outside band {residual_band}")
        ok = False
    
    if abs(rms - target_rms) > 0.002:
        print(f"  FAIL: RMS {rms:.6f} outside target {target_rms} +/- 0.002")
        ok = False
    
    if ok:
        print(f"  PASS: Amps=[{min_amp:.4f}, {max_amp:.4f}], ratio={ratio:.4f}, "
              f"resid={resid_std:.6f}, rms={rms:.6f}")
    
    return ok


def load_magnitude_csv(path):
    """Load mag.csv into (n_bins, n_frames) array."""
    data = {}
    max_frame = 0
    max_bin = 0
    with open(path) as f:
        next(f)  # Skip header
        for line in f:
            parts = line.strip().split(',')
            frame = int(parts[0])
            bin_idx = int(parts[1])
            val = float(parts[2])
            data[(frame, bin_idx)] = val
            max_frame = max(max_frame, frame)
            max_bin = max(max_bin, bin_idx)
    
    n_frames = max_frame + 1
    n_bins = max_bin + 1
    mag = np.zeros((n_bins, n_frames))
    for (frame, bin_idx), val in data.items():
        mag[bin_idx, frame] = val
    return mag


def recompute_magnitude(wav_path, stft_params):
    """Recompute STFT magnitude from WAV file.
    Handles int16, int32, and float WAV formats."""
    fs, samples = wavfile.read(wav_path)
    
    # Dtype-aware normalization (use 32767/2147483647 to match write-side)
    if samples.dtype == np.int16:
        sig = samples.astype(np.float64) / 32767.0
    elif samples.dtype == np.int32:
        sig = samples.astype(np.float64) / 2147483647.0
    else:
        # Float WAV - already in [-1, 1] range
        sig = samples.astype(np.float64)
    
    f, t, Z = sps.stft(
        sig,
        fs=fs,
        window=stft_params.get('window', 'blackman'),
        nperseg=stft_params.get('nperseg', 768),
        noverlap=stft_params.get('noverlap', 576),
        nfft=stft_params.get('nfft', 1024),
        boundary=stft_params.get('boundary', None),
        padded=stft_params.get('padded', False)
    )
    return np.abs(Z)


def verify_mag_csv(mag_csv_path, wav_path, stft_params, tolerance=1e-12):
    """Verify mag.csv matches recomputation from WAV."""
    print(f"Verifying {mag_csv_path} against {wav_path}...")
    
    mag_from_csv = load_magnitude_csv(mag_csv_path)
    mag_recomputed = recompute_magnitude(wav_path, stft_params)
    
    if mag_from_csv.shape != mag_recomputed.shape:
        print(f"  FAIL: Shape mismatch {mag_from_csv.shape} vs {mag_recomputed.shape}")
        return False
    
    diff = np.abs(mag_from_csv - mag_recomputed).max()
    if diff > tolerance:
        print(f"  FAIL: Max diff {diff:.2e} exceeds tolerance {tolerance:.2e}")
        return False
    
    print(f"  PASS: Max diff {diff:.2e}")
    return True


def load_peaks_csv(path, k=3):
    """Load peaks.csv into list of (frame, f1_bin, ..., fk_bin)."""
    peaks = []
    with open(path) as f:
        header = next(f).strip().split(',')
        expected_cols = 1 + k
        if len(header) != expected_cols:
            raise ValueError(f"Header has {len(header)} cols, expected {expected_cols}")
        
        for line in f:
            parts = line.strip().split(',')
            frame = int(parts[0])
            bins = [int(p) if p else -1 for p in parts[1:]]
            peaks.append((frame, *bins))
    return peaks


def verify_peaks_csv(peaks_csv_path, mag_array, k=3):
    """Verify peaks.csv matches independent argsort reference."""
    print(f"Verifying {peaks_csv_path} against recomputed magnitude...")
    
    n_frames = mag_array.shape[1]
    peaks = load_peaks_csv(peaks_csv_path, k=k)
    
    if len(peaks) != n_frames:
        print(f"  FAIL: Row count {len(peaks)} vs expected {n_frames}")
        return False
    
    mismatches = 0
    for fr in range(n_frames):
        # Stable descending argsort for top-k
        ref = np.argsort(-mag_array[:, fr], kind='stable')[:k]
        got = list(peaks[fr][1:])
        
        if list(ref) != got:
            print(f"  MISMATCH at frame {fr}: ref={list(ref)}, got={got}")
            mismatches += 1
            if mismatches >= 5:
                break
    
    if mismatches == 0:
        print(f"  PASS: All {n_frames} frames match")
        return True
    else:
        print(f"  FAIL: {mismatches} mismatches")
        return False


def verify_peaks_only_mode(pipeline_script, data_dir):
    """Verify PEAKS_ONLY mode produces identical output."""
    print("Verifying PEAKS_ONLY mode...")
    
    import hashlib
    import os
    
    # Resolve absolute paths
    data_dir = os.path.abspath(data_dir)
    pipeline_script = os.path.abspath(pipeline_script)
    
    wav_path = os.path.join(data_dir, 'clip.wav')
    mag_path = os.path.join(data_dir, 'mag.csv')
    peaks_path = os.path.join(data_dir, 'peaks.csv')
    
    # Save hashes before
    with open(wav_path, 'rb') as f:
        wav_hash_before = hashlib.md5(f.read()).hexdigest()
    with open(mag_path, 'rb') as f:
        mag_hash_before = hashlib.md5(f.read()).hexdigest()
    with open(peaks_path, 'rb') as f:
        peaks_before = f.read()
    
    # Delete and regenerate peaks (run from data_dir's parent)
    os.remove(peaks_path)
    script_dir = os.path.dirname(pipeline_script) or '.'
    subprocess.run(['bash', pipeline_script], env={**os.environ, 'PEAKS_ONLY': '1'}, 
                   check=True, cwd=script_dir)
    
    # Verify other files untouched
    with open(wav_path, 'rb') as f:
        if hashlib.md5(f.read()).hexdigest() != wav_hash_before:
            print("  FAIL: clip.wav was modified")
            return False
    with open(mag_path, 'rb') as f:
        if hashlib.md5(f.read()).hexdigest() != mag_hash_before:
            print("  FAIL: mag.csv was modified")
            return False
    
    # Verify peaks identical
    with open(peaks_path, 'rb') as f:
        peaks_after = f.read()
    if peaks_before != peaks_after:
        print("  FAIL: peaks.csv differs")
        return False
    
    print("  PASS: PEAKS_ONLY mode contract verified")
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: verify_pipeline.py <data_dir> [k=3]")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    
    wav_path = f"{data_dir}/clip.wav"
    mag_path = f"{data_dir}/mag.csv"
    peaks_path = f"{data_dir}/peaks.csv"
    
    # Default STFT params (adjust as needed)
    stft_params = {
        'window': 'blackman',
        'nperseg': 768,
        'noverlap': 576,
        'nfft': 1024,
        'boundary': None,
        'padded': False
    }
    
    all_pass = True
    
    # Verify synthesis quality (v01 parameters)
    frequencies = [180, 360, 540, 720]
    target_rms = 0.15
    residual_band = (0.004, 0.02)
    if not verify_synthesis(wav_path, frequencies, target_rms, residual_band):
        all_pass = False
    
    # Verify mag.csv
    if not verify_mag_csv(mag_path, wav_path, stft_params):
        all_pass = False
    
    # Load magnitude for peaks verification
    mag = recompute_magnitude(wav_path, stft_params)
    
    # Verify peaks.csv
    if not verify_peaks_csv(peaks_path, mag, k=k):
        all_pass = False
    
    # Verify PEAKS_ONLY mode contract
    pipeline_script = os.path.join(os.path.dirname(data_dir), 'run_audio_pipeline.sh')
    if not verify_peaks_only_mode(pipeline_script, data_dir):
        all_pass = False
    
    print("\n" + ("All checks PASSED" if all_pass else "Some checks FAILED"))
    sys.exit(0 if all_pass else 1)

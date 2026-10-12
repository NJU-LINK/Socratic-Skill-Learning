---
name: audio-synth-stft-peaks
description: >
  Build an audio-processing pipeline that synthesizes a deterministic WAV file
  from summed sine tones with noise and RMS normalization, computes an STFT
  magnitude spectrogram via scipy, and extracts top-k spectral peaks per frame
  using awk. Supports PEAKS_ONLY shell mode for re-running only the peak
  extraction stage.
---

# Audio-Synth-STFT-Peaks Pipeline Skill

## Task Family Overview

This skill covers a three-stage audio processing pipeline:

1. **Synthesis**: Generate a mono WAV file from summed sine tones + noise, RMS-normalized to a target level, quantized to PCM int16.
2. **STFT Analysis**: Compute the Short-Time Fourier Transform using `scipy.signal.stft` and export linear magnitude to a CSV file.
3. **Peak Extraction**: Use awk to find the top-k spectral magnitude bins per time frame, outputting them in descending order.

A shell script orchestrates the pipeline and supports a `PEAKS_ONLY=1` mode that skips synthesis/STFT and only runs the awk peak extraction on an existing `mag.csv`.

## Three Axes of Variation

### Axis 1: Synthesis Signal Parameters

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| Sample rate (fs) | 12000 Hz | Any valid audio rate |
| Duration | 2.5 s | Arbitrary |
| Tone count | 4 | Any positive integer |
| Frequencies | [180, 360, 540, 720] Hz | Arbitrary positive values < fs/2 |
| Noise distribution | Gaussian, sigma=0.01, seed=42 | Any distribution/seed |
| Target RMS | 0.15 | Any positive value < 1.0 |
| RMS tolerance | +/-0.002 | Task-specified |

**Critical implementation rule**: Normalize the *noisy* (signal+noise) signal to the target RMS *before* int16 quantization. Use `np.clip(normalized * 32767, -32768, 32767).astype(np.int16)` to prevent wrap-around from float values slightly above 1.0.

### Axis 2: STFT Configuration

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| Window | 'blackman' | Any scipy window (hann, hamming, etc.) |
| nperseg | 768 | Any positive even integer |
| noverlap | 576 | Must be < nperseg |
| nfft | 1024 | >= nperseg, typically power of 2 |
| boundary | None | None, 'even', 'odd', etc. |
| padded | False | True/False |
| return_onesided | True | True for real signals |

**Derived quantities**:
- `hop = nperseg - noverlap`
- `n_frames = (n_samples - nperseg) // hop + 1` (when boundary=None, padded=False)
- `n_bins = nfft // 2 + 1` (one-sided)

**CSV schema**: `frame,bin,val` -- one row per (frame, bin) pair, linear magnitude (not dB). Use scientific notation with sufficient precision (`.10e` format).

**Critical**: `scipy.signal.stft` returns `Zxx` with shape `(n_bins, n_frames)`. Do not swap axes when iterating.

### Axis 3: Peak Extraction Logic

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| top-k | 3 | Any positive integer <= n_bins |
| Output columns | frame,f1_bin,f2_bin,f3_bin | frame + k bin columns |
| Tie-breaking | First encountered wins (awk insertion order) | Task-specified |
| Indexing | 0-based bins and frames | 0 or 1-based |

## Implementation Patterns

### Python: Synthesis + STFT (audioproc.py)

```python
import os, numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# --- Synthesis ---
fs = <sample_rate>
duration = <duration_sec>
n_samples = int(fs * duration)
t = np.arange(n_samples) / fs

# Sum of sines
signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)

# Add noise
rng = np.random.default_rng(<seed>)
noise = rng.normal(0, <noise_std>, n_samples)
noisy = signal + noise

# RMS normalize BEFORE quantization
rms = np.sqrt(np.mean(noisy ** 2))
normalized = noisy * (target_rms / rms)

# int16 quantization with clipping
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
wavfile.write('data/clip.wav', fs, int16_signal)

# --- STFT ---
f_bins, t_frames, Zxx = stft(
    normalized,  # Use float signal, not int16
    fs=fs, window=<window>, nperseg=<nperseg>,
    noverlap=<noverlap>, nfft=<nfft>,
    boundary=<boundary>, padded=<padded>,
    return_onesided=True
)
mag = np.abs(Zxx)  # Linear magnitude

# Export CSV
with open('data/mag.csv', 'w') as fout:
    fout.write('frame,bin,val\n')
    for frame_idx in range(mag.shape[1]):
        for bin_idx in range(mag.shape[0]):
            fout.write(f'{frame_idx},{bin_idx},{mag[bin_idx, frame_idx]:.10e}\n')
```

### Awk: Top-k Peak Extraction

The awk script uses a **running top-k insertion** algorithm. Data arrives sorted by frame (contiguous rows per frame). When the frame changes, emit the previous frame's top-k and reset.

**Generic top-k awk pattern** (shown for k=3):

```awk
BEGIN { FS=","; OFS=","; cf=-1 }
NR==1 { next }
{
    f=$1; b=$2; v=$3+0
    if (f != cf) {
        if (cf >= 0) print cf, b1, b2, b3
        cf=f; v1=v2=v3=-1; b1=b2=b3=0
    }
    if (v > v1)      { v3=v2; b3=b2; v2=v1; b2=b1; v1=v; b1=b }
    else if (v > v2) { v3=v2; b3=b2; v2=v; b2=b }
    else if (v > v3) { v3=v; b3=b }
}
END { if (cf >= 0) print cf, b1, b2, b3 }
```

**Key implementation details**:
- Initialize `cf=-1` (not empty string) to avoid awk numeric coercion bug where `0 != ""` evaluates to false
- `$3+0` forces numeric comparison (prevents string comparison bugs)
- The insertion cascade maintains the invariant `v1 >= v2 >= v3`
- For general top-k, use an array and insertion sort instead of scalar variables

### Shell: Pipeline Orchestration (run_audio_pipeline.sh)

```bash
#!/bin/bash
set -e

AWK_SCRIPT='<the awk program above>'

if [ "${PEAKS_ONLY}" = "1" ]; then
    echo "frame,f1_bin,f2_bin,f3_bin" > data/peaks.csv
    awk "$AWK_SCRIPT" data/mag.csv >> data/peaks.csv
    exit 0
fi

# Full pipeline
mkdir -p data
python3 audioproc.py
echo "frame,f1_bin,f2_bin,f3_bin" > data/peaks.csv
awk "$AWK_SCRIPT" data/mag.csv >> data/peaks.csv
```

**Key constraints**:
- The shell script owns peaks.csv generation (not Python)
- `awk` is invoked via PATH (no absolute path)
- PEAKS_ONLY=1 must skip Python entirely
- Header row is written by shell, data rows by awk

## Common Pitfalls

1. **RMS after quantization**: Normalizing int16 values loses precision. Always normalize the float signal first.
2. **int16 wrap-around**: Values > 1.0 multiplied by 32767 overflow. Always clip before casting.
3. **STFT axis confusion**: `Zxx` shape is `(n_bins, n_frames)`, not `(n_frames, n_bins)`.
4. **dB vs linear**: Use `np.abs(Zxx)` for linear magnitude. dB would be `20 * np.log10(...)`.
5. **Awk empty-string comparison**: Uninitialized awk variables are "" which equals 0 numerically. Initialize `cf=-1` to detect the first frame transition correctly.
6. **String vs numeric in awk**: Always use `$3+0` to force numeric comparison of magnitude values.
7. **Missing header in peaks.csv**: The header must be present; write it from shell before awk appends data.

## Verification Checklist

- [ ] clip.wav: correct fs, duration, dtype=int16, RMS within tolerance
- [ ] mag.csv: header `frame,bin,val`, correct number of rows = n_frames * n_bins
- [ ] peaks.csv: header `frame,f1_bin,...,fk_bin`, n_frames data rows, 0-indexed
- [ ] Peak bins match independent Python verification (np.argsort)
- [ ] PEAKS_ONLY=1 produces identical peaks.csv without running Python
- [ ] Descending magnitude order: f1 >= f2 >= f3 (by construction of awk algorithm)

---
name: audio-synth-stft-peaks
description: >
  Build a three-stage audio processing pipeline: (1) synthesize a mono WAV from
  summed sine tones plus noise with RMS normalization, (2) compute an STFT via
  scipy and export linear magnitude to CSV, (3) extract top-k spectral peaks per
  frame using awk. Supports a PEAKS_ONLY mode that re-runs only the awk stage.
---

# Audio Synth → STFT → Peaks Pipeline

## Overview

This skill covers a deterministic audio-processing pipeline with three stages:

```
[Python synthesis] → clip.wav
                   → mag.csv  (STFT magnitudes)
[awk extraction]   → peaks.csv (top-k bins per frame)
```

A shell script (`run_audio_pipeline.sh`) orchestrates all stages and supports
a `PEAKS_ONLY=1` mode that skips synthesis/STFT and only regenerates peaks.csv.

## Family Invariants (always true across variants)

1. **Three stages, two languages**: Python (scipy) handles synthesis + STFT; awk
   handles peak extraction. Python must never write peaks.csv.
2. **Directory layout**: `data/clip.wav`, `data/mag.csv`, `data/peaks.csv`,
   `audioproc.py`, `run_audio_pipeline.sh` — all under `/app/`.
3. **STFT via scipy**: Always `scipy.signal.stft`. The magnitude export is
   linear (not dB) unless the variant explicitly says otherwise.
4. **awk invocation**: Always `awk` (PATH-based, never absolute path).
5. **PEAKS_ONLY mode**: Shell script must check `PEAKS_ONLY=1` env var. When
   set, read existing `mag.csv`, produce `peaks.csv` via awk, and exit without
   running Python.
6. **CSV ordering contract**: `mag.csv` rows must be in **frame-major order**
   (all bins for frame 0, then all bins for frame 1, etc.). This is required
   for the streaming awk approach that groups consecutive rows by frame.

## Key Mechanisms

### 1. Signal Synthesis

```python
n_samples = int(sample_rate * duration)
t = np.arange(n_samples) / sample_rate
signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)
signal += rng.normal(0, noise_sigma, n_samples)
# RMS normalize BEFORE quantization:
rms = np.sqrt(np.mean(signal**2))
signal *= target_rms / rms
# Then quantize to int16:
int16_data = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
```

**Critical**: Normalize the float signal first, then scale to int16. The RMS
check should be on the float signal before quantization.

**Noise level**: When the task says "Add Gaussian noise" without specifying sigma, choose a value that gives post-normalization residual_std in [0.004, 0.02]. For N unit-amplitude sines (signal_rms ≈ sqrt(N/2)), the noise gets scaled by target_rms/signal_rms. With 4 sines and target_rms=0.15, scale ≈ 0.106, so noise_sigma=0.05 gives residual_std ≈ 0.0053 (safely in range).

### 2. STFT Computation

**CRITICAL**: STFT must be computed from the **quantized signal** (read back from WAV), not the pre-quantization float. Tests verify mag.csv values against STFT recomputed from the WAV file, so the signal must match exactly.

```python
# Save WAV first
wavfile.write('data/clip.wav', sample_rate, int16_data)

# Read WAV back to get the exact quantized signal
sr_read, data_read = wavfile.read('data/clip.wav')
signal_from_wav = data_read.astype(np.float64) / 32767.0

# Compute STFT on the quantized signal
from scipy.signal import stft
f_freqs, t_frames, Zxx = stft(
    signal_from_wav, fs=sample_rate, window=window_type,
    nperseg=nperseg, noverlap=noverlap, nfft=nfft,
    boundary=boundary, padded=padded, return_onesided=onesided
)
magnitude = np.abs(Zxx)  # linear magnitude
```

**Predicting peak bin locations**: For a pure tone at frequency `f` Hz:
```
expected_bin = round(f * nfft / sample_rate)
```
This is the single most useful sanity check. For one-sided STFT with nfft=N,
bins range from 0 to N//2.

**Output shape**: `magnitude` is `(n_bins, n_frames)`. When writing CSV in
frame-major order, iterate frames in the outer loop and bins in the inner loop.

### 3. CSV Export

Standard schema: `frame,bin,val` (one row per bin per frame).
Variants may change column names, delimiter, or add dB scaling, but the
frame-major ordering must be preserved.

```python
with open("data/mag.csv", "w") as f:
    f.write("frame,bin,val\n")
    for frame_idx in range(n_frames):
        for bin_idx in range(n_bins):
            f.write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10g}\n")
```

### 4. Awk Peak Extraction (Top-k per Frame)

The awk script uses a **streaming frame-group** approach:
- Track current frame; when frame changes, emit top-k from accumulated bins.
- Use partial selection sort to find top-k bins by magnitude (descending).
- Tie-breaking: prefer lower bin index (deterministic).

```awk
BEGIN { FS=","; OFS=","; print "frame,f1_bin,f2_bin,f3_bin"; cur=-1; n=0 }

function emit_topk(k,    i,j,mx) {
    for (i=1; i<=k && i<=n; i++) {
        mx = i
        for (j=i+1; j<=n; j++)
            if (v[j]>v[mx] || (v[j]==v[mx] && b[j]<b[mx])) mx=j
        if (mx!=i) {
            tv=v[i]; v[i]=v[mx]; v[mx]=tv
            tb=b[i]; b[i]=b[mx]; b[mx]=tb
        }
    }
    printf "%d", cur
    for (i=1; i<=k; i++) printf ",%d", (i<=n ? b[i] : 0)
    printf "\n"
}

NR==1 { next }
{
    f=$1+0; bin=$2+0; val=$3+0.0
    if (f != cur) {
        if (cur >= 0) emit_topk(3)
        cur = f; n = 0
    }
    n++; v[n]=val; b[n]=bin
}
END { if (cur >= 0) emit_topk(3) }
```

**Adapting top-k**: Change the `k` argument in `emit_topk(k)` and the header
columns. The partial selection sort handles arbitrary k.

### 5. Shell Script Structure

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    awk -F',' '...' /app/data/mag.csv > /app/data/peaks.csv
    exit 0
fi

# Full pipeline
python3 /app/audioproc.py
awk -F',' '...' /app/data/mag.csv > /app/data/peaks.csv
```

## Adaptation Guide for New Variants

When encountering a new task.yaml in this family:

1. **Extract synthesis parameters**: sample_rate, duration, frequencies, noise
   type/sigma, target_rms. Plug into the synthesis template.
   - If noise sigma is unspecified, choose a value giving post-normalization
     residual_std in [0.004, 0.02]. For N unit-amplitude sines:
     noise_sigma ≈ 0.05 is a safe default (gives ~0.005 after normalization).
2. **Extract STFT parameters**: window, nperseg, noverlap, nfft, boundary,
   padded, return_onesided. Plug into `scipy.signal.stft()`.
3. **Extract peak parameters**: top-k value, tie-breaking rule, output columns.
   Adapt the awk script's `emit_topk(k)` and header.
4. **Verify with bin formula**: `expected_bin = round(freq * nfft / fs)`.
   Check that the top peaks in mag.csv land near these bins.
5. **Check CSV schema**: If the variant changes column names or adds dB scaling,
   adjust both the Python writer and awk field references.
6. **Test PEAKS_ONLY**: Always verify `PEAKS_ONLY=1 bash run_audio_pipeline.sh`
   produces identical peaks.csv to the full pipeline run.
7. **STFT signal source**: Always compute STFT from the quantized signal read
   back from WAV, not the pre-quantization float. This is required for test
   validation.

## Common Pitfalls

- **STFT on wrong signal (CRITICAL)**: STFT must be computed from the **quantized signal read back from WAV**, not the pre-quantization float. Tests recompute STFT from the WAV file and compare against mag.csv values. Computing STFT on the pre-quantization float causes ~1% mismatch that fails `math.isclose(rel_tol=1e-6)`. Always: save WAV → read WAV back → compute STFT on the read-back float signal.
- **Noise too small (CRITICAL)**: Tests check that residual_std (after fitting and subtracting the required tones) is in [0.004, 0.02]. If noise_sigma is too small (e.g., 0.01), after RMS normalization the residual will be ~0.001, failing the check. For N unit-amplitude sines with target_rms=0.15: noise_sigma must be ≥ 0.04. Use 0.05 as a safe default.
- **RMS after quantization**: Don't compute RMS on int16 data. Normalize floats
  first, then quantize.
- **Boundary/padded defaults**: scipy stft defaults are `boundary='zeros'`,
  `padded=True`. The task may specify `boundary=None, padded=False` — these
  change the number of frames significantly.
- **n_bins for one-sided**: With `return_onesided=True` and `nfft=N`, n_bins =
  N//2 + 1. With `return_onesided=False`, n_bins = N.
- **awk floating point**: mawk handles floats fine but be explicit with `+0.0`
  to force numeric comparison.
- **Frame count mismatch**: With `boundary=None, padded=False`, frame count
  depends on `(n_samples - nperseg) / (nperseg - noverlap) + 1`. Verify this
  matches expectations.
- **Awk duplication**: The awk script must appear in BOTH the PEAKS_ONLY branch
  and the full-pipeline branch of the shell script. A common mistake is to
  extract it into a function but forget to call it in one path.

## Verification Checklist

After building the pipeline, run these checks:

1. **WAV properties**: Correct sample rate, int16 dtype, correct duration
   (`len(data) == sample_rate * duration`).
2. **RMS tolerance**: Float RMS of the signal (before quantization) must be
   within the specified tolerance of the target (e.g., `|rms - 0.15| < 0.002`).
3. **Residual std**: After fitting the required tones and subtracting, the
   residual std must be in [0.004, 0.02]. Verify:
   `residual_std = np.std(signal - fitted_tones)`. If too low, increase
   noise_sigma.
4. **Frame count**: `n_frames == (n_samples - nperseg) // (nperseg - noverlap) + 1`
   when `boundary=None, padded=False`.
5. **Bin count**: `n_bins == nfft // 2 + 1` for one-sided, `n_bins == nfft` for
   two-sided.
6. **CSV row count**: `len(mag.csv) - 1 == n_frames * n_bins` (minus header).
7. **Peak bin prediction**: Top peaks should be near
   `round(freq * nfft / fs)` for each synthesized tone frequency.
8. **Descending magnitude**: For each frame in peaks.csv, verify that the
   magnitudes at f1_bin >= f2_bin >= f3_bin.
9. **PEAKS_ONLY equivalence**: `diff` peaks.csv from full pipeline vs.
   PEAKS_ONLY mode — must be identical.
10. **STFT signal source**: Verify mag.csv values match STFT recomputed from
   WAV file (read back, convert to float, compute STFT). Sample a few rows
   and check `math.isclose(csv_val, recomputed_val, rel_tol=1e-6)`.
11. **Peak row count**: `len(peaks.csv) - 1 == n_frames` (one row per frame).

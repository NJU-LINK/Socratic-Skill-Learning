---
name: audio-synth-stft-peaks
description: >
  Build a reproducible audio-processing pipeline: synthesize a mono WAV from
  summed sine tones with noise and RMS normalization, compute an STFT via
  scipy.signal.stft and export linear magnitude to CSV, then extract the top-k
  spectral peaks per frame using awk in a shell-orchestrated pipeline.
---

# Audio Synth → STFT → Peak Extraction Pipeline

## Task Family Overview

This family covers three-stage audio processing pipelines:

1. **Synthesis**: Deterministic generation of a mono WAV file from parameterized sine tones, noise, and normalization.
2. **STFT**: Compute Short-Time Fourier Transform using scipy and export magnitude data to CSV.
3. **Peak Extraction**: Use awk (not Python) to find the top-k spectral magnitude bins per time frame.

A shell script orchestrates the pipeline and supports a `PEAKS_ONLY` mode that skips synthesis/STFT.

## Key Invariants (across all variants)

- `audioproc.py` produces ONLY the WAV and magnitude CSV — never `peaks.csv`
- `run_audio_pipeline.sh` orchestrates everything and invokes `awk` (via PATH, no absolute path) to produce `peaks.csv`
- `PEAKS_ONLY=1` must skip Python entirely and only run the awk peak extraction
- The awk script must perform streaming top-k selection (not load all data into memory)
- Output directory is `data/` containing `clip.wav`, `mag.csv`, `peaks.csv`

## Stage 1: Audio Synthesis

### Mechanism

```python
import numpy as np
from scipy.io import wavfile

fs = <sample_rate>           # e.g. 12000
duration = <duration_sec>    # e.g. 2.5
n_samples = int(fs * duration)
t = np.arange(n_samples) / fs

# Sum of sine tones at specified frequencies
signal = sum(np.sin(2 * np.pi * f * t) for f in freq_list)

# Add noise (distribution and scale may vary)
rng = np.random.default_rng(seed=<seed>)
noise = rng.normal(0, <noise_std>, n_samples)
noisy = signal + noise

# RMS normalization to target
target_rms = <target>        # e.g. 0.15
current_rms = np.sqrt(np.mean(noisy ** 2))
noisy = noisy * (target_rms / current_rms)
```

### ⚠️ CRITICAL: Quantization without Peak Normalization

**DO NOT** perform peak normalization after RMS normalization. The test reads the WAV and computes RMS of the float signal (converted to [-1, 1] range). If you peak-normalize, you destroy the RMS target.

```python
# WRONG: This changes the RMS!
max_val = np.max(np.abs(noisy))
int16_signal = np.int16(noisy / max_val * 32767)  # WRONG!

# CORRECT: Directly scale RMS-normalized signal to int16
# After RMS normalization to 0.15, signal peak is ~0.4, well within int16 range
SCALE_FACTOR = 32767
int16_signal = np.int16(noisy * SCALE_FACTOR)
```

### ⚠️ CRITICAL: Consistent Scale Factors

Use the **same scale factor** for both quantization (float → int16) and read-back (int16 → float). The test's `read_wav_signal` function divides by **32767.0** (not 32768.0).

```python
# Quantize
SCALE_FACTOR = 32767
int16_signal = np.int16(noisy * SCALE_FACTOR)
wavfile.write("data/clip.wav", fs, int16_signal)

# Read back (for STFT computation)
fs_read, int16_read = wavfile.read("data/clip.wav")
signal_float = int16_read.astype(np.float64) / SCALE_FACTOR  # Same factor!
```

If you use different factors (e.g., `* 32768` and `/ 32767.0`), the STFT magnitudes will differ by ~0.003%, which fails tight tolerances (`rel_tol=1e-6`).

## Stage 2: STFT Computation

### ⚠️ CRITICAL: Compute STFT on Round-Tripped Signal

The test reads the WAV file and computes STFT on that signal. Your `mag.csv` must match the STFT of the **quantized** signal, not the original float signal.

```python
# WRONG: STFT on original float signal
f_out, t_out, Zxx = stft(noisy, ...)  # WRONG!

# CORRECT: Read back WAV and compute STFT on that
fs_read, int16_read = wavfile.read("data/clip.wav")
signal_float = int16_read.astype(np.float64) / 32767.0  # Match test's read_wav_signal
f_out, t_out, Zxx = stft(signal_float, ...)  # CORRECT!
```

### STFT Parameters

```python
from scipy.signal import stft

f_out, t_out, Zxx = stft(
    signal_float,
    fs=<fs>,
    window=<window_type>,     # e.g. 'blackman', 'hann'
    nperseg=<nperseg>,        # e.g. 768
    noverlap=<noverlap>,      # e.g. 576
    nfft=<nfft>,              # e.g. 1024
    boundary=<boundary>,      # e.g. None
    padded=<padded>,          # e.g. False
    return_onesided=True
)

mag = np.abs(Zxx)  # Linear magnitude (not dB unless spec says so)
```

### Output shape
- `Zxx.shape = (nfft//2 + 1, num_frames)` for one-sided
- `num_frames` depends on nperseg, noverlap, n_samples, and boundary/padded settings
- For `boundary=None, padded=False`: `num_frames = 1 + (n_samples - nperseg) // (nperseg - noverlap)`

### ⚠️ CRITICAL: Correct Indexing for CSV Export

`mag.shape = (n_bins, n_frames)`, so you must index as `mag[bin_idx, frame_idx]`.

```python
# WRONG: mag[frame_idx, bin_idx]  # IndexError or wrong values!

# CORRECT:
for frame_idx in range(n_frames):
    for bin_idx in range(n_bins):
        f.write(f"{frame_idx},{bin_idx},{mag[bin_idx, frame_idx]:.10g}\n")
```

### CSV export
- Schema: `frame,bin,val` (header row required)
- Iterate frames as outer loop, bins as inner loop (natural ordering for awk streaming)
- Use sufficient float precision: `f"{val:.10g}"` or `repr(val)`
- Frame and bin indices are 0-based integers

### Bin-to-frequency mapping (for verification)
```
freq_resolution = fs / nfft
bin_for_freq(f) = round(f / freq_resolution)
```

## Stage 3: Peak Extraction with awk

### Streaming top-k algorithm

The mag.csv is sorted by frame (outer) then bin (inner). Use a streaming approach:

```awk
BEGIN {
    FS = ","; OFS = ","
    print "frame,f1_bin,f2_bin,f3_bin"  # header (adapt columns to spec)
    prev_frame = -1
    # Initialize k slots to sentinel (-1 means empty)
    t1 = -1; t2 = -1; t3 = -1
    b1 = -1; b2 = -1; b3 = -1
}

NR == 1 { next }  # skip CSV header

{
    frame = $1 + 0; bin = $2 + 0; val = $3 + 0

    # Flush when frame changes
    if (frame != prev_frame && prev_frame >= 0) {
        print prev_frame, b1, b2, b3
        t1 = -1; t2 = -1; t3 = -1
        b1 = -1; b2 = -1; b3 = -1
    }

    # Insertion into sorted top-3 (descending by value)
    if (t1 < 0 || val > t1) {
        t3 = t2; b3 = b2
        t2 = t1; b2 = b1
        t1 = val; b1 = bin
    } else if (t2 < 0 || val > t2) {
        t3 = t2; b3 = b2
        t2 = val; b2 = bin
    } else if (t3 < 0 || val > t3) {
        t3 = val; b3 = bin
    }

    prev_frame = frame
}

END {
    if (prev_frame >= 0) {
        print prev_frame, b1, b2, b3
    }
}
```

### Key implementation points
- `+0` forces numeric comparison (critical for awk)
- Sentinel value `-1` for empty slots; any real magnitude will be `>= 0`
- Tie-breaking: first-encountered bin wins (lower bin index since CSV is sorted by bin within frame)
- The output values `f1 >= f2 >= f3` in magnitude (descending)

## Shell Script Structure

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p data   # or /app/data depending on runtime layout

# PEAKS_ONLY mode: skip everything except awk peak extraction
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk -f peak_extract.awk data/mag.csv > data/peaks.csv
    exit 0
fi

# Full pipeline
python3 audioproc.py
awk -f peak_extract.awk data/mag.csv > data/peaks.csv
```

### Critical contracts
- `awk` invoked by name (PATH lookup), never absolute path
- `audioproc.py` must NOT write `peaks.csv`
- `PEAKS_ONLY=1` must not invoke Python at all
- The awk script can be in a separate `.awk` file or inlined in the shell script

## Verification Checklist

1. **WAV**: correct sample rate, duration (n_samples/fs), mono, int16 dtype
2. **RMS**: float signal RMS (after int16→float conversion with `/ 32767.0`) matches target within tolerance (e.g., ±0.002)
3. **mag.csv**: header `frame,bin,val`; rows = n_bins × n_frames; frame/bin are 0-indexed integers; values match STFT of round-tripped signal
4. **peaks.csv**: header matches spec; rows = n_frames; bins are 0-indexed; values descending
5. **PEAKS_ONLY**: removing peaks.csv then running with `PEAKS_ONLY=1` regenerates it correctly
6. **Cross-validation**: compare awk output against Python `np.argsort` top-k for every frame

## Common Pitfalls

### ❌ Peak normalization after RMS normalization
**Symptom**: RMS of WAV signal is wrong (e.g., 0.40 instead of 0.15)
**Cause**: `int16_signal = np.int16(noisy / max_val * 32767)` changes the RMS
**Fix**: Use `int16_signal = np.int16(noisy * 32767)` directly

### ❌ Inconsistent scale factors
**Symptom**: STFT magnitudes don't match (fail `rel_tol=1e-6`)
**Cause**: Quantize with `* 32768` but test reads with `/ 32767.0`
**Fix**: Use the same `SCALE_FACTOR = 32767` for both (matches test's `read_wav_signal`)

### ❌ Using 32768 instead of 32767 for int16 conversion
**Symptom**: STFT magnitudes don't match (fail `rel_tol=1e-6`), ratio ≈ 32767/32768
**Cause**: Test's `read_wav_signal` divides by 32767.0, not 32768.0
**Fix**: Use `SCALE_FACTOR = 32767` for both quantization and read-back

### ❌ STFT on original float signal
**Symptom**: mag.csv values don't match test expectations
**Cause**: Test computes STFT on signal read from WAV, not original float
**Fix**: Read back WAV and compute STFT on that signal

### ❌ Wrong mag array indexing
**Symptom**: IndexError or wrong magnitude values in CSV
**Cause**: `mag[frame_idx, bin_idx]` when shape is `(n_bins, n_frames)`
**Fix**: Use `mag[bin_idx, frame_idx]`

## Adaptation Guide for Spec Variations

| Variation Axis | What Changes | What Stays the Same |
|---|---|---|
| synthesis_signal_parameters | fs, duration, freq list, noise type/scale, target RMS, envelope | Synthesis→normalize→quantize→WAV pipeline structure; no peak normalization |
| stft_configuration | window, nperseg, noverlap, nfft, boundary, padded, magnitude scaling (linear vs dB), CSV schema | scipy.signal.stft call pattern; frame-major CSV export; compute on round-tripped signal |
| peak_extraction_logic | top-k value, tie-breaking rule, output column names, mode flags | awk streaming pattern; shell orchestration; PEAKS_ONLY contract |

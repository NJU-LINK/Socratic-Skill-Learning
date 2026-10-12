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

# 16-bit quantization: scale to full int16 range then cast
max_val = np.max(np.abs(noisy))
int16_signal = np.int16(noisy / max_val * 32767)
wavfile.write("data/clip.wav", fs, int16_signal)
```

### Critical details
- `n_samples = int(fs * duration)` — must be exact integer
- RMS normalize **before** quantization (the normalization target applies to the float signal)
- The int16 scaling uses `max_val` (peak normalization for quantization), which is separate from RMS normalization
- Always verify: `np.sqrt(np.mean(noisy**2))` should be within tolerance of `target_rms`

## Stage 2: STFT Computation

### Mechanism

```python
from scipy.signal import stft

f_out, t_out, Zxx = stft(
    noisy,
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
    for (i = 1; i <= k; i++) { t[i] = -1; b[i] = -1 }
}

NR == 1 { next }  # skip CSV header

{
    frame = $1 + 0; bin = $2 + 0; val = $3 + 0

    # Flush when frame changes
    if (frame != prev_frame && prev_frame >= 0) {
        printf "%d", prev_frame
        for (i = 1; i <= k; i++) printf ",%d", b[i]
        printf "\n"
        for (i = 1; i <= k; i++) { t[i] = -1; b[i] = -1 }
    }

    # Insertion into sorted top-k (descending by value)
    inserted = 0
    for (i = 1; i <= k; i++) {
        if (t[i] < 0 || val > t[i]) {
            # Shift lower entries down
            for (j = k; j > i; j--) { t[j] = t[j-1]; b[j] = b[j-1] }
            t[i] = val; b[i] = bin
            inserted = 1
            break
        }
    }

    prev_frame = frame
}

END {
    if (prev_frame >= 0) {
        printf "%d", prev_frame
        for (i = 1; i <= k; i++) printf ",%d", b[i]
        printf "\n"
    }
}
```

### Key implementation points
- `+0` forces numeric comparison (critical for awk)
- Sentinel value `-1` for empty slots; any real magnitude will be `>= 0`
- Tie-breaking: first-encountered bin wins (lower bin index since CSV is sorted by bin within frame)
- The output values `f1 >= f2 >= f3` in magnitude (descending)
- For k=3, the hardcoded 3-slot version is slightly faster but the loop version generalizes

### Optimized k=3 version (avoid loops)
```awk
if (t1 < 0 || val > t1) {
    t3=t2; b3=b2; t2=t1; b2=b1; t1=val; b1=bin
} else if (t2 < 0 || val > t2) {
    t3=t2; b3=b2; t2=val; b2=bin
} else if (t3 < 0 || val > t3) {
    t3=val; b3=bin
}
```

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
2. **RMS**: float signal RMS matches target within tolerance (e.g., ±0.002)
3. **mag.csv**: header `frame,bin,val`; rows = n_bins × n_frames; frame/bin are 0-indexed integers
4. **peaks.csv**: header matches spec; rows = n_frames; bins are 0-indexed; values descending
5. **PEAKS_ONLY**: removing peaks.csv then running with `PEAKS_ONLY=1` regenerates it correctly
6. **Cross-validation**: compare awk output against Python `np.argsort` top-k for every frame

## Adaptation Guide for Spec Variations

| Variation Axis | What Changes | What Stays the Same |
|---|---|---|
| synthesis_signal_parameters | fs, duration, freq list, noise type/scale, target RMS, envelope | Synthesis→normalize→quantize→WAV pipeline structure |
| stft_configuration | window, nperseg, noverlap, nfft, boundary, padded, magnitude scaling (linear vs dB), CSV schema | scipy.signal.stft call pattern; frame-major CSV export |
| peak_extraction_logic | top-k value, tie-breaking rule, output column names, mode flags | awk streaming pattern; shell orchestration; PEAKS_ONLY contract |

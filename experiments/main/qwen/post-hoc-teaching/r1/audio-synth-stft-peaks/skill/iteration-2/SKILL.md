---
name: audio-synth-stft-peaks
description: >
  Build a three-stage audio processing pipeline: (1) synthesize a mono WAV from
  summed sine tones plus noise with RMS normalization, (2) compute STFT via
  scipy and export magnitude to CSV, (3) extract top-k spectral peaks per frame
  using awk. Handles parameterized variants of sample rate, duration, tone
  frequencies, STFT configuration, peak count, and output schema.
---

# Audio Synth → STFT → Peaks Pipeline

## Overview

This skill builds a deterministic audio-processing pipeline with three stages:

```
[Python: audioproc.py]          [awk via shell script]
  Synthesize WAV  ──→  clip.wav     ┐
  Compute STFT    ──→  mag.csv     ─┼──→  peaks.csv
                                    ┘
  run_audio_pipeline.sh orchestrates everything
```

**Key invariant**: Python produces `clip.wav` and `mag.csv` only. The shell script invokes awk to produce `peaks.csv`. Python must never write `peaks.csv`.

## Prerequisites

The pipeline requires `numpy` and `scipy`. If they are not already installed:

```bash
apt-get update -qq && apt-get install -y -qq python3-scipy python3-numpy
# or: python3 -m pip install scipy numpy
```

Also requires `awk` (mawk or gawk) on PATH — typically pre-installed.

## Step 0: Extract Parameters from task.yaml

Read the `instruction` field of `task.yaml` carefully. Extract all concrete values for:

### Synthesis parameters
| Parameter | Where to find | v01 example |
|-----------|--------------|-------------|
| Sample rate (Hz) | "Mono, X kHz" | 12000 |
| Duration (seconds) | "exactly Y seconds" | 2.5 |
| Tone frequencies (Hz) | "sines at [...]" | [180, 360, 540, 720] |
| Number of tones | Count from frequency list | 4 |
| Noise type | "Gaussian noise" / "uniform noise" etc. | Gaussian |
| **Noise std** | Often unspecified; compute analytically | `0.01 × signal_rms / RMS_TARGET` (see note below) |
| RMS target | "RMS-normalize ... to Z" | 0.15 |
| RMS tolerance | "+/- T" | 0.002 |
| Bit depth | "16-bit" / "PCM int16" | int16 |

**Critical note on noise std**: The task often says "Add Gaussian noise" without specifying the standard deviation. The test validates that after fitting the required tones, the residual standard deviation is in a specific range (typically [0.004, 0.02]). **Do not use a fixed range** — compute `noise_std` analytically from the signal configuration:

```python
# For N unit-amplitude sines: signal_rms = sqrt(N * 0.5)
signal_rms = np.sqrt(len(FREQUENCIES) * 0.5)
# Target residual_std ≈ 0.01 (geometric mean of [0.004, 0.02])
# residual_std = noise_std * (RMS_target / signal_rms)
# → noise_std = 0.01 * signal_rms / RMS_target
NOISE_STD = 0.01 * signal_rms / RMS_TARGET
```

This formula works for any number of tones and any RMS target. If the task explicitly specifies a noise std, use that value instead.

### STFT parameters
| Parameter | Where to find | v01 example |
|-----------|--------------|-------------|
| fs | Must match sample rate | 12000 |
| window | window='...' | 'blackman' |
| nperseg | nperseg=... | 768 |
| noverlap | noverlap=... | 576 |
| nfft | nfft=... | 1024 |
| boundary | boundary=... | None |
| padded | padded=... | False |
| return_onesided | return_onesided=... | True |
| Magnitude scaling | "linear magnitude" / "dB" / "power" | linear (abs) |

### Peak extraction parameters
| Parameter | Where to find | v01 example |
|-----------|--------------|-------------|
| Top-k | "top N spectral bins" | 3 |
| Output columns | "frame,f1_bin,f2_bin,f3_bin" | frame + k bin columns |
| Indexing | "0-indexed" / "1-indexed" | 0-indexed frames and bins |
| Ordering | "descending order" | f1 >= f2 >= ... >= fk |
| Mode flag | "PEAKS_ONLY=1" | PEAKS_ONLY=1 |

## Step 1: Write audioproc.py

### 1a. Signal synthesis

```python
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile
import os, csv

# === Extract these from task.yaml ===
SAMPLE_RATE = <sample_rate>        # e.g. 12000
DURATION = <duration>              # e.g. 2.5
FREQUENCIES = <freq_list>          # e.g. [180, 360, 540, 720]
RMS_TARGET = <rms_target>          # e.g. 0.15
NOISE_TYPE = <noise_type>          # e.g. 'gaussian'
# NOISE_STD: if not specified by task, compute analytically (see below)

os.makedirs('/app/data', exist_ok=True)
num_samples = int(SAMPLE_RATE * DURATION)
t = np.arange(num_samples) / SAMPLE_RATE

# Sum of sine tones
signal = np.zeros_like(t)
for freq in FREQUENCIES:
    signal += np.sin(2 * np.pi * freq * t)

# Compute noise std analytically if not specified by task
# residual_std ≈ noise_std * (RMS_target / signal_rms)
# For N unit-amplitude sines: signal_rms = sqrt(N * 0.5)
# Target residual_std ≈ 0.01 (geometric mean of [0.004, 0.02])
if NOISE_STD is None:
    signal_rms = np.sqrt(len(FREQUENCIES) * 0.5)
    NOISE_STD = 0.01 * signal_rms / RMS_TARGET

# Add noise (use fixed seed for reproducibility)
rng = np.random.default_rng(42)
if NOISE_TYPE == 'gaussian':
    noise = rng.normal(0, NOISE_STD, len(t))
elif NOISE_TYPE == 'uniform':
    noise = rng.uniform(-NOISE_STD, NOISE_STD, len(t))
else:
    noise = rng.normal(0, NOISE_STD, len(t))  # default fallback

noisy = signal + noise

# RMS normalize BEFORE quantization
rms = np.sqrt(np.mean(noisy**2))
normalized = noisy * (RMS_TARGET / rms)

# Verify RMS is within tolerance
actual_rms = np.sqrt(np.mean(normalized**2))
assert abs(actual_rms - RMS_TARGET) < RMS_TOLERANCE, \
    f"RMS {actual_rms} outside target {RMS_TARGET} +/- {RMS_TOLERANCE}"

# 16-bit quantization
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
wavfile.write('/app/data/clip.wav', SAMPLE_RATE, int16_signal)
```

**Critical details:**
- Normalize the continuous signal, THEN quantize to int16 (not the reverse)
- `int(sample_rate * duration)` gives exact sample count
- RMS normalization: multiply by `target / current_rms`
- **Noise std must be computed analytically**: If unspecified, use `NOISE_STD = 0.01 * signal_rms / RMS_TARGET` where `signal_rms = sqrt(N_tones * 0.5)` for unit-amplitude sines. This targets residual_std ≈ 0.01, safely inside [0.004, 0.02]. Do NOT use a fixed range like "0.05–0.15" — that only works for v01's specific configuration (4 tones, RMS_target=0.15) and will fail on variants.

### 1b. STFT computation and CSV export

**CRITICAL**: The STFT must be computed on the signal **after int16 quantization round-trip**, not on the pre-quantization float signal. The test validates by reading the WAV file back and computing STFT on the quantized signal. Computing STFT on the float signal before quantization introduces small differences that exceed the test's tolerance.

```python
# === STFT parameters from task.yaml ===
STFT_WINDOW = <window>        # e.g. 'blackman', 'hann', 'hamming'
STFT_NPERSEG = <nperseg>      # e.g. 768
STFT_NOVERLAP = <noverlap>    # e.g. 576
STFT_NFFT = <nfft>            # e.g. 1024
STFT_BOUNDARY = <boundary>    # e.g. None, 'zeros', 'even'
STFT_PADDED = <padded>        # e.g. False
RETURN_ONESIDED = <onesided>  # e.g. True
MAG_SCALING = <scaling>       # e.g. 'linear', 'db', 'power'

# CRITICAL: Compute STFT on the quantized-then-dequantized signal
# This matches what the test does (reads WAV back and computes STFT)
signal_for_stft = int16_signal.astype(np.float64) / 32767.0

f, t_frames, Zxx = stft(
    signal_for_stft,  # Use quantized signal, NOT 'normalized'
    fs=SAMPLE_RATE,
    window=STFT_WINDOW,
    nperseg=STFT_NPERSEG,
    noverlap=STFT_NOVERLAP,
    nfft=STFT_NFFT,
    boundary=STFT_BOUNDARY,
    padded=STFT_PADDED,
    return_onesided=RETURN_ONESIDED
)

magnitude = np.abs(Zxx)

# Apply scaling if needed
if MAG_SCALING == 'db':
    magnitude = 20 * np.log10(np.maximum(magnitude, 1e-10))
elif MAG_SCALING == 'power':
    magnitude = magnitude ** 2
# else 'linear' → keep np.abs(Zxx) as-is

# Write CSV: schema from task.yaml (default: frame,bin,val)
# IMPORTANT: use lineterminator='\n' to avoid \r\n (RFC 4180 default)
# which causes silent failures in awk header parsing (\r attaches to last field name)
with open('/app/data/mag.csv', 'w', newline='') as csvfile:
    writer = csv.writer(csvfile, lineterminator='\n')
    writer.writerow(['frame', 'bin', 'val'])
    for frame_idx in range(magnitude.shape[1]):
        for bin_idx in range(magnitude.shape[0]):
            writer.writerow([frame_idx, bin_idx, magnitude[bin_idx, frame_idx]])
```

**Critical details:**
- **STFT input must be the quantized signal**: Compute STFT on `int16_signal.astype(float) / 32767.0`, NOT on the pre-quantization `normalized` float. The test reads the WAV file back and computes STFT on it; using the float signal before quantization causes mismatches that exceed tolerance.
- `magnitude.shape` = (num_bins, num_frames)
- For onesided: num_bins = nfft//2 + 1
- Frame count with `boundary=None, padded=False`: `1 + (N - nperseg) // (nperseg - noverlap)`
- CSV rows are ordered: all bins of frame 0, then all bins of frame 1, etc.
- The CSV schema (column names) may vary by variant — always read from task.yaml
- **Always use `lineterminator='\n'`** in csv.writer. Python's csv module defaults to `\r\n` (RFC 4180), which causes `\r` to attach to the last header field name, making awk header-driven column lookup silently fail (e.g. `col["val\r"]` is set but `col["val"]` is 0).

## Step 2: Write run_audio_pipeline.sh

The shell script must:
1. Orchestrate the full pipeline OR support PEAKS_ONLY mode
2. Use awk (via PATH, not absolute path) for peak extraction
3. Never let Python write peaks.csv

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /app
mkdir -p data

# === Configuration (extract these values from task.yaml in Step 0) ===
TOP_K=3   # number of top spectral peaks per frame

# Mode check: PEAKS_ONLY skips synthesis and STFT
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    echo "PEAKS_ONLY mode: extracting peaks from mag.csv"
    if [ ! -f data/mag.csv ]; then
        echo "ERROR: PEAKS_ONLY=1 but data/mag.csv not found" >&2
        exit 1
    fi
else
    echo "Running full pipeline: synthesis + STFT + peaks"
    python3 audioproc.py
fi

# === Peak extraction via awk ===
# Output columns: frame,f1_bin,f2_bin,...,fK_bin
# Ordering: descending magnitude (f1 >= f2 >= ... >= fK)
# Tie-breaking: first-encountered wins (strict > comparison)
#
# IMPORTANT: Column detection is header-driven. The awk parses the CSV
# header row to build a name->column-index map, so it works regardless
# of column ordering (e.g. "bin,frame,val" vs "frame,bin,val").

awk -F',' '
{ gsub(/\r/, "") }  # strip CR: defensive against \r\n line endings
NR == 1 {
    # Build header-driven column index map
    for (i = 1; i <= NF; i++) {
        col[$i] = i
    }
    next
}
{
    frame = $(col["frame"]) + 0
    bin   = $(col["bin"])   + 0
    val   = $(col["val"])   + 0.0

    # Insert into sorted top-K list for this frame
    # Using strict > means first-encountered wins ties
    for (k = 1; k <= TOP_K; k++) {
        key = frame SUBSEP k
        if (!(key in top_val) || val > top_val[key]) {
            # Shift lower entries down
            for (j = TOP_K; j > k; j--) {
                key_j = frame SUBSEP j
                key_prev = frame SUBSEP (j-1)
                if (key_prev in top_val) {
                    top_val[key_j] = top_val[key_prev]
                    top_bin[key_j] = top_bin[key_prev]
                } else {
                    delete top_val[key_j]
                    delete top_bin[key_j]
                }
            }
            top_val[key] = val
            top_bin[key] = bin
            break
        }
    }

    # Track frame order
    if (!(frame in seen)) {
        seen[frame] = 1
        frames[++nframes] = frame
    }
}
END {
    # Build header
    hdr = "frame"
    for (k = 1; k <= TOP_K; k++) hdr = hdr ",f" k "_bin"
    print hdr

    for (i = 1; i <= nframes; i++) {
        f = frames[i]
        printf "%d", f
        for (k = 1; k <= TOP_K; k++) {
            key = f SUBSEP k
            if (key in top_bin) printf ",%d", top_bin[key]
            else printf ","
        }
        printf "\n"
    }
}
' TOP_K="$TOP_K" data/mag.csv > data/peaks.csv
```

**Alternative simpler awk for fixed top-3** (when TOP_K=3, use explicit f1/f2/f3 variables for clarity and performance, but still with header-driven column detection):

```awk
NR == 1 {
    gsub(/\r/, "")  # strip CR
    for (i = 1; i <= NF; i++) col[$i] = i
    next
}
{ gsub(/\r/, "") }
{
    frame = $(col["frame"]) + 0
    bin   = $(col["bin"])   + 0
    val   = $(col["val"])   + 0.0
    if (!(frame in f1_val) || val > f1_val[frame]) {
        f3_val[frame]=f2_val[frame]; f3_bin[frame]=f2_bin[frame]
        f2_val[frame]=f1_val[frame]; f2_bin[frame]=f1_bin[frame]
        f1_val[frame]=val; f1_bin[frame]=bin
    } else if (!(frame in f2_val) || val > f2_val[frame]) {
        f3_val[frame]=f2_val[frame]; f3_bin[frame]=f2_bin[frame]
        f2_val[frame]=val; f2_bin[frame]=bin
    } else if (!(frame in f3_val) || val > f3_val[frame]) {
        f3_val[frame]=val; f3_bin[frame]=bin
    }
    if (!(frame in seen)) { seen[frame]=1; frames[++nframes]=frame }
}
END {
    print "frame,f1_bin,f2_bin,f3_bin"
    for (i=1; i<=nframes; i++) {
        f=frames[i]
        printf "%d,%d,%d,%d\n", f, f1_bin[f], f2_bin[f], f3_bin[f]
    }
}
```

## Step 3: Verify Outputs

### WAV verification
```python
from scipy.io import wavfile
sr, data = wavfile.read('/app/data/clip.wav')
assert sr == SAMPLE_RATE
assert len(data) == int(SAMPLE_RATE * DURATION)
assert data.dtype == np.int16
rms = np.sqrt(np.mean((data.astype(float) / 32767.0)**2))
assert abs(rms - RMS_TARGET) < RMS_TOLERANCE
```

### STFT shape verification
```python
# Expected dimensions
hop = nperseg - noverlap
expected_frames = 1 + (num_samples - nperseg) // hop  # when boundary=None, padded=False
expected_bins = nfft // 2 + 1  # when return_onesided=True
# Check mag.csv row count
# rows = expected_frames * expected_bins
```

### Peak verification
- Each frame must have exactly K distinct bin indices
- Bins must be in descending magnitude order: f1 >= f2 >= ... >= fK
- Cross-check with Python: load mag.csv, sort by value per frame, compare top-K

## Common Pitfalls

1. **Normalize before quantization**: Always RMS-normalize the float signal, then scale to int16. Never quantize first.
2. **STFT input must be quantized signal**: The test validates STFT by reading the WAV file back and computing STFT on the quantized int16 data. You must compute STFT on `int16_signal.astype(float) / 32767.0`, NOT on the pre-quantization normalized float. Using the float signal causes small magnitude mismatches that exceed the test's `rel_tol=1e-6` tolerance.
3. **Noise std must be computed analytically**: If unspecified, use `NOISE_STD = 0.01 * signal_rms / RMS_TARGET` where `signal_rms = sqrt(N_tones * 0.5)` for unit-amplitude sines. This targets residual_std ≈ 0.01, safely inside [0.004, 0.02]. Do NOT use a fixed range like "0.05–0.15" — that only works for v01's specific configuration and will fail on variants.
4. **CSV ordering**: Iterate frames in outer loop, bins in inner loop.
5. **awk tie-breaking**: With `>` (strict), first-encountered bin wins ties. Use `>=` if last-encountered should win.
6. **PEAKS_ONLY**: Must skip Python entirely and only run awk on existing mag.csv.
7. **awk PATH**: Use `awk` not `/usr/bin/awk` or `/usr/bin/gawk`.
8. **Frame indexing**: 0-indexed by default; the first data row in mag.csv has frame=0.
9. **Boundary/padded**: `boundary=None, padded=False` gives exact frame count formula above. Other settings change the count.
10. **Magnitude scaling**: Default is linear magnitude `abs(Zxx)`. If task says "dB" or "power", transform accordingly.
11. **mawk vs gawk**: The `SUBSEP` approach works in both. Avoid gawk-only features like `delete array` (use `split` or loop-based clearing for mawk compatibility).
12. **Header-driven column detection**: Never hardcode `$1/$2/$3` in awk when reading CSV. Always parse the header row to build a `col[name]=index` map and use `$(col["frame"])`, `$(col["bin"])`, `$(col["val"])`. Variants may reorder columns (e.g. `bin,frame,val`) or rename them, and hardcoded positions produce silent garbage output — the most dangerous failure mode.
13. **PEAKS_ONLY guard**: Always check that `data/mag.csv` exists before running awk in PEAKS_ONLY mode, otherwise awk silently produces an empty peaks.csv.
14. **CSV line endings (\r\n)**: Python's `csv.writer` defaults to `\r\n` line terminators (RFC 4180). This causes `\r` to attach to the last header field name, making awk's `col["val"]` lookup return 0 (because the actual key is `"val\r"`). Always use `csv.writer(f, lineterminator='\n')` in Python, AND add `{ gsub(/\r/, "") }` as the first rule in awk as a defensive measure.

## Directory Structure

```
/app/
├── audioproc.py              # Python: synthesis + STFT → clip.wav + mag.csv
├── run_audio_pipeline.sh     # Bash: orchestrator + awk peak extraction → peaks.csv
└── data/
    ├── clip.wav              # PCM int16 WAV
    ├── mag.csv               # STFT magnitude: frame,bin,val
    └── peaks.csv             # Top-K bins per frame: frame,f1_bin,...,fK_bin
```

## Adapting to Variants

When task.yaml parameters differ from v01:

1. **Different sample rate / duration**: Change `SAMPLE_RATE`, `DURATION`, and `fs` in stft call.
2. **Different frequencies / tone count**: Update `FREQUENCIES` list.
3. **Different noise**: Change noise generation (Gaussian, uniform, etc.).
4. **Different STFT params**: Update all stft() keyword arguments and recalculate expected shapes.
5. **Different window**: Pass different string to `window=` (e.g., 'hann', 'hamming', 'blackman').
6. **Different magnitude scaling**: Apply log/power transform after `np.abs()`.
7. **Different top-k**: Adjust awk to track K entries instead of 3; update output header.
8. **Different CSV schema**: The awk uses header-driven column detection (`NR==1 { for(i=1;i<=NF;i++) col[$i]=i }`), so column reordering is handled automatically. If column *names* change (e.g. `magnitude` instead of `val`), update the `col["..."]` lookups in awk accordingly.
9. **Different mode flags**: Adapt shell script to check the specified environment variable.
10. **Different output columns**: Adjust awk END block to emit the required column format.

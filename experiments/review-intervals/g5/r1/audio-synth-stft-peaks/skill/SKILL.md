---
name: audio-synth-stft-peaks
description: >
  Build a deterministic audio-processing pipeline that synthesizes a WAV file
  from summed sine tones with noise and RMS normalization, computes an STFT
  via scipy and exports linear magnitude to CSV, then extracts the top-k
  spectral peaks per frame using awk. Handles arbitrary synthesis parameters,
  STFT configurations, and peak-extraction logic within the family.
---

# Audio Synth → STFT → Peaks Pipeline

## Overview

This skill covers a three-stage pipeline:

1. **Synthesis**: Generate a mono PCM WAV from summed sine tones + noise, RMS-normalized to a target level before 16-bit quantization.
2. **STFT**: Compute Short-Time Fourier Transform using `scipy.signal.stft` and export linear magnitude in long-format CSV.
3. **Peak Extraction**: Use `awk` to find the top-k spectral magnitude bins per frame, outputting one row per frame.

The pipeline is orchestrated by a Bash script that supports a `PEAKS_ONLY` mode to re-run only the awk stage.

## Critical Formulas and Invariants

### STFT Frame Count

When `boundary=None` and `padded=False`:

```
n_segments = 1 + (len(signal) - nperseg) // (nperseg - noverlap)
```

This is the exact formula scipy uses internally. It matters when variants change duration, sample rate, nperseg, or noverlap.

**Boundary handling variants**: The `boundary` and `padded` parameters affect frame count:
- `boundary=None, padded=False` (v01): Uses the formula above
- `boundary='zeros', padded=False`: Extends signal with zeros at boundaries, may add frames
- `boundary=None, padded=True`: Pads signal to fit complete segments, may add frames
- `boundary='even', padded=True`: Reflects signal at boundaries

When these parameters change, the frame count formula changes. Always verify the actual frame count by checking `Zxx.shape[1]` after computing STFT, rather than relying solely on the formula.

### Bin-to-Frequency Mapping

For one-sided STFT with `nfft` points:

```
bin_freq = bin_index * fs / nfft
```

Inverse: to find which bin a tone at frequency `f` lands on:

```
expected_bin = round(f * nfft / fs)
```

This is essential for verifying that peaks appear at the correct bins.

### Number of Bins (One-Sided)

```
n_bins = nfft // 2 + 1
```

### RMS Normalization Order

1. Generate float64 signal (sum of sines + noise)
2. Compute current RMS: `sqrt(mean(signal^2))`
3. Scale: `signal *= target_rms / current_rms`
4. Clip to [-1.0, 1.0]
5. Quantize to int16: `(signal * 32767).astype(int16)`

**The order matters**: normalization must happen on the float signal before quantization. Normalizing after int16 conversion would give different results due to integer rounding.

### STFT Must Use Quantized Signal

**Critical**: Compute STFT on the signal **as read back from the WAV file** (after int16 quantization), not on the pre-quantization float. Tests verify magnitudes by reading the WAV and computing STFT on that signal. If you compute STFT on the pre-quantization float, magnitudes will diverge slightly due to quantization error.

```python
# WRONG: STFT on pre-quantization float
f, t, Zxx = stft(signal_float, ...)

# CORRECT: Read WAV back, then STFT
with wave.open(wav_path, 'r') as wf:
    raw = wf.readframes(wf.getnframes())
    signal_quantized = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767.0
f, t, Zxx = stft(signal_quantized, ...)
```

### Noise Calibration (General Procedure)

The noise standard deviation must be calibrated so that the post-normalization residual standard deviation falls within the test's expected range. The exact range varies by variant (v01 uses [0.004, 0.02]).

**General calibration procedure**:
1. Generate the signal (sum of sines + noise) with a trial `noise_std`
2. RMS-normalize to `target_rms`
3. Fit the tones via least squares to extract the residual
4. Compute `residual_std = np.std(residual)`
5. Adjust `noise_std` iteratively until `residual_std` is in the target range

**Approximate formula** (for initial guess):
```
noise_std_after ≈ noise_std × target_rms / sqrt(sum_of_sines_rms² + noise_std²)
```

Where `sum_of_sines_rms` is the RMS of the noiseless signal before normalization. For N equal-amplitude sines, `sum_of_sines_rms = sqrt(N/2)`.

**Example for v01** (4 sines, target_rms=0.15, residual_std range [0.004, 0.02]):
- `sum_of_sines_rms = sqrt(4/2) = sqrt(2) ≈ 1.414`
- Safe range: `0.04 ≤ NOISE_STD ≤ 0.18`
- Tested value: `NOISE_STD = 0.05` gives residual_std ≈ 0.0053

**For variants**: Read the test file to find the expected `residual_std` range, then use the iterative procedure to find the right `noise_std`.

### WAV Read-Back RMS Tolerance

Due to int16 quantization, the read-back RMS will differ slightly from the target. The tolerance is typically ±0.002 for target RMS around 0.15.

## Stage 1: Audio Synthesis

```python
import numpy as np
import wave
import os

def synthesize(sample_rate, duration, frequencies, noise_std):
    """Generate sum of sines + Gaussian noise."""
    n_samples = int(sample_rate * duration)
    t = np.arange(n_samples) / sample_rate
    signal = np.zeros(n_samples, dtype=np.float64)
    for freq in frequencies:
        signal += np.sin(2 * np.pi * freq * t)
    # noise_std must be calibrated: see "Noise Calibration" section above
    signal += np.random.normal(0, noise_std, n_samples)
    return signal

**Noise distribution variants**: The task may specify a different noise distribution:
- **Gaussian noise** (v01): `np.random.normal(0, noise_std, n_samples)`
- **Uniform noise**: `np.random.uniform(-noise_std, noise_std, n_samples)`
- **Pink noise**: Requires filtering white noise (1/f spectrum)
- **No noise**: Omit the noise addition step

Always check the task specification. If it says "Gaussian noise" or doesn't specify, use `np.random.normal()`. The noise calibration procedure still applies regardless of distribution.

**Amplitude envelope variants**: The task may specify time-varying amplitude envelopes:
- **Constant amplitude** (v01): All tones have constant amplitude throughout
- **Linear fade in/out**: Multiply signal by a ramp function
- **Exponential decay**: Multiply by `np.exp(-decay_rate * t)`
- **Per-tone envelopes**: Different tones have different envelopes

If the task specifies an envelope, apply it to the signal before RMS normalization. The envelope affects the signal's RMS, so noise calibration must account for it.

def rms_normalize(signal, target_rms):
    """RMS-normalize to target."""
    current_rms = np.sqrt(np.mean(signal ** 2))
    return signal * (target_rms / current_rms)

def save_wav_16bit(signal, filepath, sample_rate):
    """Save as mono 16-bit PCM WAV."""
    clipped = np.clip(signal, -1.0, 1.0)
    int_data = (clipped * 32767).astype(np.int16)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with wave.open(filepath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int_data.tobytes())

def read_wav_signal(filepath):
    """Read WAV file back as float64 signal in [-1, 1]."""
    with wave.open(filepath, 'r') as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767.0
```

## Stage 2: STFT Computation

```python
from scipy.signal import stft

def compute_stft_from_wav(wav_path, fs, window, nperseg, noverlap, nfft):
    """Read WAV and compute STFT on the quantized signal.
    
    CRITICAL: Must read back from WAV file, not use pre-quantization float.
    Tests verify by reading the WAV and computing STFT on that signal.
    """
    signal = read_wav_signal(wav_path)
    f, t, Zxx = stft(
        signal,
        fs=fs,
        window=window,
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=nfft,
        boundary=None,
        padded=False,
        return_onesided=True
    )
    return f, t, Zxx

def export_magnitude_csv(Zxx, csv_path):
    """Export linear magnitude in long format: frame,bin,val"""
    magnitude = np.abs(Zxx)  # LINEAR magnitude, NOT dB
    n_frames = magnitude.shape[1]
    n_bins = magnitude.shape[0]
    
    with open(csv_path, 'w') as f:
        f.write('frame,bin,val\n')
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                f.write(f'{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}\n')
```

**Key points:**
- Use `np.abs()` for linear magnitude. Do NOT convert to dB unless the task explicitly requires it.
- The CSV is in **long format**: one row per (frame, bin) pair.
- Column order in scipy output: `Zxx[bin_index, frame_index]`.

**Magnitude scaling variants**: The task may require different magnitude representations:
- **Linear magnitude** (v01): `magnitude = np.abs(Zxx)` — use this by default
- **Power magnitude**: `power = np.abs(Zxx)**2`
- **dB magnitude**: `db = 20 * np.log10(np.abs(Zxx) + epsilon)` where epsilon prevents log(0)

Always check the task specification. If it says "linear magnitude" or doesn't specify, use `np.abs()`. If it says "dB" or "decibels", use the log formula.

**CSV schema variants**: The task may specify a different schema. Common variants:
- **Long format** (v01): `frame,bin,val` — one row per (frame, bin) pair
- **Wide format**: `frame,bin0_val,bin1_val,...,binN_val` — one row per frame, all bins as columns
- **Different column names**: e.g., `time,frequency,magnitude` instead of `frame,bin,val`

Always read the task specification carefully to determine the required schema. The awk peak extraction code must be adapted to match the CSV schema.

## Stage 3: Peak Extraction with awk

The awk program maintains a streaming top-k list per frame group. This is the general pattern for any k:

```bash
extract_peaks() {
    local k="${1:-3}"
    local input_csv="$2"
    local output_csv="$3"
    
    awk -v K="$k" '
BEGIN {
    FS = ","; OFS = ","
    # Print header with k columns
    header = "frame"
    for (i = 1; i <= K; i++) header = header ",f" i "_bin"
    print header
    started = 0
}
NR == 1 { next }  # skip header
{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0

    # Frame boundary: output previous frame results
    if (started && frame != cur_frame) {
        printf "%d", cur_frame
        for (i = 1; i <= K; i++) printf ",%d", top_bin[i]
        printf "\n"
    }
    # New frame: reset top-k
    if (!started || frame != cur_frame) {
        cur_frame = frame
        started = 1
        for (i = 1; i <= K; i++) {
            top_val[i] = -1
            top_bin[i] = -1
        }
    }

    # Insert into top-k (descending by val; ties: lower bin index wins)
    inserted = 0
    for (i = 1; i <= K; i++) {
        if (!inserted && (val > top_val[i] || (val == top_val[i] && bin < top_bin[i]))) {
            # Shift down
            for (j = K; j > i; j--) {
                top_val[j] = top_val[j-1]
                top_bin[j] = top_bin[j-1]
            }
            top_val[i] = val
            top_bin[i] = bin
            inserted = 1
            break
        }
    }
}
END {
    if (started) {
        printf "%d", cur_frame
        for (i = 1; i <= K; i++) printf ",%d", top_bin[i]
        printf "\n"
    }
}' "$input_csv" > "$output_csv"
}
```

### Tie-Breaking Rule

When magnitudes are equal, the **lower bin index wins** (ascending bin number). This is implemented by: `val > top_val[i] || (val == top_val[i] && bin < top_bin[i])`.

### The `started` Flag Pattern

The `started` flag is critical for correct handling of frame 0. Without it, awk's uninitialized `cur_frame` (which is "" or 0) would cause the first real frame to be treated as a "new frame" after a spurious "previous frame" output. The pattern:
- Initialize `started = 0`
- Only output on frame transitions when `started == 1`
- Set `started = 1` when processing the first data row
- Output the final frame in the `END` block

**Output column variants**: The task may specify different output columns:
- **Top-k bins** (v01): `frame,f1_bin,f2_bin,f3_bin` — bin indices of top-k magnitudes
- **Top-k values**: `frame,f1_val,f2_val,f3_val` — magnitude values instead of bin indices
- **Top-k bins and values**: `frame,f1_bin,f1_val,f2_bin,f2_val,f3_bin,f3_val`
- **Different k**: Change the loop bounds and column count

Adapt the awk header generation and output statements to match the required schema. The top-k selection logic remains the same.

## Pipeline Orchestration Script

```bash
#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="/app/data"
MAG_CSV="${DATA_DIR}/mag.csv"
PEAKS_CSV="${DATA_DIR}/peaks.csv"

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    # PEAKS_ONLY mode: only run awk stage
    if [ ! -f "$MAG_CSV" ]; then
        echo "ERROR: $MAG_CSV not found" >&2
        exit 1
    fi
    extract_peaks 3 "$MAG_CSV" "$PEAKS_CSV"
    exit 0
fi

# Full pipeline
python3 /app/audioproc.py  # produces clip.wav and mag.csv
extract_peaks 3 "$MAG_CSV" "$PEAKS_CSV"
```

**Key requirements:**
- `PEAKS_ONLY=1` must skip Python entirely and only run awk.
- The script must invoke `awk` via PATH (no absolute paths).
- Python must NOT write `peaks.csv` — only `clip.wav` and `mag.csv`.

## Verification Checklist

When validating a pipeline run:

1. **WAV properties**: Check sample rate, duration, channels, bit depth via `wave` module.
2. **RMS tolerance**: Read back WAV as float64, compute RMS, verify within ±0.002 of target.
3. **Residual std**: Fit the 4 tones via least squares, compute residual std, verify in [0.004, 0.02].
4. **STFT dimensions**: Verify `n_bins = nfft//2 + 1` and `n_frames = 1 + (n_samples - nperseg) // (nperseg - noverlap)`.
5. **CSV row count**: Should be `1 + n_frames * n_bins` (header + data).
6. **STFT magnitude match**: Read WAV back, compute STFT on quantized signal, compare a few random (frame, bin) values with CSV using `math.isclose(rel_tol=1e-6, abs_tol=1e-9)`.
7. **Peak correctness**: Cross-validate awk output against Python's `np.argsort` per frame.
8. **PEAKS_ONLY mode**: Delete peaks.csv, run with `PEAKS_ONLY=1`, verify it regenerates correctly.

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Using dB instead of linear magnitude | Values are negative or very different scale | Use `np.abs(Zxx)` not `20*np.log10(...)` |
| Wrong CSV column order | `bin,frame,val` instead of `frame,bin,val` | Iterate frames outer, bins inner |
| Forgetting `boundary=None, padded=False` | Different frame count than expected | Always pass these explicitly |
| awk frame 0 bug | First row has empty frame field | Use `started` flag pattern |
| Normalizing after int16 conversion | RMS slightly off target | Normalize float signal first, then quantize |
| Tie-breaking wrong order | Peaks differ from reference | Lower bin index wins ties (ascending) |
| Computing STFT on pre-quantization float | Magnitude mismatch with test (e.g., 1.196e-06 vs 1.249e-06) | Read WAV back, compute STFT on quantized signal |
| Noise too low | `residual_std` below test floor (e.g., 0.001 vs required 0.004) | Calibrate `noise_std` to 0.04–0.18 range; see "Noise Calibration" section |

## Adapting to Variants

When parameters change, follow this systematic approach:

### 1. Read the task specification carefully
Identify all parameters that differ from v01:
- Sample rate, duration, tone count, frequencies
- Noise distribution and calibration target
- STFT parameters (window, nperseg, noverlap, nfft, boundary, padded)
- Magnitude scaling (linear, dB, power)
- CSV schema (long format, wide format, column names)
- Peak extraction (top-k, output columns, tie-breaking)

### 2. Update synthesis parameters
```python
SAMPLE_RATE = <from task>
DURATION = <from task>
FREQUENCIES = <from task>
NOISE_STD = <calibrate using the procedure above>
TARGET_RMS = <from task>
```

### 3. Update STFT parameters
```python
f, t, Zxx = stft(
    signal,
    fs=<from task>,
    window=<from task>,  # 'hann', 'blackman', 'hamming', etc.
    nperseg=<from task>,
    noverlap=<from task>,
    nfft=<from task>,
    boundary=<from task>,  # None, 'zeros', 'even', etc.
    padded=<from task>,    # True or False
    return_onesided=True   # Usually True for real signals
)
```

**Important**: Verify the actual frame count by checking `Zxx.shape[1]` after computing STFT, especially if `boundary` or `padded` differ from v01.

### 4. Update magnitude export
```python
# Choose the appropriate magnitude scaling
if task_requires_linear:
    magnitude = np.abs(Zxx)
elif task_requires_db:
    magnitude = 20 * np.log10(np.abs(Zxx) + 1e-10)  # epsilon prevents log(0)
elif task_requires_power:
    magnitude = np.abs(Zxx) ** 2

# Export according to the required CSV schema
# Long format (v01):
for frame_idx in range(n_frames):
    for bin_idx in range(n_bins):
        f.write(f'{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}\n')

# Wide format (example):
for frame_idx in range(n_frames):
    row = [str(frame_idx)]
    for bin_idx in range(n_bins):
        row.append(f'{magnitude[bin_idx, frame_idx]:.10e}')
    f.write(','.join(row) + '\n')
```

### 5. Update peak extraction
```bash
# Adjust K for different top-k
extract_peaks <k> "$MAG_CSV" "$PEAKS_CSV"

# Adjust awk output columns if task requires different schema
# Example: output bins and values instead of just bins
awk -v K="$k" '
BEGIN { ... }
...
END {
    if (started) {
        printf "%d", cur_frame
        for (i = 1; i <= K; i++) printf ",%d,%g", top_bin[i], top_val[i]
        printf "\n"
    }
}'
```

### 6. Verify all outputs
Use the verification checklist, adapting each check to the variant's parameters:
- WAV properties match task specification
- RMS within tolerance
- Residual std in expected range
- STFT dimensions match expected values
- CSV schema matches task specification
- Peak extraction produces correct results
- PEAKS_ONLY mode works correctly

### Common variant patterns

**Different sample rate / duration**: Update `n_samples = int(fs * duration)`, recompute expected frames.

**Different tone frequencies**: Use `expected_bin = round(f * nfft / fs)` to predict peaks.

**Different window type**: Pass to `stft(window=...)` — affects spectral leakage but not frame count.

**Different nperseg/noverlap/nfft**: Recompute `n_bins` and `n_frames` using the formulas above.

**Different top-k**: Change the awk `K` variable and header generation.

**Different CSV schema**: Adjust both Python writer and awk `FS`/field references.

**Different normalization target**: Change `TARGET_RMS` constant; verify read-back RMS.

**Different noise distribution**: Use appropriate numpy random function; noise calibration procedure still applies.

**Different magnitude scaling**: Use appropriate formula (linear, dB, power); adjust awk comparisons if needed.

---
name: audio-synth-stft-peaks
description: >
  Build a deterministic audio-processing pipeline: synthesize a mono WAV from
  summed sine tones with noise and RMS normalization, compute an STFT via
  scipy.signal.stft and export linear magnitude to CSV, then extract the top-K
  spectral peaks per frame using awk. Supports a PEAKS_ONLY mode that skips
  synthesis/STFT and regenerates only the peaks CSV from an existing magnitude
  CSV.
---

# Audio Synth → STFT → Peaks Pipeline

## Overview

This skill covers a three-stage audio processing pipeline:

1. **Synthesis** (Python): Generate a mono WAV file from summed sine tones + Gaussian noise, RMS-normalized to a target level, quantized to 16-bit PCM.
2. **STFT** (Python): Compute the Short-Time Fourier Transform using `scipy.signal.stft` and export linear magnitude to a frame/bin/value CSV.
3. **Peak extraction** (awk): For each frame, find the top-K magnitude bins in descending order and write a peaks CSV.

A shell script orchestrates the pipeline and supports a `PEAKS_ONLY=1` mode that skips stages 1–2 and regenerates only the peaks CSV.

## Parameterized Recipe

### Block 1 — Synthesis Parameters

All synthesis parameters are **variables**, never hardcoded into formulas. Read them from the task specification:

| Parameter | Role | Example (v01) |
|-----------|------|---------------|
| `fs` | Sample rate (Hz) | 12000 |
| `duration` | Signal length (seconds) | 2.5 |
| `freqs` | List of sine frequencies (Hz) | [180, 360, 540, 720] |
| `noise_std` | Gaussian noise standard deviation | 0.1 |
| `target_rms` | Target RMS after normalization | 0.15 |
| `seed` | RNG seed for reproducibility | 42 |

**Procedure:**

```python
import numpy as np
import wave, os

fs = <from task>
duration = <from task>
n_samples = int(fs * duration)
freqs = <from task>

t = np.arange(n_samples) / fs

# Sum of sines
signal = sum(np.sin(2 * np.pi * f * t) for f in freqs)

# Add Gaussian noise
rng = np.random.default_rng(seed=<from task>)
noisy = signal + rng.normal(0, <noise_std>, size=n_samples)

# RMS normalize
current_rms = np.sqrt(np.mean(noisy ** 2))
normalized = noisy * (<target_rms> / current_rms)

# 16-bit quantization (direct conversion, preserve RMS)
int16_signal = (normalized * 32767).astype(np.int16)

# Save WAV
os.makedirs('<data_dir>', exist_ok=True)
with wave.open('<data_dir>/clip.wav', 'w') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(fs)
    wf.writeframes(int16_signal.tobytes())
```

**Key invariants:**
- `n_samples = int(fs * duration)` — always integer truncation
- RMS normalization happens **before** 16-bit quantization
- The int16 conversion directly multiplies by 32767 to preserve the RMS level
- Do NOT divide by peak — that would be a second normalization that changes the RMS
- Mono (1 channel), PCM int16 (sample width = 2 bytes)
- **CRITICAL**: Compute STFT on the quantized signal (int16 converted back to float), not on the pre-quantization float signal. Tests validate mag.csv against STFT computed from the WAV file, so the signal must match exactly.

### Block 2 — STFT Configuration

All STFT parameters are passed **verbatim** to `scipy.signal.stft`. Read them from the task specification:

| Parameter | Role | Example (v01) |
|-----------|------|---------------|
| `window` | Window function name | 'blackman' |
| `nperseg` | Samples per segment | 768 |
| `noverlap` | Overlap between segments | 576 |
| `nfft` | FFT size | 1024 |
| `boundary` | Boundary handling | None |
| `padded` | Whether to pad signal | False |
| `return_onesided` | One-sided vs two-sided | True |

**Procedure:**

```python
import scipy.signal as sig

# CRITICAL: Compute STFT on the quantized signal (int16 converted back to float)
# This ensures mag.csv matches what tests compute from the WAV file
stft_signal = int16_signal.astype(np.float64) / 32767.0

f_stft, t_stft, Zxx = sig.stft(
    stft_signal,
    fs=fs,
    window=<from task>,
    nperseg=<from task>,
    noverlap=<from task>,
    nfft=<from task>,
    boundary=<from task>,
    padded=<from task>,
    return_onesided=<from task>
)

magnitude = np.abs(Zxx)  # linear magnitude, NOT dB
n_frames = magnitude.shape[1]
n_bins = magnitude.shape[0]
```

**Frame and bin count formulas** (when `boundary=None, padded=False`):

```
hop = nperseg - noverlap
n_frames = (n_samples - nperseg) // hop + 1
n_bins = nfft // 2 + 1   # if return_onesided=True
n_bins = nfft             # if return_onesided=False
```

**CSV export schema:**

```
frame,bin,val
0,0,<magnitude[0,0]>
0,1,<magnitude[1,0]>
...
```

- One row per (frame, bin) pair
- `val` is linear magnitude (absolute value of complex STFT), not dB
- Use sufficient precision (e.g., `:.10e`) to preserve numerical accuracy

### Block 3 — Awk Top-K Peak Extraction

The awk stage reads `mag.csv` and produces a peaks CSV with the top-K bins per frame.

**Output schema:**

```
frame,f1_bin,f2_bin,...,fK_bin
```

- One row per frame, 0-indexed
- f1_bin has the highest magnitude, f2_bin the second-highest, etc.
- f1 >= f2 >= ... >= fK in magnitude (descending order)

**Generalized top-K insertion pattern in awk:**

```awk
BEGIN {
    FS = ","
    OFS = ","
    K = <from task>  # e.g., 3
    print "frame,f1_bin,f2_bin,...,fK_bin"  # build header dynamically
}
NR == 1 { next }  # skip header
{
    frame = $1 + 0
    bin = $2 + 0
    val = $3 + 0.0

    # Initialize frame tracking on first encounter
    if (!(frame in seen)) {
        seen[frame] = 1
        for (k = 1; k <= K; k++) {
            top_val[frame, k] = -1
            top_bin[frame, k] = -1
        }
        frame_order[frame_count++] = frame
    }

    # Insertion-sort into top-K
    inserted = 0
    for (k = 1; k <= K; k++) {
        if (val > top_val[frame, k]) {
            # Shift lower entries down
            for (j = K; j > k; j--) {
                top_val[frame, j] = top_val[frame, j-1]
                top_bin[frame, j] = top_bin[frame, j-1]
            }
            top_val[frame, k] = val
            top_bin[frame, k] = bin
            inserted = 1
            break
        }
    }
}
END {
    for (i = 0; i < frame_count; i++) {
        f = frame_order[i]
        printf "%d", f
        for (k = 1; k <= K; k++) {
            printf ",%d", top_bin[f, k]
        }
        printf "\n"
    }
}
```

**Critical gotchas:**

1. **Tie-breaking**: The strict `>` comparison means that for equal magnitudes, the **first-seen** (lower bin index, assuming CSV is ordered by bin within each frame) wins. Variants may require explicit tie-breaking by bin index (ascending or descending) — check the task specification.

2. **Frame ordering**: awk associative arrays have **no guaranteed iteration order**. You must track frame order explicitly using a `frame_order[]` array indexed by encounter sequence, then iterate `0..frame_count-1` in the END block.

3. **Header construction**: Build the output header dynamically from K, not hardcoded. For K=3: `frame,f1_bin,f2_bin,f3_bin`. For K=5: `frame,f1_bin,f2_bin,f3_bin,f4_bin,f5_bin`.

## Shell Script Architecture

The orchestration script must:

1. Support `PEAKS_ONLY=1` mode (check **before** invoking Python)
2. Extract the awk logic into a shell function to avoid duplication
3. Use `awk` from PATH (no absolute paths)
4. Python produces only `clip.wav` and `mag.csv`; awk produces `peaks.csv`

**Template:**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/data"

# Extract awk logic into a function
extract_peaks() {
    local mag_file="$1"
    local peaks_file="$2"
    local K=<from task>  # e.g., 3

    awk -F',' -v K="$K" '
    BEGIN {
        OFS = ","
        # Build header
        header = "frame"
        for (k = 1; k <= K; k++) header = header ",f" k "_bin"
        print header
    }
    NR == 1 { next }
    {
        frame = $1 + 0
        bin = $2 + 0
        val = $3 + 0.0

        if (!(frame in seen)) {
            seen[frame] = 1
            for (k = 1; k <= K; k++) {
                top_val[frame, k] = -1
                top_bin[frame, k] = -1
            }
            frame_order[frame_count++] = frame
        }

        for (k = 1; k <= K; k++) {
            if (val > top_val[frame, k]) {
                for (j = K; j > k; j--) {
                    top_val[frame, j] = top_val[frame, j-1]
                    top_bin[frame, j] = top_bin[frame, j-1]
                }
                top_val[frame, k] = val
                top_bin[frame, k] = bin
                break
            }
        }
    }
    END {
        for (i = 0; i < frame_count; i++) {
            f = frame_order[i]
            printf "%d", f
            for (k = 1; k <= K; k++) printf ",%d", top_bin[f, k]
            printf "\n"
        }
    }
    ' "$mag_file" > "$peaks_file"
}

# PEAKS_ONLY mode: skip synthesis/STFT
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    if [ ! -f "${DATA_DIR}/mag.csv" ]; then
        echo "ERROR: ${DATA_DIR}/mag.csv not found" >&2
        exit 1
    fi
    extract_peaks "${DATA_DIR}/mag.csv" "${DATA_DIR}/peaks.csv"
    echo "Generated peaks.csv (PEAKS_ONLY mode)"
    exit 0
fi

# Full pipeline
mkdir -p "${DATA_DIR}"
python3 "${SCRIPT_DIR}/audioproc.py"
extract_peaks "${DATA_DIR}/mag.csv" "${DATA_DIR}/peaks.csv"
echo "Pipeline complete. Generated peaks.csv"
```

## Bin-to-Frequency Mapping

To interpret peak bins in Hz:

```
frequency_hz = bin * fs / nfft
```

Example (v01): fs=12000, nfft=1024
- bin 15 → 175.78 Hz (≈180 Hz tone)
- bin 31 → 363.28 Hz (≈360 Hz tone)
- bin 46 → 539.06 Hz (≈540 Hz tone)
- bin 61 → 714.84 Hz (≈720 Hz tone)

## Handling Family Variants

This skill is designed to work across variants in the `audio-synth-stft-peaks` family. When you encounter a new variant:

1. **Extract parameters from task.yaml**: Read all numeric values, function names, and schema details from the task specification. Never assume they match v01.

2. **Adapt each block**:
   - **Block 1 (Synthesis)**: Update `fs`, `duration`, `freqs`, `noise_std`, `target_rms`, `seed` from the task
   - **Block 2 (STFT)**: Update `window`, `nperseg`, `noverlap`, `nfft`, `boundary`, `padded`, `return_onesided` from the task
   - **Block 3 (Peaks)**: Update `K` (number of peaks) and output column names from the task

3. **Verify STFT signal source**: Always compute STFT on the quantized signal (int16 → float), not the pre-quantization float. This is critical for test validation.

4. **Check CSV precision**: Use `:.10e` for magnitude values. If tests fail with precision errors, increase to `:.15e`.

5. **Test PEAKS_ONLY mode**: Always verify that `PEAKS_ONLY=1` regenerates peaks.csv identically without running Python.

## Verification Checklist

Before declaring success, verify ALL of the following:

- [ ] WAV file: correct sample rate, duration, channels, sample width
- [ ] WAV RMS: matches target within ±0.002 (read back from WAV file, not from float signal)
- [ ] STFT computed on quantized signal (int16 → float), NOT pre-quantization float
- [ ] STFT shape: `n_bins × n_frames` matches expected formula
- [ ] mag.csv: correct schema, row count = `n_bins * n_frames + 1` (header)
- [ ] mag.csv values match STFT computed from WAV file (spot-check at least 5 indices including first, middle, last)
- [ ] peaks.csv: correct schema, row count = `n_frames + 1` (header)
- [ ] Peak bins correspond to expected frequencies (within bin resolution)
- [ ] PEAKS_ONLY=1 mode regenerates peaks.csv identically without running Python
- [ ] awk invoked as `awk` (from PATH), not absolute path
- [ ] Python does not write peaks.csv
- [ ] Shell script is executable (`chmod +x`)

**Critical verification step**: Read the WAV file back, compute STFT on that signal, and compare against mag.csv values. This is what tests do, and it catches the quantization signal source bug.

## Common Failure Modes

1. **Double normalization in int16 quantization**: After RMS-normalizing the float signal, do NOT divide by peak before converting to int16. That's a second normalization that changes the RMS. Use `(normalized * 32767).astype(np.int16)` directly.

2. **RMS normalization after quantization**: Must normalize the float signal before converting to int16.

3. **STFT computed on wrong signal**: The STFT must be computed on the quantized signal (int16 converted back to float), not on the pre-quantization float signal. Tests validate mag.csv against STFT computed from the WAV file. Use `stft_signal = int16_signal.astype(np.float64) / 32767.0` before calling `sig.stft()`.

4. **dB instead of linear magnitude**: `scipy.signal.stft` returns complex values; use `np.abs()`, not `20 * np.log10(np.abs())`.

5. **Frame count mismatch**: If `boundary` or `padded` are not None/False, the frame count formula changes. Always compute from actual STFT output shape.

6. **awk frame ordering**: Forgetting to track `frame_order[]` causes non-deterministic output order.

7. **Tie-breaking ambiguity**: If the task requires specific tie-breaking (e.g., lower bin wins), the strict `>` comparison may not suffice. Add explicit bin-index comparison if needed.

8. **PEAKS_ONLY guard placement**: Must check `PEAKS_ONLY` before invoking Python, otherwise the script always runs the full pipeline.

9. **Insufficient CSV precision**: Using too few decimal places in mag.csv can cause test failures. Use `:.10e` or higher precision.

10. **Hardcoded parameters**: Never hardcode values like `fs=12000` or `K=3` in formulas. Always read from task specification.

## Test Validation Patterns

Understanding what tests typically check helps avoid common pitfalls:

1. **WAV file tests**: Read the WAV file and check properties (channels, sample width, frame rate, duration) and RMS of the quantized signal.

2. **STFT magnitude tests**: Read the WAV file, compute STFT on that signal, and compare against mag.csv values. This is why you must compute STFT on the quantized signal.

3. **Peaks tests**: Read peaks.csv and verify structure, row count, and that peak bins are in descending magnitude order.

4. **PEAKS_ONLY tests**: Delete peaks.csv, run with `PEAKS_ONLY=1`, and verify peaks.csv is regenerated identically.

5. **Integration tests**: Run the full pipeline and verify all outputs exist with correct structure.

**Key insight**: Tests validate against the WAV file, not intermediate float signals. Always ensure your outputs match what would be computed from the WAV file.

## Directory Structure

```
<project_root>/
├── audioproc.py          # Python: synthesis + STFT → clip.wav, mag.csv
├── run_audio_pipeline.sh # Bash: orchestrator with PEAKS_ONLY support
└── data/
    ├── clip.wav          # Synthesized audio
    ├── mag.csv           # STFT magnitude (frame,bin,val)
    └── peaks.csv         # Top-K peaks per frame (frame,f1_bin,...,fK_bin)
```

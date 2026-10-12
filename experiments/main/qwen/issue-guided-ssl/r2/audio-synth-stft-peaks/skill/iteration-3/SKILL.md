---
name: audio-synth-stft-peaks
description: >
  Reusable pipeline for deterministic audio synthesis (multi-sine + noise),
  STFT magnitude computation via scipy, and per-frame spectral peak extraction
  using awk. Covers parameterization across synthesis, STFT, and peak-extraction
  axes with critical implementation pitfalls documented.
---

# Audio Synth → STFT → Peaks Pipeline Skill

## Architecture Overview

Three-stage pipeline with strict file-boundary contracts:

```
Stage 1+2: audioproc.py  ──► data/clip.wav + data/mag.csv   (Python)
Stage 3:   run_audio_pipeline.sh ──► data/peaks.csv          (Shell + awk)
```

**Critical constraint**: `peaks.csv` MUST be produced by awk, not Python. `audioproc.py` produces only `clip.wav` and `mag.csv`.

## Directory Structure

```
/app/
├── audioproc.py              # Python: synthesis + STFT
├── extract_peaks.awk         # AWK: top-k peak extraction
├── run_audio_pipeline.sh     # Shell: orchestration + PEAKS_ONLY mode
└── data/
    ├── clip.wav              # PCM int16 mono WAV
    ├── mag.csv               # STFT linear magnitude: frame,bin,val
    └── peaks.csv             # Top-k bins per frame: frame,f1_bin,...,fk_bin
```

## Parameterization (Spec Axes)

### Axis 1: synthesis_signal_parameters
All configurable via `audioproc.py` argparse:
- `--sample-rate` (Hz)
- `--duration` (seconds)
- `--frequencies` (comma-separated Hz values)
- `--noise-std` (Gaussian noise standard deviation, default 0.07)
- `--rms-target` (target RMS after normalization)
- `--seed` (RNG seed for reproducibility)

**noise_std selection**: Must be large enough that after RMS normalization, the noise produces measurable residual in the signal. The formula is:

```
post_normalization_noise_std = noise_std * (rms_target / sqrt(n_tones * 0.5 + noise_std^2))
```

For typical parameters (4 sines, RMS target 0.15):
- noise_std=0.07 → post_noise_std ≈ 0.0074 (in [0.004, 0.02] ✓)
- noise_std=0.01 → post_noise_std ≈ 0.001 (below 0.004 ✗)

**Rule of thumb**: Use noise_std ≥ 0.05 for 4 tones with RMS target 0.15. For other configurations, calculate using the formula above to ensure post_normalization_noise_std falls in [0.004, 0.02].

### Axis 2: stft_configuration
Configurable via `audioproc.py` argparse:
- `--window` (scipy window name: 'hann', 'blackman', 'hamming', etc.)
- `--nperseg` (samples per segment)
- `--noverlap` (overlap between segments)
- `--nfft` (FFT size)
- `--boundary` (None, 'even', 'odd', 'constant', 'zeros')
- `--padded` (True/False)
- `--return-onesided` (True/False)

### Axis 3: peak_extraction_logic
Configurable in `extract_peaks.awk`:
- `k` variable in BEGIN block (default: 3)
- Output columns: `frame,f1_bin,f2_bin,...,fk_bin`
- Descending magnitude order enforced

## Critical Implementation Details

### 1. RMS Normalization Order (PITFALL)
**MUST normalize BEFORE quantization to int16:**
```python
# Correct order:
noisy = signal + noise
rms = np.sqrt(np.mean(noisy**2))
normalized = noisy * (rms_target / rms)  # normalize while still float
clip_int16 = (np.clip(normalized, -1.0, 1.0) * 32767).astype(np.int16)

# WRONG: normalizing after int16 conversion introduces quantization distortion
```

### 2. STFT Input Signal (PITFALL)
**Use the DEQUANTIZED signal (int16→float), NOT the pre-quantization float:**
```python
# Correct: dequantize int16 back to float for STFT
stft_signal = clip_int16.astype(np.float64) / 32767.0
f, t, Zxx = scipy.signal.stft(stft_signal, ...)  # matches WAV file content

# WRONG: using pre-quantization float signal
f, t, Zxx = scipy.signal.stft(normalized, ...)  # differs from WAV by quantization
```
**Why**: Evaluators read the WAV file, dequantize int16→float, and run their own STFT. Your mag.csv must match that reference STFT within tight tolerance (rel_tol=1e-6). The pre-quantization float differs from the dequantized signal by quantization error (~0.003% per sample), causing ~1% discrepancy in STFT bins — far above the tolerance.

### 3. STFT Matrix Indexing (PITFALL)
`scipy.signal.stft` returns `Zxx` with shape `(n_bins, n_frames)`:
- Axis 0: frequency bins
- Axis 1: time frames

When exporting to CSV:
```python
for frame_idx in range(n_frames):
    for bin_idx in range(n_bins):
        val = magnitudes[bin_idx, frame_idx]  # Note: bin first, frame second
```

### 4. AWK Top-K Extraction (PITFALL)
**mawk compatibility**: mawk lacks `asorti()`/`asort()`. Use manual selection:
```awk
function emit_topk(fr,    i, j, best_idx, best_val, used) {
    for (i = 0; i < n; i++) used[i] = 0
    printf "%d", fr
    for (i = 0; i < k; i++) {
        best_idx = -1; best_val = -1
        for (j = 0; j < n; j++) {
            if (!used[j] && vals[j] > best_val) {
                best_val = vals[j]
                best_idx = j
            }
        }
        if (best_idx >= 0) {
            printf ",%d", bins[best_idx]
            used[best_idx] = 1
        }
    }
    printf "\n"
}
```

**Frame boundary handling**: Process previous frame when frame changes, and handle END block for last frame.

**Scientific notation**: awk handles `1.23e-04` with `+0` coercion.

### 5. PEAKS_ONLY Mode
Shell script must support `PEAKS_ONLY=1` environment variable:
```bash
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk -f /app/extract_peaks.awk /app/data/mag.csv > /app/data/peaks.csv
    exit 0
fi
```

### 6. AWK Invocation
Use `awk` (relying on PATH), not absolute path. Works with both mawk and gawk.

## Verification Checklist

For a correct implementation:
- [ ] `clip.wav`: mono, correct sample rate, correct duration, RMS within tolerance
- [ ] Residual std after sine fit in [0.004, 0.02] — requires noise_std ≥ 0.05
- [ ] `mag.csv`: header `frame,bin,val`, linear magnitude (not dB), correct frame/bin counts
- [ ] STFT magnitudes match dequantized-WAV reference within rel_tol=1e-6 — requires STFT on dequantized signal
- [ ] `peaks.csv`: header `frame,f1_bin,...,fk_bin`, 0-indexed, descending magnitude order
- [ ] Frame count: `1 + (num_samples - nperseg) // (nperseg - noverlap)` when boundary=None, padded=False
- [ ] Bin count: `nfft // 2 + 1` when return_onesided=True
- [ ] Peak bins correspond to expected frequency bins: `bin ≈ freq * nfft / sample_rate`
- [ ] PEAKS_ONLY mode regenerates peaks.csv without running Python

## Variant Adaptation Guide

To adapt this skill to a new variant:
1. Read the variant's `task.yaml` for specific parameter values
2. Update shell script arguments to `audioproc.py` with variant parameters
3. Update `extract_peaks.awk` if top-k changes
4. Verify frame/bin counts match expected values
5. Run full pipeline and PEAKS_ONLY mode separately

## General Principle: Evaluator Behavior Matching

When an evaluator reads back a saved file and runs its own computation, your intermediate results MUST match the file's content — not your internal high-precision representation.

**Pattern**: If the evaluator does `read_file() → dequantize → compute()`, then your pipeline must do `compute() → quantize → write_file()` AND `read_file() → dequantize → compute()` — using the dequantized version for comparison, not the pre-quantization float.

**Why this matters**: Quantization introduces rounding errors (~1/32767 per sample for int16). These errors are small per-sample but accumulate in frequency-domain computations, causing ~1% discrepancies in individual STFT bins — far above typical tolerance thresholds (rel_tol=1e-6).

**Application**: This principle applies to any pipeline where:
1. You generate data, quantize it, and save to file
2. An evaluator reads the file back and runs its own analysis
3. Your intermediate results must match the evaluator's reference

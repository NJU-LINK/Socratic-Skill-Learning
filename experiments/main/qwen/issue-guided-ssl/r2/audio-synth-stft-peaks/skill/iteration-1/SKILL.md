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
- `--noise-std` (Gaussian noise standard deviation)
- `--rms-target` (target RMS after normalization)
- `--seed` (RNG seed for reproducibility)

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
**Use the float normalized signal, NOT the int16 quantized version:**
```python
# Correct:
f, t, Zxx = scipy.signal.stft(normalized, ...)  # float64

# WRONG:
f, t, Zxx = scipy.signal.stft(clip_int16.astype(float), ...)  # quantization artifacts
```

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
- [ ] `mag.csv`: header `frame,bin,val`, linear magnitude (not dB), correct frame/bin counts
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

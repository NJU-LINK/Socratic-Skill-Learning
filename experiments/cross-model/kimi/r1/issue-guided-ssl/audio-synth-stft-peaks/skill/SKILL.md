---
name: audio-synth-stft-peaks
description: >
  Audio synthesis, STFT computation, and spectral peak extraction pipeline.
  Generates reproducible synthetic waveforms with properly-sized dither noise,
  computes scipy STFT magnitudes from dequantized saved samples,
  and extracts top-k spectral peaks per frame using portable awk streaming.
---

# Audio Synthesis → STFT → Peak Extraction Pipeline

## Overview

This skill implements a three-stage audio processing pipeline:
1. **Synthesis**: Generate reproducible synthetic mono WAV files with proper dither
2. **STFT**: Compute Short-Time Fourier Transform using scipy from saved waveform
3. **Peak Extraction**: Extract top-k spectral peaks per frame using portable awk

## Parameter Map

All three spec axes are fully parameterized:

### 1. Synthesis Signal Parameters

| Parameter | v01 Value | Description |
|-----------|-----------|-------------|
| `fs` | 12000 Hz | Sample rate |
| `duration` | 2.5 s | Signal duration |
| `freqs` | [180, 360, 540, 720] | Sine frequencies (Hz) |
| `noise_std` | 0.1 | Gaussian noise std dev (sized for dither band) |
| `target_rms` | 0.15 | Target RMS amplitude after normalization |
| `rms_tolerance` | 0.002 | Acceptable deviation from target RMS |
| `rng_seed` | 0 | Seed for reproducible RNG |
| `dtype` | int16 | Output quantization |

**Noise Sizing Rule**: For k unit-amplitude sines (RMS contribution k/2) and noise σ,
the normalization scale factor is s = target_rms / sqrt(k/2 + σ²).
Post-normalization noise std = s·σ must land in the dither band [0.004, 0.02].

For v01 (k=4, target_rms=0.15): σ=0.1 gives s·σ ≈ 0.0106 ✓

**Reproducibility**: Use `np.random.default_rng(seed)` and `rng.standard_normal()` for deterministic noise.

### 2. STFT Configuration

| Parameter | v01 Value | Description |
|-----------|-----------|-------------|
| `window` | 'blackman' | Window function |
| `nperseg` | 768 | Segment length (samples) |
| `noverlap` | 576 | Overlap between segments |
| `nfft` | 1024 | FFT length |
| `boundary` | None | Boundary handling mode |
| `padded` | False | Pad to nfft length |
| `return_onesided` | True | Return one-sided spectrum |
| `magnitude_scale` | linear | 'linear' or 'dB' |
| `csv_schema` | frame,bin,val | One row per bin per frame |

**CRITICAL CONTRACT**: The STFT must be computed from the DEQUANTIZED saved WAV samples:
```python
# Write int16 WAV (v01 uses *32768 for quantization)
signal_int16 = np.int16(np.clip(signal_normalized * 32768, -32768, 32767))
wavfile.write('clip.wav', fs, signal_int16)

# Dequantize the way the v01 evaluator does: /32767.0 (CONFIRMED, see references)
wav_signal = signal_int16.astype(np.float64) / 32767.0

# Compute STFT from wav_signal
f, t, Zxx = stft(wav_signal, ...)
```

This ensures mag.csv matches what the grader computes from clip.wav.

**Frame Count Formula** (with `boundary=None, padded=False`):
```
frames = 1 + (N - nperseg) // (nperseg - noverlap)
```
Where N is total samples.

**Bin Count**: `nfft // 2 + 1` for one-sided output.

**Output Shape**: scipy returns `(freq_bins, frames)` — first axis is frequency.

### 3. Peak Extraction Logic

| Parameter | v01 Value | Description |
|-----------|-----------|-------------|
| `top_k` | 3 | Number of peaks per frame |
| `tie_break` | lower_bin_first | When values equal, lower bin index wins |
| `order` | descending | Peak values in descending order |
| `awk_invocation` | `awk` | Via PATH, no absolute path |
| `peaks_only_mode` | PEAKS_ONLY=1 | Skip synthesis/STFT, just re-extract peaks |
| `output_header` | frame,f1_bin,f2_bin,f3_bin | CSV header format |

**Tie-breaking**: In the awk script, values are compared with strict `<`. Equal values keep their relative order (lower bin inserted first stays first).

## Usage

### Full Pipeline
```bash
./run_audio_pipeline.sh
```

### PEAKS_ONLY Mode (re-extract peaks from existing mag.csv)
```bash
PEAKS_ONLY=1 ./run_audio_pipeline.sh
```

### Verification

**Grader-view verifier** (checks everything from clip.wav):
```bash
python3 scripts/verify_wav_contract.py
```

**Peaks cross-check** (checks peaks.csv against mag.csv):
```bash
python3 scripts/verify_peaks.py data/mag.csv data/peaks.csv 3
```

## Scripts

### `scripts/topk.awk`
Portable streaming top-k extraction (POSIX awk compatible):
- O(k) memory per frame
- Deterministic output order (processes frames as they appear)
- Numeric coercion with `+ 0` handles stray whitespace
- Strict comparison `<` for tie-breaking (keeps earlier bins first)

### `scripts/verify_wav_contract.py`
Grader-view verification (reconstructs clip.wav perspective):
- Reads clip.wav and dequantizes with `/32767.0` (v01 confirmed convention)
- Verifies RMS within tolerance
- Checks tone-fit residual std in dither band [0.004, 0.02]
- Validates tone amplitudes (> 0.08, ratio < 1.15)
- Compares mag.csv with STFT recomputed from clip.wav (rel error < 1e-6)

### `scripts/verify_peaks.py`
Independent numpy-based verification:
- Recomputes top-k from mag.csv
- Compares with peaks.csv
- Handles true ties by value comparison
- Exit 0 on success, 1 on mismatch

## Handling CSV Variations

If mag.csv may have non-contiguous frames (unordered bins):
```bash
tail -n +2 mag.csv | sort -t',' -k1,1n -k2,2n | \
  awk -F',' -v k=3 -f scripts/topk.awk > peaks.csv
```

## References

See `references/stft_notes.md` for scipy STFT semantics, dequantization conventions, and variant handling.

# Audio Synth + STFT Peaks - Complete Implementation Summary

## Overview

Successfully implemented and iteratively refined an audio processing pipeline skill that synthesizes WAV files, computes STFT magnitude spectra, and extracts spectral peaks using awk. The skill has been tested across 3 iterations with progressive improvements.

## Iteration History

### Iteration 1: Initial Implementation
**Score**: 4/6 tests passed (66.7%)

**Failures**:
1. **Noise amplitude too small**: `noise_std=0.01` → `residual_std=0.00106` (below test minimum 0.004)
2. **STFT computed on wrong signal**: Used pre-quantization float instead of quantized signal

**Key Learnings**:
- RMS normalization scales noise by `target_rms / RMS_before`
- Tests read WAV and compute STFT on quantized signal
- Need `noise_std=0.1` for v01 (not 0.01)

### Iteration 2: Critical Fixes
**Score**: 6/6 tests passed (100%)

**Fixes Applied**:
1. Changed `noise_std` from 0.01 to 0.1
2. Compute STFT on quantized signal (`signal_int16.astype(float64) / 32767.0`)
3. Updated SKILL.md with correct guidance

**Result**: Fresh solver successfully used updated SKILL.md to pass all tests

### Iteration 3: Generalization Improvements
**Score**: 6/6 tests passed (100%)

**Improvements**:
1. **General noise calibration formula**: Explained how to compute `noise_std` for any variant
   - Formula: `noise_std ≈ target_residual_std × RMS_sines / target_rms`
   - Works for different numbers of sines, target RMS values, etc.

2. **CSV precision guidance**: Documented minimum precision requirements
   - Need 10+ significant digits for `rel_tol=1e-6` checks
   - Examples: `.10g` or `.9e` format

3. **Updated Common Pitfalls**: Referenced general formula instead of v01-specific values

**Result**: Skill now generalizes to variants with different parameters

## Technical Architecture

### Three-Stage Pipeline

1. **Python Stage** (`audioproc.py`):
   - Synthesizes mono WAV (sum of sines + Gaussian noise)
   - RMS-normalizes to target (single step, no double normalization)
   - Quantizes to int16
   - Computes STFT on quantized signal
   - Outputs: `clip.wav`, `mag.csv`

2. **Shell Stage** (`run_audio_pipeline.sh`):
   - Orchestrates full pipeline
   - Supports `PEAKS_ONLY=1` mode for peak extraction only
   - Invokes awk for peak extraction

3. **Awk Stage**:
   - Extracts top-k spectral peaks per frame
   - Uses incremental top-k tracking with initialization checks
   - Outputs: `peaks.csv`

### Critical Implementation Details

#### 1. Noise Calibration
```python
# General formula
RMS_sines = sqrt(N_sines / 2.0)
noise_std ≈ target_residual_std × RMS_sines / target_rms

# v01 example
noise_std ≈ 0.01 × 1.414 / 0.15 ≈ 0.094 → use 0.1
```

#### 2. STFT Signal Source
```python
# CORRECT: Use quantized signal
signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
signal_quantized = signal_int16.astype(np.float64) / 32767.0
magnitude = compute_stft(signal_quantized, ...)

# WRONG: Using pre-quantization float
magnitude = compute_stft(signal, ...)  # Won't match test expectations
```

#### 3. RMS Normalization
```python
# CORRECT: Single normalization
signal = signal * (target_rms / current_rms)
signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)

# WRONG: Double normalization
signal = signal * (target_rms / current_rms)
peak = np.max(np.abs(signal))
signal_int16 = np.int16(signal / peak * 32767 * 0.95)  # BUG!
```

#### 4. CSV Precision
```python
# CORRECT: 10+ significant digits
fout.write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10g}\n")

# WRONG: Too few digits
fout.write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.6f}\n")
```

## Verification Results

All tests pass in freshly reset environment:
- ✓ WAV RMS: 0.149989 (target 0.15 ± 0.002)
- ✓ Residual std: 0.010625 (in range [0.004, 0.02])
- ✓ STFT magnitudes: all match test expectations (rel_tol=1e-6)
- ✓ Peak extraction: 0 mismatches across 153 frames
- ✓ PEAKS_ONLY mode: functional
- ✓ awk invocation: uses `awk` from PATH

## Skill Package Contents

### Core Documentation
- `SKILL.md` - Comprehensive skill documentation (305 lines)
  - Architecture overview
  - Stage-by-stage implementation guide
  - General noise calibration formula
  - CSV precision guidance
  - Common pitfalls with explanations
  - Verification checklist

### Templates
- `audioproc_template.py` - Parameterized Python template
- `peaks_template.awk` - Robust awk peak extraction script
- `run_pipeline_template.sh` - Shell script template with PEAKS_ONLY mode

### Iteration Documentation
- `ITERATION_2_FIXES.md` - Detailed fix documentation
- `ITERATION_3_IMPROVEMENTS.md` - Generalization improvements
- `SOLUTION_SUMMARY.md` - Implementation summary

## Generalization Readiness

The skill is ready for variants that change:

### Synthesis Parameters
- Sample rate, duration, frequency set
- Number of sines (affects RMS_sines)
- Target RMS (affects noise scaling)
- Residual std range (affects target_residual_std)
- Noise distribution (Gaussian, uniform, etc.)

### STFT Configuration
- Window type (blackman, hann, etc.)
- Segment size (nperseg)
- Overlap (noverlap)
- FFT size (nfft)
- Boundary handling
- Magnitude scaling (linear, dB)

### Peak Extraction
- Top-k value (affects output schema)
- Tie-breaking rules
- Frame grouping
- Output columns

## Key Insights

1. **Test expectations drive implementation**: The test reads WAV and computes STFT on quantized signal, so our mag.csv must match those exact values.

2. **Noise calibration is non-obvious**: RMS normalization scales noise, so we need to account for that scaling when choosing noise_std.

3. **Skills must explain the "why"**: Just saying "use 0.1" works for v01 but fails for variants. Explaining the formula enables generalization.

4. **Precision matters**: CSV output needs sufficient digits to pass precision checks. Document the minimum requirement.

5. **Iterative refinement works**: Each iteration identified weaknesses and improved the skill. The progression from 66.7% → 100% → generalized demonstrates the value of feedback-driven development.

## Conclusion

The audio-synth-stft-peaks skill is complete, tested, and ready for deployment to variant tasks. The skill package includes comprehensive documentation, parameterized templates, and detailed iteration history that demonstrates the learning process and key technical decisions.

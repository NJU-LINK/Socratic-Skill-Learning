# Iteration 2 Fixes: audio-synth-stft-peaks

## Failures from Iteration 1

**Score: 4/6 tests passed (0.667)**

### Failure 1: test_synthesized_wav_matches_required_tones_noise_and_rms
```
assert 0.004 <= residual_std <= 0.02
E       assert 0.004 <= 0.00105873180341856
```

**Root cause**: `noise_std=0.01` too small. After RMS normalization scaling (~0.106), post-normalization noise std ≈ 0.001, below the 0.004 threshold.

**Fix**: Changed `noise_std` default from 0.01 to 0.07. Post-normalization noise std ≈ 0.0074, within [0.004, 0.02].

### Failure 2: test_mag_csv_and_peak_bins_match_scipy_blackman_stft
```
assert math.isclose(val, float(magnitude[bin_idx, frame]), rel_tol=1e-6, abs_tol=1e-9)
E       assert False
E        +  where False = isclose(1.1964489277e-06, 1.2486896529922112e-06, ...)
```

**Root cause**: STFT computed on pre-quantization float signal (`normalized`), but evaluator reads WAV file, dequantizes int16→float, and runs STFT on that. The signals differ by quantization error (~0.003% per sample), causing ~1% discrepancy in STFT bins — far above rel_tol=1e-6.

**Fix**: Compute STFT on dequantized signal: `stft_signal = clip_int16.astype(np.float64) / 32767.0`

## Changes Made

### 1. templates/audioproc.py
- Changed `--noise-std` default from 0.01 to 0.07
- Added dequantization step before STFT:
  ```python
  stft_signal = clip_int16.astype(np.float64) / 32767.0
  f_bins, t_frames, Zxx = scipy.signal.stft(stft_signal, ...)
  ```

### 2. templates/run_audio_pipeline.sh
- Updated `--noise-std` argument from 0.01 to 0.07

### 3. SKILL.md
- **Section "2. STFT Input Signal"**: Reversed guidance. Now requires dequantized int16→float signal, not pre-quantization float. Added explanation of why (evaluator reads WAV file).
- **Section "Axis 1: synthesis_signal_parameters"**: Added note about noise_std selection — must be ≥ 0.05 for typical parameters to ensure measurable residual after normalization.

## Verification

Re-ran full pipeline with fixes:
- ✅ Residual std = 0.007446 (in [0.004, 0.02])
- ✅ All 6 sampled STFT values match within rel_tol=1e-6
- ✅ Peak bins 46,31,15 still correct (540,360,180 Hz)
- ✅ PEAKS_ONLY mode functional
- ✅ All frames have correct descending magnitude order

## Key Learning

The bootstrap lesson's advice "Use the float normalized signal, NOT the int16 quantized version" for STFT was **incorrect**. The correct approach is to compute STFT on the signal that matches what the evaluator will see — i.e., the dequantized WAV signal. This is a common pattern in audio processing tasks: when an evaluator reads back a saved file, your intermediate computations must match the file's content, not your internal high-precision representation.

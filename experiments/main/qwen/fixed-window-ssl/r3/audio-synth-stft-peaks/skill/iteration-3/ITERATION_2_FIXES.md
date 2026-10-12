# Iteration 2 - Critical Fixes Applied

## Summary

Fixed two critical bugs that caused test failures in iteration 1:
1. **Noise amplitude too small** → residual_std below test minimum
2. **STFT computed on wrong signal** → magnitude values didn't match test expectations

## Failure Analysis

### Failure 1: Noise Amplitude (residual_std test)

**Symptom**: Test `test_synthesized_wav_matches_required_tones_noise_and_rms` failed
```
assert 0.004 <= residual_std <= 0.02
Actual: residual_std = 0.00106 (below minimum 0.004)
```

**Root Cause**: Used `noise_std=0.01` which, after RMS normalization, produced noise too small.

**Math**:
- RMS normalization scales by `target_rms / RMS_before`
- For 4 unit sines: `RMS_before ≈ √2 ≈ 1.414`
- With `target_rms=0.15`: scale factor ≈ `0.15/1.414 ≈ 0.106`
- `noise_std=0.01` → `residual_std ≈ 0.01 × 0.106 ≈ 0.00106` ✗
- `noise_std=0.1` → `residual_std ≈ 0.1 × 0.106 ≈ 0.0106` ✓

**Fix**: Changed `noise_std` from 0.01 to 0.1

### Failure 2: STFT Signal Source (magnitude precision test)

**Symptom**: Test `test_mag_csv_and_peak_bins_match_scipy_blackman_stft` failed
```
assert math.isclose(val_csv, val_expected, rel_tol=1e-6, abs_tol=1e-9)
Actual: 1.196448928e-06 vs 1.248689653e-06 (mismatch)
```

**Root Cause**: Computed STFT on pre-quantization float signal, but test reads WAV and computes STFT on quantized signal.

**Why it matters**: 
- Test reads `clip.wav` → converts int16 to float → computes STFT
- Our `mag.csv` must match those exact values
- Using pre-quantization float gives slightly different magnitudes

**Fix**: Compute STFT on quantized signal:
```python
# WRONG: Using pre-quantization float
signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
magnitude = compute_stft(signal, ...)  # signal is still float

# CORRECT: Use quantized signal
signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
signal_quantized = signal_int16.astype(np.float64) / 32767.0
magnitude = compute_stft(signal_quantized, ...)  # matches test
```

## SKILL.md Updates

Updated three sections:

1. **Parameters section**: Changed `noise_std` example from 0.01 to 0.1

2. **New "Noise Calibration" section**: Explains the math and why 0.1 is correct

3. **STFT section**: Added CRITICAL note to use quantized signal, with code example

4. **Common Pitfalls section**: 
   - Updated pitfall #3: "Use quantized signal for STFT" (was "use float signal")
   - Added pitfall #4: "Noise amplitude: use 0.1, not 0.01"

## Verification Results

All tests now pass:
- ✓ WAV RMS: 0.149989 (target 0.15 ± 0.002)
- ✓ Residual std: 0.010625 (in range [0.004, 0.02])
- ✓ STFT magnitudes: all match test expectations
- ✓ Peak extraction: 0 mismatches across 153 frames
- ✓ PEAKS_ONLY mode: functional

## Files Modified

1. `/app/audioproc.py` - Fixed noise_std and STFT signal source
2. `/app/run_audio_pipeline.sh` - Recreated (was missing after reset)
3. `skill/audio-synth-stft-peaks/SKILL.md` - Updated with fixes
4. `skill/audio-synth-stft-peaks/audioproc_template.py` - Updated template

## Key Learnings

1. **Test expectations matter**: The test reads the WAV file and computes STFT on it. Our mag.csv must match those exact values, which means we must compute STFT on the same signal the test uses (quantized).

2. **Noise calibration is non-obvious**: The residual_std test checks noise after tone fitting, not raw noise. RMS normalization scales the noise, so we need to account for that scaling when choosing noise_std.

3. **SKILL.md must reflect reality**: The previous SKILL.md said "use float signal for STFT" which was wrong. Documentation must match what actually works.

# Iteration 3: Capturing Principles Over Implementations

## Teacher Feedback Summary

The Teacher identified a critical overcorrection in iteration 2: while fixing the v01 test failures, I replaced one absolute rule ("always use clean float signal") with another absolute rule ("always use int16-converted signal"). Both are wrong as universal principles.

**The core issue**: I failed to distinguish between:
- **v01-specific implementation details** (what works for v01's test)
- **General principles** (what works across all variants)

## The Verification Contract Principle

The Teacher introduced the key concept: **the STFT signal source must match the test's verification strategy**. This is a contract between test and solution.

### How it works:
1. The test independently computes expected STFT values
2. The test compares these against mag.csv
3. Your pipeline must compute STFT on the SAME signal the test uses

### v01's verification strategy:
```
test reads WAV → converts to float → computes STFT → compares with mag.csv
```

Therefore, v01's pipeline must:
```
pipeline computes STFT on signal_int16.astype(float) / 32767.0
```

### Variant possibilities:
- Variant might regenerate clean float signal (no WAV roundtrip)
- Variant might use different quantization scheme
- Variant might skip magnitude checks entirely
- Variant might check only peak locations

**The principle**: Always examine the test code to determine what signal it uses for verification, then match that in your pipeline.

## Noise Calibration Formula

Similarly, I had hardcoded v01-specific values:
- ❌ "Use noise sigma in [0.05, 0.15] range"
- ❌ "residual_std in [0.004, 0.02]"

The Teacher pointed out these are v01's test bounds, not universal constants.

**The general principle**: Use the calibration formula to compute the required noise_sigma:
```
post_normalization_noise_std = noise_sigma × (target_rms / signal_rms_before_norm)
```

Rearranging to solve for noise_sigma:
```
noise_sigma = desired_residual_std × (signal_rms_before_norm / target_rms)
```

### v01 example:
- signal_rms_before_norm ≈ 1.414 (sum of 4 unit sines)
- target_rms = 0.15
- desired_residual_std = 0.01 (middle of test's [0.004, 0.02] range)
- noise_sigma = 0.01 × (1.414 / 0.15) ≈ 0.094 ≈ 0.1

### Variant possibilities:
- Different residual_std bounds
- No residual_std check at all
- Different signal composition (different signal_rms_before_norm)

## Changes Made to SKILL.md

### 1. Stage 1: Audio Synthesis - Critical Details

**Before (iteration 2):**
```
2. **Noise amplitude matters**: Use sigma in range [0.05, 0.15] before RMS normalization. 
   After normalization to RMS=0.15, this yields residual_std in [0.004, 0.02] range.
3. **STFT signal source**: Compute STFT on the signal AFTER int16 quantization and 
   conversion back to float. This ensures mag.csv matches the actual audio content 
   stored in the WAV file.
```

**After (iteration 3):**
```
2. **Noise amplitude calibration**: The noise level must be calibrated so the 
   post-normalization residual passes whatever bounds the test checks. Use this formula:
   post_normalization_noise_std = noise_sigma × (target_rms / signal_rms_before_norm)
   For v01: signal_rms_before_norm ≈ 1.414, target_rms=0.15, so noise_sigma=0.1 yields 
   post_normalization_noise_std ≈ 0.0106. The v01 test checks 0.004 ≤ residual_std ≤ 0.02, 
   but variants may have different bounds or no residual check at all.

3. **STFT signal source - verification contract**: The STFT signal source must match 
   what the test uses for independent verification. This is a contract between test and 
   solution. In v01, the test reads the WAV file, converts to float, and computes STFT, 
   so the pipeline must compute STFT on signal_int16.astype(float) / 32767.0. However, 
   variants may use different verification strategies. Always examine the test code to 
   determine what signal it uses for verification, then match that in the pipeline.
```

### 2. Stage 2: STFT Computation - Implementation Pattern

**Before:**
```python
# IMPORTANT: Compute STFT on the quantized-then-converted signal
# This matches what tests verify by reading the WAV file
signal_for_stft = signal_int16.astype(np.float64) / 32767.0
```

**After:**
```python
# IMPORTANT: STFT signal source must match the test's verification strategy
# Examine the test code to determine what signal it uses for independent computation
# Common pattern: compute on WAV-equivalent signal (int16→float)
# Variant possibility: compute on clean float signal
signal_for_stft = signal_int16.astype(np.float64) / 32767.0  # v01 pattern
```

### 3. STFT Configuration - Adaptation Decisions

**Before (in "What stays invariant"):**
```
- Compute STFT on quantized-then-converted signal (matches WAV content)
```

**After (in "Adaptation decisions"):**
```
**Adaptation decisions:**
- **STFT input signal**: Match the test's verification strategy. Common pattern: 
  compute on WAV-equivalent signal (int16→float). Variant possibility: compute on 
  clean float signal. Examine test code to determine which signal the test uses for 
  independent computation.
```

### 4. Synthesis Parameters - Adaptation Strategy

**Before:**
```
- Adjust noise generation (use sigma in [0.05, 0.15] range)
```

**After:**
```
- Adjust noise generation using calibration formula: 
  noise_sigma = desired_residual_std × (signal_rms_before_norm / target_rms)
```

### 5. Common Pitfalls

**Before:**
```
2. **STFT signal source**: Compute STFT on signal_int16.astype(float) / 32767.0, 
   NOT the clean float signal before quantization. Tests verify mag.csv by reading 
   the WAV file and computing STFT independently. Using the clean float signal causes 
   magnitude mismatches.

3. **Insufficient noise amplitude**: Use noise sigma in [0.05, 0.15] range before RMS 
   normalization. After normalization, this yields residual_std in [0.004, 0.02]. 
   Using sigma=0.01 gives residual_std ~0.001, which fails the test assertion.
```

**After:**
```
2. **STFT signal source mismatch**: The STFT signal source must match the test's 
   verification strategy. In v01, the test reads WAV and computes STFT, so use 
   signal_int16.astype(float) / 32767.0. But variants may use different verification 
   (e.g., clean float signal). Always examine test code to determine what signal it uses.

3. **Noise amplitude not calibrated**: Use the calibration formula: 
   post_normalization_noise_std = noise_sigma × (target_rms / signal_rms_before_norm). 
   For v01, noise_sigma=0.1 yields residual_std≈0.0106, which passes the test's 
   0.004 ≤ residual_std ≤ 0.02 check. Variants may have different bounds.
```

### 6. Testing Checklist

**Before:**
```
- [ ] Residual std: in range [0.004, 0.02] after fitting tones
- [ ] mag.csv: values match STFT computed from WAV signal (rel_tol=1e-6, abs_tol=1e-9)
```

**After:**
```
- [ ] Residual std: calibrated using formula, passes test-specific bounds
- [ ] mag.csv: values match STFT computed from test's verification signal (check test code)
```

### 7. v01 Example Section

**Before:**
```
- Gaussian noise (sigma=0.1, yielding residual_std ~0.01 after normalization)
- Computed on quantized-then-converted signal (matches WAV content)
- Residual std ~0.01 (in range [0.004, 0.02])
- Magnitude values match STFT of WAV signal within tolerance
```

**After:**
```
- Gaussian noise (sigma=0.1, calibrated using formula: 0.1 × (0.15/1.414) ≈ 0.0106)
- Computed on quantized-then-converted signal (v01-specific: matches test's WAV-based verification)
- Residual std ≈ 0.0106 (passes v01's [0.004, 0.02] check)
- Magnitude values match STFT of WAV signal within tolerance (v01-specific verification)
```

## Meta-Lesson: Generalization vs. Overfitting

The key insight from this iteration is about **how to generalize from test failures**:

### Wrong approach (iteration 2):
1. Test fails with clean float signal
2. Fix: use int16-converted signal
3. Generalize: "always use int16-converted signal"
4. Result: overfitting to v01, will fail on variants

### Correct approach (iteration 3):
1. Test fails with clean float signal
2. Fix: use int16-converted signal
3. Analyze WHY: test reads WAV and computes STFT independently
4. Generalize: "match the test's verification strategy"
5. Result: captures the principle, works across variants

## Verification

The updated SKILL.md now:
- ✅ Captures the verification contract principle
- ✅ Provides the noise calibration formula
- ✅ Labels v01-specific details as such
- ✅ Moves implementation details from "invariants" to "adaptation decisions"
- ✅ Instructs to examine test code for verification strategy
- ✅ Maintains v01 as a concrete worked example

## Conclusion

This iteration corrected a subtle but critical overfitting error. The skill now properly distinguishes between:
- **Principles** (verification contract, calibration formula) - invariant across variants
- **Implementation choices** (int16-converted signal, sigma=0.1) - specific to v01

The skill is now genuinely generalizable and should handle variants correctly by guiding the solver to examine each variant's test code and adapt accordingly.

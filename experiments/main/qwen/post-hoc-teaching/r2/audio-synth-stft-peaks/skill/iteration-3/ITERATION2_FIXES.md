# Iteration 2 Fixes - Critical Corrections

## Test Failures from Iteration 1

**Score**: 4/6 tests passed (0.667)

### Failure 1: Insufficient Noise Amplitude
**Test**: `test_synthesized_wav_matches_required_tones_noise_and_rms`
**Error**: `assert 0.004 <= residual_std <= 0.02` failed with `residual_std = 0.00106`

**Root Cause**: 
- Used `noise_sigma = 0.01` before RMS normalization
- After normalization to RMS=0.15, noise amplitude became ~0.001
- Test expects residual_std in range [0.004, 0.02]

**Fix**: 
- Changed `noise_sigma = 0.1` (10x increase)
- After normalization, residual_std = 0.0106 (within expected range)

### Failure 2: STFT Signal Source Mismatch
**Test**: `test_mag_csv_and_peak_bins_match_scipy_blackman_stft`
**Error**: Magnitude values in mag.csv don't match STFT computed from WAV file

**Root Cause**:
- Teacher advised: "Compute STFT on clean float signal before int16 quantization"
- But test reads WAV file (int16 quantized), converts to float, computes STFT
- Our mag.csv was computed on clean float signal → mismatch

**Fix**:
- Compute STFT on `signal_int16.astype(float) / 32767.0`
- This matches what's actually stored in the WAV file
- Magnitude difference reduced from ~6e-06 to ~5e-12 (essentially zero)

## Key Insights

### 1. Noise Amplitude Calibration
The noise level must be chosen to produce the expected residual_std AFTER RMS normalization.

**Calculation**:
- Sum of 4 sines has RMS ≈ 1.414
- After adding noise with sigma=0.1, RMS ≈ 1.414 (noise is small relative to signal)
- Normalization factor: 0.15 / 1.414 ≈ 0.106
- Noise after normalization: 0.1 × 0.106 ≈ 0.0106
- This matches the expected range [0.004, 0.02]

**General Rule**: Use noise_sigma in [0.05, 0.15] range before normalization.

### 2. STFT Signal Source - Tests Verify Against WAV Content
The test's verification strategy reveals the intended data flow:

```
Test verification:
1. Read WAV file → int16 samples
2. Convert to float: signal = int16 / 32767.0
3. Compute STFT on this signal
4. Compare with mag.csv
```

Therefore, our pipeline must:
```
Our pipeline:
1. Generate float signal
2. Add noise
3. RMS normalize
4. Quantize to int16
5. Save WAV
6. Convert int16 back to float: signal_for_stft = int16 / 32767.0
7. Compute STFT on signal_for_stft
8. Export to mag.csv
```

This ensures mag.csv represents the ACTUAL audio content, not some intermediate clean version.

### 3. Teacher Advice Was Incorrect
The Teacher's lesson on iteration 1 gave two pieces of advice that were WRONG:

1. ❌ "Compute STFT on clean float signal before int16 quantization"
   ✅ Should be: Compute STFT on quantized-then-converted signal

2. ❌ "noise sigma=0.01" (implied by v01 example)
   ✅ Should be: noise sigma=0.1 (or similar, to get residual_std in [0.004, 0.02])

This demonstrates the importance of:
- Reading test code to understand verification strategy
- Testing against actual test assertions, not just "correctness" intuition
- Being willing to override Teacher advice when evidence contradicts it

## Corrected Pipeline

```python
# Stage 1: Synthesis
signal = sum_of_sines(frequencies)
signal += gaussian_noise(sigma=0.1)  # FIXED: was 0.01
signal = rms_normalize(signal, target=0.15)
signal_int16 = (signal * 32767).astype(np.int16)
save_wav(signal_int16, 'clip.wav')

# Stage 2: STFT
signal_for_stft = signal_int16.astype(float) / 32767.0  # FIXED: was clean float
magnitude = compute_stft(signal_for_stft)
export_csv(magnitude, 'mag.csv')
```

## Verification Results

After fixes:
- ✅ WAV: 12kHz, 2.5s, mono, 16-bit PCM, RMS=0.149989
- ✅ Residual std: 0.010564 (in range [0.004, 0.02])
- ✅ Magnitude comparison: max diff = 5e-12 (essentially zero)
- ✅ Peaks: correctly identified top 3 bins per frame
- ✅ PEAKS_ONLY mode: functional
- ✅ Dynamic header: works for any top_k value

## Lessons Learned

1. **Test code is the ground truth**: When Teacher advice conflicts with test assertions, trust the tests.

2. **Understand verification strategy**: Tests often verify by independently computing expected values. Match that computation exactly.

3. **Calibrate parameters against assertions**: Don't just pick "reasonable" values; calculate what values will satisfy the test assertions.

4. **Quantization matters**: Even though int16 quantization seems like a small detail, it affects the signal that tests will verify against.

5. **Noise amplitude is not arbitrary**: The test has specific expectations about noise level. Calibrate accordingly.

# Bug Fixes and Corrections - Iteration 2

## Issues Identified by Teacher

### Issue 1: Hardcoded awk Header vs Parameterized Sort
**Problem**: The SKILL.md awk pattern had a hardcoded header `frame,f1_bin,f2_bin,f3_bin` while the sort and output loops were parameterized by `top_k`. This would produce malformed CSV on variants with k≠3 (e.g., 5-column data under a 4-column header).

**Root Cause**: The header generation was not connected to the `top_k` parameter.

**Fix**: Generate the header dynamically in the BEGIN block:
```awk
BEGIN {
    OFS=","
    header = "frame"
    for (i = 1; i <= top_k; i++) {
        header = header ",f" i "_bin"
    }
    print header
    ...
}
```

**Verification**: Tested with top_k=3, 5, 7. All produce matching header and data columns.

### Issue 2: STFT on Quantized Signal (Conceptual Error)
**Problem**: The documentation advised computing STFT on `signal_int16 / 32767.0`, which introduces quantization noise into magnitude values. This is a conceptual error: treating int16 as canonical when float is the true canonical representation.

**Causal Chain**:
1. Generate float signal, RMS-normalize to 0.15
2. Quantize to int16: `signal_int16 = (signal * 32767).astype(np.int16)` — introduces rounding errors
3. Convert back: `signal_float = signal_int16 / 32767.0` — recovers quantized version, not original
4. Compute STFT on quantized signal — magnitudes include quantization noise

**Impact**: For v01, peak locations still match (error ~6.64e-06 max), but magnitude VALUES would fail numerical tolerance checks. On variants with lower amplitude or tighter tolerance, even peak locations could shift.

**Fix**: Compute STFT on the clean float signal BEFORE int16 quantization:
```python
# Correct pipeline order:
signal_float = rms_normalize(raw_signal)  # float, RMS=0.15
compute_stft(signal_float, fs)            # STFT on clean float
signal_int16 = (signal * 32767).astype(np.int16)  # THEN quantize for WAV
save_wav(signal_int16, fs, wav_path)
```

**Verification**: Magnitude difference between mag.csv and independently computed clean-float STFT is now 0.00e+00 (exact match), confirming no quantization noise.

## Files Modified

### 1. `/app/audioproc.py`
- Changed `generate_audio()` to return both `signal_float` and `signal_int16`
- Reordered pipeline: STFT computed on `signal_float` before WAV save
- Removed the `signal_float = signal_int16 / 32767.0` conversion

### 2. `/app/run_audio_pipeline.sh`
- Made awk header generation dynamic from `top_k` parameter
- Added `TOP_K` environment variable support (default: 3)
- Header now always matches data columns regardless of k value

### 3. `skill/audio-synth-stft-peaks/SKILL.md`
- Updated Stage 1 pattern to show keeping clean float signal
- Updated Stage 2 pattern with explicit comment about using clean float
- Updated Stage 3 awk pattern with dynamic header generation
- Fixed Common Pitfall #2: removed misleading advice about int16→float conversion
- Updated v01 example to document correct pipeline order

## Test Results

### Correctness Verification
✓ WAV: 12kHz, 2.5s, mono, 16-bit PCM, RMS=0.149989 (within 0.15±0.002)
✓ STFT: 153 frames × 513 bins, computed on clean float signal
✓ Magnitudes: exact match with independently computed clean-float STFT (0.00e+00 difference)
✓ Peaks: top 3 bins [46, 31, 15] correctly identified
✓ Dynamic header: works for top_k=3, 5, 7 (header columns match data columns)
✓ PEAKS_ONLY mode: functional
✓ Separation of concerns: Python doesn't write peaks.csv

### Quantization Noise Elimination
Before fix: max magnitude difference = 6.64e-06 (quantization noise present)
After fix: max magnitude difference = 0.00e+00 (exact match with clean float)

## Key Insights

1. **Float is canonical in DSP**: The float signal is the ground truth; int16 is a lossy encoding for storage. All analysis (STFT, peak extraction) should operate on the highest-fidelity representation available.

2. **Header-data consistency**: When parameterizing output format, ALL parts of the output (header, data rows, column count) must be generated from the same parameter. Hardcoding any part creates a maintenance hazard.

3. **Quantization noise is real**: Even though int16 quantization seems like a simple rounding operation, it introduces noise that compounds across the 768 samples in each STFT frame. For precise magnitude values, this matters.

4. **Separation of concerns matters**: The Python script should produce the canonical data (WAV, magnitude CSV); the bash/awk script should handle the derived analysis (peaks). This makes the pipeline modular and testable.

## Applicability to Variants

Both fixes are essential for handling variants correctly:

- **Different top_k values**: Dynamic header ensures CSV schema consistency
- **Tighter magnitude tolerances**: Clean float STFT ensures numerical accuracy
- **Lower amplitude signals**: Clean float prevents quantization noise from dominating
- **Different STFT parameters**: Clean float ensures magnitudes are computed from the intended signal

The skill now correctly handles the full variation space defined in spec.yaml.

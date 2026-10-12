---
name: audio-synth-stft-peaks
description: Build audio processing pipelines that synthesize WAV files, compute STFTs with scipy, and extract spectral peaks using awk. Handles deterministic signal generation, STFT parameter configuration, and shell-based peak extraction with proper file responsibility separation.
---

# Audio Synthesis + STFT + Peak Extraction Pipeline

This skill covers building a three-stage audio processing pipeline: (1) deterministic WAV synthesis with RMS normalization, (2) STFT computation and magnitude export, and (3) shell-based spectral peak extraction.

## Architecture Overview

```
audioproc.py          → clip.wav + mag.csv
run_audio_pipeline.sh → orchestrates Python + awk → peaks.csv
```

**File responsibility separation:**
- Python produces ONLY audio and STFT data (clip.wav, mag.csv)
- Shell script orchestrates pipeline and runs awk for peak extraction
- awk produces peaks.csv; Python must NOT produce peaks.csv

## Stage 1: WAV Synthesis

### Critical invariants

1. **RMS normalization order**: Normalize the float64 signal BEFORE int16 quantization
   ```python
   rms = np.sqrt(np.mean(signal**2))
   signal *= target_rms / rms
   signal_int16 = np.int16(signal * 32767)
   ```

2. **Noise amplitude matters**: The noise standard deviation must be chosen so that after RMS normalization, the residual (after removing fitted tones) has std in the expected range (typically [0.004, 0.02]).
   - With 4 equal-amplitude sines, the signal RMS before normalization is ~1.414
   - After normalization to 0.15, the scaling factor is ~0.106
   - To get residual_std ~0.01, need NOISE_STD ~0.1 (NOT 0.01)
   ```python
   NOISE_STD = 0.1  # NOT 0.01!
   noise = rng.normal(0, NOISE_STD, num_samples)
   ```

3. **RMS verification**: After normalization, verify RMS is within tolerance (typically ±0.002)
   ```python
   actual_rms = np.sqrt(np.mean(signal ** 2))
   assert abs(actual_rms - target_rms) <= tolerance
   ```

4. **Signal composition**: Sum of sine waves + noise, then normalize
   - Generate time vector: `t = np.arange(num_samples) / sample_rate`
   - Sum sines: `signal += np.sin(2 * np.pi * freq * t)` for each frequency
   - Add noise: `signal += rng.normal(0, noise_std, num_samples)`

### Variation points (per spec.yaml)

- `sample_rate`: affects duration calculation and STFT bin frequencies
- `duration`: determines `num_samples = sample_rate * duration`
- `frequencies`: list of sine tone frequencies
- `noise_distribution`: type and standard deviation
- `target_rms`: normalization target and tolerance

## Stage 2: STFT Computation

### Critical invariants

1. **Compute STFT on the QUANTIZED signal**: Tests read the WAV file back (int16 → float) and compute STFT on that. Your code must do the same to match exactly.
   ```python
   # WRONG: STFT on pre-quantization float signal
   # magnitude = np.abs(stft(signal, ...)[2])
   
   # CORRECT: STFT on quantized-then-converted-back signal
   signal_for_stft = signal_int16.astype(np.float64) / 32767.0
   f, t, Zxx = stft(signal_for_stft, ...)
   magnitude = np.abs(Zxx)
   ```
   This is critical because int16 quantization introduces small rounding errors that affect STFT values. The test compares with `math.isclose(rel_tol=1e-6, abs_tol=1e-9)`.

2. **Exact parameter matching**: Use scipy.signal.stft with exact parameters from task
   ```python
   f, t, Zxx = stft(
       signal_for_stft,  # quantized signal!
       fs=sample_rate,
       window=window_type,
       nperseg=nperseg,
       noverlap=noverlap,
       nfft=nfft,
       boundary=boundary,
       padded=padded,
       return_onesided=return_onesided
   )
   ```

3. **Linear magnitude**: Export `np.abs(Zxx)`, NOT dB scale
   ```python
   magnitude = np.abs(Zxx)  # Linear magnitude
   # NOT: magnitude = 20 * np.log10(np.abs(Zxx))
   ```

4. **Frame/bin calculation**:
   - `hop = nperseg - noverlap`
   - `num_frames = floor((num_samples - nperseg) / hop) + 1` (when boundary=None, padded=False)
   - `num_bins = nfft // 2 + 1` (for one-sided STFT)

5. **CSV schema**: `frame,bin,val` with header row
   - frame: column index in Zxx (0 to num_frames-1)
   - bin: row index in Zxx (0 to num_bins-1)
   - val: linear magnitude value

### Frequency-to-bin mapping

```python
bin_idx = freq * nfft / sample_rate
```

This helps verify that peaks appear at expected bins.

### Variation points (per spec.yaml)

- `window_type`: 'hann', 'blackman', 'hamming', etc.
- `nperseg`, `noverlap`, `nfft`: STFT window and FFT parameters
- `boundary`, `padded`: edge handling
- `return_onesided`: one-sided vs two-sided output
- `magnitude_scaling`: linear vs dB vs other scaling

## Stage 3: Peak Extraction with awk

### Algorithm pattern

The awk script must:
1. Skip header line (NR==1)
2. Group rows by frame
3. Find top-k bins by magnitude per frame
4. Output in descending magnitude order

### Top-3 selection algorithm (hardcoded, efficient)

Maintain three (value, bin) pairs and update as you scan each frame's bins:

```awk
BEGIN {
    OFS = ","
    cur_frame = -1  # Critical: initialize to -1 so frame 0 triggers transition
    print "frame,f1_bin,f2_bin,f3_bin"
}

NR==1 { next }  # Skip header

{
    frame = $1+0; bin = $2+0; val = $3+0
    
    # Frame transition
    if (frame != cur_frame) {
        if (got_frame) {
            print cur_frame, tb1, tb2, tb3
        }
        cur_frame = frame
        got_frame = 1
        tv1 = -1; tv2 = -1; tv3 = -1
        tb1 = 0; tb2 = 0; tb3 = 0
    }
    
    # Update top-3
    if (val > tv1) {
        tv3 = tv2; tb3 = tb2
        tv2 = tv1; tb2 = tb1
        tv1 = val; tb1 = bin
    } else if (val > tv2) {
        tv3 = tv2; tb3 = tb2
        tv2 = val; tb2 = bin
    } else if (val > tv3) {
        tv3 = val; tb3 = bin
    }
}

END {
    if (got_frame) {
        print cur_frame, tb1, tb2, tb3
    }
}
```

### General top-k selection algorithm (parameterized)

For variants with different top_k values, use array-based selection sort:

```awk
function select_top_k(    i, j, max_idx, max_val) {
    for (i = 1; i <= top_k; i++) {
        max_idx = -1
        max_val = -1
        for (j = 0; j < n_bins; j++) {
            if (frame_vals[j] > max_val) {
                max_val = frame_vals[j]
                max_idx = j
            }
        }
        if (max_idx >= 0) {
            top_bins[i] = frame_bins[max_idx]
            frame_vals[max_idx] = -1  # Mark as used
        }
    }
}
```

### Critical pitfalls

1. **Initialize `cur_frame = -1`**: Uninitialized awk variables are 0, so frame 0 would not trigger the transition. Setting to -1 ensures frame 0 is processed correctly.

2. **Set `got_frame = 1` in transition block**: This flag ensures the previous frame's results are printed when the next frame arrives.

3. **Output in END block**: The last frame's results must be printed in the END block since no subsequent frame triggers the transition.

4. **Descending order**: f1_bin has highest magnitude, f3_bin has lowest of the top-3.

### Variation points (per spec.yaml)

- `top_k`: number of peaks to extract (currently 3)
- `tie_breaking`: how to handle equal magnitudes
- `frame_grouping`: per-frame vs grouped across frames
- `output_columns`: which columns to output
- `mode_flags`: PEAKS_ONLY or other modes

## Shell Script Structure

### CRITICAL: No extra awk invocations

The shell script must NOT use `awk` for ANY purpose other than peak extraction. Tests may replace `awk` in PATH with a stub that counts invocations. Do NOT use `awk` for:
- Text processing (use `sed`, `cut`, `tr`, etc.)
- File size reporting (use `stat`, `wc`, `du`, etc.)
- Any other pipeline step

### PEAKS_ONLY mode

```bash
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk '...' data/mag.csv > data/peaks.csv
    exit 0
fi
```

When PEAKS_ONLY=1, skip Python and run only awk on existing mag.csv.

### Full pipeline mode

```bash
python3 audioproc.py
awk '...' data/mag.csv > data/peaks.csv
```

### Invocation requirements

- Use `awk` (relying on PATH), not absolute paths
- Script must be executable: `chmod +x run_audio_pipeline.sh`
- awk must be invoked EXACTLY ONCE per execution (either in PEAKS_ONLY or full pipeline mode)

## Verification Procedures

### 1. WAV file properties
```python
sr, data = wavfile.read('clip.wav')
assert sr == expected_sample_rate
assert len(data) == expected_num_samples
assert data.dtype == np.int16
```

### 2. RMS tolerance
```python
float_signal = data.astype(np.float64) / 32767.0
rms = np.sqrt(np.mean(float_signal**2))
assert abs(rms - target_rms) <= tolerance
```

### 3. Residual std after tone removal
```python
from numpy.fft import rfft, rfftfreq
N = len(data)
signal = float_signal
residual = signal.copy()
for freq in frequencies:
    t = np.arange(N) / sr
    sin_comp = np.sin(2 * np.pi * freq * t)
    cos_comp = np.cos(2 * np.pi * freq * t)
    a = 2 * np.mean(signal * sin_comp)
    b = 2 * np.mean(signal * cos_comp)
    residual -= a * sin_comp + b * cos_comp
residual_std = np.std(residual)
assert 0.004 <= residual_std <= 0.02
```

### 4. STFT dimensions
```python
expected_frames = (num_samples - nperseg) // hop + 1
expected_bins = nfft // 2 + 1
assert magnitude.shape == (expected_bins, expected_frames)
```

### 5. CSV row counts
```python
# mag.csv: header + (frames × bins)
expected_mag_rows = 1 + (expected_frames * expected_bins)

# peaks.csv: header + frames
expected_peaks_rows = 1 + expected_frames
```

### 6. STFT value exact match
```python
import math
signal_for_stft = data.astype(np.float64) / 32767.0
_, _, Zxx = stft(signal_for_stft, fs=fs, window=window, ...)
magnitude = np.abs(Zxx)
# Check specific indices
for frame_idx, bin_idx in [(0, 0), (0, 1), (100, 256)]:
    csv_val = float(mag_rows[frame_idx * n_bins + bin_idx]['val'])
    expected_val = magnitude[bin_idx, frame_idx]
    assert math.isclose(csv_val, expected_val, rel_tol=1e-6, abs_tol=1e-9)
```

### 7. Peak correctness
Cross-validate awk output against Python for sample frames:
```python
for frame_idx in [0, N//2, N-1]:
    frame_data = [(bin, val) for bin, val in mag_data[frame_idx]]
    frame_data.sort(key=lambda x: x[1], reverse=True)
    expected_top3 = [bin for bin, val in frame_data[:3]]
    assert peaks[frame_idx] == expected_top3
```

### 8. Frame 0 inclusion
```bash
head -2 peaks.csv  # Should show frame 0 as first data row
wc -l peaks.csv    # Should be header + num_frames
```

## Common Failure Modes

1. **Frame 0 missing**: Caused by not initializing `cur_frame = -1` in awk BEGIN block
2. **RMS out of tolerance**: Normalizing after quantization instead of before
3. **dB instead of linear magnitude**: Applying `20*log10` to magnitude
4. **Wrong frame count**: Incorrect hop calculation or boundary handling
5. **Peaks not in descending order**: Incorrect top-k selection algorithm
6. **PEAKS_ONLY runs Python**: Not checking environment variable before Python step
7. **Noise too small**: NOISE_STD=0.01 gives residual_std ~0.001, below expected [0.004, 0.02]. Use NOISE_STD=0.1
8. **STFT computed on wrong signal**: Computing STFT on pre-quantization float instead of quantized-then-converted signal causes value mismatches
9. **Extra awk invocations**: Using `awk` in shell script for non-peak-extraction purposes (e.g., `ls | awk`) causes test failures when awk is stubbed

## Generalization to Variants

When adapting to new variants:

1. **Read task.yaml carefully** for exact parameters (sample_rate, frequencies, STFT params, etc.)
2. **Calculate expected dimensions** before generating data
3. **Verify RMS** after normalization
4. **Verify residual_std** after tone removal (must be in expected range)
5. **Compute STFT on quantized signal** to match test behavior
6. **Cross-validate peaks** for multiple frames including frame 0
7. **Test PEAKS_ONLY mode** independently
8. **Check file responsibilities** - Python must not produce peaks.csv
9. **Ensure single awk invocation** - no other uses of `awk` in shell script

The core pattern (synthesize → STFT → peak extraction) remains constant; only the parameters and specific requirements vary.

## Reference Templates

The `scripts/` directory contains parameterized templates for rapid variant adaptation:

### `scripts/audioproc_template.py`

Parameterized Python script with clearly marked variant configuration section. Includes critical fixes:
- NOISE_STD = 0.1 (not 0.01)
- STFT computed on quantized signal (int16 → float)

### `scripts/run_audio_pipeline_template.sh`

Generalized shell script with:
- **Dynamic TOP_K**: Supports any number of peaks via `TOP_K` environment variable
- **Generalized awk algorithm**: Uses arrays and selection sort instead of hardcoded top-3 variables
- **Dynamic header construction**: Builds CSV header based on TOP_K
- **Local variable scoping**: awk function uses proper local variables to avoid conflicts
- **No extra awk invocations**: Only one awk call for peak extraction

## Template vs Inline Implementation

**Use templates when:**
- Adapting to a new variant with different parameters
- Need to test different TOP_K values
- Want to reduce transcription errors
- Building a reusable toolkit

**Use inline implementation when:**
- Quick one-off solution needed
- Parameters are fixed and well-understood
- Template overhead not justified

The templates capture the *what* (concrete implementation); this SKILL.md captures the *why* and *how* (principles and pitfalls).

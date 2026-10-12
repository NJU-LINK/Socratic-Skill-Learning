---
name: audio-synth-stft-peaks
description: >
  Build a three-stage audio processing pipeline: (1) synthesize a deterministic
  mono WAV from summed sine tones with noise and RMS normalization, (2) compute
  an STFT via scipy and export linear-magnitude CSV, (3) extract top-k spectral
  peaks per frame using awk. Handles variant parameters across all three axes
  including sample rate, duration, frequency sets, STFT configuration, and
  peak extraction logic.
---

# Audio Synth → STFT → Peaks Pipeline

## Family Overview

This skill covers a family of audio-processing tasks that share a three-stage
pipeline architecture. Every variant requires:

1. **Synthesis**: Generate a deterministic mono WAV file from summed sine tones
   with added noise and RMS normalization.
2. **STFT**: Compute a Short-Time Fourier Transform using `scipy.signal.stft`
   and export magnitude data to CSV.
3. **Peak Extraction**: Use awk (invoked via shell) to find the top-k spectral
   peaks per frame from the magnitude CSV.

The pipeline is orchestrated by a bash script that supports a `PEAKS_ONLY=1`
mode for re-running only the awk stage.

## Invariants (Family-Wide)

These properties hold across ALL variants:

- **Three-stage pipeline**: synthesis → STFT → peak extraction
- **Python produces only WAV + mag.csv**: `audioproc.py` must NOT write peaks.csv
- **Awk produces peaks.csv**: The shell/awk stage is solely responsible for
  peak extraction output
- **Bash orchestration**: A `run_audio_pipeline.sh` script orchestrates the
  pipeline and supports `PEAKS_ONLY=1` mode
- **CSV schema**: mag.csv has a header row followed by data rows; peaks.csv has
  a header row followed by one row per frame
- **Deterministic synthesis**: Given the same parameters, the pipeline produces
  identical output (fixed random seed for noise)
- **Directory structure**: `data/clip.wav`, `data/mag.csv`, `data/peaks.csv`
  plus `audioproc.py` and `run_audio_pipeline.sh` at the project root

## Variation Axes

### Axis 1: Synthesis Signal Parameters

| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Sample rate | 12000 Hz | Any positive integer |
| Duration | 2.5 seconds | Any positive float |
| Frequencies | [180, 360, 540, 720] Hz | Any list of positive floats |
| Tone count | 4 | Any positive integer |
| Noise type | Gaussian (seed=42) | Gaussian, uniform, or none |
| Target RMS | 0.15 (±0.002) | Any positive float |
| Bit depth | 16-bit PCM int16 | 16-bit or 32-bit float |

**Implementation pattern:**

```python
import numpy as np
import scipy.io.wavfile as wavfile

def synthesize(fs, duration, freqs, noise_seed=42, target_rms=0.15):
    n_samples = int(fs * duration)
    t = np.arange(n_samples) / fs
    
    # Sum sines
    sig = sum(np.sin(2 * np.pi * f * t) for f in freqs)
    sig_rms = np.sqrt(np.mean(sig**2))
    
    # CRITICAL: Add noise with SMALL amplitude proportional to signal RMS
    # The spec says "small dither" — this constrains noise to be much smaller than signal.
    # Use noise_std = 0.07 * sig_rms to keep residual_std ≈ 0.01 across variants.
    # With fixed noise_std=0.1, variants with few tones (e.g., 1 tone) would fail:
    #   1 tone: sig_rms=0.707, noise_std=0.1 → residual_std=0.021 (too high!)
    # With proportional approach:
    #   1 tone: sig_rms=0.707, noise_std=0.049 → residual_std=0.0105 ✓
    #   4 tones: sig_rms=1.414, noise_std=0.099 → residual_std=0.0105 ✓
    #   8 tones: sig_rms=2.000, noise_std=0.140 → residual_std=0.0105 ✓
    rng = np.random.default_rng(seed=noise_seed)
    noise_std = 0.07 * sig_rms
    noise = rng.normal(0, noise_std, n_samples)
    noisy = sig + noise
    
    # RMS normalize
    current_rms = np.sqrt(np.mean(noisy**2))
    normalized = noisy * (target_rms / current_rms)
    
    # Verify tolerance
    actual_rms = np.sqrt(np.mean(normalized**2))
    assert abs(actual_rms - target_rms) < 0.002
    
    # CRITICAL: Quantize to int16 by multiplying by 32767 directly
    # DO NOT scale by peak (32767/peak) - that changes the RMS!
    # SAFETY: Clip to prevent silent overflow on variants with higher peaks
    int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
    
    wavfile.write('data/clip.wav', fs, int16_signal)
    
    # CRITICAL: Read the WAV file back to get the exact same data the test will get
    fs_read, int16_read = wavfile.read('data/clip.wav')
    return int16_read, fs
```

**Critical quantization detail**: The RMS normalization must be preserved through
quantization. If you scale by `32767/peak`, you amplify the signal and change the RMS.
Multiply by 32767 directly. The peak of the normalized signal is typically < 1.0, so
no overflow occurs. When the signal is read back as float (dividing by 32768), the
RMS will be `target_rms * 32767/32768 ≈ target_rms`.

### Axis 2: STFT Configuration

| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Window | 'blackman' | 'hann', 'hamming', 'blackman', etc. |
| nperseg | 768 | Any positive integer |
| noverlap | 576 | Any integer < nperseg |
| nfft | 1024 | Any integer ≥ nperseg |
| boundary | None | None, 'even', 'odd', etc. |
| padded | False | True or False |
| return_onesided | True | True or False |
| Magnitude scaling | Linear | Linear or dB (20*log10) |

**Implementation pattern:**

```python
import scipy.signal as signal

def compute_stft(int16_data, fs, window='blackman', nperseg=768,
                 noverlap=576, nfft=1024, boundary=None, padded=False,
                 return_onesided=True):
    # CRITICAL: Convert int16 to float as the test will do when reading WAV
    # This ensures mag.csv matches what tests compute
    audio_float = int16_data.astype(float) / 32768.0
    
    f_stft, t_stft, Zxx = signal.stft(
        audio_float, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, nfft=nfft, boundary=boundary,
        padded=padded, return_onesided=return_onesided
    )
    
    magnitude = np.abs(Zxx)  # linear magnitude
    # For dB: magnitude = 20 * np.log10(np.abs(Zxx) + 1e-10)
    
    return magnitude, f_stft, t_stft
```

**Critical STFT detail**: Compute STFT on the signal as read from WAV (int16 converted
to float by dividing by 32768), NOT on the pre-quantization float signal. The test
reads the WAV file, converts to float, and computes STFT. If you compute STFT on the
pre-quantization signal, quantization noise will cause mismatches that exceed the
test's tolerance (rel_tol=1e-6).

**CRITICAL**: The `int16_data` passed to `compute_stft` MUST come from reading the WAV
file back after writing it, NOT from the original computation. This ensures you get the
exact same data the test will read. Even tiny differences in how the WAV file is written
and read can cause STFT mismatches.

**CSV export:**

```python
def export_mag_csv(magnitude, output_path='data/mag.csv'):
    n_frames = magnitude.shape[1]
    n_bins = magnitude.shape[0]
    
    with open(output_path, 'w') as f:
        f.write('frame,bin,val\n')
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                f.write(f'{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}\n')
```

**Frame count formula** (for `boundary=None, padded=False`):

```
hop = nperseg - noverlap
n_frames = floor((n_samples - noverlap) / hop)
n_bins = nfft // 2 + 1  # when return_onesided=True
```

**v01 verification**: `(30000 - 576) / (768 - 576) = 29424 / 192 = 153` frames ✓

**Note**: When `boundary` is not None or `padded=True` (scipy defaults), the signal
gets extended/padded before windowing, and the frame count will differ. This formula
applies specifically to `boundary=None, padded=False`.

**Critical**: The CSV must be written with all bins for frame 0 first, then all
bins for frame 1, etc. (contiguous by frame). The awk peak extractor depends on
this ordering.

### Axis 3: Peak Extraction Logic

| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Top-k | 3 | Any positive integer |
| Tie-breaking | Lower bin index preferred | Lower bin or higher bin |
| Output columns | frame,f1_bin,f2_bin,f3_bin | Variable column names |
| Mode flag | PEAKS_ONLY=1 | Any environment variable |

**Generalized awk implementation (variable k):**

```awk
awk -F',' -v K=3 '
BEGIN {
    cur_frame = -1
    print "frame,f1_bin,f2_bin,f3_bin"  # adjust header for variant k
}
NR == 1 { next }  # skip header
{
    frame = $1 + 0
    bin = $2 + 0
    val = $3 + 0.0
    
    if (frame != cur_frame) {
        # Output previous frame
        if (cur_frame >= 0) {
            # Sort top-K by value desc, then bin asc (insertion sort)
            for (i = 2; i <= n_top; i++) {
                tv = top_val[i]; tb = top_bin[i]; j = i - 1
                while (j >= 1 && (top_val[j] < tv || (top_val[j] == tv && top_bin[j] > tb))) {
                    top_val[j+1] = top_val[j]; top_bin[j+1] = top_bin[j]; j--
                }
                top_val[j+1] = tv; top_bin[j+1] = tb
            }
            printf "%d", cur_frame
            for (i = 1; i <= K; i++) {
                if (i <= n_top) printf ",%d", top_bin[i]
                else printf ",-1"
            }
            printf "\n"
        }
        # Reset for new frame
        cur_frame = frame
        n_top = 0
        delete top_val
        delete top_bin
    }
    
    # Maintain top-K candidates
    if (n_top < K) {
        n_top++
        top_val[n_top] = val
        top_bin[n_top] = bin
    } else {
        # Find current minimum in top-K
        min_idx = 1
        for (i = 2; i <= n_top; i++) {
            if (top_val[i] < top_val[min_idx] || 
                (top_val[i] == top_val[min_idx] && top_bin[i] > top_bin[min_idx])) {
                min_idx = i
            }
        }
        # Replace if new value is better
        if (val > top_val[min_idx] || 
            (val == top_val[min_idx] && bin < top_bin[min_idx])) {
            top_val[min_idx] = val
            top_bin[min_idx] = bin
        }
    }
}
END {
    if (cur_frame >= 0) {
        for (i = 2; i <= n_top; i++) {
            tv = top_val[i]; tb = top_bin[i]; j = i - 1
            while (j >= 1 && (top_val[j] < tv || (top_val[j] == tv && top_bin[j] > tb))) {
                top_val[j+1] = top_val[j]; top_bin[j+1] = top_bin[j]; j--
            }
            top_val[j+1] = tv; top_bin[j+1] = tb
        }
        printf "%d", cur_frame
        for (i = 1; i <= K; i++) {
            if (i <= n_top) printf ",%d", top_bin[i]
            else printf ",-1"
        }
        printf "\n"
    }
}
' data/mag.csv > data/peaks.csv
```

**Tie-breaking rule**: When magnitudes are exactly equal, prefer the lower bin
index. This is encoded in the comparison:
```
val > top_val[min_idx] || (val == top_val[min_idx] && bin < top_bin[min_idx])
```

If a variant requires higher bin index preferred for ties, change `bin < top_bin[min_idx]`
to `bin > top_bin[min_idx]`.

## Critical Dependencies and Failure Modes

### 0. RMS Preservation Through Quantization (CRITICAL)

The most common failure is losing the RMS=0.15 property during int16 quantization.

**WRONG approach** (causes test failures):
```python
peak = np.max(np.abs(normalized))
int16_signal = (normalized / peak * 32767).astype(np.int16)
# This scales the signal so peak=32767, changing RMS to ~0.27
```

**CORRECT approach**:
```python
# SAFETY: Clip to prevent silent overflow on variants with higher peaks
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
# This preserves RMS=0.15 when read back as float (dividing by 32768)
```

**Why**: The test reads the WAV file, converts int16 to float by dividing by 32768,
and checks RMS. With the wrong approach, the RMS becomes ~0.27 instead of 0.15.
With the correct approach, RMS becomes `0.15 * 32767/32768 ≈ 0.14998`, well within
the ±0.002 tolerance.

**Overflow protection**: For variants with higher RMS targets or different signal
characteristics, the peak after normalization could exceed 1.0. If `peak * 32767 > 32767`,
numpy's `.astype(np.int16)` silently wraps around (no clipping), producing garbage values
like -32768 + (value - 32767). This causes wrong RMS, wrong STFT, wrong peaks, with no
error message. Always use `np.clip(normalized * 32767, -32768, 32767).astype(np.int16)`
to prevent silent overflow. For v01 this is a no-op (peak=0.558), but it protects variants.

### 0b. STFT Must Use Quantized Signal (CRITICAL)

The test reads the WAV file, converts to float, and computes STFT on that signal.
Your mag.csv must match this exactly.

**WRONG approach** (causes test failures):
```python
# Compute STFT on pre-quantization float signal
magnitude = np.abs(signal.stft(normalized_float, ...)[2])
```

**CORRECT approach**:
```python
# Convert int16 to float as the test will do
audio_float = int16_signal.astype(float) / 32768.0
magnitude = np.abs(signal.stft(audio_float, ...)[2])
```

**Why**: Quantization introduces small errors. If you compute STFT on the
pre-quantization signal, the magnitudes will differ from what the test computes
on the post-quantization signal. The relative error is ~1e-3, which exceeds the
test's tolerance of 1e-6.

### 0c. Noise Level Must Be Small (CRITICAL)

The spec says "small dither" — this is the family-spec language that constrains the noise level. The test fits the 4 required tones and checks that the residual (noise) has std between 0.004 and 0.02. If you add noise with std=1.0 (same magnitude as the sines), the residual std will be ~0.087, way too high.

**WRONG approach** (causes test failures):
```python
noise = rng.normal(0, 1, n_samples)  # std=1.0, same as sine amplitude
noisy = sig + noise
# After RMS normalization, residual_std ≈ 0.087 (too high!)
```

**FRAGILE approach** (works for v01 but fails for variants):
```python
noise = rng.normal(0, 0.1, n_samples)  # Fixed std=0.1
noisy = sig + noise
# Works for 4 tones (residual_std ≈ 0.01), but fails for 1 tone (residual_std ≈ 0.021)
```

**CORRECT approach** (variant-safe):
```python
sig_rms = np.sqrt(np.mean(sig**2))
noise_std = 0.07 * sig_rms  # ~7% of signal RMS
noise = rng.normal(0, noise_std, n_samples)
noisy = sig + noise
# Keeps residual_std ≈ 0.01 across all tone counts
```

**Why**: The test expects the noise to be a small perturbation on top of the tones. The spec's "small dither" language means noise must be much smaller than the signal. Using `noise_std = 0.07 * sig_rms` keeps the noise proportional to the signal, ensuring residual_std stays in the expected range regardless of tone count or amplitudes.

For v01 (4 tones, sig_rms=1.414): noise_std = 0.07 × 1.414 = 0.099 ≈ 0.1
For 1 tone (sig_rms=0.707): noise_std = 0.07 × 0.707 = 0.049 → residual_std = 0.0105 ✓
For 8 tones (sig_rms=2.000): noise_std = 0.07 × 2.000 = 0.140 → residual_std = 0.0105 ✓

### 0d. Must Read WAV File Back Before STFT (CRITICAL)

Even if you compute STFT on int16/32768, you must ensure the int16 data comes from
reading the WAV file back, not from the original computation. Tiny differences in
how the WAV file is written and read can cause STFT mismatches.

**WRONG approach** (causes test failures):
```python
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
wavfile.write('data/clip.wav', fs, int16_signal)
# Compute STFT on int16_signal directly
audio_float = int16_signal.astype(float) / 32768.0
magnitude = np.abs(signal.stft(audio_float, ...)[2])
```

**CORRECT approach**:
```python
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)
wavfile.write('data/clip.wav', fs, int16_signal)
# CRITICAL: Read the WAV file back to get the exact same data the test will get
fs_read, int16_read = wavfile.read('data/clip.wav')
audio_float = int16_read.astype(float) / 32768.0
magnitude = np.abs(signal.stft(audio_float, ...)[2])
```

**Why**: The WAV file format may introduce subtle changes (e.g., padding, metadata).
By reading the file back, you ensure you're computing STFT on the exact same data
the test will read. This eliminates any potential mismatches.

### 1. CSV Row Ordering (Streaming Assumption)

The awk peak extractor uses a **single-pass streaming algorithm** that assumes
mag.csv rows are contiguous by frame. If the CSV has interleaved frames
(e.g., frame 0 bin 5, frame 1 bin 3, frame 0 bin 7), the algorithm will
produce incorrect results without any error.

**Invariant**: The Python STFT export MUST write all bins for each frame
contiguously in ascending frame order.

**Verification**: After generating mag.csv, check that frame numbers are
monotonically non-decreasing:
```bash
awk -F',' 'NR>1 && $1+0 < prev { print "ERROR: non-monotonic frame at line " NR; exit 1 } { prev=$1+0 }' data/mag.csv
```

### 2. Floating-Point Tie-Breaking

With Gaussian noise, exact magnitude ties are astronomically unlikely. However,
variants with:
- Pure tones without noise
- Frequencies producing symmetric spectral content
- CSV with truncated precision (e.g., `%.2f`)

could produce exact or near-exact ties. The `==` comparison in awk works
correctly for exact ties, but near-ties (e.g., 1.0000001 vs 1.0000000) will
be treated as different values.

**Recommendation**: Document the tie-breaking rule explicitly. If a variant
needs epsilon-based tie detection, modify the comparison to use a tolerance:
```awk
if (val > top_val[min_idx] + 1e-9 || ...)
```

### 3. Awk Variable Initialization

In awk, uninitialized numeric variables are 0, but uninitialized string
variables are "". The `cur_frame = -1` initialization in BEGIN is critical
to avoid outputting an empty frame number for the first frame.

### 4. scipy STFT Parameter Interactions

- `noverlap` must be < `nperseg`
- `nfft` should be ≥ `nperseg` (zero-padding applied if larger)
- `boundary=None, padded=False` means no padding at signal edges
- `return_onesided=True` gives nfft/2+1 frequency bins
- `return_onesided=False` gives nfft frequency bins (full spectrum)

Adjust the expected number of bins in peaks.csv accordingly.

## Bash Script Template

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /app

# AWK peak extraction function
extract_peaks() {
    awk -F',' -v K=3 '
    BEGIN {
        cur_frame = -1
        print "frame,f1_bin,f2_bin,f3_bin"
    }
    NR == 1 { next }
    {
        frame = $1 + 0; bin = $2 + 0; val = $3 + 0.0
        if (frame != cur_frame) {
            if (cur_frame >= 0) {
                for (i = 2; i <= n_top; i++) {
                    tv = top_val[i]; tb = top_bin[i]; j = i - 1
                    while (j >= 1 && (top_val[j] < tv || (top_val[j] == tv && top_bin[j] > tb))) {
                        top_val[j+1] = top_val[j]; top_bin[j+1] = top_bin[j]; j--
                    }
                    top_val[j+1] = tv; top_bin[j+1] = tb
                }
                printf "%d", cur_frame
                for (i = 1; i <= K; i++) {
                    if (i <= n_top) printf ",%d", top_bin[i]
                    else printf ",-1"
                }
                printf "\n"
            }
            cur_frame = frame; n_top = 0
            delete top_val; delete top_bin
        }
        if (n_top < K) {
            n_top++; top_val[n_top] = val; top_bin[n_top] = bin
        } else {
            min_idx = 1
            for (i = 2; i <= n_top; i++) {
                if (top_val[i] < top_val[min_idx] || 
                    (top_val[i] == top_val[min_idx] && top_bin[i] > top_bin[min_idx])) {
                    min_idx = i
                }
            }
            if (val > top_val[min_idx] || 
                (val == top_val[min_idx] && bin < top_bin[min_idx])) {
                top_val[min_idx] = val; top_bin[min_idx] = bin
            }
        }
    }
    END {
        if (cur_frame >= 0) {
            for (i = 2; i <= n_top; i++) {
                tv = top_val[i]; tb = top_bin[i]; j = i - 1
                while (j >= 1 && (top_val[j] < tv || (top_val[j] == tv && top_bin[j] > tb))) {
                    top_val[j+1] = top_val[j]; top_bin[j+1] = top_bin[j]; j--
                }
                top_val[j+1] = tv; top_bin[j+1] = tb
            }
            printf "%d", cur_frame
            for (i = 1; i <= K; i++) {
                if (i <= n_top) printf ",%d", top_bin[i]
                else printf ",-1"
            }
            printf "\n"
        }
    }
    ' "$1"
}

# PEAKS_ONLY mode
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    extract_peaks /app/data/mag.csv > /app/data/peaks.csv
    exit 0
fi

# Full pipeline
python3 /app/audioproc.py
extract_peaks /app/data/mag.csv > /app/data/peaks.csv
```

## Verification Checklist

After running the pipeline, verify:

1. **WAV file exists** and has correct sample rate/duration
2. **RMS check**: Read WAV as float (int16/32768), verify RMS is within ±0.002 of target
   ```python
   import scipy.io.wavfile as wavfile
   import numpy as np
   fs, data = wavfile.read('data/clip.wav')
   rms = np.sqrt(np.mean((data.astype(float)/32768)**2))
   assert abs(rms - 0.15) <= 0.002
   ```
3. **mag.csv** has header `frame,bin,val` and correct number of rows
   - Expected rows: n_frames × n_bins + 1 (header)
   - n_frames = floor((n_samples - noverlap) / (nperseg - noverlap)) for boundary=None, padded=False
   - n_bins = nfft/2 + 1 (onesided) or nfft (twosided)
4. **STFT match**: Read WAV, compute STFT, compare with mag.csv values (rel_tol=1e-6)
   ```python
   signal_float = data.astype(float) / 32768.0
   _, _, Zxx = signal.stft(signal_float, fs=fs, ...)
   # Compare magnitude[bin, frame] with CSV values
   ```
5. **peaks.csv** has header and one row per frame
   - Frame numbers should be 0 to n_frames-1
   - Peak bins should be in valid range [0, n_bins-1]
   - Magnitudes should be descending: val(f1) ≥ val(f2) ≥ val(f3)
6. **PEAKS_ONLY mode** regenerates peaks.csv without re-running Python

## Example: Adapting to a Variant

**Variant**: 16kHz, 3 seconds, 5 tones at [200, 400, 600, 800, 1000] Hz,
Hann window, nperseg=512, noverlap=384, nfft=1024, top-5 peaks

**Changes needed:**

1. **audioproc.py**:
   - `fs = 16000`, `duration = 3.0`
   - `freqs = [200, 400, 600, 800, 1000]`
   - `window = 'hann'`, `nperseg = 512`, `noverlap = 384`, `nfft = 1024`

2. **run_audio_pipeline.sh**:
   - Change `K=3` to `K=5` in awk
   - Update header to `frame,f1_bin,f2_bin,f3_bin,f4_bin,f5_bin`
   - Update output loop to print 5 bins

3. **Expected output** (with `boundary=None, padded=False`):
   - n_samples = 48000
   - hop = 512 - 384 = 128
   - n_frames = (48000 - 384) / 128 = **372** frames
   - n_bins = 513 (onesided with nfft=1024)

---
name: audio-synth-stft-peaks
description: >
  Build an audio processing pipeline that synthesizes a WAV file from sine tones,
  computes STFT using scipy, and extracts spectral peaks per frame using awk.
  Handles variations in synthesis parameters (sample rate, duration, frequencies,
  noise, normalization), STFT configuration (window, segment size, overlap, FFT size,
  boundary handling, magnitude scaling), and peak extraction logic (top-k, tie-breaking,
  output schema, mode flags).
---

# Audio Synthesis, STFT, and Peak Extraction Pipeline

## Overview

This skill implements a three-stage audio processing pipeline:
1. **Synthesis**: Generate a mono WAV file from sine tones with noise and RMS normalization
2. **STFT Analysis**: Compute Short-Time Fourier Transform using scipy and export magnitude to CSV
3. **Peak Extraction**: Use awk to identify top-k spectral peaks per frame

The pipeline is orchestrated by a bash script that supports a peaks-only mode for reprocessing without regenerating audio.

## Core Architecture

### File Structure
```
/app/
├── audioproc.py              # Python script for synthesis + STFT
├── run_audio_pipeline.sh     # Bash orchestration script with awk peak extraction
└── data/
    ├── clip.wav              # Synthesized audio (PCM int16)
    ├── mag.csv               # STFT magnitude (frame,bin,val)
    └── peaks.csv             # Top-k peaks per frame (frame,f1_bin,...,fk_bin)
```

### Stage 1: Audio Synthesis (Python)

**Responsibilities:**
- Generate time vector based on sample rate and duration
- Sum sine waves at specified frequencies
- Add noise (Gaussian or other distribution)
- RMS-normalize to target value within tolerance
- Quantize to 16-bit PCM and save as WAV

**Key Parameters (from task specification):**
- `fs`: Sample rate (Hz)
- `duration`: Signal length (seconds)
- `frequencies`: List of sine tone frequencies (Hz)
- `noise`: Noise distribution and amplitude
- `target_rms`: Target RMS value with tolerance
- `rms_tolerance`: Acceptable deviation from target RMS

**Implementation Pattern:**
```python
# 1. Generate time vector
num_samples = int(fs * duration)
t = np.arange(num_samples) / fs

# 2. Sum sine components
signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)

# 3. Add noise
# Calibrate noise_sigma using the formula in Critical Details section
signal += noise_function(num_samples)

# 4. RMS normalize
current_rms = np.sqrt(np.mean(signal**2))
signal = signal * (target_rms / current_rms)

# 5. Verify tolerance
assert abs(np.sqrt(np.mean(signal**2)) - target_rms) <= rms_tolerance

# 6. Convert to int16 for WAV
signal_int16 = (signal * 32767).astype(np.int16)

# 7. Convert back to float for STFT (this matches what's in the WAV file)
signal_for_stft = signal_int16.astype(np.float64) / 32767.0
```

**Critical Details:**
1. RMS normalization must occur BEFORE 16-bit quantization. Do NOT apply additional scaling after RMS normalization, as this changes the RMS value.
2. **Noise amplitude calibration**: The noise level must be calibrated so the post-normalization residual passes whatever bounds the test checks. Use this formula:
   ```
   post_normalization_noise_std = noise_sigma × (target_rms / signal_rms_before_norm)
   ```
   For v01: signal_rms_before_norm ≈ 1.414 (sum of 4 unit sines), target_rms=0.15, so noise_sigma=0.1 yields post_normalization_noise_std ≈ 0.0106. The v01 test checks `0.004 ≤ residual_std ≤ 0.02`, but variants may have different bounds or no residual check at all.
3. **STFT signal source - verification contract**: The STFT signal source must match what the test uses for independent verification. This is a contract between test and solution. In v01, the test reads the WAV file, converts to float, and computes STFT, so the pipeline must compute STFT on `signal_int16.astype(float) / 32767.0`. However, variants may use different verification strategies (e.g., regenerate clean float signal, use different quantization, or skip magnitude checks entirely). Always examine the test code to determine what signal it uses for verification, then match that in the pipeline.

### Stage 2: STFT Computation (Python)

**Responsibilities:**
- Compute STFT using scipy.signal.stft
- Extract magnitude (linear or dB scale)
- Export to CSV with specified schema

**Key Parameters:**
- `window`: Window function type ('hann', 'blackman', 'hamming', etc.)
- `nperseg`: Samples per segment
- `noverlap`: Overlap between segments
- `nfft`: FFT size
- `boundary`: Boundary handling (None, 'zeros', 'even', 'odd')
- `padded`: Whether to pad signal
- `return_onesided`: One-sided vs two-sided spectrum
- `magnitude_scale`: 'linear' or 'db'

**Implementation Pattern:**
```python
# IMPORTANT: STFT signal source must match the test's verification strategy
# Examine the test code to determine what signal it uses for independent computation
# Common pattern: compute on WAV-equivalent signal (int16→float)
# Variant possibility: compute on clean float signal
signal_for_stft = signal_int16.astype(np.float64) / 32767.0  # v01 pattern

f, t, Zxx = sps.stft(
    signal_for_stft,
    fs=fs,
    window=window,
    nperseg=nperseg,
    noverlap=noverlap,
    nfft=nfft,
    boundary=boundary,
    padded=padded,
    return_onesided=return_onesided
)

if magnitude_scale == 'linear':
    magnitude = np.abs(Zxx)
elif magnitude_scale == 'db':
    magnitude = 20 * np.log10(np.abs(Zxx) + 1e-10)
```

**CSV Export:**
- Schema varies by task: common formats are `frame,bin,val` or `time,frequency,magnitude`
- One row per bin per frame
- Frame and bin indices are 0-based
- IMPORTANT: magnitude array has shape (n_bins, n_frames), so index as magnitude[bin_idx, frame_idx]
- **Numerical precision**: Use sufficient precision to pass test tolerance checks. Format like `:.10e` or `:.10g` provides ~10 significant digits, which is safe for typical tolerances (rel_tol=1e-6). For tighter tolerances, use `:.15g` or higher.

### Stage 3: Peak Extraction (awk)

**Responsibilities:**
- Read magnitude CSV
- For each frame, identify top-k bins by magnitude
- Apply tie-breaking rules (typically lower bin index wins)
- Output peaks CSV with specified schema

**Key Parameters:**
- `top_k`: Number of peaks to extract per frame
- `tie_break`: Rule for equal magnitudes ('lower_bin', 'higher_bin')
- `output_schema`: Column format (e.g., 'frame,f1_bin,f2_bin,f3_bin')
- `peaks_only_flag`: Environment variable to enable peaks-only mode

**Implementation Pattern:**
```bash
# Process mag.csv with awk
# IMPORTANT: Header must be generated dynamically from top_k to match data columns
awk -F',' -v top_k=3 -v tie_break="lower" '
BEGIN {
    OFS=","
    # Generate header dynamically from top_k
    header = "frame"
    for (i = 1; i <= top_k; i++) {
        header = header ",f" i "_bin"
    }
    print header
    prev_frame = -1
    n = 0
}
NR == 1 { next }  # Skip input header
{
    frame = $1 + 0
    bin_val = $2 + 0
    mag = $3 + 0.0
    
    # Detect frame boundary
    if (frame != prev_frame) {
        if (prev_frame >= 0) {
            emit_peaks(prev_frame)
        }
        n = 0
        prev_frame = frame
    }
    
    # Accumulate bins for current frame
    n++
    frame_bins[n] = bin_val
    frame_mags[n] = mag
}
END {
    if (prev_frame >= 0) {
        emit_peaks(prev_frame)
    }
}

function emit_peaks(frame,    i, j, best, tb, tv, tmp_b, tmp_v) {
    # Copy to sortable arrays
    for (i = 1; i <= n; i++) {
        tb[i] = frame_bins[i]
        tv[i] = frame_mags[i]
    }
    
    # Selection sort: find top-k by magnitude (descending)
    for (i = 1; i <= top_k && i <= n; i++) {
        best = i
        for (j = i + 1; j <= n; j++) {
            if (tv[j] > tv[best]) {
                best = j
            } else if (tv[j] == tv[best] && tie_break == "lower" && tb[j] < tb[best]) {
                best = j
            }
        }
        # Swap
        if (best != i) {
            tmp_b = tb[i]; tb[i] = tb[best]; tb[best] = tmp_b
            tmp_v = tv[i]; tv[i] = tv[best]; tv[best] = tmp_v
        }
    }
    
    # Output top-k bins
    printf "%d", frame
    for (i = 1; i <= top_k; i++) {
        if (i <= n) printf ",%d", tb[i]
        else printf ",0"
    }
    printf "\n"
    
    # Clear arrays
    delete frame_bins
    delete frame_mags
}
' mag.csv > peaks.csv
```

**Performance Note:** For large datasets, the O(n²) selection sort per frame may be slow. Consider using a heap-based approach or limiting the sort to top-k elements only.

## Orchestration Script

The bash script must:
1. Support `PEAKS_ONLY=1` environment variable for reprocessing mode
2. In full mode: run Python script, then extract peaks
3. In peaks-only mode: skip Python, only run awk on existing mag.csv
4. Use `awk` from PATH (not absolute path)
5. Ensure Python script does NOT write peaks.csv

**Pattern:**
```bash
#!/bin/bash
set -e

extract_peaks() {
    if [ ! -f /app/data/mag.csv ]; then
        echo "Error: mag.csv not found" >&2
        exit 1
    fi
    
    # awk command here (see Stage 3)
    awk ... /app/data/mag.csv > /app/data/peaks.csv
}

if [ "${PEAKS_ONLY}" = "1" ]; then
    echo "PEAKS_ONLY mode"
    extract_peaks
    exit 0
fi

# Full pipeline
python3 /app/audioproc.py
extract_peaks
```

## Variation Handling

### Synthesis Parameters

**What changes:**
- Sample rate (e.g., 12kHz → 16kHz or 44.1kHz)
- Duration (e.g., 2.5s → 3s or 5s)
- Frequency set (e.g., 4 tones → 5 tones, different frequencies)
- Noise type/amplitude (Gaussian, uniform, different sigma)
- RMS target and tolerance

**What stays invariant:**
- Mono channel
- 16-bit PCM quantization
- RMS normalization before quantization
- Reproducible synthesis (use fixed random seed)

**Adaptation strategy:**
- Read parameters from task specification
- Adjust time vector generation: `num_samples = int(fs * duration)`
- Adjust frequency loop
- Adjust noise generation using calibration formula: `noise_sigma = desired_residual_std × (signal_rms_before_norm / target_rms)`
- Keep RMS normalization logic unchanged

### STFT Configuration

**What changes:**
- Window type ('hann', 'blackman', 'hamming', etc.)
- nperseg, noverlap, nfft values
- Boundary handling (None, 'zeros', 'even', 'odd')
- Padded flag
- One-sided vs two-sided
- Magnitude scaling (linear vs dB)
- CSV schema (column names and order)

**What stays invariant:**
- Use scipy.signal.stft
- Export magnitude (not phase)
- One row per bin per frame
- 0-based indexing for frames and bins

**Adaptation decisions:**
- **STFT input signal**: Match the test's verification strategy. Common pattern: compute on WAV-equivalent signal (int16→float). Variant possibility: compute on clean float signal. Examine test code to determine which signal the test uses for independent computation.

**Adaptation strategy:**
- Pass parameters directly to `sps.stft()`
- Adjust magnitude computation based on scale
- Adjust CSV header and column order based on schema
- For two-sided spectrum, bin indices may be negative or centered

### Peak Extraction Logic

**What changes:**
- top_k value (e.g., 3 → 5 or 10)
- Tie-breaking rule (lower bin vs higher bin)
- Frame grouping (per-frame vs grouped across multiple frames)
- Output columns (e.g., include magnitude values)
- Mode flags (PEAKS_ONLY, different environment variables)

**What stays invariant:**
- Use awk (mawk or gawk) for peak selection
- Read from mag.csv, write to peaks.csv
- Peaks ordered by magnitude (descending)
- Python does not write peaks.csv

**Adaptation strategy:**
- Adjust `top_k` variable in awk
- Adjust tie-breaking comparison in selection sort
- Adjust output format string
- Adjust environment variable check in bash script

## Common Pitfalls

1. **RMS normalization after scaling**: Do not normalize to max before RMS normalization. RMS normalize first, then quantize.

2. **STFT signal source mismatch**: The STFT signal source must match the test's verification strategy. In v01, the test reads WAV and computes STFT, so use `signal_int16.astype(float) / 32767.0`. But variants may use different verification (e.g., clean float signal). Always examine test code to determine what signal it uses.

3. **Noise amplitude not calibrated**: Use the calibration formula: `post_normalization_noise_std = noise_sigma × (target_rms / signal_rms_before_norm)`. For v01, noise_sigma=0.1 yields residual_std≈0.0106, which passes the test's `0.004 ≤ residual_std ≤ 0.02` check. Variants may have different bounds.

4. **Magnitude CSV schema mismatch**: Verify exact column names and order from task spec. Common variants: `frame,bin,val` vs `time,frequency,magnitude`.

5. **Magnitude array indexing**: scipy.signal.stft returns magnitude with shape (n_bins, n_frames). When exporting to CSV with frame-major order, index as `magnitude[bin_idx, frame_idx]`.

6. **awk array indexing**: awk arrays are 1-indexed by convention. Use consistent indexing throughout.

7. **Frame boundary detection in awk**: Check `frame != prev_frame` to detect boundaries. Initialize `prev_frame = -1` to handle first frame.

8. **Tie-breaking consistency**: When magnitudes are equal, tie-breaking must be deterministic. Specify rule clearly (e.g., "lower bin index wins").

9. **PEAKS_ONLY mode**: Must skip Python script entirely. Only read existing mag.csv and write peaks.csv.

10. **awk invocation**: Use `awk` from PATH, not `/usr/bin/awk` or absolute path.

## Testing Checklist

- [ ] WAV file: correct sample rate, duration, channels, bit depth
- [ ] WAV RMS: within tolerance of target
- [ ] Residual std: calibrated using formula, passes test-specific bounds
- [ ] mag.csv: correct schema, correct number of frames and bins
- [ ] mag.csv: values match STFT computed from test's verification signal (check test code)
- [ ] peaks.csv: correct schema, correct number of rows (one per frame)
- [ ] peaks.csv: top-k bins are correct (verify manually for first frame)
- [ ] PEAKS_ONLY mode: works without regenerating audio
- [ ] Full pipeline: produces all three output files
- [ ] Python script: does not write peaks.csv
- [ ] Bash script: uses `awk` from PATH

## Example: v01 Concrete Instance

**Synthesis:**
- fs=12000, duration=2.5s
- frequencies=[180, 360, 540, 720] Hz
- Gaussian noise (sigma=0.1, calibrated using formula: 0.1 × (0.15/1.414) ≈ 0.0106)
- target_rms=0.15, tolerance=0.002
- Pipeline: generate float signal → add noise → RMS normalize → quantize to int16 for WAV → convert back to float for STFT (matches v01 test's verification strategy)

**STFT:**
- window='blackman', nperseg=768, noverlap=576, nfft=1024
- boundary=None, padded=False, return_onesided=True
- Linear magnitude
- Schema: frame,bin,val
- Computed on quantized-then-converted signal (v01-specific: matches test's WAV-based verification)

**Peaks:**
- top_k=3
- Tie-break: lower bin index
- Schema: frame,f1_bin,f2_bin,f3_bin (generated dynamically from top_k)
- PEAKS_ONLY=1 mode supported

**Expected output:**
- 153 frames, 513 bins (nfft/2 + 1 for one-sided)
- Top 3 bins typically at indices 15, 31, 46 (corresponding to 180, 360, 540 Hz)
- Residual std ≈ 0.0106 (passes v01's [0.004, 0.02] check)
- Magnitude values match STFT of WAV signal within tolerance (v01-specific verification)

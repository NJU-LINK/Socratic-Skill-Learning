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
signal += noise_function(num_samples)

# 4. RMS normalize
current_rms = np.sqrt(np.mean(signal**2))
signal = signal * (target_rms / current_rms)

# 5. Verify tolerance
assert abs(np.sqrt(np.mean(signal**2)) - target_rms) <= rms_tolerance

# 6. Keep clean float signal for STFT (canonical representation)
signal_float = signal.copy()

# 7. Convert to int16 for WAV (lossy encoding)
signal_int16 = (signal * 32767).astype(np.int16)
```

**Critical Details:**
1. RMS normalization must occur BEFORE 16-bit quantization. Do NOT apply additional scaling after RMS normalization, as this changes the RMS value.
2. Keep the clean float signal for STFT computation. The float signal is the canonical representation; int16 is a lossy encoding. Compute STFT on the float signal BEFORE quantization to avoid introducing quantization noise into magnitude values.

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
# IMPORTANT: Compute STFT on the clean float signal, NOT the int16-quantized signal
# The float signal is canonical; int16 introduces quantization noise
f, t, Zxx = sps.stft(
    signal_float,  # Clean float signal from synthesis stage
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
- Adjust noise generation
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

2. **STFT on quantized signal**: Do NOT compute STFT on `signal_int16 / 32767.0`. This introduces quantization noise. Compute STFT on the clean float signal BEFORE int16 quantization. The float signal is canonical; int16 is a lossy encoding.

3. **Magnitude CSV schema mismatch**: Verify exact column names and order from task spec. Common variants: `frame,bin,val` vs `time,frequency,magnitude`.

4. **awk array indexing**: awk arrays are 1-indexed by convention. Use consistent indexing throughout.

5. **Frame boundary detection in awk**: Check `frame != prev_frame` to detect boundaries. Initialize `prev_frame = -1` to handle first frame.

6. **Tie-breaking consistency**: When magnitudes are equal, tie-breaking must be deterministic. Specify rule clearly (e.g., "lower bin index wins").

7. **PEAKS_ONLY mode**: Must skip Python script entirely. Only read existing mag.csv and write peaks.csv.

8. **awk invocation**: Use `awk` from PATH, not `/usr/bin/awk` or absolute path.

## Testing Checklist

- [ ] WAV file: correct sample rate, duration, channels, bit depth
- [ ] WAV RMS: within tolerance of target
- [ ] mag.csv: correct schema, correct number of frames and bins
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
- Gaussian noise (sigma=0.01)
- target_rms=0.15, tolerance=0.002
- Pipeline: generate float signal → RMS normalize → compute STFT on float → quantize to int16 for WAV

**STFT:**
- window='blackman', nperseg=768, noverlap=576, nfft=1024
- boundary=None, padded=False, return_onesided=True
- Linear magnitude
- Schema: frame,bin,val
- Computed on clean float signal (not quantized)

**Peaks:**
- top_k=3
- Tie-break: lower bin index
- Schema: frame,f1_bin,f2_bin,f3_bin (generated dynamically from top_k)
- PEAKS_ONLY=1 mode supported

**Expected output:**
- 153 frames, 513 bins (nfft/2 + 1 for one-sided)
- Top 3 bins typically at indices 15, 31, 46 (corresponding to 180, 360, 540 Hz)
- Magnitudes computed from clean float signal (no quantization noise)

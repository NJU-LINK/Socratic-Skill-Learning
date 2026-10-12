---
name: audio-synth-stft-peaks
description: >
  Build a three-stage audio processing pipeline: (1) synthesize a deterministic
  mono WAV from summed sine tones plus noise with RMS normalization, (2) compute
  STFT magnitude via scipy and export to CSV, (3) extract top-k spectral peaks
  per frame using awk. Supports a PEAKS_ONLY mode that runs only the awk stage.
---

# Audio Synth → STFT → Peaks Pipeline

## Architecture (hard invariants)

The pipeline has exactly three stages with a strict ownership boundary:

| Stage | Tool | Inputs | Outputs |
|-------|------|--------|---------|
| 1. Synthesize | Python (`audioproc.py`) | Parameters from task.yaml | `data/clip.wav` |
| 2. STFT | Python (`audioproc.py`) | `data/clip.wav` | `data/mag.csv` |
| 3. Peak extraction | awk (via `run_audio_pipeline.sh`) | `data/mag.csv` | `data/peaks.csv` |

**Critical constraint:** `audioproc.py` must NEVER produce `peaks.csv`. The peak extraction is always done by awk invoked from the shell script.

## Directory layout

```
/app/
├── audioproc.py
├── run_audio_pipeline.sh
└── data/
    ├── clip.wav
    ├── mag.csv
    └── peaks.csv
```

## Stage 1: WAV Synthesis

Read parameters from `task.yaml` (the `synthesis_signal_parameters` axis):

- **Sample rate** (Hz)
- **Duration** (seconds)
- **Frequencies** (list of Hz values for sine tones)
- **Noise** (Gaussian noise standard deviation)
- **RMS target** (float, with tolerance ±tol)

### Algorithm

```python
n_samples = int(sample_rate * duration)
t = np.arange(n_samples) / sample_rate

# Sum of sines
signal = sum(np.sin(2 * pi * f * t) for f in frequencies)

# Add Gaussian noise
signal += rng.normal(0, noise_std, size=n_samples)

# RMS normalize BEFORE quantization
rms = sqrt(mean(signal**2))
signal = signal * (rms_target / rms)

# Verify RMS within tolerance
assert abs(sqrt(mean(signal**2)) - rms_target) <= rms_tolerance

# Quantize to int16 AFTER normalization
int16_signal = clip(signal * 32767, -32768, 32767).astype(int16)
wavfile.write(path, sample_rate, int16_signal)
```

**Key pitfall:** Normalize the float signal first, then quantize. Do NOT quantize first and then normalize.

### Noise level selection (critical)

When the task says "Add Gaussian noise" without specifying the std, the noise_std
must be chosen so the residual after tone-fitting falls in [0.004, 0.02].

After RMS normalization, the effective noise floor is:

    effective_noise ≈ noise_std × rms_target / sqrt(rms_sines² + noise_std²)

where rms_sines ≈ sqrt(N_tones × 0.5) for unit-amplitude sines.

For 4 sines at rms_target=0.15: rms_sines = sqrt(2) ≈ 1.414
- noise_std=0.01 → effective_noise ≈ 0.001 (TOO LOW, fails test)
- noise_std=0.1  → effective_noise ≈ 0.011 (safe, in range)
- noise_std=0.2  → effective_noise ≈ 0.021 (borderline)

Safe range for this task: noise_std ∈ [0.05, 0.15]. Default to 0.1.

## Stage 2: STFT Computation

Read parameters from `task.yaml` (the `stft_configuration` axis):

- **Window type** (e.g., `'blackman'`, `'hann'`, `'hamming'`)
- **nperseg** (samples per segment)
- **noverlap** (overlap between segments)
- **nfft** (FFT size)
- **boundary** (e.g., `None`)
- **padded** (bool)
- **return_onesided** (bool, typically `True`)

### Algorithm

```python
f, t, Zxx = scipy.signal.stft(
    signal, fs=sample_rate, window=window_type,
    nperseg=nperseg, noverlap=noverlap, nfft=nfft,
    boundary=boundary, padded=padded, return_onesided=return_onesided
)
mag = np.abs(Zxx)  # LINEAR magnitude, NOT dB, NOT power
```

### CSV export

Schema: `frame,bin,val` (one row per bin per frame).

- Iterate frames in outer loop, bins in inner loop
- Use sufficient precision (e.g., `:.10e`) to avoid losing peak discrimination

### Expected shape

For `return_onesided=True`: number of frequency bins = `nfft // 2 + 1`.
Number of frames = `floor((n_samples - nperseg) / (nperseg - noverlap)) + 1` when `boundary=None, padded=False`.

## Stage 3: Peak Extraction with awk

Read parameters from `task.yaml` (the `peak_extraction_logic` axis):

- **top_k** (number of peaks per frame)
- **Output column names** (e.g., `f1_bin,f2_bin,f3_bin`)
- **Tie-breaking rule** (typically: first encountered wins, i.e., lower bin index)

### Shell script structure

```bash
#!/usr/bin/env bash
set -euo pipefail

TOP_K="${TOP_K:-3}"  # configurable

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    # Skip Python, just run awk on existing mag.csv
    :
else
    python3 /app/audioproc.py
fi

awk -v TOP_K="${TOP_K}" -F, '...' /app/data/mag.csv > /app/data/peaks.csv
```

### awk top-k selection pattern

Use selection-sort: iterate TOP_K times, each time finding the maximum among unused bins.

```awk
BEGIN {
    OFS = ","
    # Build header dynamically
    header = "frame"
    for (j = 1; j <= TOP_K; j++) header = header ",f" j "_bin"
    print header
    nbins = 0; cur_frame = -1
}
NR == 1 { next }  # skip CSV header
{
    frame = $1 + 0; bin = $2 + 0; val = $3 + 0
    if (cur_frame >= 0 && frame != cur_frame) {
        process_frame()
        delete bins; delete vals; nbins = 0
    }
    cur_frame = frame
    bins[nbins] = bin; vals[nbins] = val; nbins++
}
END { if (nbins > 0) process_frame() }

function process_frame(    j, i, max_idx, max_val, line) {
    delete used
    line = cur_frame
    for (j = 1; j <= TOP_K; j++) {
        max_val = -1; max_idx = -1
        for (i = 0; i < nbins; i++) {
            if (!(i in used) && vals[i] > max_val) {
                max_val = vals[i]; max_idx = i
            }
        }
        if (max_idx >= 0) {
            used[max_idx] = 1
            line = line "," bins[max_idx]
        } else {
            line = line ",0"
        }
    }
    print line
}
```

**Tie-breaking note:** When two bins have equal magnitude, the one encountered first (lower index in the array, which corresponds to the order in mag.csv) wins because `>` is strict. This gives lower-bin-index preference, which is the typical default.

## PEAKS_ONLY mode

When `PEAKS_ONLY=1` is set as an environment variable:
- The shell script must NOT run `audioproc.py`
- It must read the existing `data/mag.csv` and produce `data/peaks.csv` via awk
- This allows re-running peak extraction without recomputing the STFT

## Verification checklist

1. **WAV**: correct sample rate, duration, mono, int16 PCM
2. **RMS**: within tolerance of target (on float signal before quantization)
3. **mag.csv**: correct header, correct number of rows = frames × bins, linear magnitude
4. **peaks.csv**: correct header, correct number of frames, bins in descending magnitude order
5. **Peak bins**: correspond to expected frequency locations (bin ≈ freq × nfft / fs)
6. **PEAKS_ONLY**: works independently, produces identical peaks.csv
7. **awk invocation**: uses `awk` (from PATH), not an absolute path

## Variant adaptation

The assets (`assets/audioproc.py` and `assets/run_audio_pipeline.sh`) are reference implementations for v01 with hardcoded parameters. For variants, you must:

1. **Read `task.yaml`** to extract the actual parameters for each axis
2. **Adapt the assets** by replacing hardcoded values with the variant-specific parameters

### What to adapt in `audioproc.py`:

- **Synthesis parameters**: `SAMPLE_RATE`, `DURATION`, `FREQUENCIES`, `NOISE_STD`, `RMS_TARGET`, `RMS_TOL`
- **STFT parameters**: `STFT_FS`, `STFT_WINDOW`, `STFT_NPERSEG`, `STFT_NOVERLAP`, `STFT_NFFT`
- **Noise level**: Recalculate using the formula in "Noise level selection" if the number of tones or RMS target changes

### What to adapt in `run_audio_pipeline.sh`:

- **TOP_K default**: Change `${TOP_K:-3}` to match the variant's top-k requirement
- **awk logic**: The selection-sort pattern generalizes to any TOP_K via the `-v TOP_K=` parameter

### Example adaptation workflow:

```bash
# 1. Read task.yaml to get parameters
# 2. Copy assets to /app
cp assets/audioproc.py /app/
cp assets/run_audio_pipeline.sh /app/
# 3. Edit the files to match task.yaml parameters
# 4. Run the pipeline
bash /app/run_audio_pipeline.sh
```

The architecture (three stages, ownership boundary, PEAKS_ONLY mode) is invariant across all variants. Only the parameter values change.

## Reference solution

See `assets/audioproc.py` and `assets/run_audio_pipeline.sh` for the complete v01 implementation.

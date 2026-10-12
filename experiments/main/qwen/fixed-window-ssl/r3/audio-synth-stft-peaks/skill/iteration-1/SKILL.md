---
name: audio-synth-stft-peaks
description: >
  Build an audio processing pipeline that synthesizes a WAV file from summed
  sine tones with noise, computes an STFT using scipy, and extracts the top-k
  spectral peaks per frame using awk. Handles parameterized synthesis (sample
  rate, duration, frequencies, RMS normalization), configurable STFT (window
  type, segment size, overlap, FFT size, boundary handling), and flexible peak
  extraction (top-k, output schema, PEAKS_ONLY mode).
---

# Audio Synth + STFT Peaks Pipeline

## Architecture

The pipeline has three stages with clear separation of concerns:

1. **Python stage** (`audioproc.py`): Synthesizes WAV + computes STFT magnitude
2. **Shell stage** (`run_audio_pipeline.sh`): Orchestrates the pipeline
3. **Awk stage** (invoked by shell script): Extracts top-k peaks per frame

**Critical constraint**: Python produces only `clip.wav` and `mag.csv`. The shell/awk stage produces `peaks.csv`. Never write `peaks.csv` from Python.

## Stage 1: Audio Synthesis

### Parameters (from task.yaml)
- `sr`: Sample rate (e.g., 12000 Hz)
- `duration`: Signal length in seconds (e.g., 2.5)
- `freqs`: List of sine frequencies (e.g., [180, 360, 540, 720])
- `target_rms`: Target RMS after normalization (e.g., 0.15)
- `rms_tol`: Tolerance for RMS verification (e.g., ±0.002)
- `noise_std`: Standard deviation of Gaussian noise (e.g., 0.01)
- `seed`: Random seed for reproducibility (e.g., 42)

### RMS Normalization Semantics

**CRITICAL**: The task says "RMS-normalize to target" then "normalize before 16-bit quantization". This is **one normalization step**, not two.

```python
# CORRECT: RMS normalize once, then quantize directly
signal = signal * (target_rms / current_rms)
signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)
```

**WRONG** (double normalization bug):
```python
signal = signal * (target_rms / current_rms)  # RMS normalize
peak = np.max(np.abs(signal))
signal_int16 = np.int16(signal / peak * 32767 * 0.95)  # Peak normalize AGAIN - BUG!
```

The second normalization destroys the RMS target. With RMS=0.15, the signal peak is well under 1.0, so `signal * 32767` fits safely in int16 range.

### WAV Output
- Format: PCM int16, mono
- Use `wave` module or `scipy.io.wavfile.write`
- Verify RMS after quantization: `rms_int16 / 32767.0` should match `target_rms ± rms_tol`

## Stage 2: STFT Computation

### Parameters (from task.yaml)
- `fs`: Sample rate (must match synthesis)
- `window`: Window function (e.g., 'blackman', 'hann')
- `nperseg`: Samples per segment (e.g., 768)
- `noverlap`: Overlap between segments (e.g., 576)
- `nfft`: FFT size (e.g., 1024)
- `boundary`: Boundary handling (e.g., None, 'even', 'odd')
- `padded`: Whether to pad signal (e.g., False)
- `return_onesided`: One-sided vs two-sided (e.g., True for real signals)

### scipy.signal.stft Call
```python
f, t, Zxx = sps.stft(
    signal,
    fs=fs,
    window=window,
    nperseg=nperseg,
    noverlap=noverlap,
    nfft=nfft,
    boundary=boundary,
    padded=padded,
    return_onesided=return_onesided
)
magnitude = np.abs(Zxx)
```

### CSV Output Schema
```
frame,bin,val
0,0,1.889572595e-05
0,1,2.051781933e-05
...
```

- One row per (frame, bin) pair
- `frame`: 0-indexed frame number
- `bin`: Frequency bin index (0 to nfft//2 for one-sided)
- `val`: Linear magnitude (not dB) unless task specifies otherwise

**Frequency resolution**: `bin_freq = bin * (fs / nfft)` Hz

## Stage 3: Peak Extraction with awk

### Parameters (from task.yaml)
- `top_k`: Number of peaks per frame (e.g., 3)
- Output columns: `frame,f1_bin,f2_bin,...,fk_bin` (descending order)
- Bin indexing: 0-based

### Robust Top-k Algorithm

**Initialization trap**: When tracking top-k incrementally, uninitialized slots default to 0. This works for non-negative magnitudes but fails for:
- Negative values (e.g., raw real-part instead of magnitude)
- Fewer than k bins with value > 0 (bin 0 becomes a false positive)

**Safe pattern**: Track count per frame and only compare against filled slots.

```awk
BEGIN { FS=","; OFS="," }
NR == 1 { next }  # skip header
{
    frame = $1 + 0
    bin = $2 + 0
    val = $3 + 0.0
    
    # Track top 3 with proper initialization check
    if (!(frame in n1) || val > top1[frame]) {
        top3[frame] = top2[frame]; top3_bin[frame] = top2_bin[frame]
        top2[frame] = top1[frame]; top2_bin[frame] = top1_bin[frame]
        top1[frame] = val; top1_bin[frame] = bin
        n1[frame] = 1
    } else if (!(frame in n2) || val > top2[frame]) {
        top3[frame] = top2[frame]; top3_bin[frame] = top2_bin[frame]
        top2[frame] = val; top2_bin[frame] = bin
        n2[frame] = 1
    } else if (!(frame in n3) || val > top3[frame]) {
        top3[frame] = val; top3_bin[frame] = bin
        n3[frame] = 1
    }
    
    if (!(frame in seen)) {
        seen[frame] = 1
        frames[++nf] = frame
    }
}
END {
    # Sort frames numerically
    for (i = 1; i <= nf; i++) {
        for (j = i+1; j <= nf; j++) {
            if (frames[i] > frames[j]) {
                tmp = frames[i]; frames[i] = frames[j]; frames[j] = tmp
            }
        }
    }
    
    print "frame,f1_bin,f2_bin,f3_bin"
    for (i = 1; i <= nf; i++) {
        f = frames[i]
        printf "%d,%d,%d,%d\n", f, top1_bin[f], top2_bin[f], top3_bin[f]
    }
}
```

**Alternative (safer but more memory-intensive)**: Store all values per frame, then sort in END block. Use this for variants with negative values or complex tie-breaking rules.

### Invocation
```bash
awk -F',' '...' /app/data/mag.csv > /app/data/peaks.csv
```

**CRITICAL**: Use `awk` from PATH, not an absolute path like `/usr/bin/awk`.

## Shell Script: run_audio_pipeline.sh

### PEAKS_ONLY Mode
When `PEAKS_ONLY=1` is set:
- Read existing `mag.csv`
- Produce `peaks.csv` via awk
- **Skip** synthesis and STFT computation
- Exit immediately after peak extraction

```bash
if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    # Peak extraction only
    awk '...' "${MAG_CSV}" > "${PEAKS_CSV}"
    exit 0
fi
```

### Full Pipeline
```bash
# Step 1 & 2: Python does synthesis + STFT
python3 /app/audioproc.py

# Step 3: Awk does peak extraction
awk '...' "${MAG_CSV}" > "${PEAKS_CSV}"
```

## Directory Structure
```
/app/
├── audioproc.py
├── run_audio_pipeline.sh
└── data/
    ├── clip.wav
    ├── mag.csv
    └── peaks.csv
```

## Verification Checklist

- [ ] WAV: mono, int16, correct sample rate and duration
- [ ] WAV RMS: `rms_int16 / 32767.0` matches `target_rms ± rms_tol`
- [ ] STFT: correct parameters, one-sided if specified
- [ ] mag.csv: schema `frame,bin,val`, linear magnitude
- [ ] peaks.csv: schema `frame,f1_bin,...,fk_bin`, descending order
- [ ] Peak correctness: verify top-k bins match Python's `np.argsort`
- [ ] PEAKS_ONLY mode: works independently, skips synthesis/STFT
- [ ] awk invocation: uses `awk` from PATH, not absolute path

## Common Pitfalls

1. **Double normalization**: RMS normalize once, then quantize directly. Don't peak-normalize after RMS.
2. **awk initialization**: Check if slot is filled before comparing, especially for non-magnitude values.
3. **STFT signal source**: Use the float signal (before int16 quantization) for STFT computation.
4. **Frame ordering**: awk processes rows in file order, but sort frames numerically in END block for safety.
5. **Bin indexing**: 0-based in Python/awk output. Frequency = `bin * (fs / nfft)`.

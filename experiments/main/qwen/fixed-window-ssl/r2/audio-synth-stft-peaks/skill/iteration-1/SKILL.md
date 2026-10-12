---
name: audio-synth-stft-peaks
description: >
  Build a deterministic audio-processing pipeline: synthesize a mono WAV from
  summed sine tones + noise with RMS normalization, compute STFT magnitude via
  scipy, and extract top-k spectral peaks per frame using awk. The pipeline
  consists of a Python script (WAV synthesis + STFT), a Bash orchestrator with
  PEAKS_ONLY mode, and an inline awk program for peak extraction.
---

# Audio Synth → STFT → Peaks Pipeline

## Architecture Overview

The pipeline has three stages orchestrated by a Bash script:

1. **Python (`audioproc.py`)** — Synthesizes WAV and computes STFT magnitude CSV
2. **Bash (`run_audio_pipeline.sh`)** — Orchestrates the pipeline; supports `PEAKS_ONLY=1`
3. **awk (inline in shell)** — Extracts top-k spectral peaks per frame from magnitude CSV

### File Layout
```
data/
├── clip.wav      # Synthesized audio (PCM int16)
├── mag.csv       # STFT linear magnitude: frame,bin,val
└── peaks.csv     # Top-k peaks: frame,f1_bin,f2_bin,...,fk_bin
audioproc.py
run_audio_pipeline.sh
```

---

## Stage 1: WAV Synthesis (Python)

### Core Pattern
```python
# 1. Time vector
n_samples = int(sr * duration)
t = np.arange(n_samples) / sr

# 2. Sum sine tones
signal = sum(np.sin(2 * np.pi * f * t) for f in freqs)

# 3. Add noise
noise = rng.standard_normal(n_samples)  # or uniform, etc.
noisy = signal + noise

# 4. RMS-normalize to target (THIS IS THE ONLY NORMALIZATION)
rms = np.sqrt(np.mean(noisy**2))
noisy = noisy * (rms_target / rms)

# 5. Quantize to int16 directly — NO peak normalization
audio_int16 = (noisy * 32767).astype(np.int16)
wavfile.write(path, sr, audio_int16)
```

### CRITICAL: Single Normalization Rule
The RMS normalization to target is the **only** normalization before int16 quantization. Do **NOT** apply a second peak normalization (dividing by max abs value) after RMS normalization — this destroys the RMS target. With RMS=0.15, signal peaks are well under 1.0, so clipping is not a concern.

### Verification
After writing, read back the WAV and verify RMS:
```python
sr2, data2 = wavfile.read(path)
rms_readback = np.sqrt(np.mean((data2 / 32767.0)**2))
# Should match rms_target within tolerance (e.g., ±0.002)
```

---

## Stage 2: STFT Computation (Python)

### scipy.signal.stft Interface
```python
from scipy.signal import stft

f, t, Zxx = stft(audio, fs=fs, window=window_type,
                  nperseg=nperseg, noverlap=noverlap, nfft=nfft,
                  boundary=boundary, padded=padded,
                  return_onesided=onesided)
```

**Key facts:**
- Returns shape `(n_freq_bins, n_time_frames)` — iterate as `Zxx[bin_idx, frame_idx]`
- For `return_onesided=True`: `n_freq_bins = nfft // 2 + 1`
- Frequency resolution: `bin_freq = bin_idx * fs / nfft`
- `f` array gives the center frequency of each bin
- Magnitude: `np.abs(Zxx)` for linear magnitude; `20 * np.log10(...)` for dB

### CSV Export
Schema: `frame,bin,val` — one row per (frame, bin) pair. Iterate frames in outer loop, bins in inner loop:
```python
for frame_idx in range(n_frames):
    for bin_idx in range(n_bins):
        write(f"{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}")
```

---

## Stage 3: Peak Extraction (awk)

### Portable Top-k Algorithm
The awk script must work with both **mawk** and **gawk**. Avoid gawk-specific features like `asorti()`.

**Frame-transition approach** (exploits the fact that mag.csv rows are ordered by frame, then by bin within frame):

```awk
BEGIN { FS=","; OFS=","; reset_topk() }
NR == 1 { next }  # skip header
{
    frame = $1 + 0; bin = $2 + 0; val = $3 + 0

    # Frame transition: flush previous frame
    if (prev_frame >= 0 && frame != prev_frame) {
        print prev_frame, top bins...
        reset_topk()
    }
    prev_frame = frame

    # Insert into top-k with tie-breaking (lower bin wins)
    update_topk(bin, val)
}
END { if (prev_frame >= 0) print prev_frame, top bins... }
```

### Tie-breaking Rule
When two bins have equal magnitude, the **lower bin index** wins. Implement as:
```
if (val > top_val || (val == top_val && bin < top_bin))
```
This ensures deterministic results regardless of input row order.

### Top-k Insertion Logic (for k=3)
```awk
if (val > f1_val || (val == f1_val && f1_bin >= 0 && bin < f1_bin)) {
    f3 = f2; f2 = f1; f1 = (val, bin)
} else if (val > f2_val || (val == f2_val && f2_bin >= 0 && bin < f2_bin)) {
    f3 = f2; f2 = (val, bin)
} else if (val > f3_val || (val == f3_val && f3_bin >= 0 && bin < f3_bin)) {
    f3 = (val, bin)
}
```

Initialize all values to `-1` so the first bin always enters (any non-negative magnitude > -1).

---

## Bash Orchestrator

### PEAKS_ONLY Mode
When `PEAKS_ONLY=1` is set, the script must:
1. Read existing `mag.csv`
2. Run awk to produce `peaks.csv`
3. Exit without running Python

```bash
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    { echo "header"; extract_peaks mag.csv; } > peaks.csv
    exit 0
fi
```

### Important Constraints
- Invoke awk as `awk` (via PATH), never with an absolute path
- Do NOT write `peaks.csv` from Python — only from awk
- `audioproc.py` should only produce `clip.wav` and `mag.csv`

---

## Parameterization Axes (Family Variants)

### synthesis_signal_parameters
| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Sample rate | 12000 Hz | Any reasonable rate (8000–48000) |
| Duration | 2.5 s | Any positive duration |
| Frequencies | [180, 360, 540, 720] Hz | Any set of sine frequencies |
| Tone count | 4 | Variable |
| Noise type | Gaussian (standard normal) | May change distribution |
| RMS target | 0.15 | Any value where peaks < 1.0 |
| Seed | 42 | Any integer |

### stft_configuration
| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Window | 'blackman' | 'hann', 'hamming', 'blackman', etc. |
| nperseg | 768 | Any valid segment length |
| noverlap | 576 | Must be < nperseg |
| nfft | 1024 | Typically >= nperseg |
| boundary | None | None or 'zeros' etc. |
| padded | False | True or False |
| return_onesided | True | True or False |
| Magnitude scaling | Linear | May use dB or other |

### peak_extraction_logic
| Parameter | v01 Default | Variant Range |
|-----------|-------------|---------------|
| Top-k | 3 | Any positive integer |
| Tie-breaking | Lower bin wins | May vary |
| Output columns | frame,f1_bin,...,fk_bin | May include values |
| Indexing | 0-based | May be 1-based |

---

## Adaptation Checklist for New Variants

1. **Read the task spec** for concrete parameter values
2. **Update `audioproc.py`** with new synthesis parameters and STFT config
3. **Update awk** if top-k changes or output schema changes
4. **Verify**:
   - WAV RMS matches target (read back and check)
   - STFT shape matches expected (n_bins × n_frames)
   - awk peaks match Python-computed peaks (cross-validate)
   - PEAKS_ONLY mode works independently
5. **Check portability**: awk must not use gawk-only features unless spec allows

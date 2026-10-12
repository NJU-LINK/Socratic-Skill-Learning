---
name: audio-synth-stft-peaks
description: >
  Reusable 3-stage audio processing pipeline: deterministic WAV synthesis
  (scipy), STFT magnitude computation (scipy.signal.stft), and shell/awk-based
  spectral peak extraction. Parameterized across synthesis signal parameters,
  STFT configuration, and peak extraction logic.
---

# Audio Synth → STFT → Peaks Pipeline

## Pipeline Architecture

The pipeline has exactly **three stages** with strict separation of concerns:

```
Stage 1+2 (Python)  →  clip.wav + mag.csv
Stage 3 (awk)       →  peaks.csv
Orchestrator (bash) →  run_audio_pipeline.sh
```

### Invariants (family-wide)

| Property | Invariant |
|----------|-----------|
| Stage 1+2 language | Python with scipy |
| Stage 3 language | awk (mawk or gawk via PATH) |
| Orchestrator | Bash script |
| Python NEVER writes peaks.csv | peaks.csv is exclusively awk's output |
| Intermediate format | CSV with header row |
| Reproducibility | Fixed random seed for noise |
| PEAKS_ONLY mode | Shell-only; reads existing mag.csv, runs awk, exits |

### Variation Axes (from spec.yaml)

1. **synthesis_signal_parameters**: sample rate, duration, number of tones, frequency set, amplitude envelope, noise distribution/seed, RMS normalization target
2. **stft_configuration**: window type, nperseg, noverlap, nfft, boundary handling, padded flag, magnitude scaling (linear vs dB), CSV schema
3. **peak_extraction_logic**: top-k value, tie-breaking rule, frame grouping strategy, output column names, awk implementation details, mode flags

## Stage 1: WAV Synthesis

### Algorithm
1. Generate time vector: `t = np.arange(n_samples) / fs` where `n_samples = int(fs * duration)`
2. Sum sine tones: `signal = Σ sin(2π * f_i * t)` for each frequency f_i
3. Add Gaussian noise with fixed seed: `rng = np.random.RandomState(seed); signal += rng.randn(n_samples)`
4. RMS-normalize on float64 BEFORE quantization: `signal *= (target_rms / np.sqrt(np.mean(signal**2)))`
5. Quantize to int16: `np.clip(signal * 32767, -32768, 32767).astype(np.int16)`
6. Write with `scipy.io.wavfile.write(path, fs, audio_int16)`

### Critical: Normalization Order
Normalize on **float64** first, then quantize to int16. Quantizing first loses precision and shifts the RMS.

### Expected RMS Verification
After normalization, the float signal RMS should equal the target within quantization error (~0.002 tolerance for int16).

## Stage 2: STFT Computation

### scipy.signal.stft Call Pattern
```python
f_bins, t_frames, Zxx = stft(
    signal,
    fs=fs,
    window=window_type,     # e.g. 'blackman', 'hann'
    nperseg=nperseg,
    noverlap=noverlap,
    nfft=nfft,
    boundary=None,          # or 'zeros', 'even', etc.
    padded=False,           # or True
    return_onesided=True,   # True for real signals
)
```

### Output Shape
- `Zxx.shape = (n_bins, n_frames)`
- For `return_onesided=True`: `n_bins = nfft // 2 + 1`
- For `boundary=None, padded=False`: `n_frames = (n_samples - nperseg) // (nperseg - noverlap) + 1`

### Magnitude Extraction
**Zxx is complex-valued.** Always take `mag = np.abs(Zxx)` before export.

### Bin Frequency Resolution
`df = fs / nfft` Hz per bin. Tone at frequency f appears near bin `round(f / df)`.

### CSV Export
Frame-major order (outer loop = frames, inner loop = bins) for efficient awk processing:
```
frame,bin,val
0,0,<magnitude>
0,1,<magnitude>
...
```

## Stage 3: AWK Peak Extraction

### Algorithm: Streaming Top-K via Insertion
Since mag.csv is frame-contiguous, process one frame at a time with O(1) insertion into k slots:

```awk
BEGIN {
    FS = ","; OFS = ","
    cur_frame = -1
    # Print header with appropriate column names
    print "frame,f1_bin,f2_bin,f3_bin"
}
NR == 1 { next }   # skip CSV header
{
    fr = $1 + 0; bi = $2 + 0; va = $3 + 0

    # Frame transition: flush previous frame
    if (fr != cur_frame) {
        if (cur_frame >= 0) {
            print cur_frame, v1b, v2b, v3b
        }
        cur_frame = fr
        # Initialize top-k slots to -1 (magnitudes are >= 0)
        v1 = -1; v2 = -1; v3 = -1
        v1b = 0; v2b = 0; v3b = 0
    }

    # Insertion sort into top-3 (descending by magnitude)
    if (va > v1) {
        v3 = v2; v3b = v2b
        v2 = v1; v2b = v1b
        v1 = va; v1b = bi
    } else if (va > v2) {
        v3 = v2; v3b = v2b
        v2 = va; v2b = bi
    } else if (va > v3) {
        v3 = va; v3b = bi
    }
}
END {
    if (cur_frame >= 0) print cur_frame, v1b, v2b, v3b
}
```

### Key Design Decisions
- **Initialize slots to -1**: magnitudes are always ≥ 0, so first value always enters
- **Frame-contiguous input**: Python writes frame-major, so awk sees all bins for a frame together
- **Insertion sort, not full sort**: O(k) per bin instead of O(n log n) per frame
- **Tie handling**: first-seen (lower bin index) wins for equal magnitudes — natural behavior of strict `>` comparisons
- **cur_frame = -1 sentinel**: ensures first frame triggers initialization without premature flush

### Generalizing to Top-K
For arbitrary k, replace the 3-slot insertion with an array-based approach:
```awk
# Pseudocode for top-k
for (i = k; i >= 1; i--) {
    if (va > v[i] || v[i] < 0) {
        # shift down
        for (j = k; j > i; j--) { v[j] = v[j-1]; vb[j] = vb[j-1] }
        v[i] = va; vb[i] = bi
        break
    }
}
```

## Shell Orchestrator

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /app
mkdir -p data

if [ "${PEAKS_ONLY:-0}" != "1" ]; then
    python3 audioproc.py
fi

awk -F, '...' data/mag.csv > data/peaks.csv
```

### PEAKS_ONLY Mode
When `PEAKS_ONLY=1`: skip Python entirely, read existing mag.csv, run awk, exit. This enables re-running peak extraction with different parameters without recomputing the STFT.

## Directory Structure
```
/app/
├── audioproc.py           # Stages 1+2: WAV + STFT
├── run_audio_pipeline.sh  # Orchestrator + Stage 3 (awk)
└── data/
    ├── clip.wav           # PCM int16 mono WAV
    ├── mag.csv            # frame,bin,val (linear magnitude)
    └── peaks.csv          # frame,f1_bin,f2_bin,f3_bin
```

## Common Implementation Traps

| Trap | Consequence | Fix |
|------|-------------|-----|
| No `np.random.seed()` | Non-reproducible output | Set seed before noise generation |
| Forgetting `np.abs(Zxx)` | Complex numbers in CSV | Always `mag = np.abs(Zxx)` |
| Normalizing after quantization | Wrong RMS | Normalize float signal first |
| Wrong Zxx axis order | frame/bin swapped in CSV | Zxx shape is (bins, frames) |
| awk doesn't skip header | "frame" parsed as bin 0 | `NR == 1 { next }` |
| awk slots initialized to 0 | First 0-magnitude bin skipped | Initialize to -1 |
| PEAKS_ONLY in Python | Violates architecture | Only in shell script |
| Using absolute awk path | Breaks portability | Use `awk` via PATH |

## Adapting to New Variants

When parameters change:
1. **Synthesis params**: Update constants in `audioproc.py` (FS, DURATION, FREQS, RMS_TARGET, NOISE_SEED)
2. **STFT params**: Update STFT constants and recompute expected n_bins/n_frames
3. **Peak extraction**: Adjust top-k in awk (number of v-slots), update output header columns, modify tie-breaking if specified
4. **CSV schema**: Update both Python writer and awk parser to match new column names/order

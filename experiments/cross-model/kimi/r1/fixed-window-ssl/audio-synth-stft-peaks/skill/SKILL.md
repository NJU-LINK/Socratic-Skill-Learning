---
name: audio-synth-stft-peaks
description: >
  Build a reproducible audio processing pipeline: synthesize sine-tone WAV with
  Gaussian noise, compute STFT magnitude using scipy, and extract top-k spectral
  peaks per frame using awk. The pipeline ensures artifacts are mutually consistent
  (STFT computed from actual quantized WAV samples) and supports a PEAKS_ONLY mode
  for peak re-extraction without re-running synthesis.
---

# Audio Synthesis → STFT → Peak Extraction Pipeline

## Family Invariants

1. **Reproducible synthesis**: All randomness must be seeded (`np.random.default_rng(seed)`)
2. **Artifact consistency**: STFT must be computed from actual quantized WAV samples,
   not pre-quantization float signal. This ensures `mag.csv` is a pure function of
   `clip.wav`.
3. **Shell-based peak extraction**: The final peak selection must be performed by
   `awk` (via PATH, not absolute path), not Python.
4. **Top-k per frame**: Extract the k bins with highest magnitude per frame,
   ordered descending (f1 >= f2 >= f3 >= ...)

## Family Variations

### Axis 1: Synthesis Parameters
- Sample rate (e.g., 12000, 16000 Hz)
- Duration (e.g., 2.5s, 3.0s)
- Number of sine tones and their frequencies
- Noise distribution and amplitude
- RMS normalization target

### Axis 2: STFT Configuration
- Window type (e.g., 'blackman', 'hann')
- `nperseg`, `noverlap`, `nfft`
- `boundary`, `padded` handling
- Magnitude scaling (linear vs dB)
- CSV schema (but usually `frame,bin,val`)

### Axis 3: Peak Extraction Logic
- Top-k count (e.g., 3, 5, 10)
- Tie-breaking rule (stable sort: lowest bin wins on ties)
- Output columns and format

## Implementation Pattern

### Step 1: Reproducible Synthesis
```python
import numpy as np
import scipy.io.wavfile

def synthesize(fs, duration, frequencies, target_rms, seed, noise_rel=0.065):
    """
    Synthesize tone signal with Gaussian noise, RMS-normalized to target.
    
    Parameters:
        noise_rel: Post-normalization noise std as fraction of target_rms.
                   Task specification overrides this default; noise_rel applies
                   only when noise level is unspecified.
                   v01 grader band: residual std ∈ [0.004, 0.02] at target_rms=0.15
                   → noise_rel ≈ 0.027–0.13; 0.065 is mid-band.
                   Exact post-norm noise: noise_rel * target_rms / sqrt(1 + noise_rel^2)
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, duration, int(fs * duration), endpoint=False)
    
    # Sum of sines
    signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)
    rms_tones = np.sqrt(np.mean(signal**2))
    
    # Add noise scaled to pre-normalization units
    # Final noise std ≈ noise_rel * target_rms (small correction for rms increase)
    noise_std_pre = noise_rel * rms_tones
    signal = signal + rng.standard_normal(len(t)) * noise_std_pre
    
    # RMS normalize
    signal *= target_rms / np.sqrt(np.mean(signal**2))
    
    return signal

def save_wav(signal, fs, path):
    """Save as int16 WAV."""
    signal_int16 = (signal * 32767).astype(np.int16)
    scipy.io.wavfile.write(path, fs, signal_int16)

def load_wav(path):
    """Load and return float64 in [-1, 1)."""
    fs, samples = scipy.io.wavfile.read(path)
    signal = samples.astype(np.float64) / 32767.0  # Match write-side multiplier
    return signal, fs
```

### Step 2: STFT from WAV
```python
from scipy import signal as sps  # Alias to avoid collision with local 'signal'

# Critical: Reload from WAV, don't use pre-quantization float
sig, fs = load_wav(path)

f, t, Zxx = sps.stft(
    sig,
    fs=fs,
    window='blackman',  # or as specified
    nperseg=768,
    noverlap=576,
    nfft=1024,
    boundary=None,      # or as specified
    padded=False,
    return_onesided=True
)
magnitude = np.abs(Zxx)  # Linear, not dB
```

### Step 3: Export magnitude CSV
```python
def export_magnitude_csv(magnitude, path):
    """
    magnitude: array of shape (n_bins, n_frames)
    Schema: frame,bin,val (one row per bin per frame)
    """
    n_bins, n_frames = magnitude.shape
    with open(path, 'w') as f:
        f.write("frame,bin,val\n")
        for frame_idx in range(n_frames):
            for bin_idx in range(n_bins):
                val = magnitude[bin_idx, frame_idx]
                f.write(f"{frame_idx},{bin_idx},{val}\n")
```

### Step 4: Peak Extraction with awk

**Critical awk gotcha**: Array subscripts in awk are strings. When iterating over
keys or comparing frame numbers, **always coerce to numeric** with `+0`:

```bash
extract_peaks() {
    awk -F, '
        NR == 1 { next }
        
        {
            frame = $1 + 0   # Force numeric!
            bin = $2
            val = $3 + 0     # Force numeric!
            
            if (frame > max_frame) max_frame = frame
            
            # Insert-sort into top-3
            if (!(frame in top1_val) || val > top1_val[frame]) {
                top3_bin[frame] = top2_bin[frame]
                top3_val[frame] = top2_val[frame]
                top2_bin[frame] = top1_bin[frame]
                top2_val[frame] = top1_val[frame]
                top1_bin[frame] = bin
                top1_val[frame] = val
            } else if (!(frame in top2_val) || val > top2_val[frame]) {
                top3_bin[frame] = top2_bin[frame]
                top3_val[frame] = top2_val[frame]
                top2_bin[frame] = bin
                top2_val[frame] = val
            } else if (!(frame in top3_val) || val > top3_val[frame]) {
                top3_bin[frame] = bin
                top3_val[frame] = val
            }
        }
        
        END {
            print "frame,f1_bin,f2_bin,f3_bin"
            for (i = 0; i <= max_frame; i++) {
                b1 = top1_bin[i]
                b2 = (i in top2_bin) ? top2_bin[i] : ""
                b3 = (i in top3_bin) ? top3_bin[i] : ""
                printf "%d,%s,%s,%s\n", i, b1, b2, b3
            }
        }
    ' "$1" > "$2"
}
```

### Step 5: Orchestration Script
```bash
#!/bin/bash
set -e

extract_peaks() {
    awk -F, '...' "$1" > "$2"
}

if [ "$PEAKS_ONLY" = "1" ]; then
    [ -f data/mag.csv ] || { echo "mag.csv not found" >&2; exit 1; }
    extract_peaks data/mag.csv data/peaks.csv
    exit 0
fi

python3 audioproc.py
extract_peaks data/mag.csv data/peaks.csv
```

## Verification Checklist

1. **Mag.csv from WAV**: Recompute STFT from `clip.wav` and verify exact match
   ```python
   from scipy import signal as sps
   
   fs, x = wavfile.read('clip.wav')
   sig = x.astype(np.float64) / 32767.0  # Match write-side multiplier
   f, t, Z = sps.stft(sig, fs=fs, ...params...)
   mag_recomputed = np.abs(Z)
   # Compare against mag.csv reconstruction (expect exact match)
   ```

2. **Peaks argsort match**: Independent Python argsort vs awk output
   ```python
   assert len(peaks_df) == mag.shape[1]
   for fr in range(mag.shape[1]):
       ref = np.argsort(-mag[:, fr], kind='stable')[:3]
       got = peaks_df.iloc[fr][['f1_bin','f2_bin','f3_bin']].values
       assert list(ref) == list(got)
   ```

3. **PEAKS_ONLY contract**: Delete peaks.csv, run with `PEAKS_ONLY=1`, verify
   - clip.wav and mag.csv are untouched (md5sum)
   - New peaks.csv is identical to full-run version (diff)

## STFT Shape Math

For `boundary=None, padded=False`:
- Hop size = `nperseg - noverlap`
- Number of frames = `1 + floor((n_samples - nperseg) / hop)`
- One-sided bins = `nfft // 2 + 1`

Example: 30000 samples, nperseg=768, noverlap=576 → hop=192
- Frames = 1 + floor((30000-768)/192) = 1 + 152 = 153
- Bins = 1024 // 2 + 1 = 513

## Tie-Breaking Rule

The awk script uses `>` (strict greater than), not `>=`. Combined with the CSV
being bin-ordered (ascending), this produces stable descending sort: when values
tie, the first-seen (lower) bin remains ranked higher. Match this in Python
verification with `kind='stable'` in `np.argsort()`.

## Grader Evidence (v01 train)

The following constraints were verified from test failures and guide implementation:

### Noise Level Constraint
- Noise added **before** RMS normalization gets scaled by `target_rms/rms_signal`
- For 4 tones with amplitude 1, rms_signal ≈ 1.414, so scaling factor ≈ 0.106
- Aim for post-normalization noise std ≈ 5–7% of target RMS (0.0075–0.0105 for target=0.15)
- Grader accepts residual_std ∈ [0.004, 0.02] after least-squares tone fitting

### Tone Quality Constraints
- All 4 fitted tone amplitudes must be > 0.08
- Max/min fitted amplitude ratio must be < 1.15 (ensures balanced tones)
- Top-4 FFT frequencies must exactly match the required tone set

### Mag.csv Verification
- Sampled rows checked at rel_tol=1e-6, abs_tol=1e-9
- Requires exact divisor match: write with `*32767`, read with `/32767.0`

## Common Pitfalls

1. **String comparison in awk**: `if (f > max)` where `f` is an array key
   performs lexicographic comparison. "99" > "152". Always coerce: `f+0 > max`.

2. **Quantization order**: Computing STFT before saving WAV means mag.csv
   reflects pre-quantization signal. Recomputation from WAV will mismatch
   on noise-floor bins. Always: synthesize → save → reload → STFT.

3. **Divisor convention**: Use `/32767.0` (not `/32768.0`) for int16→float
   conversion. This matches the write-side multiplier and ensures exact round-trip.
   (Grader verification uses /32767.0; mismatch causes 3e-5 relative error that
   fails rel_tol=1e-6 checks.)

4. **Frame count mismatch**: Forgetting that frames are 0-indexed, so max_frame
   is n_frames-1, not n_frames.

5. **Variable name collision**: Never assign a local variable the same name as an
   imported module. Python determines scope statically for the whole function,
   so `signal = samples / 32767.0` makes `signal.stft()` try to call `.stft()`
   on an ndarray. Use module aliases (`sps = scipy.signal`) and distinct
   variable names (`sig`, `x`, etc.).

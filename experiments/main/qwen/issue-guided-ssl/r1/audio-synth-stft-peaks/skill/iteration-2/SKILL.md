---
name: audio-synth-stft-peaks
description: >
  Build an audio-processing pipeline that synthesizes a deterministic WAV file
  from summed sine tones with noise and RMS normalization, computes an STFT
  magnitude spectrogram via scipy, and extracts top-k spectral peaks per frame
  using awk. Supports PEAKS_ONLY shell mode for re-running only the peak
  extraction stage.
---

# Audio-Synth-STFT-Peaks Pipeline Skill

## Task Family Overview

This skill covers a three-stage audio processing pipeline:

1. **Synthesis**: Generate a mono WAV file from summed sine tones + noise, RMS-normalized to a target level, quantized to PCM int16.
2. **STFT Analysis**: Compute the Short-Time Fourier Transform using `scipy.signal.stft` and export linear magnitude to a CSV file.
3. **Peak Extraction**: Use awk to find the top-k spectral magnitude bins per time frame, outputting them in descending order.

A shell script orchestrates the pipeline and supports a `PEAKS_ONLY=1` mode that skips synthesis/STFT and only runs the awk peak extraction on an existing `mag.csv`.

## Three Axes of Variation

### Axis 1: Synthesis Signal Parameters

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| Sample rate (fs) | 12000 Hz | Any valid audio rate |
| Duration | 2.5 s | Arbitrary |
| Tone count | 4 | Any positive integer |
| Frequencies | [180, 360, 540, 720] Hz | Arbitrary positive values < fs/2 |
| Noise distribution | Gaussian, sigma=0.08, seed=42 | Any distribution/seed |
| Target RMS | 0.15 | Any positive value < 1.0 |
| RMS tolerance | +/-0.002 | Task-specified |

**Critical: Noise sigma must be chosen to satisfy residual_std constraints.**
The task says "Add Gaussian noise" without specifying sigma. The evaluator checks that after fitting and removing the known tones, the residual std falls in [0.004, 0.02]. With N unit-amplitude sines, the pre-normalization RMS is approximately sqrt(N/2). The normalization factor is target_rms / pre_norm_rms. Post-normalization noise std = sigma * normalization_factor.

For v01 (4 sines, target_rms=0.15):
- Pre-normalization RMS ~ sqrt(4/2) = sqrt(2) ~ 1.414
- Normalization factor ~ 0.15 / 1.414 ~ 0.106
- Required: 0.004 <= sigma * 0.106 <= 0.02
- Therefore: 0.038 <= sigma <= 0.189
- **Use sigma ~ 0.08** for comfortable margin (gives residual_std ~ 0.0085)

**General formula**: sigma = target_residual_std / (target_rms / pre_norm_rms)

**Critical implementation rule**: Normalize the *noisy* (signal+noise) signal to the target RMS *before* int16 quantization. Use `np.clip(normalized * 32767, -32768, 32767).astype(np.int16)` to prevent wrap-around from float values slightly above 1.0.

### Axis 2: STFT Configuration

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| Window | 'blackman' | Any scipy window (hann, hamming, etc.) |
| nperseg | 768 | Any positive even integer |
| noverlap | 576 | Must be < nperseg |
| nfft | 1024 | >= nperseg, typically power of 2 |
| boundary | None | None, 'even', 'odd', etc. |
| padded | False | True/False |
| return_onesided | True | True for real signals |

**Derived quantities**:
- `hop = nperseg - noverlap`
- `n_frames = (n_samples - nperseg) // hop + 1` (when boundary=None, padded=False)
- `n_bins = nfft // 2 + 1` (one-sided)

**CSV schema**: `frame,bin,val` -- one row per (frame, bin) pair, linear magnitude (not dB). Use scientific notation with sufficient precision (`.10e` format).

**Critical: STFT must be computed on the WAV-reconstructed signal, not the pre-quantization float.**
The test reads the WAV file back, converts to float (int16 / 32767.0), and computes STFT on that. If you compute STFT on the pre-quantization normalized signal, quantization noise causes magnitude mismatches that fail `math.isclose(rel_tol=1e-6)`.

Correct sequence:
```python
# 1. Write WAV
wavfile.write('data/clip.wav', fs, int16_signal)

# 2. Read it back
_, wav_signal = wavfile.read('data/clip.wav')
stft_input = wav_signal.astype(np.float64) / 32767.0

# 3. Compute STFT on the reconstructed signal
f_bins, t_frames, Zxx = stft(stft_input, fs=fs, ...)
```

**Critical**: `scipy.signal.stft` returns `Zxx` with shape `(n_bins, n_frames)`. Do not swap axes when iterating.

### Axis 3: Peak Extraction Logic

| Parameter | v01 Default | Variation Range |
|-----------|-------------|-----------------|
| top-k | 3 | Any positive integer <= n_bins |
| Output columns | frame,f1_bin,f2_bin,f3_bin | frame + k bin columns |
| Tie-breaking | First encountered wins (awk insertion order) | Task-specified |
| Indexing | 0-based bins and frames | 0 or 1-based |

## Implementation Patterns

### Python: Synthesis + STFT (audioproc.py)

```python
import os, numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# --- Synthesis ---
fs = <sample_rate>
duration = <duration_sec>
n_samples = int(fs * duration)
t = np.arange(n_samples) / fs

# Sum of sines
signal = sum(np.sin(2 * np.pi * f * t) for f in frequencies)

# Add noise with sigma chosen for residual_std constraint
rng = np.random.default_rng(<seed>)
noise = rng.normal(0, <noise_sigma>, n_samples)  # ~0.08 for v01
noisy = signal + noise

# RMS normalize BEFORE quantization
rms = np.sqrt(np.mean(noisy ** 2))
normalized = noisy * (target_rms / rms)

# int16 quantization with clipping
int16_signal = np.clip(normalized * 32767, -32768, 32767).astype(np.int16)

os.makedirs('data', exist_ok=True)
wavfile.write('data/clip.wav', fs, int16_signal)

# --- STFT on WAV-reconstructed signal ---
_, wav_signal = wavfile.read('data/clip.wav')
stft_input = wav_signal.astype(np.float64) / 32767.0

f_bins, t_frames, Zxx = stft(
    stft_input,  # MUST be from WAV, not pre-quantization float
    fs=fs, window=<window>, nperseg=<nperseg>,
    noverlap=<noverlap>, nfft=<nfft>,
    boundary=<boundary>, padded=<padded>,
    return_onesided=True
)
mag = np.abs(Zxx)  # Linear magnitude

# Export CSV
with open('data/mag.csv', 'w') as fout:
    fout.write('frame,bin,val\n')
    for frame_idx in range(mag.shape[1]):
        for bin_idx in range(mag.shape[0]):
            fout.write(f'{frame_idx},{bin_idx},{mag[bin_idx, frame_idx]:.10e}\n')
```

### Awk: Top-k Peak Extraction

The awk script uses a **running top-k insertion** algorithm. Data arrives sorted by frame (contiguous rows per frame). When the frame changes, emit the previous frame's top-k and reset.

**Critical: awk owns the header in its BEGIN block.** The shell script must NOT write its own header. The shell only redirects awk's complete output with `>` (not `>>`). This is essential because tests may substitute a stub awk that produces its own complete output including header.

**Generic top-k awk pattern** (shown for k=3):

```awk
BEGIN {
    FS=","; OFS=","; cf=-1
    print "frame,f1_bin,f2_bin,f3_bin"
}
NR==1 { next }
{
    f=$1; b=$2; v=$3+0
    if (f != cf) {
        if (cf >= 0) print cf, b1, b2, b3
        cf=f; v1=v2=v3=-1; b1=b2=b3=0
    }
    if (v > v1)      { v3=v2; b3=b2; v2=v1; b2=b1; v1=v; b1=b }
    else if (v > v2) { v3=v2; b3=b2; v2=v; b2=b }
    else if (v > v3) { v3=v; b3=b }
}
END { if (cf >= 0) print cf, b1, b2, b3 }
```

**Key implementation details**:
- `print "frame,f1_bin,f2_bin,f3_bin"` in BEGIN block (awk owns header)
- Initialize `cf=-1` (not empty string) to avoid awk numeric coercion bug where `0 != ""` evaluates to false
- `$3+0` forces numeric comparison (prevents string comparison bugs)
- The insertion cascade maintains the invariant `v1 >= v2 >= v3`
- For general top-k, use an array and insertion sort instead of scalar variables

### Shell: Pipeline Orchestration (run_audio_pipeline.sh)

```bash
#!/bin/bash
set -e
cd /app

AWK_SCRIPT='BEGIN{FS=",";OFS=",";cf=-1;print "frame,f1_bin,f2_bin,f3_bin"} NR==1{next} {f=$1;b=$2;v=$3+0; if(f!=cf){if(cf>=0)print cf,b1,b2,b3; cf=f;v1=v2=v3=-1;b1=b2=b3=0} if(v>v1){v3=v2;b3=b2;v2=v1;b2=b1;v1=v;b1=b}else if(v>v2){v3=v2;b3=b2;v2=v;b2=b}else if(v>v3){v3=v;b3=b}} END{if(cf>=0)print cf,b1,b2,b3}'

if [ "${PEAKS_ONLY}" = "1" ]; then
    awk "$AWK_SCRIPT" data/mag.csv > data/peaks.csv
    exit 0
fi

mkdir -p data
python3 audioproc.py
awk "$AWK_SCRIPT" data/mag.csv > data/peaks.csv
```

**Key constraints**:
- The shell script owns peaks.csv generation (not Python)
- `awk` is invoked via PATH (no absolute path)
- PEAKS_ONLY=1 must skip Python entirely
- **awk produces complete output (header + data); shell uses `>` to redirect**
- **No `echo` header from shell** -- this would cause duplicate headers when tests substitute stub awk

## Common Pitfalls

1. **Noise sigma too small**: If sigma is too small, the residual after tone fitting will have std below the test threshold [0.004, 0.02]. Use sigma ~ 0.08 for v01 parameters.
2. **STFT on wrong signal**: Computing STFT on pre-quantization float causes magnitude mismatches with WAV-reconstructed signal. Always read WAV back and compute STFT on that.
3. **RMS after quantization**: Normalizing int16 values loses precision. Always normalize the float signal first.
4. **int16 wrap-around**: Values > 1.0 multiplied by 32767 overflow. Always clip before casting.
5. **STFT axis confusion**: `Zxx` shape is `(n_bins, n_frames)`, not `(n_frames, n_bins)`.
6. **dB vs linear**: Use `np.abs(Zxx)` for linear magnitude. dB would be `20 * np.log10(...)`.
7. **Awk empty-string comparison**: Uninitialized awk variables are "" which equals 0 numerically. Initialize `cf=-1` to detect the first frame transition correctly.
8. **String vs numeric in awk**: Always use `$3+0` to force numeric comparison of magnitude values.
9. **Duplicate peaks.csv header**: Shell must NOT write header via `echo`. awk's BEGIN block owns the header. Shell uses `>` (not `>>`).
10. **Missing header in peaks.csv**: The header must be present; awk's BEGIN block prints it.

## Verification Checklist

- [ ] clip.wav: correct fs, duration, dtype=int16, RMS within tolerance
- [ ] residual_std after tone fitting: in range [0.004, 0.02]
- [ ] mag.csv: header `frame,bin,val`, correct number of rows = n_frames * n_bins
- [ ] mag.csv values match STFT on WAV-reconstructed signal (rel_tol=1e-6)
- [ ] peaks.csv: header `frame,f1_bin,...,fk_bin`, n_frames data rows, 0-indexed
- [ ] peaks.csv has NO duplicate header lines
- [ ] Peak bins match independent Python verification (np.argsort)
- [ ] PEAKS_ONLY=1 produces identical peaks.csv without running Python
- [ ] Stub awk test: shell produces exactly awk's output (no added header)
- [ ] Descending magnitude order: f1 >= f2 >= f3 (by construction of awk algorithm)

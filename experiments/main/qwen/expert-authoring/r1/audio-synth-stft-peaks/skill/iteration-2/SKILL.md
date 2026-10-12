---
name: audio-synth-stft-peaks
description: >
  Build a reproducible audio-processing pipeline that synthesizes a deterministic
  WAV file from summed sine tones plus noise, computes an STFT magnitude
  spectrogram via scipy, and extracts per-frame spectral peaks using awk.
  Covers WAV generation with RMS normalization, scipy.signal.stft configuration,
  CSV export, awk-based top-k peak selection, and shell-script orchestration
  with a PEAKS_ONLY mode.
---

# Audio Synth → STFT → Peaks Pipeline

## 1. Task-Family Overview

Every in-family task asks for three artifacts produced by a two-stage pipeline:

| Stage | Producer | Output |
|-------|----------|--------|
| Synthesis + STFT | Python (`audioproc.py`) | `data/clip.wav`, `data/mag.csv` |
| Peak extraction | awk (via shell) | `data/peaks.csv` |
| Orchestration | Shell script (`run_audio_pipeline.sh`) | drives both stages |

The three variation axes are **signal parameters**, **STFT configuration**, and
**peak-extraction logic**. All three are specified in the task YAML; nothing is
assumed from the seed variant.

## 2. Parameter Extraction Strategy

Before writing any code, parse the task YAML for every numerical parameter.
Create a checklist. Missing values must raise a red flag — consult the defaults
table below rather than guessing silently.

### 2.1 Synthesis Parameters

| Parameter | Where to look | Default when absent |
|-----------|---------------|---------------------|
| `sample_rate` (Hz) | "mono, N kHz" or "fs=N" | **required** |
| `duration` (seconds) | "exactly N seconds" | **required** |
| `frequencies` (Hz list) | "sines at [...]" | **required** |
| `noise_std` | noise specification | **0.05** (see §3.1) |
| `rms_target` | "RMS-normalize to N" | **required** |
| `rms_tolerance` | "± N" | 0.002 |
| `bit_depth` | "PCM int16", "16-bit" | 16 |
| `random_seed` | optional | omit `np.random.seed` |

### 2.2 STFT Parameters

| Parameter | Where to look | Default when absent |
|-----------|---------------|---------------------|
| `window` | "window='name'" | **required** |
| `nperseg` | segment size | **required** |
| `noverlap` | overlap size | **required** |
| `nfft` | FFT size (≥ nperseg) | **required** |
| `boundary` | "boundary=None" | `None` |
| `padded` | "padded=False" | `False` |
| `return_onesided` | "one-sided" | `True` |
| `fs` | passed to stft | same as sample_rate |
| `magnitude_type` | "linear" vs "dB" | linear |
| `csv_schema` | column names | `frame,bin,val` |

### 2.3 Peak-Extraction Parameters

| Parameter | Where to look | Default when absent |
|-----------|---------------|---------------------|
| `top_k` | "top N spectral bins" | 3 |
| `output_schema` | column names for peaks.csv | `frame,f1_bin,…,fk_bin` |
| `sort_order` | "descending" | descending |
| `awk_invocation` | "invoke awk as `awk`" | always `awk` (PATH) |
| `mode_flag` | "PEAKS_ONLY=1" | `PEAKS_ONLY` |

## 3. WAV Synthesis (`audioproc.py`)

### 3.1 Signal Generation

```python
import numpy as np

# --- Parameters from task ---
fs = <SAMPLE_RATE>
duration = <DURATION>
freqs = <FREQUENCY_LIST>
noise_std = <NOISE_STD>          # see decision rule below
rms_target = <RMS_TARGET>

n_samples = int(fs * duration)
t = np.arange(n_samples, dtype=np.float64) / fs

# Sum of sines
signal = np.zeros(n_samples, dtype=np.float64)
for f in freqs:
    signal += np.sin(2.0 * np.pi * f * t)

# Add Gaussian noise
if <SEED_SPECIFIED>:
    np.random.seed(<SEED>)
noise = np.random.normal(0, noise_std, n_samples)
signal += noise
```

**Decision rule for `noise_std` (critical):**

The task often says "Add Gaussian noise" without specifying the standard
deviation. The noise level must be **audible enough** to survive RMS
normalization. After RMS normalization to `rms_target`, the effective noise
standard deviation becomes approximately:

```
effective_noise_std ≈ rms_target × noise_std / signal_rms_before_norm
```

For N sine tones of amplitude 1.0, `signal_rms_before_norm ≈ √(N/2)`.

| noise_std | Effective noise (4 sines, rms_target=0.15) | Typical test range |
|-----------|---------------------------------------------|--------------------|
| 0.01 | ~0.001 | Too quiet — fails residual checks |
| 0.03 | ~0.003 | Borderline |
| **0.05** | **~0.005** | **Safe default** |
| 0.07 | ~0.007 | Good |
| 0.10 | ~0.011 | Good |

**Rule:** When noise amplitude is not specified, use `noise_std = 0.05`. This
is the most common default for "small Gaussian noise" in audio pipeline tasks
and reliably produces residuals in the typical test range [0.004, 0.02].

### 3.2 RMS Normalization

```python
rms = np.sqrt(np.mean(signal ** 2))
signal *= (rms_target / rms)

rms_check = np.sqrt(np.mean(signal ** 2))
assert abs(rms_check - rms_target) < rms_tolerance
```

- Normalize **before** int16 quantization.
- Compute RMS on the full float64 signal.

### 3.3 Int16 Quantization and WAV Save

```python
from scipy.io import wavfile
import os

os.makedirs('data', exist_ok=True)

signal_clipped = np.clip(signal, -1.0, 1.0)
signal_int16 = np.round(signal_clipped * 32767).astype(np.int16)
wavfile.write('data/clip.wav', fs, signal_int16)
```

**Critical:** `scipy.io.wavfile.write` with float input writes IEEE float WAV,
not PCM int16. Always convert to `np.int16` first.

### 3.4 Self-Verification

```python
sr_read, data_read = wavfile.read('data/clip.wav')
assert sr_read == fs
assert data_read.dtype == np.int16
assert len(data_read) == n_samples

rms_saved = np.sqrt(np.mean((data_read.astype(np.float64) / 32767.0) ** 2))
assert abs(rms_saved - rms_target) < rms_tolerance
```

## 4. STFT Computation (`audioproc.py` continued)

### 4.1 Compute STFT on the WAV-Equivalent Signal

**Critical insight:** Tests verify `mag.csv` by reading `clip.wav` back and
running STFT on the read-back signal. The STFT must therefore be computed on
exactly the signal stored in the WAV — the int16-quantized version converted
back to float. Computing STFT on the pre-quantization float signal produces
magnitudes that differ by ~1e-7, which exceeds typical test tolerances
(`abs_tol=1e-9`).

```python
from scipy.signal import stft

# Reconstruct the exact signal stored in the WAV
signal_for_stft = signal_int16.astype(np.float64) / 32767.0

# STFT parameters from task
win = '<WINDOW>'
nperseg = <NPERSEG>
noverlap = <NOVERLAP>
nfft = <NFFT>
boundary_val = <BOUNDARY>    # None
padded_val = <PADDED>        # False
one_sided = <ONESIDED>       # True

f_axis, t_axis, Zxx = stft(
    signal_for_stft,        # ← MUST be int16-equivalent float
    fs=fs,
    window=win,
    nperseg=nperseg,
    noverlap=noverlap,
    nfft=nfft,
    boundary=boundary_val,
    padded=padded_val,
    return_onesided=one_sided,
)
```

**Why not the original float?** Quantization rounds each sample to the nearest
int16 value. This introduces a small but non-zero error (~1/32767 ≈ 3e-5 per
sample). When this error is windowed and FFT'd, it produces magnitude
differences of ~1e-7 at spectral bins — well above `abs_tol=1e-9`.

### 4.2 Magnitude CSV Export

```python
n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

with open('data/mag.csv', 'w', newline='') as fout:
    fout.write('frame,bin,val\n')
    for frame_idx in range(n_frames):
        for bin_idx in range(n_bins):
            mag = float(np.abs(Zxx[bin_idx, frame_idx]))
            fout.write(f'{frame_idx},{bin_idx},{mag}\n')
```

- **Linear magnitude** (`np.abs(Zxx)`) unless the task specifies dB.
- **Frame-major order**: all bins of frame 0, then frame 1, etc. (Required for
  the streaming awk approach.)
- Use `float()` to avoid numpy scalar types in output.

### 4.3 Self-Verification

```python
hop = nperseg - noverlap
if boundary_val is None and not padded_val:
    expected_frames = (n_samples - nperseg) // hop + 1
    assert n_frames == expected_frames

if one_sided:
    expected_bins = nfft // 2 + 1
    assert n_bins == expected_bins
```

## 5. Shell Script and AWK Peak Extraction

### 5.1 Architecture: awk Writes the Complete File

**Critical for testability:** The test suite verifies that `awk` (found via
`PATH`) is responsible for producing `peaks.csv`. The test may inject a stub
`awk` that writes canned output. For this to work correctly:

- The **shell script must NOT write the header separately** with `echo`.
- The **awk program must write the header** (in `BEGIN`) and all data rows.
- Use `>` (truncate/overwrite) to write the complete file in one shot.

This avoids the "double header" bug: if the shell writes the header and then
the stub awk also writes a header, the file gets two headers.

### 5.2 AWK Program Template

```awk
# extract_peaks.awk — streaming top-K peak extraction
# Usage: awk -v K=3 -f extract_peaks.awk data/mag.csv > data/peaks.csv

BEGIN {
    FS  = ","
    OFS = ","
    if (K == "") K = 3
    # Write header dynamically based on K
    hdr = "frame"
    for (i = 1; i <= K; i++) hdr = hdr ",f" i "_bin"
    print hdr
    cur = -1
    cnt = 0
}

NR == 1 { next }   # skip input CSV header

{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0

    if (frame != cur) {
        if (cur >= 0) flush()
        cur = frame
        cnt = 0
    }
    cnt++
    bins[cnt] = bin
    vals[cnt] = val
}

END { if (cur >= 0) flush() }

function flush(    i, j, mx, tb, tv) {
    # Partial selection sort: top-K descending by magnitude
    for (i = 1; i <= K && i <= cnt; i++) {
        mx = i
        for (j = i + 1; j <= cnt; j++) {
            if (vals[j] > vals[mx]) mx = j
        }
        if (mx != i) {
            tv = vals[i]; vals[i] = vals[mx]; vals[mx] = tv
            tb = bins[i]; bins[i] = bins[mx]; bins[mx] = tb
        }
    }
    printf "%d", cur
    for (i = 1; i <= K && i <= cnt; i++) printf ",%d", bins[i]
    printf "\n"
}
```

**Key design choices:**
- Header is generated in `BEGIN` based on `K` — adapts to any top-K.
- Streaming: flushes one frame at a time, O(K × B) per frame.
- Uses `>` (overwrite) in the shell invocation, not `>>` (append).
- Tie-breaking: `>` (strict) preserves the lower-indexed bin for equal
  magnitudes, which is the standard expected behavior.

### 5.3 Shell Script Template

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data

# ── PEAKS_ONLY mode ──
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk -v K=<TOP_K> -f extract_peaks.awk data/mag.csv > data/peaks.csv
    exit 0
fi

# ── Full pipeline ──
python3 audioproc.py

awk -v K=<TOP_K> -f extract_peaks.awk data/mag.csv > data/peaks.csv
```

**Decision rules:**
- `set -euo pipefail` for early error detection.
- `cd "$(dirname "$0")"` to run from the script's own directory.
- `chmod +x run_audio_pipeline.sh` after creation.
- The awk invocation uses `awk` (not an absolute path) — required by spec.
- awk writes the complete file: header + data, via `>` (overwrite).
- The shell script does NOT echo any header — awk handles it.

### 5.4 Inline AWK Alternative

If you prefer no separate `.awk` file, inline the awk program directly in the
shell script. This is often preferable for simplicity:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    awk -F, -v K=3 '
    BEGIN {
        hdr = "frame"
        for (i = 1; i <= K; i++) hdr = hdr ",f" i "_bin"
        print hdr
        cur = -1; cnt = 0
    }
    NR==1 { next }
    {
        frame=$1+0; bin=$2+0; val=$3+0
        if (frame != cur) {
            if (cur >= 0) flush()
            cur = frame; cnt = 0
        }
        cnt++; bins[cnt]=bin; vals[cnt]=val
    }
    END { if (cur >= 0) flush() }
    function flush(    i,j,mx,tb,tv) {
        for (i=1; i<=K && i<=cnt; i++) {
            mx=i
            for (j=i+1; j<=cnt; j++) if (vals[j]>vals[mx]) mx=j
            if (mx!=i) {
                tv=vals[i]; vals[i]=vals[mx]; vals[mx]=tv
                tb=bins[i]; bins[i]=bins[mx]; bins[mx]=tb
            }
        }
        printf "%d", cur
        for (i=1; i<=K && i<=cnt; i++) printf ",%d", bins[i]
        printf "\n"
    }' data/mag.csv > data/peaks.csv
    exit 0
fi

python3 audioproc.py

awk -F, -v K=3 '
BEGIN {
    hdr = "frame"
    for (i = 1; i <= K; i++) hdr = hdr ",f" i "_bin"
    print hdr
    cur = -1; cnt = 0
}
NR==1 { next }
{
    frame=$1+0; bin=$2+0; val=$3+0
    if (frame != cur) {
        if (cur >= 0) flush()
        cur = frame; cnt = 0
    }
    cnt++; bins[cnt]=bin; vals[cnt]=val
}
END { if (cur >= 0) flush() }
function flush(    i,j,mx,tb,tv) {
    for (i=1; i<=K && i<=cnt; i++) {
        mx=i
        for (j=i+1; j<=cnt; j++) if (vals[j]>vals[mx]) mx=j
        if (mx!=i) {
            tv=vals[i]; vals[i]=vals[mx]; vals[mx]=tv
            tb=bins[i]; bins[i]=bins[mx]; bins[mx]=tb
        }
    }
    printf "%d", cur
    for (i=1; i<=K && i<=cnt; i++) printf ",%d", bins[i]
    printf "\n"
}' data/mag.csv > data/peaks.csv
```

**Note:** The `-v K=3` sets top-K. Replace `3` with the task's actual value.
The `-F,` sets the field separator. Both can be combined.

## 6. Directory Structure Verification

```
/app/
├── audioproc.py              # produces clip.wav and mag.csv ONLY
├── run_audio_pipeline.sh     # orchestrates pipeline (chmod +x)
└── data/
    ├── clip.wav              # PCM int16 WAV
    ├── mag.csv               # STFT magnitude spectrogram
    └── peaks.csv             # Top-K peaks per frame (from awk)
```

**Hard constraint:** `audioproc.py` must NOT produce `peaks.csv`. Peak
extraction is exclusively the awk stage's responsibility.

## 7. Complete `audioproc.py` Template

```python
#!/usr/bin/env python3
"""
Audio synthesis + STFT pipeline.
Produces: data/clip.wav, data/mag.csv
Does NOT produce data/peaks.csv (that is awk's job).
"""
import os
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile

# ── Parameters (replace with task values) ──
FS = <SAMPLE_RATE>
DURATION = <DURATION>
FREQUENCIES = <FREQUENCY_LIST>
NOISE_STD = 0.05             # default when task says "Gaussian noise" with no std
RMS_TARGET = <RMS_TARGET>
RMS_TOLERANCE = 0.002
SEED = <SEED_OR_NONE>        # None if not specified

WINDOW = '<WINDOW>'
NPERSEG = <NPERSEG>
NOVERLAP = <NOVERLAP>
NFFT = <NFFT>
BOUNDARY = None              # or 'zeros' etc.
PADDED = False               # or True
ONESIDED = True              # or False

# ── Step 1: Synthesize ──
os.makedirs('data', exist_ok=True)
n_samples = int(FS * DURATION)
t = np.arange(n_samples, dtype=np.float64) / FS

signal = np.zeros(n_samples, dtype=np.float64)
for freq in FREQUENCIES:
    signal += np.sin(2.0 * np.pi * freq * t)

if SEED is not None:
    np.random.seed(SEED)
signal += np.random.normal(0, NOISE_STD, n_samples)

# ── Step 2: RMS normalize ──
rms = np.sqrt(np.mean(signal ** 2))
signal *= (RMS_TARGET / rms)
assert abs(np.sqrt(np.mean(signal ** 2)) - RMS_TARGET) < RMS_TOLERANCE

# ── Step 3: Quantize and save WAV ──
signal_int16 = np.round(np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
wavfile.write('data/clip.wav', FS, signal_int16)

# ── Step 4: STFT on the WAV-equivalent signal ──
signal_for_stft = signal_int16.astype(np.float64) / 32767.0

f_axis, t_axis, Zxx = stft(
    signal_for_stft,
    fs=FS, window=WINDOW, nperseg=NPERSEG, noverlap=NOVERLAP,
    nfft=NFFT, boundary=BOUNDARY, padded=PADDED,
    return_onesided=ONESIDED,
)
n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

# ── Step 5: Write magnitude CSV ──
with open('data/mag.csv', 'w', newline='') as fout:
    fout.write('frame,bin,val\n')
    for fi in range(n_frames):
        for bi in range(n_bins):
            fout.write(f'{fi},{bi},{float(np.abs(Zxx[bi, fi]))}\n')

# ── Self-verify ──
sr, d = wavfile.read('data/clip.wav')
assert sr == FS and d.dtype == np.int16 and len(d) == n_samples
hop = NPERSEG - NOVERLAP
if BOUNDARY is None and not PADDED:
    assert n_frames == (n_samples - NPERSEG) // hop + 1
if ONESIDED:
    assert n_bins == NFFT // 2 + 1

print(f'WAV: {n_samples} samples, sr={FS}, dtype=int16')
print(f'STFT: {n_frames} frames x {n_bins} bins')
print('Done: data/clip.wav, data/mag.csv')
```

## 8. End-to-End Self-Verification

After building the pipeline, verify:

### 8.1 WAV
- [ ] `clip.wav` exists, readable, correct sample rate
- [ ] Sample count = `int(fs × duration)`
- [ ] dtype is int16
- [ ] RMS within tolerance of target

### 8.2 mag.csv
- [ ] Correct header: `frame,bin,val`
- [ ] Row count = `n_frames × n_bins`
- [ ] Values are linear magnitudes ≥ 0
- [ ] Spot-check: recompute 3 values from STFT and compare

### 8.3 peaks.csv
- [ ] Correct header matching task schema
- [ ] One row per frame, K+1 columns per row
- [ ] Bin indices valid (0 ≤ bin < n_bins)
- [ ] Descending magnitude order within each frame

### 8.4 Shell script
- [ ] Executable (`chmod +x`)
- [ ] Full run produces all three outputs
- [ ] `PEAKS_ONLY=1` reads `mag.csv` and produces `peaks.csv` only

### 8.5 Spot-Check Script

```python
import csv, numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# Verify mag.csv against re-read WAV
sr, sig = wavfile.read('data/clip.wav')
sig_f = sig.astype(np.float64) / 32767.0
_, _, Zxx = stft(sig_f, fs=sr, window='<WINDOW>', nperseg=<NPERSEG>,
                  noverlap=<NOVERLAP>, nfft=<NFFT>,
                  boundary=None, padded=False, return_onesided=True)
mag = np.abs(Zxx)

with open('data/mag.csv') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        fr, bi, vl = int(row['frame']), int(row['bin']), float(row['val'])
        import math
        assert math.isclose(vl, float(mag[bi, fr]), rel_tol=1e-9, abs_tol=1e-12), \
            f"Row {i}: mag[{bi},{fr}] = {mag[bi,fr]} vs csv {vl}"

# Verify peaks.csv against mag.csv
frame_mags = {}
with open('data/mag.csv') as f:
    for row in csv.DictReader(f):
        fr, bn, vl = int(row['frame']), int(row['bin']), float(row['val'])
        frame_mags.setdefault(fr, []).append((vl, bn))

with open('data/peaks.csv') as f:
    for row in csv.DictReader(f):
        fr = int(row['frame'])
        peak_bins = [int(row[c]) for c in sorted(row) if c.endswith('_bin')]
        expected = [b for _, b in sorted(frame_mags[fr], key=lambda x: (-x[0], x[1]))[:len(peak_bins)]]
        assert peak_bins == expected, f"Frame {fr}: {peak_bins} != {expected}"

print("All checks passed!")
```

## 9. Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| `noise_std=0.01` → residual too quiet | Use `noise_std=0.05` as default |
| STFT on pre-quantization float → mag mismatch | Compute STFT on `signal_int16 / 32767.0` |
| `echo header > file` then `awk >> file` → double header with stub | awk writes header+data via `>` |
| `wavfile.write(float)` → IEEE float WAV | Convert to `np.int16` first |
| STFT on int16 numpy array → wrong scaling | Convert to float64 / 32767.0 first |
| `np.arange(n_samples) / fs` rounding | `int(fs * duration)` is exact for typical values |
| `scipy.signal.stft` default boundary is `'zeros'` | Explicitly pass `boundary=None` |
| peaks.csv from Python | **Forbidden** — must come from awk |
| awk absolute path | Use `awk` (PATH lookup) |
| Forgetting `chmod +x` | Always chmod the shell script |

## 10. Generalization Notes

- **Top-K:** The awk template generates the header dynamically from K. Change
  `-v K=N` in the shell script.
- **CSV schema:** If column names change, update both the awk `BEGIN` header
  generation and the awk field parsing.
- **Window/segment changes:** The Python STFT call adapts directly.
- **Amplitude envelopes:** Apply before RMS normalization.
- **dB magnitude:** `20 * np.log10(np.abs(Zxx) + 1e-10)`.
- **Boundary/padding:** If not `None`/`False`, use `len(t_axis)` for frame
  count instead of the manual formula.

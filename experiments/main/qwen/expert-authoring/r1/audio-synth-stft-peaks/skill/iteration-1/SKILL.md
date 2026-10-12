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

The three variation axes from `spec.yaml` are **signal parameters**, **STFT
configuration**, and **peak-extraction logic**. All three are specified in the
task YAML; nothing is assumed from the seed.

## 2. Parameter Extraction Strategy

Before writing any code, parse the task YAML for every numerical parameter.
Create a checklist and cross off each value. Missing values must raise a red
flag — never guess silently.

### 2.1 Synthesis Parameters

| Parameter | Where to look | Typical range |
|-----------|---------------|---------------|
| `sample_rate` (Hz) | "mono, N kHz" or "fs=N" | 8000–48000 |
| `duration` (seconds) | "exactly N seconds" | 1–10 |
| `frequencies` (Hz list) | "sines at [...]" | any |
| `tone_count` | implicit from frequency list | 1–10 |
| `noise_type` | "Gaussian noise", "dither" | normal or uniform |
| `noise_std` or `noise_amp` | noise specification | varies |
| `rms_target` | "RMS-normalize to N" | 0.05–0.5 |
| `rms_tolerance` | "± N" | 0.001–0.01 |
| `bit_depth` | "PCM int16", "16-bit" | 16 |
| `random_seed` | optional; may not be specified | integer or absent |

### 2.2 STFT Parameters

| Parameter | Where to look | Typical range |
|-----------|---------------|---------------|
| `window` | "window='name'" | hann, hamming, blackman, … |
| `nperseg` | segment size | 128–4096 |
| `noverlap` | overlap size | 0 to nperseg-1 |
| `nfft` | FFT size (≥ nperseg) | 256–8192 |
| `boundary` | "boundary=None" or "boundary='zeros'" | None or 'zeros' |
| `padded` | "padded=False" or "padded=True" | bool |
| `return_onesided` | "one-sided" or explicit True | bool |
| `fs` | passed to stft | same as sample_rate |
| `magnitude_type` | "linear magnitude" vs "dB" | linear or dB |
| `csv_schema` | column names for mag.csv | frame,bin,val typical |

### 2.3 Peak-Extraction Parameters

| Parameter | Where to look | Typical range |
|-----------|---------------|---------------|
| `top_k` | "top N spectral bins" | 1–10 |
| `output_schema` | column names for peaks.csv | frame,f1_bin,...,fk_bin |
| `sort_order` | "descending" | descending typical |
| `awk_invocation` | "invoke awk as `awk`" | always `awk` (PATH) |
| `mode_flag` | "PEAKS_ONLY=1" | env var name varies |

## 3. WAV Synthesis (`audioproc.py`)

### 3.1 Signal Generation

```python
import numpy as np

# --- Parameters from task (replace with actual values) ---
fs = <SAMPLE_RATE>
duration = <DURATION>
freqs = <FREQUENCY_LIST>   # e.g. [180, 360, 540, 720]
noise_std = <NOISE_STD>    # check task for value or "small dither"
rms_target = <RMS_TARGET>

n_samples = int(fs * duration)
t = np.arange(n_samples) / fs

# Sum of sines
signal = np.zeros(n_samples, dtype=np.float64)
for f in freqs:
    signal += np.sin(2 * np.pi * f * t)

# Add noise (Gaussian unless specified otherwise)
np.random.seed(<SEED>)  # only if task specifies a seed
noise = np.random.normal(0, noise_std, n_samples)
signal += noise
```

**Decision rules:**
- `int(fs * duration)` truncates; verify with `len(t) == int(fs * duration)`.
- If no random seed is specified, omit `np.random.seed()` — accept non-deterministic noise.
- If noise is described as "dither" with no amplitude, use a small std (e.g. 0.01–0.05).

### 3.2 RMS Normalization

```python
rms = np.sqrt(np.mean(signal ** 2))
signal = signal * (rms_target / rms)

# Verify
rms_check = np.sqrt(np.mean(signal ** 2))
assert abs(rms_check - rms_target) < <RMS_TOLERANCE>, f"RMS {rms_check} out of tolerance"
```

**Decision rules:**
- Always normalize **before** int16 quantization (task says "Normalize before 16-bit quantization").
- Compute RMS on the full float64 signal.
- If `rms_target` is small enough (< 0.5 typically), clipping to [-1, 1] before int16 conversion is unlikely but should still be done for safety.

### 3.3 Int16 Quantization and WAV Save

```python
from scipy.io import wavfile
import os

os.makedirs('data', exist_ok=True)

# Clip to prevent overflow
signal_clipped = np.clip(signal, -1.0, 1.0)
signal_int16 = np.round(signal_clipped * 32767).astype(np.int16)

wavfile.write('data/clip.wav', fs, signal_int16)
```

**Critical pitfall:** `scipy.io.wavfile.write` with float input writes IEEE float WAV, **not** PCM int16. Always convert to `np.int16` first.

### 3.4 Self-Verification for WAV

```python
sr_read, data_read = wavfile.read('data/clip.wav')
assert sr_read == fs, f"Sample rate mismatch: {sr_read} vs {fs}"
assert data_read.dtype == np.int16, f"Expected int16, got {data_read.dtype}"
assert len(data_read) == n_samples, f"Sample count mismatch: {len(data_read)} vs {n_samples}"

# Verify RMS of the saved signal
rms_saved = np.sqrt(np.mean((data_read.astype(np.float64) / 32767.0) ** 2))
assert abs(rms_saved - rms_target) < <RMS_TOLERANCE>, f"Saved RMS {rms_saved} out of tolerance"
```

## 4. STFT Computation (`audioproc.py` continued)

### 4.1 scipy.signal.stft Call

```python
from scipy.signal import stft

# Parameters from task
win = '<WINDOW>'          # e.g. 'blackman', 'hann'
nperseg = <NPERSEG>
noverlap = <NOVERLAP>
nfft = <NFFT>
boundary_val = <BOUNDARY>  # None or 'zeros' etc.
padded_val = <PADDED>      # True or False
one_sided = <ONESIDED>     # True or False

f_axis, t_axis, Zxx = stft(
    signal,            # use the float signal, NOT the int16 version
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

**Decision rules:**
- Compute STFT on the **float** normalized signal (after RMS normalization, before int16 conversion). This is the standard signal-processing approach.
- If `boundary=None` and `padded=False`, frame count = `(n_samples - nperseg) // (nperseg - noverlap) + 1`.
- One-sided output: `n_bins = nfft // 2 + 1`.

### 4.2 Magnitude CSV Export

```python
import csv

n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

with open('data/mag.csv', 'w', newline='') as fout:
    writer = csv.writer(fout)
    writer.writerow(['frame', 'bin', 'val'])  # check task for exact schema
    for frame_idx in range(n_frames):
        for bin_idx in range(n_bins):
            mag = float(np.abs(Zxx[bin_idx, frame_idx]))
            writer.writerow([frame_idx, bin_idx, mag])
```

**Decision rules:**
- Use **linear magnitude** (`np.abs(Zxx)`) unless the task specifies dB.
- CSV rows must be ordered frame-major (all bins of frame 0, then frame 1, …). This ordering is critical for the streaming awk approach.
- Use `float()` to avoid numpy scalar types in CSV output.
- Match the exact column names from the task (typically `frame,bin,val`).

### 4.3 Self-Verification for STFT

```python
# Verify frame count
hop = nperseg - noverlap
if boundary_val is None and not padded_val:
    expected_frames = (n_samples - nperseg) // hop + 1
    assert n_frames == expected_frames, f"Frame count: {n_frames} vs expected {expected_frames}"

# Verify bin count
if one_sided:
    expected_bins = nfft // 2 + 1
    assert n_bins == expected_bins, f"Bin count: {n_bins} vs expected {expected_bins}"

# Spot-check a magnitude value
import cmath
# The STFT at frame 0, bin 0 should match manual computation
manual_seg = signal[:nperseg] * scipy.signal.get_window(win, nperseg)
manual_dft_0 = np.sum(manual_seg * np.exp(-2j * np.pi * 0 * np.arange(nperseg) / nfft))
assert abs(abs(manual_dft_0) - np.abs(Zxx[0, 0])) < 1e-10, "STFT magnitude mismatch at (0,0)"
```

## 5. AWK Peak Extraction

### 5.1 Strategy

The awk script must:
1. Read `mag.csv` (skip header).
2. Group rows by frame number.
3. For each frame, find the top-K bins by magnitude (descending).
4. Output one row per frame with the top-K bin indices.

**Assumption:** `mag.csv` is sorted by frame (frame-major output from Python). This allows a streaming approach that only holds one frame in memory at a time.

### 5.2 Template (Parameterized by top_k)

```awk
# extract_peaks.awk
# Usage: awk -f extract_peaks.awk data/mag.csv >> data/peaks.csv
# (header is written by the shell script before invoking awk)

BEGIN {
    FS  = ","
    K   = <TOP_K>       # replaced by task value, e.g. 3
    cur = -1
    cnt = 0
}

NR == 1 { next }   # skip CSV header

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
    # Partial selection sort: find top K descending
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
    # Output: frame, bin1, bin2, ..., binK
    printf "%d", cur
    for (i = 1; i <= K && i <= cnt; i++) printf ",%d", bins[i]
    printf "\n"
}
```

**Decision rules:**
- Partial selection sort is O(K × B) per frame where B = bins per frame. For typical K=3, B=513, this is ~1539 comparisons/frame — very fast.
- The streaming approach (`flush()` on frame change) avoids storing the entire CSV in memory.
- The awk script must **not** print its own header; the shell script writes the header before awk runs.
- Invoke as `awk -f script.awk mag.csv`, **not** with an absolute awk path.
- For tie-breaking: selection sort naturally picks the lower-indexed bin first when values are equal (since `>` not `>=` is used). If the task requires different tie-breaking, adjust the comparison.

### 5.3 Non-Streaming Alternative (Unsorted CSV)

If `mag.csv` might not be frame-sorted, use the batch approach:

```awk
BEGIN { FS=","; K=<TOP_K> }
NR==1 { next }
{
    f=$1+0; b=$2+0; v=$3+0
    if (!(f in n)) { n[f]=0; nf++; flist[nf]=f }
    n[f]++
    bins[f, n[f]] = b
    vals[f, n[f]] = v
}
END {
    # Sort frame list
    for (i=2; i<=nf; i++) {
        key=flist[i]; j=i-1
        while (j>=1 && flist[j]>key) { flist[j+1]=flist[j]; j-- }
        flist[j+1]=key
    }
    for (fi=1; fi<=nf; fi++) {
        f=flist[fi]; c=n[f]
        for (i=1; i<=c; i++) { tb[i]=bins[f,i]; tv[i]=vals[f,i] }
        for (i=1; i<=K && i<=c; i++) {
            mx=i
            for (j=i+1; j<=c; j++) if (tv[j]>tv[mx]) mx=j
            if (mx!=i) {
                t=tv[i]; tv[i]=tv[mx]; tv[mx]=t
                t=tb[i]; tb[i]=tb[mx]; tb[mx]=t
            }
        }
        printf "%d", f
        for (i=1; i<=K; i++) printf ",%d", tb[i]
        printf "\n"
    }
}
```

## 6. Shell Script (`run_audio_pipeline.sh`)

### 6.1 Template

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data

# ── PEAKS_ONLY mode ──
if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    # Only run peak extraction from existing mag.csv
    HEADER="frame,<f1_bin>,<f2_bin>,<f3_bin>"  # adjust columns to task spec
    echo "$HEADER" > data/peaks.csv
    awk -f extract_peaks.awk data/mag.csv >> data/peaks.csv
    exit 0
fi

# ── Full pipeline ──
# Step 1: Synthesize WAV and compute STFT
python3 audioproc.py

# Step 2: Extract peaks
HEADER="frame,<f1_bin>,<f2_bin>,<f3_bin>"  # adjust columns to task spec
echo "$HEADER" > data/peaks.csv
awk -f extract_peaks.awk data/mag.csv >> data/peaks.csv
```

**Decision rules:**
- `set -euo pipefail` ensures errors are caught immediately.
- `PEAKS_ONLY` must read from `data/mag.csv` (not re-run Python).
- The awk script file (`extract_peaks.awk`) should be alongside the shell script, **or** the awk code can be inlined as a single-quoted string in the shell script. Inlining avoids needing a separate file.
- The `cd "$(dirname "$0")"` ensures the script runs from its own directory, so relative paths to `data/` work regardless of the caller's working directory.
- Header columns must exactly match the task specification.

### 6.2 Inline AWK Variant

If you prefer not to create a separate `.awk` file, inline the awk program:

```bash
awk -F, '
NR==1{next}
{
    frame=$1+0; bin=$2+0; val=$3+0
    if(frame!=cur){
        if(cur>=0) flush()
        cur=frame; cnt=0
    }
    cnt++; bins[cnt]=bin; vals[cnt]=val
}
END{if(cur>=0)flush()}
function flush(    i,j,mx,tb,tv){
    for(i=1;i<=3&&i<=cnt;i++){
        mx=i
        for(j=i+1;j<=cnt;j++) if(vals[j]>vals[mx]) mx=j
        if(mx!=i){
            tv=vals[i];vals[i]=vals[mx];vals[mx]=tv
            tb=bins[i];bins[i]=bins[mx];bins[mx]=tb
        }
    }
    printf "%d,%d,%d,%d\n",cur,bins[1],bins[2],bins[3]
}' data/mag.csv
```

## 7. Directory Structure Verification

After running the pipeline, verify:

```
/app/
├── audioproc.py          # Python: produces clip.wav and mag.csv only
├── run_audio_pipeline.sh # Shell: orchestrates pipeline
├── extract_peaks.awk     # (optional) AWK script, or inlined in shell script
└── data/
    ├── clip.wav          # PCM int16 WAV
    ├── mag.csv           # STFT magnitude spectrogram
    └── peaks.csv         # Top-K peaks per frame
```

**Constraint from spec:** `audioproc.py` must **only** produce `clip.wav` and `mag.csv`. It must **not** produce `peaks.csv`. The peak extraction is exclusively the awk/shell stage's responsibility.

## 8. End-to-End Self-Verification Checklist

Run through this checklist after building the pipeline:

### 8.1 WAV Verification
- [ ] `clip.wav` exists and is readable
- [ ] Sample rate matches task spec
- [ ] Duration matches task spec (sample count = `int(fs * duration)`)
- [ ] Bit depth is 16-bit (PCM int16)
- [ ] RMS of saved signal is within tolerance of target

### 8.2 mag.csv Verification
- [ ] `mag.csv` exists with correct header
- [ ] Row count = `n_frames × n_bins`
- [ ] Frame indices are 0-based, contiguous
- [ ] Bin indices are 0-based, contiguous per frame
- [ ] Values are linear magnitudes (≥ 0)
- [ ] Spot-check 3 random values against direct scipy STFT computation

### 8.3 peaks.csv Verification
- [ ] `peaks.csv` exists with correct header
- [ ] Row count = `n_frames` (one row per frame)
- [ ] Each row has exactly K+1 columns (frame + K bins)
- [ ] Bin indices are valid (0 ≤ bin < n_bins)
- [ ] Peaks are in descending magnitude order within each frame
- [ ] Spot-check 3 frames: recompute top-K from mag.csv and compare

### 8.4 Shell Script Verification
- [ ] `run_audio_pipeline.sh` is executable (`chmod +x`)
- [ ] Full run produces all three outputs
- [ ] `PEAKS_ONLY=1` run only reads `mag.csv` and produces `peaks.csv`
- [ ] `PEAKS_ONLY=1` works correctly when `clip.wav` does not exist (only needs `mag.csv`)

### 8.5 Spot-Check Script

```python
# Quick verification script (run after pipeline)
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile
import csv

# 1. Verify WAV
sr, wav_data = wavfile.read('data/clip.wav')
assert wav_data.dtype == np.int16
assert sr == <FS>
rms = np.sqrt(np.mean((wav_data.astype(np.float64) / 32767.0) ** 2))
print(f"WAV: sr={sr}, samples={len(wav_data)}, dtype={wav_data.dtype}, rms={rms:.6f}")

# 2. Verify peaks against mag.csv
with open('data/mag.csv') as f:
    reader = csv.DictReader(f)
    frame_mags = {}
    for row in reader:
        fr = int(row['frame'])
        bn = int(row['bin'])
        vl = float(row['val'])
        if fr not in frame_mags:
            frame_mags[fr] = []
        frame_mags[fr].append((vl, bn))

with open('data/peaks.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        fr = int(row['frame'])
        # Get top-k bin names from the row
        peak_bins = [int(row[c]) for c in row if c.startswith('f') and c.endswith('_bin')]
        # Compare with recomputed top-k
        mags = sorted(frame_mags[fr], key=lambda x: (-x[0], x[1]))
        expected_bins = [b for _, b in mags[:len(peak_bins)]]
        assert peak_bins == expected_bins, f"Frame {fr}: {peak_bins} != {expected_bins}"

print("All spot-checks passed!")
```

## 9. Common Pitfalls

| Pitfall | How to avoid |
|---------|-------------|
| Writing float32 to WAV → IEEE float format, not PCM | Always `np.round(sig * 32767).astype(np.int16)` before `wavfile.write` |
| Computing STFT on int16 signal → quantization noise | Compute STFT on the float normalized signal |
| Using `>` instead of `>=` in awk sort | `>` gives stable first-encountered ordering for ties (lower bin index wins) — usually desired |
| awk header collision | Let the shell script write the header; awk only outputs data rows |
| `np.arange(n_samples) / fs` rounding | `int(fs * duration)` is exact for integer seconds; verify `len(t)` |
| Forgetting `os.makedirs('data', exist_ok=True)` | Always create the output directory |
| Shell script not `chmod +x` | `chmod +x run_audio_pipeline.sh` after creation |
| awk absolute path | Always invoke as `awk` (relying on PATH), never `/usr/bin/awk` |
| STFT `boundary` default is `'zeros'` | Explicitly pass `boundary=` parameter to `stft()` |
| peaks.csv from Python | **Forbidden** — peaks.csv must come from the awk stage |

## 10. Generalization Notes

- The **top-K** value is parameterizable. The awk template uses a `K` variable. Adjust the output header and printf format accordingly.
- If the task changes the **CSV schema** (e.g., different column names), update the awk `FS` parsing and the shell script header.
- If the task changes **window type** or **nperseg/noverlap/nfft**, the Python STFT call adapts directly — no structural changes needed.
- If the task adds **amplitude envelopes** (e.g., ADSR, fade-in/out), apply them to the float signal before RMS normalization.
- If the task specifies **dB magnitude** instead of linear, convert: `mag_db = 20 * np.log10(np.abs(Zxx) + 1e-10)`.
- If `boundary` is not `None` or `padded` is `True`, the frame count formula changes — use `len(t_axis)` from scipy's return value rather than manual calculation.

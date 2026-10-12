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

## 1. Overview and Critical Rules

Two-stage pipeline producing three artifacts:

| Stage | Producer | Output |
|-------|----------|--------|
| Synthesis + STFT | `audioproc.py` (Python) | `data/clip.wav`, `data/mag.csv` |
| Peak extraction | `awk` (shell) | `data/peaks.csv` |
| Orchestration | `run_audio_pipeline.sh` | drives both stages |

**Three non-negotiable rules** (read before writing any code):

1. **`noise_std = 0.05`** when task says "Gaussian noise" without specifying amplitude.
   Smaller values (0.01–0.03) produce residuals too quiet for test validation.
2. **STFT must run on the WAV-equivalent signal** (`signal_int16 / 32767.0`),
   NOT the pre-quantization float. Tests re-read clip.wav and compare magnitudes
   at `abs_tol=1e-9`; using the original float produces ~1e-7 mismatches.
3. **awk writes the complete peaks.csv** (header + data) via `>` (overwrite).
   The shell script must NOT write the header with `echo` — this causes a
   double-header when tests inject a stub awk.

## 2. Parameter Extraction

Parse the task YAML for every parameter before writing code. Use these defaults
when values are not specified:

| Parameter | Default when absent | Notes |
|-----------|---------------------|-------|
| `noise_std` | **0.05** | See rule #1 above |
| `rms_tolerance` | 0.002 | |
| `boundary` | `None` | scipy default is `'zeros'` — always pass explicitly |
| `padded` | `False` | |
| `return_onesided` | `True` | |
| `top_k` | 3 | |
| `csv_schema` (mag) | `frame,bin,val` | |
| `csv_schema` (peaks) | `frame,f1_bin,...,fk_bin` | |
| `mode_flag` | `PEAKS_ONLY` | env var, value `"1"` |

All other parameters (sample_rate, duration, frequencies, window, nperseg,
noverlap, nfft, rms_target) are **required** from the task.

## 3. Complete `audioproc.py` Template

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

WINDOW = '<WINDOW>'          # e.g. 'blackman', 'hann'
NPERSEG = <NPERSEG>          # e.g. 768
NOVERLAP = <NOVERLAP>        # e.g. 576
NFFT = <NFFT>                # e.g. 1024
BOUNDARY = None              # or 'zeros' etc. — always pass explicitly
PADDED = False
ONESIDED = True

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

# ── Step 2: RMS normalize (before int16 quantization) ──
rms = np.sqrt(np.mean(signal ** 2))
signal *= (RMS_TARGET / rms)
assert abs(np.sqrt(np.mean(signal ** 2)) - RMS_TARGET) < RMS_TOLERANCE

# ── Step 3: Quantize and save WAV ──
# wavfile.write with float → IEEE float WAV, NOT PCM. Must use int16.
signal_int16 = np.round(np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
wavfile.write('data/clip.wav', FS, signal_int16)

# ── Step 4: STFT on the WAV-equivalent signal ──
# CRITICAL: tests re-read clip.wav and run STFT to verify mag.csv.
# Must use the int16-equivalent float, not the pre-quantization signal.
signal_for_stft = signal_int16.astype(np.float64) / 32767.0

f_axis, t_axis, Zxx = stft(
    signal_for_stft,
    fs=FS, window=WINDOW, nperseg=NPERSEG, noverlap=NOVERLAP,
    nfft=NFFT, boundary=BOUNDARY, padded=PADDED,
    return_onesided=ONESIDED,
)
n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

# ── Step 5: Write magnitude CSV (frame-major order) ──
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

## 4. Complete `run_audio_pipeline.sh` Template (Inline AWK)

The awk program is inlined in the shell script. This avoids needing a separate
`.awk` file and is the recommended approach.

**CRITICAL:** awk writes the complete file (header in `BEGIN` + data rows) via
`>` (overwrite). The shell script does NOT write any header.

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

**Adaptation notes:**
- Replace `-v K=3` with the task's actual top-K value.
- Replace `echo "Done: data/peaks.csv"` at end if desired (optional).
- `chmod +x run_audio_pipeline.sh` after creation.
- Invoke as `awk` (PATH lookup), never an absolute path.

## 5. AWK Algorithm Details

The streaming peak extraction uses partial selection sort, O(K × B) per frame:

- **Input:** `mag.csv` with schema `frame,bin,val` (frame-major order).
- **Grouping:** Detects frame boundaries; flushes previous frame on change.
- **Sorting:** Finds top-K by descending magnitude via partial selection sort.
- **Tie-breaking:** `>` (strict) preserves lower-indexed bin for equal values.
- **Header:** Generated in `BEGIN` block, adapts to any K.
- **Output:** One row per frame: `frame,f1_bin,f2_bin,...,fk_bin`.

## 6. Directory Structure

```
/app/
├── audioproc.py              # produces clip.wav and mag.csv ONLY
├── run_audio_pipeline.sh     # orchestrates pipeline (chmod +x)
└── data/
    ├── clip.wav              # PCM int16 WAV
    ├── mag.csv               # STFT magnitude spectrogram
    └── peaks.csv             # Top-K peaks per frame (from awk)
```

**Hard constraint:** `audioproc.py` must NOT produce `peaks.csv`.

## 7. Self-Verification Checklist

After building the pipeline:

- [ ] `clip.wav`: correct sr, `int(fs×duration)` samples, int16, RMS in tolerance
- [ ] `mag.csv`: header `frame,bin,val`, rows = `n_frames × n_bins`, values ≥ 0
- [ ] `peaks.csv`: correct header, one row per frame, K+1 columns, valid bins
- [ ] `run_audio_pipeline.sh`: executable, full run and PEAKS_ONLY=1 both work
- [ ] Spot-check 3 mag.csv values against `stft(wavfile.read('data/clip.wav'))`
- [ ] Spot-check 3 peaks.csv rows against top-K recomputed from mag.csv

## 8. Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| `noise_std=0.01` → residual too quiet | Use `noise_std=0.05` as default |
| STFT on pre-quantization float → mag mismatch | Compute STFT on `signal_int16 / 32767.0` |
| `echo header > file` then `awk >> file` → double header with stub | awk writes header+data via `>` |
| `wavfile.write(float)` → IEEE float WAV | Convert to `np.int16` first |
| STFT on raw int16 array → wrong scaling | Convert to `float64 / 32767.0` first |
| `scipy.signal.stft` default boundary is `'zeros'` | Explicitly pass `boundary=None` |
| peaks.csv from Python | **Forbidden** — must come from awk |
| awk absolute path | Use `awk` (PATH lookup) |

## 9. Generalization

- **Top-K:** Change `-v K=N` in shell script; awk header adapts automatically.
- **CSV schema:** Update awk `BEGIN` header generation and shell script.
- **Window/segment changes:** Python STFT call adapts directly.
- **Amplitude envelopes:** Apply before RMS normalization.
- **dB magnitude:** `20 * np.log10(np.abs(Zxx) + 1e-10)`.
- **Boundary/padding:** If not `None`/`False`, use `len(t_axis)` for frame count.

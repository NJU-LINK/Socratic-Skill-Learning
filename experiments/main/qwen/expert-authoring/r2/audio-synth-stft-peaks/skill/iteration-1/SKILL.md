---
name: audio-synth-stft-peaks
description: >
  Build a reproducible audio-processing pipeline that synthesizes a WAV file
  from sine tones plus noise, computes an STFT via scipy, and extracts the
  top-k spectral peaks per frame using awk. Covers parameter extraction from
  task.yaml, WAV synthesis with RMS normalization, scipy STFT configuration,
  magnitude CSV export, shell/awk peak extraction, and PEAKS_ONLY mode.
---

# Audio Synth → STFT → Peaks Pipeline

## Family Overview

This task family requires building a three-stage audio pipeline:

1. **Synthesize** a deterministic mono WAV (sum of sines + noise, RMS-normalized, PCM int16).
2. **Compute STFT** with `scipy.signal.stft` and export a magnitude CSV (`frame,bin,val`).
3. **Extract top-k peaks** per frame using `awk` (not Python), producing a peaks CSV.

An orchestration shell script ties the stages together and must support a
`PEAKS_ONLY=1` mode that skips synthesis/STFT and only runs the awk step.

## Step 0 — Parse the Task Specification

Read `task.yaml` (or the task instructions) and extract **every numeric and
string parameter**. Do NOT assume default values; the variant under test may
differ from the seed. Build a checklist:

| Parameter Group | Keys to Extract |
|---|---|
| **Signal** | `fs` (sample rate), `duration` (seconds), `freqs` (list of Hz), noise seed/scale, `rms_target` |
| **STFT** | `window`, `nperseg`, `noverlap`, `nfft`, `boundary`, `padded`, `return_onesided` |
| **Peaks** | top-k count, output column names, tie-breaking rule, sort order |
| **Files** | output paths for `.wav`, `mag.csv`, `peaks.csv`, script names |
| **Modes** | `PEAKS_ONLY` env var name and value |

Store these in clearly named constants at the top of `audioproc.py` and in
shell variables in the orchestration script so they are easy to audit.

## Step 1 — Synthesize the WAV (`audioproc.py`)

### 1a. Waveform Generation

```
n_samples = int(fs * duration)
t = np.arange(n_samples) / fs
signal = sum(sin(2π·f·t) for f in freqs)
```

- Use `np.float64` throughout for precision.
- Add reproducible Gaussian noise: seed a `np.random.RandomState(seed)` and
  add `rng.randn(n_samples) * noise_scale`. The noise scale is typically
  small (e.g. 0.02) — check the task spec.

### 1b. RMS Normalization (Before Quantization)

```python
rms = np.sqrt(np.mean(signal ** 2))
signal = signal * (rms_target / rms)
```

**Invariant**: Normalize the *float* signal to the target RMS **before**
clipping and int16 conversion. This is a common error point — normalizing
after quantization produces incorrect RMS.

### 1c. Quantization and WAV Write

```python
signal = np.clip(signal, -1.0, 1.0)
int_data = (signal * 32767).astype(np.int16)
```

Write with the `wave` module: mono (1 channel), sample width 2 bytes,
framerate = `fs`. Save to the specified path (e.g. `data/clip.wav`).

### 1d. Self-Verification (Recommended)

After writing, read back the WAV and check:
- Channel count, sample width, frame rate match spec.
- Frame count == `int(fs * duration)`.
- RMS of the int16 samples (converted back to float) is within tolerance
  of `rms_target` (typically ±0.002).

Print these diagnostics to stdout so tests can observe them.

## Step 2 — Compute the STFT and Export Magnitude CSV

### 2a. Read Back the WAV

Re-read the saved WAV file to ensure the STFT operates on exactly what was
persisted (avoids floating-point drift between generation and analysis):

```python
with wave.open(wav_path, 'rb') as wf:
    raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767.0
```

### 2b. Call `scipy.signal.stft`

Pass **all** parameters exactly as specified in the task. Common parameters:

```python
f, t, Zxx = scipy.signal.stft(
    samples,
    fs=fs,
    window=window,        # e.g. 'hann', 'blackman'
    nperseg=nperseg,
    noverlap=noverlap,
    nfft=nfft,
    boundary=boundary,    # None or a string like 'zeros'
    padded=padded,        # True or False
    return_onesided=return_onesided,
)
```

**Key**: `return_onesided=True` for real signals produces `nfft//2 + 1` bins.
With `nfft=1024` that's 513 bins.

### 2c. Export Linear Magnitude CSV

```python
magnitude = np.abs(Zxx)  # linear magnitude, NOT dB
```

CSV schema: `frame,bin,val` — one header row, then one row per (frame, bin)
pair. Frame index is 0-based, bin index is 0-based, value is the linear
magnitude in scientific notation (e.g. `1.2345678901e-04`).

```python
for frame_idx in range(n_frames):
    for bin_idx in range(n_bins):
        f.write(f'{frame_idx},{bin_idx},{magnitude[bin_idx, frame_idx]:.10e}\n')
```

**Note**: `Zxx` shape is `(n_bins, n_frames)` — index as `Zxx[bin, frame]`.

### 2d. Sanity Checks

- Total data rows = `n_frames × n_bins`.
- `n_frames` depends on signal length, `nperseg`, and `noverlap`:
  `n_frames = (n_samples - nperseg) // (nperseg - noverlap) + 1` when
  `boundary=None, padded=False`.
- Print frame count and bin count for verification.

## Step 3 — Extract Peaks with Awk

### 3a. Architecture Rule

**`audioproc.py` must NOT produce `peaks.csv`.** The peak extraction is
exclusively done by `awk` invoked from the shell script. This is a family
invariant.

### 3b. Awk Top-k Selection Algorithm

For each frame, maintain the top-k (val, bin) pairs via insertion sort.
The default tie-breaking rule is: **higher magnitude wins; on equal
magnitude, lower bin index wins** (confirm from task spec).

Generic awk pattern for top-k (illustrated for k=3):

```awk
BEGIN { FS="," }
NR == 1 { next }
{
    frame = $1 + 0
    bin   = $2 + 0
    val   = $3 + 0.0
    # accumulate per frame
    ...
}
END {
    # for each frame, output top-k bins in descending magnitude order
}
```

**Selection sort approach** (robust for small k):
- Maintain k slots: `(v1,b1), (v2,b2), ..., (vk,bk)` initialized to -1.
- For each entry, compare against slot 1 first; if it beats slot 1, shift
  slots down and insert. Otherwise compare against slot 2, etc.
- Comparison: `v > v_slot || (v == v_slot && b < b_slot)`.

**Important awk detail**: Scientific notation (`1.23e-05`) is parsed
correctly by `+0.0` in both `gawk` and `mawk`. Do not use string comparison
for magnitudes.

### 3c. Output Format

Typical schema: `frame,f1_bin,f2_bin,f3_bin` (header), one row per frame,
bins listed in descending magnitude order (f1 = highest magnitude bin).

### 3d. Invoking Awk

- Use `awk` (not an absolute path) — rely on PATH.
- Both `mawk` and `gawk` must work. The awk code above is POSIX-compatible
  except for associative arrays (used for frame tracking), which both support.

## Step 4 — Orchestration Shell Script

### 4a. Structure

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /app
mkdir -p data

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
    # awk-only path
    awk '...' data/mag.csv > data/peaks.csv
    exit 0
fi

# Full pipeline
python3 audioproc.py
awk '...' data/mag.csv > data/peaks.csv
```

### 4b. PEAKS_ONLY Mode

When `PEAKS_ONLY=1` is set:
- Read existing `data/mag.csv`.
- Run only the awk peak extraction.
- Write `data/peaks.csv`.
- Exit immediately without running Python.

This is a **required feature**, not optional. Tests will invoke it.

### 4c. Make Executable

```bash
chmod +x /app/run_audio_pipeline.sh
```

## Step 5 — Self-Verification Checklist

Run these checks before considering the task complete:

| Check | Command |
|---|---|
| WAV properties | Read back with `wave` module: channels, sampwidth, framerate, nframes |
| RMS tolerance | `np.sqrt(np.mean(samples**2))` within ±0.002 of target |
| mag.csv row count | Should equal `n_frames × n_bins + 1` (header) |
| peaks.csv row count | Should equal `n_frames + 1` (header) |
| Peak ordering | For every frame: `val[f1] >= val[f2] >= val[f3]` |
| Peak correctness | Cross-validate a few frames with Python `sorted()` |
| PEAKS_ONLY mode | Delete peaks.csv, run with `PEAKS_ONLY=1`, verify output |
| Awk invocation | `grep -c '/usr/bin/awk\|/usr/bin/gawk\|/usr/bin/mawk' run_audio_pipeline.sh` should be 0 |

## Common Pitfalls

1. **Normalizing after quantization** — Always RMS-normalize the float64 signal
   before clipping and int16 conversion.
2. **STFT axis confusion** — `Zxx` is `(n_bins, n_frames)`, not `(n_frames, n_bins)`.
3. **Peaks from Python** — The task explicitly forbids writing peaks.csv from
   Python. Use awk only.
4. **Absolute awk path** — Use `awk` not `/usr/bin/awk` or `/usr/bin/gawk`.
5. **Missing PEAKS_ONLY** — The shell script must handle this mode; it's tested.
6. **Boundary/padded defaults** — `scipy.signal.stft` defaults to
   `boundary='zeros', padded=True`. The task may require `boundary=None,
   padded=False` — always read from spec.
7. **Off-by-one in frame count** — With `boundary=None, padded=False`, the
   formula is `(N - nperseg) // hop + 1` where `hop = nperseg - noverlap`.
8. **Scientific notation in awk** — Use `$3 + 0.0` to force numeric parsing;
   never compare magnitude strings lexicographically.
9. **Forgetting mkdir -p data** — The `data/` directory may not exist.
10. **int16 overflow** — Always `np.clip(signal, -1.0, 1.0)` before
    `(signal * 32767).astype(np.int16)`.

## Variation Dimensions

### Signal Parameters May Change
- Different `fs` (e.g. 16000, 44100), `duration` (e.g. 3.0, 5.0).
- Different number of tones (3, 5, 6) and frequency sets.
- Different noise scale or seed; possibly different noise distribution.
- Different RMS target (e.g. 0.1, 0.2).
- Possible amplitude envelopes (not just uniform).

### STFT Configuration May Change
- Window type: `'hann'`, `'blackman'`, `'hamming'`, etc.
- `nperseg`, `noverlap`, `nfft` values.
- `boundary` (None, 'zeros', 'reflect', etc.) and `padded` (True/False).
- The CSV schema columns or value format.

### Peak Extraction May Change
- Top-k (e.g. 2, 3, 5 instead of 3).
- Output column names (e.g. `peak1_bin, peak2_bin`).
- Tie-breaking rules (lower bin vs higher bin).
- Additional mode flags or env vars.

**Adaptation rule**: Always read parameters from the task spec. The code
structure (Python for synth+STFT, awk for peaks, shell for orchestration)
is the family invariant; the numeric values are not.

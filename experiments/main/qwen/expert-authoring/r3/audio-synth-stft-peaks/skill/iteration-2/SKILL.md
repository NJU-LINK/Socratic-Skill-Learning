---
name: audio-synth-stft-peaks
description: >
  Build a deterministic audio-processing pipeline that synthesizes a WAV file
  from sine tones plus noise, computes an STFT using scipy, and extracts the
  top-k spectral peaks per frame using awk. Covers WAV synthesis with RMS
  normalization, scipy.signal.stft on float-normalized signals, CSV magnitude
  export, and shell/awk peak selection with PEAKS_ONLY support.
---

# Audio Synthesis + STFT + Peak Extraction Pipeline

## Architecture

```
audioproc.py            # Python: produces clip.wav + mag.csv ONLY
run_audio_pipeline.sh   # Shell: orchestrates pipeline, owns awk peak extraction
data/
  ├── clip.wav          # PCM int16 WAV
  ├── mag.csv           # STFT linear magnitude (frame,bin,val)
  └── peaks.csv         # Top-k peaks per frame (frame,f1_bin,f2_bin,...,fk_bin)
```

**Hard boundary:** `audioproc.py` MUST NOT generate `peaks.csv`. Peak extraction
MUST be performed by `awk` inside the shell script. This is a family invariant.

## Step 1 — WAV Synthesis (in `audioproc.py`)

### Decision Rules

1. Read all task parameters: `fs` (sample rate), `duration`, `freqs` (list of
   sine frequencies), `noise_std`, `rms_target`.
2. Compute sample count: `n_samples = int(fs * duration)`.
3. Build time vector: `t = np.arange(n_samples) / fs`.
4. Synthesize clean signal: `signal = sum(sin(2π·f·t) for f in freqs)`.
5. Generate noise: `noise = np.random.randn(n_samples) * noise_std`.
   - If a seed is specified, call `np.random.seed(seed)` before noise generation.
6. Combine: `noisy = signal + noise`.
7. **RMS normalize BEFORE quantization:**
   ```python
   rms = np.sqrt(np.mean(noisy**2))
   normalized = noisy * (rms_target / rms)
   ```
8. Quantize to int16:
   ```python
   int16_data = np.clip(np.round(normalized * 32767), -32768, 32767).astype(np.int16)
   ```
9. Save with `scipy.io.wavfile.write(path, fs, int16_data)`.

### Choosing noise_std (CRITICAL)

The task typically says "add Gaussian noise" without specifying `noise_std`.
The tests check that the residual (signal minus fitted tones) has a standard
deviation in a specific range (e.g., `0.004 ≤ residual_std ≤ 0.02`).

The noise_std MUST be chosen so that after RMS normalization, the noise
component has std within the test's expected range. Since normalization scales
everything by `rms_target / rms_of_noisy_signal`:

```
post_norm_noise_std ≈ noise_std * (rms_target / rms_of_signal)
```

For a sum of N unit-amplitude sines, `rms_of_signal ≈ sqrt(N/2)`. With
`rms_target = 0.15` and 4 sines: `rms_of_signal ≈ sqrt(2) ≈ 1.414`, so the
scaling factor is `0.15 / 1.414 ≈ 0.106`.

| noise_std | post_norm_noise_std | In range [0.004, 0.02]? |
|-----------|-------------------|------------------------|
| 0.01      | 0.00106           | ❌ TOO LOW             |
| 0.03      | 0.00320           | ❌ Marginal            |
| **0.05**  | **0.00530**       | ✅ **Safe**            |
| 0.07      | 0.00742           | ✅ Safe                |
| 0.10      | 0.01057           | ✅ Safe                |
| 0.20      | 0.02114           | ❌ TOO HIGH            |

**Default to `noise_std = 0.05`** unless the task specifies otherwise. This
gives a comfortable margin within the typical [0.004, 0.02] test range.

### Invariants
- Mono output (1-D array).
- Normalize → then quantize. Never quantize before normalizing.
- Use `os.makedirs(data_dir, exist_ok=True)` to ensure `data/` exists.

## Step 2 — STFT & Magnitude CSV (in `audioproc.py`)

### Decision Rules

1. **CRITICAL — Signal normalization for STFT:**
   Reload the WAV signal and **normalize int16 to float64 in [-1, 1]** before
   computing the STFT. This is the standard scipy convention and what tests
   expect:

   ```python
   rate, data = scipy.io.wavfile.read(wav_path)
   signal = data.astype(np.float64) / 32767.0   # ← MUST divide by 32767!
   ```

   **Do NOT** pass raw int16 values or `data.astype(np.float64)` without
   division. Raw int16 produces magnitudes ~32767× too large and will fail
   tests that compare against a reference STFT computed on float-normalized
   data.

2. Call `scipy.signal.stft` with **all** task-specified parameters:
   ```python
   f, t, Zxx = scipy.signal.stft(
       signal,
       fs=FS,              # sampling rate
       window=WINDOW,      # e.g. 'hann', 'blackman', 'hamming'
       nperseg=NPERSEG,    # segment length
       noverlap=NOVERLAP,  # overlap in samples
       nfft=NFFT,          # FFT size (may exceed nperseg for zero-padding)
       boundary=BOUNDARY,  # None, 'zeros', 'even', 'odd', 'constant'
       padded=PADDED,      # True or False
       return_onesided=ONESIDED  # True for real signals
   )
   ```

3. Compute linear magnitude: `mag = np.abs(Zxx)`.
   - Output shape with `return_onesided=True`: `(nfft//2 + 1, n_frames)`.
   - **Do NOT** convert to dB. Export raw linear magnitude.

4. Export CSV with header `frame,bin,val`:
   ```python
   n_bins, n_frames = mag.shape
   with open(mag_path, 'w') as fh:
       fh.write('frame,bin,val\n')
       for frame_idx in range(n_frames):
           for bin_idx in range(n_bins):
               fh.write(f'{frame_idx},{bin_idx},{mag[bin_idx, frame_idx]:.10f}\n')
   ```
   - Iterate frames (outer) × bins (inner) so awk sees data in frame order.
   - Use ≥10 decimal digits to preserve precision for awk comparisons.

### STFT Parameter Reference

| Parameter | Effect |
|-----------|--------|
| `fs` | Sampling rate for frequency axis labeling |
| `window` | Window function name or array; must match `nperseg` length |
| `nperseg` | Segment length in samples |
| `noverlap` | Overlap between segments (must satisfy COLA: `nperseg-noverlap` divides `nperseg`) |
| `nfft` | FFT size; `≥ nperseg`; zero-pads if larger |
| `boundary` | `None` = no extension; `'zeros'` = pad with zeros at edges |
| `padded` | `True` = zero-pad tail to fill last segment |
| `return_onesided` | `True` → `nfft//2+1` bins (real signals); `False` → `nfft` bins |

**Frame count formula** (when `boundary=None, padded=False`):
```
n_frames = floor((n_samples - nperseg) / (nperseg - noverlap)) + 1
```

## Step 3 — Peak Extraction with awk (in shell script)

### Requirements
- Read `/app/data/mag.csv` (schema: `frame,bin,val`).
- For each frame, find the top-k bins by magnitude in **descending** order.
- Write `/app/data/peaks.csv` with header `frame,f1_bin,f2_bin,...,fk_bin`.
- Ties: break by lower bin index (deterministic).
- Invoke as `awk` (rely on PATH; no absolute path).
- Must work with both `gawk` and `mawk`.

### Algorithm: Streaming Top-k (O(N·k) time, O(F·k) memory)

Maintain a descending sorted list of the top-k entries per frame while reading
each CSV line. This avoids storing all magnitude data.

**Logic per incoming line `(frame, bin, val)`:**
1. If frame has fewer than k entries: append `(val, bin)` and bubble up to
   restore descending order.
2. Else if `val > worst entry (position k-1)`: replace worst, then bubble the
   new entry into its correct sorted position.
3. Else: skip (value cannot enter the top-k).

**Verified awk implementation** (general, works for any k ≥ 1):

```bash
awk -F',' -v K="$NUM_PEAKS" '
BEGIN {
    printf "frame"
    for (i = 1; i <= K; i++) printf ",f%d_bin", i
    printf "\n"
}
NR == 1 { next }
{
    f = $1 + 0; b = $2 + 0; v = $3 + 0
    if (!(f in frame_seen)) {
        frames[++num_frames] = f
        frame_seen[f] = 1
        cnt[f] = 0
    }
    n = cnt[f]
    if (n < K) {
        tv[f, n] = v; tb[f, n] = b; cnt[f]++
        pos = cnt[f] - 1
        while (pos > 0 && tv[f, pos] > tv[f, pos-1]) {
            tmp = tv[f, pos]; tv[f, pos] = tv[f, pos-1]; tv[f, pos-1] = tmp
            tmp = tb[f, pos]; tb[f, pos] = tb[f, pos-1]; tb[f, pos-1] = tmp
            pos--
        }
    } else if (v > tv[f, K-1]) {
        tv[f, K-1] = v; tb[f, K-1] = b
        pos = K - 1
        while (pos > 0 && tv[f, pos] > tv[f, pos-1]) {
            tmp = tv[f, pos]; tv[f, pos] = tv[f, pos-1]; tv[f, pos-1] = tmp
            tmp = tb[f, pos]; tb[f, pos] = tb[f, pos-1]; tb[f, pos-1] = tmp
            pos--
        }
    }
}
END {
    for (fi = 1; fi <= num_frames; fi++) {
        fr = frames[fi]
        printf "%d", fr
        for (i = 0; i < K && i < cnt[fr]; i++)
            printf ",%d", tb[fr, i]
        printf "\n"
    }
}' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
```

**Tie-breaking note:** The `>` comparison (strictly greater) means equal-magnitude
bins retain insertion order. Since bins are processed in ascending index order
from the CSV, ties naturally resolve to lower bin index first — matching the
expected deterministic behavior.

### Performance Reference

| Method | Time (513 bins × 153 frames, k=3) | Memory |
|--------|-----------------------------------|--------|
| Streaming top-k | ~0.05s | O(F·k) |
| Bubble sort | ~5.0s | O(F·B) |

## Step 4 — Shell Script Orchestration

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
mkdir -p "$DATA_DIR"

# Number of peaks to extract (from task parameters)
NUM_PEAKS=3

# ── Step A: Synthesis + STFT (skip if PEAKS_ONLY=1) ──────────────
if [ "${PEAKS_ONLY:-0}" != "1" ]; then
    python3 "$SCRIPT_DIR/audioproc.py"
fi

# ── Step B: Peak extraction via awk (ALWAYS runs) ────────────────
awk -F',' -v K="$NUM_PEAKS" '
BEGIN {
    printf "frame"
    for (i = 1; i <= K; i++) printf ",f%d_bin", i
    printf "\n"
}
NR == 1 { next }
{
    f = $1 + 0; b = $2 + 0; v = $3 + 0
    if (!(f in frame_seen)) {
        frames[++num_frames] = f
        frame_seen[f] = 1
        cnt[f] = 0
    }
    n = cnt[f]
    if (n < K) {
        tv[f, n] = v; tb[f, n] = b; cnt[f]++
        pos = cnt[f] - 1
        while (pos > 0 && tv[f, pos] > tv[f, pos-1]) {
            tmp = tv[f, pos]; tv[f, pos] = tv[f, pos-1]; tv[f, pos-1] = tmp
            tmp = tb[f, pos]; tb[f, pos] = tb[f, pos-1]; tb[f, pos-1] = tmp
            pos--
        }
    } else if (v > tv[f, K-1]) {
        tv[f, K-1] = v; tb[f, K-1] = b
        pos = K - 1
        while (pos > 0 && tv[f, pos] > tv[f, pos-1]) {
            tmp = tv[f, pos]; tv[f, pos] = tv[f, pos-1]; tv[f, pos-1] = tmp
            tmp = tb[f, pos]; tb[f, pos] = tb[f, pos-1]; tb[f, pos-1] = tmp
            pos--
        }
    }
}
END {
    for (fi = 1; fi <= num_frames; fi++) {
        fr = frames[fi]
        printf "%d", fr
        for (i = 0; i < K && i < cnt[fr]; i++)
            printf ",%d", tb[fr, i]
        printf "\n"
    }
}' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
```

### PEAKS_ONLY Mode (CRITICAL)

- When `PEAKS_ONLY=1`: skip `audioproc.py` entirely. Do NOT regenerate mag.csv.
- Read the **existing** `data/mag.csv` and produce `data/peaks.csv` via awk only.
- The shell script's `if [ "${PEAKS_ONLY:-0}" != "1" ]` guard ensures this.
- `mag.csv` MUST already exist; if it doesn't, the script will fail (expected).

**Why this matters:** Tests verify PEAKS_ONLY by first running the full pipeline,
then modifying mag.csv with custom values, then calling the script again with
`PEAKS_ONLY=1`. If `audioproc.py` runs during the PEAKS_ONLY invocation, it
**overwrites the test's modified mag.csv** and the awk reads stale data. This is
the single most common failure mode.

**Verification:** After writing the shell script, test PEAKS_ONLY manually:
```bash
# 1. Run full pipeline
bash run_audio_pipeline.sh

# 2. Modify mag.csv with test data
python3 -c "
import csv
with open('data/mag.csv') as f:
    rows = list(csv.DictReader(f))
rows[0]['val'] = '1.0'
rows[1]['bin'] = '20'; rows[1]['val'] = '9.0'
rows[2]['bin'] = '10'; rows[2]['val'] = '7.0'
rows[3]['bin'] = '30'; rows[3]['val'] = '5.0'
with open('data/mag.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['frame','bin','val'])
    w.writeheader(); w.writerows(rows)
"

# 3. Run PEAKS_ONLY
PEAKS_ONLY=1 bash run_audio_pipeline.sh

# 4. Check frame 0 peaks — should be 0,20,10,30
head -2 data/peaks.csv
```

### Making K Dynamic
The number of peaks (k) should be a configurable parameter. Hardcode from the
task spec (e.g., `NUM_PEAKS=3`). The awk script receives it via `-v K=...`.

## Verification Checklist

Run these checks after the pipeline completes:

| Check | How |
|-------|-----|
| WAV exists and is valid | `python3 -c "from scipy.io import wavfile; r,d=wavfile.read('data/clip.wav'); print(r, len(d))"` |
| Correct sample rate | wavfile.read returns expected fs |
| Correct duration | `len(data) / fs ≈ target_duration` |
| RMS in target range | `np.sqrt(np.mean((data/32767.0)**2))` within ±0.002 of target |
| Residual std check | `0.004 ≤ residual_std ≤ 0.02` (use noise_std ≈ 0.05) |
| mag.csv header | `head -1 data/mag.csv` → `frame,bin,val` |
| mag.csv row count | `wc -l` → `1 + n_bins × n_frames` |
| mag.csv matches test STFT | Load WAV as `float64/32767.0`, compute STFT, compare with CSV |
| peaks.csv header | Correct number of columns for k peaks |
| peaks.csv row count | `1 + n_frames` (header + one row per frame) |
| peaks descending | For each row: `val[b1] ≥ val[b2] ≥ ... ≥ val[bk]` |
| PEAKS_ONLY works | Modify mag.csv → `PEAKS_ONLY=1 bash run_audio_pipeline.sh` → check peaks match modified data |

### Quick Python Cross-Validation Script

```python
import numpy as np, csv

# Load mag.csv
mag = {}
with open('data/mag.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        fr, b, v = int(row['frame']), int(row['bin']), float(row['val'])
        mag.setdefault(fr, {})[b] = v

# Check peaks.csv
with open('data/peaks.csv') as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        fr = int(row[0])
        peak_bins = [int(x) for x in row[1:]]
        vals = [mag[fr][b] for b in peak_bins]
        assert vals == sorted(vals, reverse=True), f"Frame {fr}: not descending"
        ref = sorted(mag[fr], key=lambda b: (-mag[fr][b], b))[:len(peak_bins)]
        ref_vals = [mag[fr][b] for b in ref]
        assert vals == ref_vals, f"Frame {fr}: wrong peaks"
print("All peaks verified.")
```

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| **noise_std too small** | Use `noise_std ≈ 0.05`, not 0.01. Tests check residual std ∈ [0.004, 0.02] |
| **STFT on raw int16 data** | MUST normalize: `data.astype(np.float64) / 32767.0` before STFT |
| Quantizing before RMS normalization | Always normalize float signal first, then scale to int16 |
| Exporting dB instead of linear magnitude | Use `np.abs(Zxx)` directly; do NOT apply `20*log10` |
| Writing peaks.csv from Python | Peak extraction MUST go through awk in the shell script |
| STFT frame/bin orientation swapped | `Zxx.shape = (n_bins, n_frames)`; CSV iterates frames outer, bins inner |
| Using absolute awk path | Invoke as `awk` (rely on PATH), not `/usr/bin/awk` |
| Forgetting `set -euo pipefail` | Shell script should fail fast on any error |
| Boundary/padded mismatch | Read task params exactly; `boundary=None` is Python `None`, not string `"None"` |
| Off-by-one in nfft vs n_bins | One-sided: `n_bins = nfft // 2 + 1` |
| PEAKS_ONLY running Python | When `PEAKS_ONLY=1`, skip the Python step entirely; verify with manual test |
| Tie-breaking inconsistency | Use strict `>` in awk so first-seen (lower bin index) wins |

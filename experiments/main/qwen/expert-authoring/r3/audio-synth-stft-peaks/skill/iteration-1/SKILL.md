---
name: audio-synth-stft-peaks
description: >
  Build a deterministic audio-processing pipeline that synthesizes a WAV file
  from sine tones plus noise, computes an STFT magnitude spectrogram via scipy,
  and extracts the top-k spectral peaks per frame using awk. Covers WAV
  synthesis with RMS normalization, scipy.signal.stft parameterization, CSV
  magnitude export, and shell/awk peak selection with PEAKS_ONLY support.
---

# Audio Synthesis + STFT + Peak Extraction Pipeline

## Architecture

```
audioproc.py            # Python: produces clip.wav + mag.csv ONLY
run_audio_pipeline.sh   # Shell: orchestrates pipeline, owns awk peak extraction
data/
  ├── clip.wav          # PCM int16 WAV
  ├── mag.csv           # STFT linear magnitude (frame,bin,val)
  └── peaks.csv         # Top-k peaks per frame (frame,b1,b2,...,bk)
```

**Hard boundary:** `audioproc.py` MUST NOT generate `peaks.csv`. Peak extraction
MUST be performed by `awk` inside the shell script. This is a family invariant.

## Step 1 — WAV Synthesis (in `audioproc.py`)

### Decision Rules

1. Read all task parameters: `fs` (sample rate), `duration`, `freqs` (list of
   sine frequencies), `noise_std` or noise spec, `rms_target`.
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

### Invariants
- Mono output (1-D array).
- Normalize → then quantize. Never quantize before normalizing.
- Use `os.makedirs(data_dir, exist_ok=True)` to ensure `data/` exists.

## Step 2 — STFT & Magnitude CSV (in `audioproc.py`)

### Decision Rules

1. Reload the signal from `clip.wav` using `scipy.io.wavfile.read` OR reuse the
   in-memory float array (both are valid; reusing avoids round-trip quantization
   error — prefer reusing if the test computes STFT from the pre-quantized signal).
   **Check the task carefully**: if it says "compute STFT of the saved WAV",
   reload from disk; if it just says "compute STFT", use the pre-quantized array.
   Default to reloading from the WAV to match the literal file content.

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

### Alternative: Partial Selection (simpler but O(F·B·k))

Store all data, then in `END` make k passes per frame, zeroing out the found
maximum after each pass. Simpler to reason about but ~3× slower for k=3 and
increasingly worse for larger k. Use only as a debugging cross-check.

```bash
# For each frame in END: find max → record → zero it → repeat k times
```

### Performance Reference

| Method | Time (513 bins × 153 frames, k=3) | Memory |
|--------|-----------------------------------|--------|
| Streaming top-k | ~0.05s | O(F·k) |
| Partial selection | ~0.16s | O(F·B) |
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

if [ "${PEAKS_ONLY:-0}" != "1" ]; then
    python3 "$SCRIPT_DIR/audioproc.py"
fi

# --- Peak extraction via awk (always runs) ---
awk -F',' -v K="$NUM_PEAKS" '
BEGIN {
    printf "frame"
    for (i = 1; i <= K; i++) printf ",f%d_bin", i
    printf "\n"
}
NR == 1 { next }
... (streaming top-k body from Step 3) ...
' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
```

### PEAKS_ONLY Mode
- When `PEAKS_ONLY=1`: skip `audioproc.py` entirely.
- Read the **existing** `data/mag.csv` and produce `data/peaks.csv` via awk.
- Exit immediately after peak extraction.
- `mag.csv` MUST already exist; the script should not regenerate it.

### Making K Dynamic
The number of peaks (k) should be a configurable parameter. Options:
1. Hardcode from the task spec (e.g., `NUM_PEAKS=3`).
2. Read from an environment variable with a sensible default.
3. Pass as a command-line argument to the shell script.

**Recommendation:** Extract k from the task parameters and set it as an env var
or hardcode it in the shell script. The awk script receives it via `-v K=...`.

## Verification Checklist

Run these checks after the pipeline completes:

| Check | How |
|-------|-----|
| WAV exists and is valid | `python3 -c "from scipy.io import wavfile; r,d=wavfile.read('data/clip.wav'); print(r, len(d))"` |
| Correct sample rate | wavfile.read returns expected fs |
| Correct duration | `len(data) / fs ≈ target_duration` |
| mag.csv header | `head -1 data/mag.csv` → `frame,bin,val` |
| mag.csv row count | `wc -l` → `1 + n_bins × n_frames` |
| mag.csv bin range | bins span `0 .. (nfft//2)` for one-sided |
| mag.csv values ≥ 0 | All magnitudes non-negative (linear, not dB) |
| peaks.csv header | Correct number of columns for k peaks |
| peaks.csv row count | `1 + n_frames` (header + one row per frame) |
| peaks descending | For each row: `val[b1] ≥ val[b2] ≥ ... ≥ val[bk]` (cross-reference mag.csv) |
| peaks bins valid | All bin indices in `0 .. max_bin` |
| PEAKS_ONLY works | `PEAKS_ONLY=1 bash run_audio_pipeline.sh` regenerates peaks.csv without running Python |
| Peaks match reference | Cross-check a few frames with Python numpy argsort |

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

# Check peaks.csv (header: frame,f1_bin,f2_bin,...)
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
| Quantizing before RMS normalization | Always normalize float signal first, then scale to int16 |
| Exporting dB instead of linear magnitude | Use `np.abs(Zxx)` directly; do NOT apply `20*log10` |
| Writing peaks.csv from Python | Peak extraction MUST go through awk in the shell script |
| STFT frame/bin orientation swapped | `Zxx.shape = (n_bins, n_frames)`; CSV iterates frames outer, bins inner |
| Using absolute awk path | Invoke as `awk` (rely on PATH), not `/usr/bin/awk` |
| Forgetting `set -euo pipefail` | Shell script should fail fast on any error |
| Boundary/padded mismatch | Read task params exactly; `boundary=None` is Python `None`, not string `"None"` |
| Off-by-one in nfft vs n_bins | One-sided: `n_bins = nfft // 2 + 1` |
| PEAKS_ONLY running Python | When `PEAKS_ONLY=1`, skip the Python step entirely |
| Tie-breaking inconsistency | Use strict `>` in awk so first-seen (lower bin index) wins |

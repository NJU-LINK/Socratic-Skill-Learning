---
name: audio-synth-stft-peaks
description: Build a reproducible audio pipeline that synthesizes a normalized WAV, exports scipy STFT magnitudes to CSV, and extracts top-K spectral peaks per frame with awk under a Bash orchestrator (incl. a peaks-only mode). Use when a task asks for deterministic tone+noise synthesis, scipy.signal.stft magnitude CSV export, and shell/awk-based peak selection with exact schemas.
---

# Audio Synth → STFT → awk Peaks Pipeline

## What the family is

A three-stage pipeline with a strict separation of duties:

1. **Python (`audioproc.py`-like)** synthesizes a deterministic mono WAV (sum of sine
   tones + noise, RMS-normalized, 16-bit PCM) and computes `scipy.signal.stft`,
   exporting magnitudes to a tidy CSV (one row per frame×bin).
2. **Bash orchestrator (`run_*_pipeline.sh`-like)** runs the Python step and then
   produces the peaks CSV **using awk**. It also supports a mode flag (e.g.
   `PEAKS_ONLY=1`) that regenerates peaks from the existing magnitude CSV alone.
3. **awk stage** performs the *final* top-K bin selection per frame. Python must
   never write the peaks file.

Concrete parameter values (sample rate, duration, frequencies, window, nperseg,
top-k, column names, flag names) **always come from the current instruction** —
they vary across the family (see spec axes). The v01 anchor used 12 kHz/2.5 s/4
tones, blackman/768/576/1024, `frame,bin,val`, top-3, `PEAKS_ONLY`; treat those as
illustrative only.

**Recommended path:** copy `scripts/audioproc_template.py` and
`scripts/run_pipeline_template.sh` into place, edit the CONFIG blocks from the
instruction, run, then run `scripts/verify_pipeline.py` and
`scripts/stub_awk_test.sh`. The scripts encode validated details that are easy
to get wrong when retyping (awk ordering logic, de-quantization constant, the
single-invocation peaks stage). A prior solver read only this file, retyped the
awk by hand, and burned several turns on ordering bugs the shipped program
already avoids.

## Grader conventions observed on v01 (calibration-critical)

The hidden grader cannot know your RNG seed, noise σ, or phases, so it verifies
**properties of the artifacts**. On v01 it did the following — expect per-variant
tests to follow the same template with rescaled constants:

- Reads the WAV as `int16 / np.iinfo(np.int16).max` — i.e. divides by **32767**,
  NOT 32768. A mag value compared at `rel_tol=1e-6` fails with rel diff
  ≈ 3.05e-5 = 32768/32767 when the conventions differ. Use 32767 everywhere
  (quantize `round(x*32767)`, de-quantize `/32767`). Diagnostic: if a strict
  numeric comparison is off by ≈3.05e-5 relative, this convention is why.
- Checks the top-|freqs| FFT peak frequencies **equal the required tone freqs**
  (works because integer-Hz tones complete an integer number of cycles, so DFT
  leakage is zero and tone bins dominate the noise floor by orders of magnitude).
- Least-squares fits sin/cos at each required frequency and asserts fitted
  amplitudes are **all > 0.08** and **max/min < 1.15** (≈ equal amplitudes).
  amp_post ≈ target_rms / sqrt(k/2) for k unit-amplitude tones (0.106 for v01).
- Asserts `0.004 <= residual_std <= 0.02`, where the residual is the signal after
  projecting out the fitted tones — i.e. **the noise must be audible**: not too
  small, not too big. As a fraction of the 0.15 RMS target this band is
  ≈ [0.027, 0.133]. **Calibrate noise to φ ≈ 0.065 (band middle):**
  `σ = φ · rms(tones_only)`; after normalization the noise std lands at
  ≈ φ · target_rms. (v01 failure: σ chosen "small" gave residual 0.00106 < 0.004.)
  If the instruction pins a noise level, follow the instruction instead.
- **Stubs `awk` on PATH** (a fake that logs invocations and prints fixed peaks
  content), runs the pipeline, and asserts `peaks.csv` **equals the stub's
  stdout byte-for-byte** and that awk ran **exactly once** per run (full and
  peaks-only modes alike). Consequence: the peaks file must be the raw stdout
  of a single awk invocation — any shell-added header or post-processing pipe
  (`| sort`, `| head`, a second awk) breaks the byte diff. (Iteration-2 failure:
  a `{ echo header; awk … | sort }` wrapper duplicated the header and reordered
  the stub's rows.) Rehearse this yourself with `scripts/stub_awk_test.sh`.

## Invariants vs. variation axes

| Invariant (do not improvise) | Varies per instance (read from instruction) |
|---|---|
| Deterministic, seeded synthesis; normalize **before** quantization; de-quantize by int16 max | synthesis: fs, duration, tone count/freqs, amplitudes/envelope, noise distribution/level, RMS target & tolerance |
| `scipy.signal.stft` with **every** parameter passed explicitly | stft: window type, nperseg, noverlap, nfft, boundary, padded, linear vs dB, CSV schema |
| awk (bare `awk` via PATH) does final peak selection; peaks file = **one** awk invocation's raw stdout | peaks: top-k, tie-break, output columns, mode flag name, mawk vs gawk |
| 0-indexed frames/bins; one peaks row per frame; header rows exactly as specified | paths and file names |

## Stage 1 — synthesis decision rules

- Parse fs, duration, frequencies, noise spec, RMS target from the instruction.
  Sample count `N = int(round(fs * duration))`.
- Seed the RNG: `rng = np.random.default_rng(0)` (any fixed seed). Determinism is
  cheap insurance — a grader may rerun and compare bytes.
- `tones = sum(sin(2π f_i t))` with **equal unit amplitudes and zero phases**
  unless the instruction says otherwise (grader checks amplitude equality);
  keep integer-Hz tones so cycles complete exactly (tone bins dominate the FFT).
- Noise: `σ = 0.065 · sqrt(mean(tones**2))` (see calibration section above);
  `x = tones + σ · rng.standard_normal(N)`.
- RMS normalize: `x *= target / sqrt(mean(x**2))` **before** quantizing. Guard
  clipping: assert `max(abs(x)) < 1.0`.
- Quantize `pcm = np.round(x * 32767).astype(np.int16)`, write with
  `scipy.io.wavfile.write(path, fs, pcm)` (int16 → PCM16; 1-D → mono).
- If an instance specifies an envelope or a different normalization rule, follow
  the instruction; the normalize-before-quantize ordering still holds.

## Stage 2 — STFT + magnitude CSV decision rules

- Pass **all** stft arguments explicitly: `fs`, `window` (string as given),
  `nperseg`, `noverlap`, `nfft`, `boundary`, `padded`, `return_onesided`.
  Never rely on scipy defaults — defaults are `boundary='zeros', padded=True`,
  which change the frame count and are a top failure cause.
- Compute the STFT on the signal **as stored on disk**: re-read the WAV
  (`scipy.io.wavfile.read` returns `(rate, data)` — tuple order matters!) and use
  `data.astype(np.float64) / np.iinfo(np.int16).max`. Graders recompute from
  `clip.wav` with the same de-quantization (observed on v01), giving 0 error.
- Magnitude: `mag = np.abs(Zxx)` for linear export. If dB is requested, use
  `20 * np.log10(np.maximum(mag, tiny))`; dB is monotonic, so the awk peak
  ordering logic is unchanged.
- Export frame-major, one row per bin per frame, header exactly as specified.
  Use full precision: `np.savetxt(path, rows, fmt=['%d','%d','%.17g'],
  delimiter=',', header=..., comments='')` with
  `rows = column_stack([repeat(arange(n_frames), n_bins), tile(arange(n_bins),
  n_frames), mag.T.ravel()])` (`Zxx` is `(bins, frames)` — transpose!).
- Sanity-check shapes: one-sided bins = `nfft//2 + 1`; with `boundary=None,
  padded=False`, frames = `1 + (N - nperseg) // (nperseg - noverlap)`. For other
  boundary/padded settings, trust `Zxx.shape` instead of a formula.

## Stage 3 — awk top-K decision rules

**awk owns the entire peaks file.** The whole stage is ONE invocation whose
stdout is redirected straight to the file:
`awk -F',' -v K=<k> -v HEADER="<header>" '…' mag.csv > peaks.csv`.
The program prints the header itself (BEGIN) and emits rows in numeric frame
order (END) — no shell `echo` of the header, no post-processing pipe, because
the grader byte-compares against stubbed awk output (see conventions section).
Validated program (POSIX; identical output under mawk and gawk; `O(rows)`;
robust to shuffled input rows, exact ties, scientific notation, frame gaps,
empty input):

```awk
BEGIN { OFS=","; print HEADER }   # awk emits the header itself
NR==1 && $1=="frame" { next }      # skip CSV header if present
NF < 3 { next }
{
  f = $1 + 0; b = $2 + 0; v = $3 + 0
  if (!(f in seen)) { seen[f] = 1; cnt[f] = 0; if (f > maxf) maxf = f }
  m = cnt[f] < K ? cnt[f] : K
  p = 0
  for (i = 1; i <= m; i++)
    if (v > BV[f,i] || (v == BV[f,i] && b < BB[f,i])) { p = i; break }
  if (p == 0 && cnt[f] < K) p = cnt[f] + 1
  if (p > 0) {
    for (i = K - 1; i >= p; i--) { BV[f,i+1] = BV[f,i]; BB[f,i+1] = BB[f,i] }
    BV[f,p] = v; BB[f,p] = b
  }
  cnt[f]++
}
END {
  # frames are 0-indexed contiguous integers (STFT export): numeric order is
  # a plain integer loop; gaps are skipped. Input row order does not matter.
  for (f = 0; f <= maxf; f++) {
    if (!(f in seen)) continue
    line = f
    for (j = 1; j <= K; j++) line = line OFS BB[f,j]
    print line
  }
}
```

Tie-break **value desc, then bin asc** matches `np.argsort(-col, kind='stable')[:K]`,
the likely grader reference; change the comparator in the one marked spot if the
instruction says otherwise. Traps observed in student runs (avoid by using the
program as-is):

- Wrapping awk's output (`{ echo "$HEADER"; awk … | sort } > peaks.csv`) —
  duplicates the header and reorders rows when awk is stubbed; the byte-compare
  fails. The redirect target must be awk's stdout, nothing else.
- awk array iteration (`for (f in seen)`) is **unordered**; printing frames from
  it yields lexicographic/garbled order (10 before 2). Numeric ordering must be
  an integer loop (as above) — an external `| sort -n` would break the stub diff.
- Do not mix `print ... | "sort"` inside awk with normal prints — the streams
  interleave and corrupt the header.
- Do not use sentinel-zero slot tests (`best == 0`): 0.0 is a legitimate
  magnitude. Track an explicit per-frame count (`cnt[f]`).
- Do not rescan mag.csv once per frame from a shell loop (`O(frames × rows)`);
  the single pass above handles everything.
- Emit header/columns exactly as instructed (e.g. `frame,f1_bin,f2_bin,f3_bin`);
  frames/bins are 0-indexed.

## Orchestrator decision rules

- `#!/usr/bin/env bash`, `set -euo pipefail`, absolute paths (or `cd` first).
- Structure: define `extract_peaks()` as **one awk invocation with stdout
  redirected to the peaks file** → check the mode flag **before** heavy steps:
  `if [ "${PEAKS_ONLY:-0}" = "1" ]; then extract_peaks; exit 0; fi`
  → run Python → `extract_peaks`. Both modes must call awk exactly once.
- Invoke awk as bare `awk` (the grader stubs it on PATH and greps for absolute
  paths); never produce the peaks CSV from Python.
- Keep the peaks stage dependent only on the mag CSV (not on synthesis state), so
  the peaks-only mode works standalone from any valid mag CSV.
- Make everything idempotent: rerunning the script must reproduce all outputs.

## Self-verification (always run before finishing)

`scripts/verify_pipeline.py` automates all of this, including the grader-mimic
signal checks (dominant FFT freqs == required freqs; least-squares tone
amplitudes above floor with max/min < 1.15; residual-after-fit std within the
noise band — defaults are the v01-observed constants, adjust per instruction):

1. Read back the WAV: correct fs, mono, dtype int16, `N == round(fs*dur)`,
   RMS of `data/32767` within tolerance.
2. Recompute `stft` from `clip.wav` (`/32767`) and compare against mag.csv
   (`rel_tol=1e-6`) — expect exact match; check frame/bin counts vs `Zxx.shape`.
3. Recompute top-K per frame with numpy (`argsort(-col, kind='stable')[:K]`) and
   compare to peaks.csv on **every** frame; assert frame ids are `0..n-1`.
4. Run the orchestrator twice → byte-identical WAV/CSVs (determinism check).
5. Exercise the peaks-only flag from a clean state and confirm Python is not
   invoked and no other step runs.
6. **Stub rehearsal:** run `scripts/stub_awk_test.sh` (or equivalent): fake awk
   first on PATH → peaks.csv must equal the stub's stdout byte-for-byte and the
   invocation log must show exactly one call, in BOTH full and peaks-only modes.
7. If both mawk and gawk exist, run the awk program under both and diff.

## Failure modes observed / inferred

- **Observed (iteration 1 graded run, score 4/6):** failures were (a) noise too
  small — residual-after-tone-fit 0.00106 below the 0.004 floor — and (b)
  de-quantizing by 32768 instead of the grader's 32767 (rel diff 3.05e-5 >
  rel_tol 1e-6). Both are fixed by the calibration and convention rules above.
- **Observed (iteration 2 graded run, score 5/6):** the iteration-1 fixes held
  (WAV/tone/noise and mag/STFT tests passed). The one failure was the awk-stub
  test: the template wrapped awk's output as `{ echo header; awk … | sort }`,
  so with a stubbed awk the peaks file contained a duplicated header and
  reordered rows — fixed by making awk own the whole file (single invocation,
  header in BEGIN, in-awk numeric ordering, no post-processing).
  The shipped awk program matches numpy top-K on every frame under both mawk
  and gawk, and passes the stub rehearsal byte-exactly in both modes.
- **Inferred:** per-variant graders reuse the same helper template
  (`read_wav_signal`, `dominant_fft_frequencies`, `fit_required_tones`), so the
  /32767 convention and fraction-of-target noise band likely persist with
  rescaled constants; they may swap mag.csv and run the peaks-only mode; they may
  grep that `audioproc.py` never writes peaks and that awk is invoked via PATH.
- Classic pitfalls: scipy default boundary/padding silently changing frame count;
  exporting `Zxx` without transposing; rounding magnitudes to few decimals;
  forgetting the CSV header; 1-indexing; normalizing after quantization;
  unseeded RNG; `noverlap` confused with hop size (`hop = nperseg - noverlap`);
  `wavfile.read` returning `(rate, data)`, not `(data, rate)`.

## Files

- `scripts/audioproc_template.py` — synthesis + STFT export template; edit the
  CONFIG block from the instruction (noise is auto-calibrated via `NOISE_FRAC`).
- `scripts/run_pipeline_template.sh` — orchestrator with the validated top-K awk
  program and mode-flag handling (single awk invocation; awk owns the file).
- `scripts/verify_pipeline.py` — checker for all artifacts, incl. grader-mimic
  signal checks (tone fit, residual band, dominant freqs).
- `scripts/stub_awk_test.sh` — rehearses the grader's awk-stub test: byte-exact
  peaks passthrough and exactly-one-invocation, for full and peaks-only modes.

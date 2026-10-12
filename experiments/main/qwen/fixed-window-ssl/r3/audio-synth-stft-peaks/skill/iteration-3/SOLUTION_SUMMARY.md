# Solution Summary: Audio Synth + STFT Peaks Pipeline

## Task Completion

Successfully implemented a complete audio processing pipeline that:
1. Synthesizes a mono WAV file (12 kHz, 2.5s, 4 sine tones + noise, RMS=0.15)
2. Computes STFT using scipy with Blackman window
3. Extracts top-3 spectral peaks per frame using awk

## Files Created

### In /app (working solution):
- `audioproc.py` - Python script for WAV synthesis + STFT computation
- `run_audio_pipeline.sh` - Shell script orchestrating the pipeline
- `data/clip.wav` - Generated WAV file (60 KB)
- `data/mag.csv` - STFT magnitude CSV (1.8 MB, 153 frames × 513 bins)
- `data/peaks.csv` - Top-3 peaks per frame (154 lines including header)

### In skill/audio-synth-stft-peaks (reusable skill package):
- `SKILL.md` - Comprehensive documentation with YAML frontmatter
- `audioproc_template.py` - Parameterized Python template
- `peaks_template.awk` - Robust awk peak extraction script
- `run_pipeline_template.sh` - Shell script template with PEAKS_ONLY mode

## Key Technical Decisions

### 1. RMS Normalization (Critical Fix)
**Problem**: Initial implementation had double normalization bug - RMS normalize then peak normalize.
**Solution**: RMS normalize once, then quantize directly to int16 without additional scaling.
**Verification**: WAV RMS = 0.149989 (within ±0.002 tolerance of 0.15 target).

### 2. STFT Signal Source
Used the float signal (before int16 quantization) for STFT computation to avoid quantization artifacts.

### 3. Awk Top-k Algorithm
Implemented incremental top-3 tracker with proper initialization checks to avoid the "0-initialization trap" that would fail for negative values or sparse data.

### 4. PEAKS_ONLY Mode
Shell script supports `PEAKS_ONLY=1` environment variable to run only peak extraction from existing mag.csv, skipping synthesis and STFT computation.

## Verification Results

✓ WAV: mono, int16, 12000 Hz, 30000 samples (2.5s)
✓ RMS: 0.149989 (target 0.15 ± 0.002)
✓ STFT: 153 frames × 513 bins (one-sided, nfft=1024)
✓ Peaks: All 153 frames match Python verification
✓ Top-3 bins: 46, 31, 15 (corresponding to 540, 360, 180 Hz)
✓ PEAKS_ONLY mode: Works independently
✓ awk invocation: Uses `awk` from PATH, not absolute path

## Frequency Analysis

With sr=12000 and nfft=1024:
- Frequency resolution: 11.71875 Hz/bin
- 180 Hz → bin 15 (exact: 15.36)
- 360 Hz → bin 31 (exact: 30.72)
- 540 Hz → bin 46 (exact: 46.08)
- 720 Hz → bin 61 (exact: 61.44) - 4th strongest, correctly excluded from top-3

The Blackman window's spectral characteristics cause the 720 Hz tone to have slightly lower magnitude than the other three tones, making it the 4th peak.

## Generalization to Variants

The skill package handles spec.yaml variation dimensions:

### 1. synthesis_signal_parameters
- Template supports arbitrary sample rate, duration, frequency list
- RMS normalization target and tolerance are parameterized
- Noise distribution and seed are configurable

### 2. stft_configuration
- All scipy.signal.stft parameters are configurable (window, nperseg, noverlap, nfft, boundary, padded, return_onesided)
- CSV schema is fixed (frame,bin,val) but magnitude scaling can vary

### 3. peak_extraction_logic
- TOP_K is parameterized via environment variable
- Output schema adapts to top-k (frame,f1_bin,...,fk_bin)
- Awk algorithm handles non-negative magnitudes safely
- PEAKS_ONLY mode contract is preserved

## Common Pitfalls Documented

1. Double normalization bug (RMS + peak)
2. awk 0-initialization trap for non-magnitude values
3. Using quantized int16 signal for STFT instead of float
4. Frame ordering issues in awk output
5. Bin indexing confusion (0-based vs 1-based)

## Conclusion

The solution is complete, verified, and packaged as a reusable skill that generalizes to family variants while maintaining correctness for the v01 anchor case.

# Skill Development Summary: audio-synth-stft-peaks

## What Was Built

A complete, reusable Agent Skill for the audio-synth-stft-peaks task family covering deterministic audio synthesis, STFT computation, and spectral peak extraction.

## Skill Package Contents

```
skill/audio-synth-stft-peaks/
├── SKILL.md                          # Comprehensive documentation
└── templates/
    ├── audioproc.py                  # Python synthesis + STFT
    ├── extract_peaks.awk             # AWK peak extraction
    └── run_audio_pipeline.sh         # Shell orchestration
```

## Key Knowledge Captured

### Architecture
- Three-stage pipeline with strict file boundaries
- Python produces WAV + mag.csv; awk produces peaks.csv
- PEAKS_ONLY mode for incremental regeneration

### Parameterization (Spec Axes)
1. **Synthesis**: sample_rate, duration, frequencies, noise_std, rms_target, seed
2. **STFT**: window, nperseg, noverlap, nfft, boundary, padded, return_onesided
3. **Peaks**: top_k value, output schema

### Critical Pitfalls Documented
1. RMS normalization MUST happen before int16 quantization
2. STFT MUST use float signal, not quantized int16
3. Zxx matrix shape is (n_bins, n_frames) — indexing order matters
4. AWK top-k requires manual selection (mawk lacks asorti/asort)
5. Frame boundary handling in awk (first/last frame, END block)
6. Scientific notation handling with +0 coercion

## Verification Evidence

v01 implementation tested and verified:
- ✓ clip.wav: mono, 12kHz, 2.5s, RMS=0.149989 (within 0.15±0.002)
- ✓ mag.csv: 153 frames × 513 bins, correct schema
- ✓ peaks.csv: 153 rows, correct schema, descending magnitude order
- ✓ Peak bins 46,31,15 match expected frequencies 540,360,180 Hz
- ✓ PEAKS_ONLY mode works correctly
- ✓ All dimension formulas verified

## Reusability

The skill is parameterized to handle variants that change:
- Audio synthesis parameters (sample rate, duration, tone count/frequencies, noise, RMS target)
- STFT configuration (window type, segment size, overlap, FFT size, boundary handling)
- Peak extraction logic (top-k value, tie-breaking rules, output format)

To adapt to a new variant: update shell script arguments and awk k value, then verify dimensions.

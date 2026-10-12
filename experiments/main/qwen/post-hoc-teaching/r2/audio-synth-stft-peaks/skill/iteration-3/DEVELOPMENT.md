# Skill Development Summary

## Task Family: audio-synth-stft-peaks

### Objective
Develop a reusable skill for building audio processing pipelines that:
1. Synthesize WAV files from sine tones with noise and RMS normalization
2. Compute STFT using scipy and export magnitude to CSV
3. Extract spectral peaks per frame using awk

### What Was Built

#### 1. Working Implementation (v01)
- **audioproc.py**: Python script handling synthesis and STFT
- **run_audio_pipeline.sh**: Bash orchestration with awk peak extraction
- **Verified outputs**: clip.wav, mag.csv, peaks.csv

#### 2. Skill Documentation (SKILL.md)
Comprehensive guide covering:
- Three-stage pipeline architecture
- Parameter variation handling across all three dimensions
- Implementation patterns with code examples
- Common pitfalls and testing checklist
- Adaptation strategies for new variants

#### 3. Reference Documentation (README.md)
Quick reference for:
- File structure and verification results
- Key implementation details
- Testing procedures

### Key Insights Discovered

#### Critical Implementation Details
1. **RMS Normalization Order**: Must normalize BEFORE 16-bit quantization. Additional scaling after RMS normalization changes the RMS value.
   
2. **STFT Input Format**: scipy.signal.stft expects float data in [-1, 1] range. Convert int16 via `signal / 32767.0`.

3. **awk Frame Detection**: Use `frame != prev_frame` to detect boundaries. Initialize `prev_frame = -1` to handle first frame correctly.

4. **Tie-Breaking**: When magnitudes are equal, use deterministic rule (e.g., lower bin index wins).

5. **Separation of Concerns**: Python writes clip.wav and mag.csv only. Bash/awk writes peaks.csv only.

#### Variation Dimensions (from spec.yaml)

**1. Synthesis Parameters**
- Sample rate, duration, frequency set
- Noise distribution and amplitude
- RMS target and tolerance
- *Invariant*: Mono, 16-bit PCM, RMS normalization before quantization

**2. STFT Configuration**
- Window type, nperseg, noverlap, nfft
- Boundary handling, padding
- One-sided vs two-sided
- Magnitude scaling (linear vs dB)
- CSV schema
- *Invariant*: scipy.signal.stft, magnitude export, 0-based indexing

**3. Peak Extraction Logic**
- top_k value
- Tie-breaking rules
- Frame grouping
- Output schema
- Mode flags
- *Invariant*: awk for peak selection, Python doesn't write peaks.csv

### Testing Performed

✓ Full pipeline execution
✓ PEAKS_ONLY mode
✓ WAV file properties (sample rate, duration, channels, bit depth)
✓ RMS normalization (0.149989 within 0.15 ± 0.002)
✓ STFT output (153 frames × 513 bins)
✓ Peak extraction correctness (top 3 bins: [46, 31, 15])
✓ Parameter variations (different sample rates, durations, frequency counts, STFT configs)
✓ Separation of concerns (Python doesn't write peaks.csv)

### How to Apply This Skill

For a new variant in this family:

1. **Read the task specification** to identify:
   - Synthesis parameters (fs, duration, frequencies, noise, target_rms)
   - STFT parameters (window, nperseg, noverlap, nfft, boundary, padded, return_onesided, magnitude_scale)
   - Peak extraction parameters (top_k, tie_break, output_schema, mode_flags)

2. **Adapt audioproc.py**:
   - Update synthesis parameters
   - Update STFT parameters
   - Adjust CSV schema if needed

3. **Adapt run_audio_pipeline.sh**:
   - Update awk script for top_k value
   - Update tie-breaking logic if needed
   - Update output schema
   - Update mode flag if different from PEAKS_ONLY

4. **Test thoroughly**:
   - Verify WAV properties
   - Verify RMS within tolerance
   - Verify CSV schemas
   - Verify peak correctness
   - Test PEAKS_ONLY mode

### Files Delivered

```
skill/audio-synth-stft-peaks/
├── SKILL.md       # Comprehensive skill documentation (11KB)
└── README.md      # Quick reference and verification results (2KB)
```

### Verification

All v01 requirements met and verified:
- ✓ Correct file structure
- ✓ Correct WAV format and RMS
- ✓ Correct STFT computation
- ✓ Correct peak extraction
- ✓ PEAKS_ONLY mode works
- ✓ Separation of concerns maintained
- ✓ Skill documentation complete and actionable

The skill is ready to handle new variants in the audio-synth-stft-peaks family.

# Audio Synth STFT Peaks - Implementation Reference

This directory contains the skill documentation for the audio-synth-stft-peaks task family.

## Working Implementation (v01)

The v01 implementation has been tested and verified at `/app/`:

### Files
- `audioproc.py` - Python script for audio synthesis and STFT computation
- `run_audio_pipeline.sh` - Bash orchestration script with awk peak extraction
- `data/clip.wav` - Synthesized audio (mono, 12kHz, 2.5s, 16-bit PCM)
- `data/mag.csv` - STFT magnitude (153 frames × 513 bins)
- `data/peaks.csv` - Top 3 peaks per frame

### Verification Results

All v01 requirements verified:
- ✓ WAV: mono, 12kHz, 2.5s, 16-bit PCM
- ✓ RMS: 0.149989 (within 0.15 ± 0.002 tolerance)
- ✓ STFT: blackman window, nperseg=768, noverlap=576, nfft=1024
- ✓ Magnitude CSV: frame,bin,val schema (78,489 data rows)
- ✓ Peaks CSV: frame,f1_bin,f2_bin,f3_bin schema (153 data rows)
- ✓ Top 3 bins: [46, 31, 15] corresponding to ~540, 360, 180 Hz
- ✓ PEAKS_ONLY=1 mode: works correctly
- ✓ Python does not write peaks.csv
- ✓ Bash script uses awk from PATH

### Key Implementation Details

1. **RMS Normalization**: Applied BEFORE 16-bit quantization, no additional scaling
2. **STFT Input**: Convert int16 to float64 in [-1, 1] range: `signal / 32767.0`
3. **Peak Extraction**: Selection sort in awk, tie-break by lower bin index
4. **Frame Detection**: Check `frame != prev_frame` in awk, initialize `prev_frame = -1`

## Skill Documentation

See `SKILL.md` for:
- Complete architecture overview
- Parameter variation handling
- Implementation patterns for each stage
- Common pitfalls and testing checklist
- Guidance for adapting to new task variants

## Testing

To verify the implementation:
```bash
cd /app
bash run_audio_pipeline.sh  # Full pipeline
PEAKS_ONLY=1 bash run_audio_pipeline.sh  # Peaks only
```

To test variations, modify parameters in `audioproc.py` and `run_audio_pipeline.sh` according to the patterns documented in SKILL.md.

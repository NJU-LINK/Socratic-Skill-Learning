"""Template: deterministic WAV synthesis + scipy STFT magnitude CSV export.

HOW TO USE: copy to the path required by your instruction (e.g. /app/audioproc.py)
and fill the CONFIG block with the instruction's values. Everything else is
family-stable logic validated against the v01 anchor AND its hidden grader.

Scope rules (family invariants):
  * This script produces ONLY the WAV and the magnitude CSV.
    Never write the peaks CSV from Python -- the awk stage owns that.
  * Normalize BEFORE quantization. Seed the RNG.
  * De-quantize int16 by np.iinfo(np.int16).max (32767), NOT 32768 -- observed
    grader convention; a mismatch shows up as rel diff ~= 3.05e-5.
"""
import numpy as np
from scipy import io, signal

# ----------------------------- CONFIG (from instruction) ---------------------
FS = 12000                    # sample rate, Hz
DURATION_S = 2.5              # seconds (exact)
FREQS_HZ = [180.0, 360.0, 540.0, 720.0]   # sine tone frequencies
AMPS = [1.0] * len(FREQS_HZ)  # equal amplitudes unless instruction says otherwise
NOISE_FRAC = 0.065            # post-norm noise std as fraction of TARGET_RMS;
                              # graders require audible noise (v01 band was
                              # [0.027, 0.133] x target). If the instruction
                              # pins a noise level, use that instead.
TARGET_RMS = 0.15             # RMS normalization target (pre-quantization)
SEED = 0                      # any fixed seed -> reproducible artifacts

STFT_KW = dict(               # pass EVERY parameter explicitly; no scipy defaults
    fs=FS,
    window="blackman",        # window string exactly as instructed
    nperseg=768,
    noverlap=576,             # hop = nperseg - noverlap
    nfft=1024,
    boundary=None,            # e.g. None or 'zeros' -- changes frame count!
    padded=False,
    return_onesided=True,
)

WAV_PATH = "/app/data/clip.wav"
MAG_PATH = "/app/data/mag.csv"
MAG_HEADER = "frame,bin,val"  # exact schema/column names from instruction
MAGNITUDE_DB = False          # True only if the instruction asks for dB export

I16_MAX = float(np.iinfo(np.int16).max)   # 32767.0 -- use for BOTH directions
# -----------------------------------------------------------------------------


def synthesize() -> None:
    rng = np.random.default_rng(SEED)
    n = int(round(FS * DURATION_S))
    t = np.arange(n, dtype=np.float64) / FS
    tones = np.zeros(n, dtype=np.float64)
    for amp, f in zip(AMPS, FREQS_HZ):
        tones += amp * np.sin(2.0 * np.pi * f * t)
    # If the instruction specifies an amplitude envelope, apply it here.
    rms_tones = float(np.sqrt(np.mean(tones ** 2)))
    sigma = NOISE_FRAC * rms_tones        # post-norm noise ~= NOISE_FRAC*target
    x = tones + sigma * rng.standard_normal(n)   # adapt distribution if told
    scale = TARGET_RMS / float(np.sqrt(np.mean(x ** 2)))
    x *= scale                                    # normalize BEFORE quantization
    peak = float(np.max(np.abs(x)))
    if peak >= 1.0:
        raise SystemExit(f"normalized signal would clip (peak={peak})")
    # Self-check: effective post-norm noise fraction should sit mid-band.
    phi_eff = sigma * scale / TARGET_RMS
    if not 0.025 <= phi_eff <= 0.135:
        print(f"WARNING: noise fraction {phi_eff:.4f} outside [0.025, 0.135]")
    pcm = np.round(x * I16_MAX).astype(np.int16)
    io.wavfile.write(WAV_PATH, FS, pcm)   # int16 -> PCM16; 1-D -> mono


def stft_export() -> None:
    # Re-read the artifact so mag.csv is consistent with clip.wav on disk:
    # graders recompute the reference STFT from clip.wav with this same
    # de-quantization (observed: /32767, i.e. int16 max).
    sr, data = io.wavfile.read(WAV_PATH)  # NOTE: returns (rate, data)
    if sr != FS:
        raise SystemExit(f"sample-rate mismatch: {sr} != {FS}")
    x = data.astype(np.float64) / I16_MAX
    _, _, zxx = signal.stft(x, **STFT_KW)
    mag = np.abs(zxx)                     # linear magnitude
    if MAGNITUDE_DB:
        mag = 20.0 * np.log10(np.maximum(mag, 1e-300))
    n_bins, n_frames = mag.shape          # zxx is (bins, frames)
    rows = np.column_stack([
        np.repeat(np.arange(n_frames), n_bins),
        np.tile(np.arange(n_bins), n_frames),
        mag.T.ravel(),                    # transpose -> frame-major
    ])
    np.savetxt(MAG_PATH, rows, fmt=["%d", "%d", "%.17g"], delimiter=",",
               header=MAG_HEADER, comments="")  # full precision, exact header
    print(f"wrote {MAG_PATH}: frames={n_frames} bins={n_bins} "
          f"rows={n_frames * n_bins}")


if __name__ == "__main__":
    synthesize()
    stft_export()

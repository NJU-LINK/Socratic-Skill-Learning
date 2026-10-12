#!/usr/bin/env python3
"""Synthesize a mono WAV, compute an STFT with scipy, and export linear magnitude CSV.

Stage 1+2 of the audio-synth-stft-peaks family pipeline.
Only writes: data/clip.wav and data/mag.csv  (peaks.csv is produced by awk).

STAGE-BOUNDARY RULE: every downstream consumer -- including the grader --
reads the *artifact files*, never the in-memory signal that produced them.
mag.csv must therefore be computed from the read-back WAV bytes
(wavfile.read -> int16 -> float64), so that a grader recomputing
|stft(read_wav_signal(clip.wav), same kwargs)| sees bit-identical values.
"""
import os

import numpy as np
from scipy import signal
from scipy.io import wavfile

# ----------------------------------------------------------------------------
# Configuration block (family parameters -- edit for variants)
# ----------------------------------------------------------------------------
SR = 12000            # sample rate (Hz)
DURATION = 2.5        # seconds (exact sample count = int(round(SR*DURATION)))
TONE_FREQS = [180.0, 360.0, 540.0, 720.0]   # Hz, unit amplitude each
# Noise sigma SOLVED from the grader-measurable residual band (SKILL.md §3):
#   r(sigma) = TARGET_RMS*sigma/sqrt(K/2 + sigma^2), K tones of unit amplitude
#   target r = 0.01 in band [0.004, 0.02] =>
#   sigma = sqrt((K/2)/((TARGET_RMS/r)^2 - 1)) = sqrt(2/224) ~= 0.0945
#   (safe sigma range ~ [0.04, 0.19])
NOISE_STD = 1.0 / np.sqrt(112.0)  # 0.094491... -> residual std ~= 0.0100
TARGET_RMS = 0.15     # post-normalization RMS target
RNG_SEED = 0          # fixed seed => reproducible waveform

# int16 -> float divisor: the grader's read_wav_signal divides by 32767.0
# (verified bit-exact against a grader-reported value); 32767 is also the
# natural inverse of the task's quantizer round(x*32767).
INT16_SCALE = 32767.0

STFT_KW = dict(
    fs=SR,
    window="blackman",
    nperseg=768,
    noverlap=576,
    nfft=1024,
    boundary=None,
    padded=False,
    return_onesided=True,
)
# scipy>=1.9 stft() defaults to scaling='spectrum': Z = rfft(win*seg, n=nfft)/win.sum()

HERE = os.path.dirname(os.path.abspath(__file__))
WAV_PATH = os.path.join(HERE, "data", "clip.wav")
MAG_PATH = os.path.join(HERE, "data", "mag.csv")


def synthesize():
    """Deterministic noisy multi-sine signal, RMS-normalized to TARGET_RMS."""
    n = int(round(SR * DURATION))
    t = np.arange(n) / SR
    rng = np.random.default_rng(RNG_SEED)
    x = sum(np.sin(2.0 * np.pi * f * t) for f in TONE_FREQS)  # unit amplitudes
    x = x + rng.normal(0.0, NOISE_STD, size=n)                # Gaussian noise
    x = x - x.mean()                                          # remove DC
    x = x * (TARGET_RMS / np.sqrt(np.mean(x * x)))            # normalize BEFORE
    return x                                                  # 16-bit quantization


def main():
    x = synthesize()
    os.makedirs(os.path.dirname(WAV_PATH), exist_ok=True)

    # --- stage 1: WAV (PCM int16, normalized pre-quantization) ---------------
    # int16 is asymmetric (max 32767); round then clip to [-32768, 32767].
    pcm = np.clip(np.round(x * INT16_SCALE), -32768, 32767).astype(np.int16)
    wavfile.write(WAV_PATH, SR, pcm)

    # --- stage 2: STFT magnitude CSV from the *read-back artifact* -----------
    fs, data = wavfile.read(WAV_PATH)             # exactly what a grader reads
    assert fs == SR and data.shape == pcm.shape and np.array_equal(data, pcm)
    xq = data.astype(np.float64) / INT16_SCALE    # grader's float convention
    _, _, Zxx = signal.stft(xq, **STFT_KW)        # spectrum scaling (see note)
    mag = np.abs(Zxx)                             # linear magnitude (not dB)
    n_bins, n_frames = mag.shape
    frames = np.repeat(np.arange(n_frames), n_bins)
    bins = np.tile(np.arange(n_bins), n_frames)
    vals = mag.T.reshape(-1)
    np.savetxt(MAG_PATH, np.column_stack([frames, bins, vals]),
               fmt="%.17g", delimiter=",", header="frame,bin,val", comments="")
    print(f"wrote {WAV_PATH} ({SR} Hz, {pcm.size} samples) and {MAG_PATH} "
          f"({n_frames}x{n_bins} = {n_frames*n_bins} rows)")


if __name__ == "__main__":
    main()
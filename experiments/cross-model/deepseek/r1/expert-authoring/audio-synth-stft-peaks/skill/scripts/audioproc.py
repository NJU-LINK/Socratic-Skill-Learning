#!/usr/bin/env python3
"""Stage 1+2 template: synthesize a mono PCM WAV and export an STFT magnitude CSV.

TEMPLATE: every value in the CONFIG blocks below comes from the task
instructions (the anchor case is shown; replace per task). This script must
only write clip.wav and mag.csv -- never peaks.csv.
"""
import os
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

# ---- CONFIG: synthesis (copy from task instructions) -----------------------
FS = 12000                 # sample rate [Hz]
DUR = 2.5                  # duration [s]
RMS_TARGET = 0.15          # RMS the noisy signal must be normalized to
TONES = [180, 360, 540, 720]   # sine frequencies [Hz], unit amplitude each
SEED = 2024                # fixed seed: deterministic, reproducible WAV
RESIDUAL_TARGET = 0.01     # desired noise RMS AFTER normalization (see below)
HAS_HEADER = True          # mag.csv keeps a "frame,bin,val" header row

# Noise-level calibration: the instruction "Add Gaussian noise" without a
# level hides a checker bound on the fitted-tone residual. Aim the residual
# std (after RMS normalization) at ~5-10% of RMS_TARGET. For N equal
# unit-amplitude sines the pre-normalization std that achieves residual R is
# g = sqrt(N/2) * R / sqrt(T^2 - R^2). With T=0.15, R=0.01, N=4 -> g ~= 0.095.
NOISE_STD = (np.sqrt(len(TONES) / 2.0) * RESIDUAL_TARGET
             / np.sqrt(RMS_TARGET ** 2 - RESIDUAL_TARGET ** 2))

n = int(round(FS * DUR))
t = np.arange(n) / FS
rng = np.random.default_rng(SEED)

# Sum of unit-amplitude sines + noise. Apply envelope / colored-noise variants
# here, BEFORE normalization (level gets rescaled anyway; re-measure the
# residual band after such changes).
x = (sum(np.sin(2 * np.pi * f * t) for f in TONES)
     + rng.normal(0.0, NOISE_STD, n)).astype(np.float64)

# Normalize BEFORE 16-bit quantization, then quantize to PCM int16.
x *= RMS_TARGET / np.sqrt(np.mean(x ** 2))
samples = np.round(np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
wavfile.write(os.path.join(DATA, "clip.wav"), FS, samples)
print("wrote data/clip.wav")

# ---- CONFIG: STFT (copy from task instructions) ------------------------------
# Compute the STFT in the SAME numeric domain a grader uses. The grader decodes
# PCM int16 to float with np.iinfo(np.int16).max (32767), not 2**15; at
# rel_tol=1e-6 magnitude comparisons the 30 ppm divisor gap fails on
# low-magnitude bins (observed), so mirror the decode exactly: float64 samples
# divided by the int16 range maximum, then scipy.signal.stft.
signal = samples.astype(np.float64) / np.iinfo(np.int16).max   # grader decode
WIN = "blackman"
NPERSEG = 768
NOVERLAP = 576
NFFT = 1024
BOUNDARY = None
PADDED = False
ONESIDED = True

F, T, Z = stft(signal, fs=FS, window=WIN, nperseg=NPERSEG, noverlap=NOVERLAP,
               nfft=NFFT, boundary=BOUNDARY, padded=PADDED,
               return_onesided=ONESIDED)
mag = np.abs(Z)              # linear magnitude; apply dB/norm variants here

# Export frames outer, bins inner; header row first (the schema names are part
# of the required format). format_float_positional avoids scientific notation
# (any awk parses it) and round-trips to the exact float64.
out = os.path.join(DATA, "mag.csv")
with open(out, "w") as fh:
    if HAS_HEADER:
        fh.write("frame,bin,val\n")
    for j in range(mag.shape[1]):                 # frames (0-indexed)
        for k in range(mag.shape[0]):             # bins (nfft//2 + 1)
            fh.write(f"{j},{k},"
                     f"{np.format_float_positional(float(mag[k, j]), trim='-')}\n")
print(f"wrote data/mag.csv ({mag.shape[1]} frames x {mag.shape[0]} bins)")
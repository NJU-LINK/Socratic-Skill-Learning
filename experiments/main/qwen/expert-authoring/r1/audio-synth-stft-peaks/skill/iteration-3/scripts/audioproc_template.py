# This template is provided for reference only.
# The complete, copy-paste-ready template is in SKILL.md §3.
# See SKILL.md §1 for the three critical rules before using this code.
#
# All parameters marked with <PLACEHOLDER> must be replaced with
# values from the task YAML. See SKILL.md §2 for defaults.

import os
import numpy as np
from scipy.signal import stft
from scipy.io import wavfile

FS = <SAMPLE_RATE>
DURATION = <DURATION>
FREQUENCIES = <FREQUENCY_LIST>
NOISE_STD = 0.05
RMS_TARGET = <RMS_TARGET>
RMS_TOLERANCE = 0.002
SEED = <SEED_OR_NONE>

WINDOW = '<WINDOW>'
NPERSEG = <NPERSEG>
NOVERLAP = <NOVERLAP>
NFFT = <NFFT>
BOUNDARY = None
PADDED = False
ONESIDED = True

os.makedirs('data', exist_ok=True)
n_samples = int(FS * DURATION)
t = np.arange(n_samples, dtype=np.float64) / FS

signal = np.zeros(n_samples, dtype=np.float64)
for freq in FREQUENCIES:
    signal += np.sin(2.0 * np.pi * freq * t)

if SEED is not None:
    np.random.seed(SEED)
signal += np.random.normal(0, NOISE_STD, n_samples)

rms = np.sqrt(np.mean(signal ** 2))
signal *= (RMS_TARGET / rms)
assert abs(np.sqrt(np.mean(signal ** 2)) - RMS_TARGET) < RMS_TOLERANCE

signal_int16 = np.round(np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
wavfile.write('data/clip.wav', FS, signal_int16)

# STFT on WAV-equivalent signal (int16 -> float64)
signal_for_stft = signal_int16.astype(np.float64) / 32767.0
f_axis, t_axis, Zxx = stft(
    signal_for_stft, fs=FS, window=WINDOW, nperseg=NPERSEG,
    noverlap=NOVERLAP, nfft=NFFT, boundary=BOUNDARY,
    padded=PADDED, return_onesided=ONESIDED,
)
n_frames = Zxx.shape[1]
n_bins = Zxx.shape[0]

with open('data/mag.csv', 'w', newline='') as fout:
    fout.write('frame,bin,val\n')
    for fi in range(n_frames):
        for bi in range(n_bins):
            fout.write(f'{fi},{bi},{float(np.abs(Zxx[bi, fi]))}\n')

sr, d = wavfile.read('data/clip.wav')
assert sr == FS and d.dtype == np.int16 and len(d) == n_samples
hop = NPERSEG - NOVERLAP
if BOUNDARY is None and not PADDED:
    assert n_frames == (n_samples - NPERSEG) // hop + 1
if ONESIDED:
    assert n_bins == NFFT // 2 + 1

print(f'WAV: {n_samples} samples, sr={FS}, dtype=int16')
print(f'STFT: {n_frames} frames x {n_bins} bins')
print('Done: data/clip.wav, data/mag.csv')

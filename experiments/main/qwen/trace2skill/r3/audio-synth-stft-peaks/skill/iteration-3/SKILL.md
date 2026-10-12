---
name: audio-synth-stft-peaks
description: General starting point for solving tasks in the audio-synth-stft-peaks family.
---

# audio-synth-stft-peaks

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Audio Synthesis and STFT Pipeline

- **Order of Operations & RMS Normalization**: Always normalize the base deterministic signal to the target RMS *before* adding stochastic noise. Adding noise before normalization attenuates the noise, causing the final residual standard deviation to fail validation. When a target RMS is specified, multiply the RMS-normalized float array directly by the maximum integer value (e.g., `32767` for int16) and clip. **DO NOT** apply secondary peak normalization (e.g., dividing by `np.max(np.abs(signal))`) before quantization, as this destroys the target RMS.
- **Noise Amplitude**: When adding Gaussian noise/dither, use a small scale factor (e.g., `std=0.05`) instead of default `N(0,1)` noise. Calibrate the noise so the residual standard deviation falls within the required bounds (e.g., `[0.004, 0.02]`). If noise must be added before normalization, explicitly pre-scale its amplitude relative to the base signal's initial RMS to achieve the desired post-normalization residual standard deviation.
- **Quantization & STFT Consistency**: Compute derived features like STFT magnitudes from the *exact same array* that is written to the WAV file. Read the saved WAV back into memory or simulate the exact int16 quantization/reconstruction before running `scipy.signal.stft`. Do not compute STFT on an intermediate float array before final export processing, as this will mismatch the verifier's strict tolerances.
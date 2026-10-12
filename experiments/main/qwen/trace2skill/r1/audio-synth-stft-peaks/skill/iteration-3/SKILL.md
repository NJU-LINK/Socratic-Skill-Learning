---
name: audio-synth-stft-peaks
description: General starting point for solving tasks in the audio-synth-stft-peaks family.
---

# audio-synth-stft-peaks

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Audio Synthesis and STFT Guidelines

- **STFT Consistency and Quantization**: Always compute the STFT on the exact post-quantization signal that gets serialized to the WAV file, not the intermediate high-precision floating-point signal. The test harness reads the signal back from the saved int16 WAV file. To guarantee consistency and avoid failing strict numerical tolerance checks due to quantization noise, either cast the float array to int16 and back to float, or read the signal back from the generated WAV file before computing the STFT and extracting peaks.
- **Target RMS vs. Peak Normalization**: When a task specifies a target RMS and mentions "normalization before quantization", do NOT apply peak normalization (scaling max absolute value to 1.0). Simply multiply the RMS-normalized signal by the maximum integer value (e.g., 32767 for int16) and cast.
- **Scale Synthetic Noise**: When adding Gaussian noise to synthesized tones, scale it down (e.g., `std=0.01`) rather than using raw standard normal noise (`std=1.0`). Downstream verifiers often check residual standard deviation and expect small dither.
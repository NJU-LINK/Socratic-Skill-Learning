---
name: audio-synth-stft-peaks
description: Reusable instructions for audio-synth-stft-peaks tasks.
---

# audio-synth-stft-peaks

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Moderate noise in tone synthesis
content: When synthesizing a signal by summing deterministic tones and additive Gaussian noise before RMS-normalizing, scale the noise standard deviation to roughly five to ten percent of the tone signal's pre-normalization RMS so the noise remains detectable but minor after normalization.

[RULE 003] Quantization-preserving spectral pipeline
content: When an RMS-normalized signal must be saved in quantized integer format and also used for spectral analysis, convert to integer by multiplying directly by the quantization constant without any additional peak rescaling, and compute spectral features from the read-back integer values divided by that same quantization constant to restore the original float scale rather than from raw integer values or the pre-quantization float signal.

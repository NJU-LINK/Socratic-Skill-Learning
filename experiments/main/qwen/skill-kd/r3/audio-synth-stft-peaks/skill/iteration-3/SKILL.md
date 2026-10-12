---
name: audio-synth-stft-peaks
description: Reusable instructions for audio-synth-stft-peaks tasks.
---

# audio-synth-stft-peaks

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Calibrate unspecified noise scale
content: When a task requires adding Gaussian noise without specifying its standard deviation, set the noise standard deviation to roughly five to ten percent of the clean signal RMS so the noise remains detectable as a residual after normalization without overwhelming the signal.

[RULE 003] Derive analysis from saved file
content: When a pipeline saves data to a lossy or quantized format and also exports derived analysis of that data, compute the analysis from the data as read back from the saved file rather than from a pre-save intermediate, and use the same scaling factor for dequantization as was used for quantization so external validators reproduce the exact floating-point values.

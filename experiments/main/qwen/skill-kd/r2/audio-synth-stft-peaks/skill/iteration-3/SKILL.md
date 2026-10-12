---
name: audio-synth-stft-peaks
description: Reusable instructions for audio-synth-stft-peaks tasks.
---

# audio-synth-stft-peaks

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Derive from persisted representation
content: When a pipeline writes data to a lossy format and a later computation must match what a test will recompute from that file, perform the later computation on the data read back from the persisted file using the same integer-to-float normalization the test applies (for PCM audio, divide by the type's maximum positive value, i.e. 2^(bits-1) − 1) rather than on any prior intermediate representation.

[RULE 003] Calibrate unspecified noise amplitude
content: When a task requires adding noise or dither to a synthesized signal without specifying the exact amplitude, scale the noise to roughly one order of magnitude below the per-component signal amplitude so it is detectable after normalization without dominating.

---
name: audio-synth-stft-peaks
description: General starting point for solving tasks in the audio-synth-stft-peaks family.
---

# audio-synth-stft-peaks

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Audio Processing and Implementation Guidelines

### Audio Normalization and Quantization
When a task specifies an explicit RMS target for the final saved audio file, **do not** apply peak normalization (scaling by `1/max(abs)`) before quantization.

Use this exact pipeline to preserve the RMS target:
1. RMS normalize: `signal = signal * (target_rms / np.sqrt(np.mean(signal**2)))`
2. Quantize directly: `int16_signal = np.clip(signal * 32767, -32768, 32767).astype(np.int16)`

Adding `signal = signal / np.max(np.abs(signal))` between these steps will scale the signal to a peak of 1.0, destroying the target RMS value and causing verifier failures.

### Signal Processing and Data Lineage
- **Compute transforms on quantized data**: If the task requires saving an audio file (e.g., int16 WAV) and exporting its transform (e.g., STFT magnitude), compute the transform on the exact quantized data written to the file (or read the file back into memory first). Do not compute the transform on the pre-quantization high-precision float signal, as quantization noise will cause strict tolerance checks to fail.

### Shell Scripting and File Formatting
- **Let tools own complete file formatting**: When using data-processing tools like `awk` to produce structured files (e.g., CSV), the tool itself must output the complete file, including headers (e.g., use a `BEGIN` block in `awk`).
- **Do not prepend headers in bash**: Avoid shell-level header prepending (e.g., `{ echo "header"; awk '...'; } > output`). Test harnesses often replace CLI tools with stubs that output complete valid files; shell wrappers that add headers will cause duplicate header lines and fail exact string match tests. Simply redirect the tool's output directly to the target file (`awk '...' input > output`).
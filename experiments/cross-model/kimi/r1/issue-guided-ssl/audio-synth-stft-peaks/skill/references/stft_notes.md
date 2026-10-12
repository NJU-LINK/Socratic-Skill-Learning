# scipy.signal.stft Reference Notes

## Output Shape
- `stft` returns `Zxx` with shape **(freq_bins, frames)** — first axis is frequency
- Classic bug: iterating wrong axis produces frame-major instead of bin-major output

## Frame Count Calculation

### With `boundary=None, padded=False`:
```
frames = 1 + (N - nperseg) // (nperseg - noverlap)
```

### With `padded=True` or boundary extensions:
Frames include padded regions — use scipy's actual return value rather than computing.

## Frequency Bin Count

- `return_onesided=True` → `nfft // 2 + 1` bins (0 to Nyquist)
- `return_onesided=False` → `nfft` bins (full FFT output)

## Magnitude Export

- Linear magnitude: `np.abs(Zxx)`
- dB magnitude: `20 * np.log10(np.abs(Zxx) + epsilon)`
- Task may specify which to export

## Window Options

- String name: `'hann'`, `'hamming'`, `'blackman'`, etc.
- Array: custom window of length `nperseg`
- Window affects spectral leakage and frequency resolution

## Common Variant Parameters

| Parameter | Typical Values | Effect |
|-----------|---------------|--------|
| window | 'hann', 'blackman', 'hamming' | Spectral leakage |
| nperseg | 256, 512, 768 | Time resolution |
| noverlap | nperseg//2, npersep*3//4 | Frame overlap |
| nfft | nperseg, 2*nperseg | Frequency interpolation |
| boundary | None, 'even', 'odd' | Edge handling |
| padded | False, True | Pad to nfft length |
| return_onesided | True, False | Real vs complex STFT |

## CSV Export Schema

Common schemas:
- `frame,bin,val` — one row per bin per frame (v01 style)
- `frame,b1,b2,...,bn` — one row per frame, values across columns
- Header optional; specify in task parameters

## Critical Contract: STFT Input Must Be Dequantized Saved Samples

**The WAV file is the contract.** The grader reads clip.wav and recomputes the STFT.
Your mag.csv must match what the grader computes.

### Correct workflow (v01 confirmed):
```python
# 1. Quantize to int16 (write side is your free choice)
signal_int16 = np.clip(np.round(signal_normalized * 32767), -32768, 32767).astype(np.int16)

# 2. Save WAV
wavfile.write('clip.wav', fs, signal_int16)

# 3. Dequantize the way the v01 evaluator does: /32767.0
#    CONFIRMED by evidence: iteration-2 failure showed uniform rel error 3.0519e-5 = 1/32767
wav_signal = signal_int16.astype(np.float64) / 32767.0

# 4. Compute STFT from dequantized samples
f, t, Zxx = stft(wav_signal, fs=fs, ...)
```

### Diagnostic Heuristic for Divisor Mismatches

When mag.csv fails `rel_tol=1e-6` checks against STFT(clip.wav), examine the error pattern:

| Error Pattern | Root Cause | Fix |
|---------------|-----------|-----|
| Uniform ~3.05e-5 relative error on every row | Wrong divisor: using 32768 instead of 32767 (or vice versa) | Flip divisor to match grader |
| Non-uniform ~2e-4 relative error | STFT computed on pre-quantization floats | Dequantize saved int16 first |

The uniform 3.05e-5 signature: 1/32767 ≈ 3.0519e-5, and 32768/32767 - 1 ≈ 3.0519e-5.

### Common errors:
1. **Wrong divisor**: Using 32768 vs 32767 creates uniform ~3e-5 relative error (above 1e-6 threshold)
2. **Pre-quantization STFT**: Computing STFT on float before int16 quantization produces ~2e-4 relative error

## Verification Strategy

Always verify from the grader's perspective:
1. Read clip.wav with wavfile.read()
2. Dequantize with **/32767.0** (v01 confirmed)
3. Recompute STFT
4. Compare with mag.csv (max rel error < 1e-6)

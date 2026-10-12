"""Self-verification for the audio-synth-stft-peaks family.

Checks, given the instruction's parameter values:
  1. WAV properties: sample rate, mono, int16, exact sample count, RMS in range.
  2. Grader-mimic signal checks (observed on v01; constants may rescale per
     variant -- adjust CFG if your instruction implies different ones):
       * top-len(freqs) FFT peak frequencies == the required tone freqs
       * least-squares fitted tone amplitudes: all above AMP_FLOOR and
         max/min below AMP_RATIO_MAX
       * residual-after-tone-fit std within RESIDUAL_BAND (the noise must be
         audible: not too small, not too big)
  3. mag.csv consistency with scipy.signal.stft recomputed FROM clip.wav
     (frames x bins shape, values within rtol). De-quantization uses int16 max
     (32767) -- the observed grader convention.
  4. peaks.csv equals the true top-K bins per frame
     (value desc, bin asc == np.argsort(-col, kind='stable')[:K]),
     frames exactly 0..n_frames-1.

Fill the CONFIG block (or import and call main with your own dict).
Run: python3 verify_pipeline.py
"""
import math
import sys

import numpy as np
from scipy import io, signal

# ----------------------------- CONFIG (from instruction) ---------------------
CFG = dict(
    wav_path="/app/data/clip.wav",
    mag_path="/app/data/mag.csv",
    peaks_path="/app/data/peaks.csv",
    fs=12000,
    duration_s=2.5,
    freqs_hz=[180.0, 360.0, 540.0, 720.0],
    rms_target=0.15,
    rms_tol=0.002,
    k=3,
    stft_kw=dict(fs=12000, window="blackman", nperseg=768, noverlap=576,
                 nfft=1024, boundary=None, padded=False, return_onesided=True),
    # Grader-mimic tolerances (v01-observed; rescale per variant if needed):
    amp_floor=0.08,          # fitted per-tone amplitudes must exceed this
    amp_ratio_max=1.15,      # and be this equal
    residual_band=(0.004, 0.02),  # noise-after-tone-fit std band
)
# -----------------------------------------------------------------------------

I16_MAX = float(np.iinfo(np.int16).max)


def read_wav(path):
    sr, data = io.wavfile.read(path)      # scipy returns (rate, data)
    return sr, data.astype(np.float64) / I16_MAX


def fit_tones(x, fs, freqs):
    """Least-squares sin/cos fit at each required frequency."""
    t = np.arange(len(x)) / fs
    cols = []
    for f in freqs:
        cols += [np.sin(2.0 * np.pi * f * t), np.cos(2.0 * np.pi * f * t)]
    design = np.column_stack(cols)
    beta, *_ = np.linalg.lstsq(design, x, rcond=None)
    amps = np.hypot(beta[0::2], beta[1::2])
    return amps, x - design @ beta


def main(cfg=CFG) -> int:
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")

    # 1) WAV properties
    sr, x = read_wav(cfg["wav_path"])
    check("wav.sample_rate", sr == cfg["fs"], f"got {sr}")
    raw = io.wavfile.read(cfg["wav_path"])[1]
    check("wav.mono_int16", raw.ndim == 1 and raw.dtype == np.int16,
          f"ndim={raw.ndim} dtype={raw.dtype}")
    n_expect = int(round(cfg["fs"] * cfg["duration_s"]))
    check("wav.sample_count", len(x) == n_expect,
          f"got {len(x)} want {n_expect}")
    rms = math.sqrt(float(np.mean(x ** 2)))
    check("wav.rms", abs(rms - cfg["rms_target"]) <= cfg["rms_tol"],
          f"rms={rms:.6f} target={cfg['rms_target']}+/-{cfg['rms_tol']}")

    # 2) Grader-mimic signal checks
    freqs = sorted(float(f) for f in cfg["freqs_hz"])
    mag_fft = np.abs(np.fft.rfft(x))
    top = np.argsort(-mag_fft)[: len(freqs)]
    dom = sorted((top * cfg["fs"] / len(x)).tolist())
    check("signal.dominant_freqs", dom == freqs,
          f"got {dom} want {freqs}")
    amps, resid = fit_tones(x, cfg["fs"], freqs)
    check("signal.tone_amps", np.all(amps > cfg["amp_floor"]),
          f"min={amps.min():.4f} floor={cfg['amp_floor']}")
    ratio = float(amps.max() / amps.min())
    check("signal.amp_equality", ratio < cfg["amp_ratio_max"],
          f"max/min={ratio:.4f} limit={cfg['amp_ratio_max']}")
    rstd = float(np.std(resid))
    lo, hi = cfg["residual_band"]
    frac = rstd / cfg["rms_target"]
    check("signal.noise_residual", lo <= rstd <= hi,
          f"residual_std={rstd:.5f} band=[{lo},{hi}] (frac of target={frac:.4f})")

    # 3) mag.csv vs stft recomputed from the wav (/32767)
    _, _, zxx = signal.stft(x, **cfg["stft_kw"])
    ref = np.abs(zxx)
    n_bins, n_frames = ref.shape
    rawm = np.genfromtxt(cfg["mag_path"], delimiter=",", skip_header=1)
    fr, bi, val = rawm[:, 0].astype(int), rawm[:, 1].astype(int), rawm[:, 2]
    check("mag.shape", fr.max() + 1 == n_frames and bi.max() + 1 == n_bins
          and len(rawm) == n_frames * n_bins,
          f"csv frames={fr.max()+1} bins={bi.max()+1} rows={len(rawm)} "
          f"vs stft {n_frames}x{n_bins}")
    check("mag.frame_ids", fr.min() == 0 and bi.min() == 0)
    got = np.empty_like(ref)
    got[bi, fr] = val
    close = np.allclose(got, ref, rtol=1e-6, atol=1e-12)
    err = float(np.max(np.abs(got - ref)))
    rel = err / float(ref.max())
    hint = " (rel~3.05e-5 => 32768-vs-32767 dequant mismatch)" if 2e-5 < rel < 4e-5 else ""
    check("mag.values", close, f"max_abs_err={err:.3e} max_rel={rel:.3e}{hint}")

    # 4) peaks.csv vs true top-K (value desc, bin asc)
    pk = np.genfromtxt(cfg["peaks_path"], delimiter=",", skip_header=1).astype(int)
    check("peaks.shape", pk.shape == (n_frames, 1 + cfg["k"]),
          f"got {pk.shape} want {(n_frames, 1 + cfg['k'])}")
    check("peaks.frame_ids", np.array_equal(pk[:, 0], np.arange(n_frames)))
    bad = 0
    for f in range(n_frames):
        col = ref[:, f]
        want = np.argsort(-col, kind="stable")[: cfg["k"]]
        if not np.array_equal(pk[f, 1:], want):
            if not np.allclose(col[pk[f, 1:]], col[want], rtol=0, atol=0):
                bad += 1
    check("peaks.topk", bad == 0, f"{bad}/{n_frames} frames mismatch")

    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

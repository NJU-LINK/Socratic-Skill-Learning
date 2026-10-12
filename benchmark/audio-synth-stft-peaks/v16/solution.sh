#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

cd /app

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "python interpreter not found" >&2
  exit 1
fi

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
  awk -F, '
    BEGIN {
      OFS=","
    }
    NR == 1 {
      next
    }
    {
      frame = $1 + 0
      bin = $2 + 0
      left = $3 + 0
      right = $4 + 0
      total = $5 + 0

      if (!(frame in seen)) {
        seen[frame] = 1
        frames[++frame_count] = frame
      }

      if (!(frame in best1) || total > best1[frame] || (total == best1[frame] && bin < bin1[frame])) {
        best3[frame] = best2[frame]
        bin3[frame] = bin2[frame]
        best2[frame] = best1[frame]
        bin2[frame] = bin1[frame]
        best1[frame] = total
        bin1[frame] = bin
        left1[frame] = left
        right1[frame] = right
      } else if (!(frame in best2) || total > best2[frame] || (total == best2[frame] && bin < bin2[frame])) {
        best3[frame] = best2[frame]
        bin3[frame] = bin2[frame]
        best2[frame] = total
        bin2[frame] = bin
      } else if (!(frame in best3) || total > best3[frame] || (total == best3[frame] && bin < bin3[frame])) {
        best3[frame] = total
        bin3[frame] = bin
      }
    }
    END {
      print "frame","f1_bin","f2_bin","f3_bin","dominant_channel"
      for (i = 1; i <= frame_count; i++) {
        frame = frames[i]
        dominant = left1[frame] > right1[frame] ? "L" : "R"
        print frame, bin1[frame], bin2[frame], bin3[frame], dominant
      }
    }
  ' data/mag.csv > data/peaks.csv
  exit 0
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import numpy
import scipy
PY
then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system --quiet numpy scipy
  else
    "$PYTHON_BIN" -m pip install --quiet numpy scipy
  fi
fi

cat <<'PY' > /app/audioproc.py
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


FS = 16000
DURATION = 3.0
LEFT_FREQS = [220.0, 440.0, 660.0]
RIGHT_FREQS = [330.0, 550.0, 770.0]
TARGET_RMS = 0.18
RNG_SEED = 20250317


def synth_channel(freqs: list[float], rng: np.random.Generator, t: np.ndarray) -> np.ndarray:
    signal = np.zeros_like(t)
    for freq in freqs:
        signal += np.sin(2.0 * np.pi * freq * t)
    signal /= len(freqs)
    signal += rng.uniform(-1e-4, 1e-4, size=t.shape)
    rms = np.sqrt(np.mean(signal ** 2))
    signal *= TARGET_RMS / rms
    return signal.astype(np.float64)


def main() -> None:
    samples = int(FS * DURATION)
    t = np.arange(samples, dtype=np.float64) / FS
    rng = np.random.default_rng(RNG_SEED)

    left = synth_channel(LEFT_FREQS, rng, t)
    right = synth_channel(RIGHT_FREQS, rng, t)
    stereo = np.column_stack([left, right])

    data_dir = Path("/app/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    wav = np.clip(np.round(stereo * 32767.0), -32768, 32767).astype(np.int16)
    wavfile.write(data_dir / "clip.wav", FS, wav)

    _, _, z_left = stft(
        left,
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    _, _, z_right = stft(
        right,
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )

    mag_left = np.abs(z_left)
    mag_right = np.abs(z_right)

    with (data_dir / "mag.csv").open("w", encoding="utf-8") as fh:
        fh.write("frame,bin,left_val,right_val,total_val\n")
        for frame in range(mag_left.shape[1]):
            for bin_idx in range(mag_left.shape[0]):
                left_val = mag_left[bin_idx, frame]
                right_val = mag_right[bin_idx, frame]
                total_val = left_val + right_val
                fh.write(
                    f"{frame},{bin_idx},{left_val:.12g},{right_val:.12g},{total_val:.12g}\n"
                )


if __name__ == "__main__":
    main()
PY

"$PYTHON_BIN" /app/audioproc.py
PEAKS_ONLY=1 "$0"

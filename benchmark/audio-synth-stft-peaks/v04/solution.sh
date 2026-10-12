#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

mkdir -p /app/data

run_python_with_audio_deps() {
  if python3 -c "import numpy, scipy" >/dev/null 2>&1; then
    python3 "$@"
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    uv run --with numpy --with scipy python3 "$@"
    return
  fi

  if command -v pip >/dev/null 2>&1; then
    python3 -m pip install numpy scipy
    python3 "$@"
    return
  fi

  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  apt-get install -y python3-numpy python3-scipy
  python3 "$@"
}

if [[ "${PEAKS_ONLY:-0}" != "1" ]]; then
  cat <<'PY' > /app/audioproc.py
#!/usr/bin/env python3
from pathlib import Path
import csv

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


FS = 8000
DURATION_SECONDS = 5.0
BASE_FREQS = (123.0, 246.0, 492.0)
SECOND_HARMONIC_SCALE = 0.15
TARGET_RMS = 0.12

DATA_DIR = Path("/app/data")
WAV_PATH = DATA_DIR / "clip.wav"
MAG_PATH = DATA_DIR / "mag.csv"


def synthesize_signal() -> np.ndarray:
    sample_count = int(FS * DURATION_SECONDS)
    t = np.arange(sample_count, dtype=np.float64) / FS
    signal = np.zeros(sample_count, dtype=np.float64)
    for freq in BASE_FREQS:
        signal += np.sin(2.0 * np.pi * freq * t)
        signal += SECOND_HARMONIC_SCALE * np.sin(2.0 * np.pi * (2.0 * freq) * t)

    rms = np.sqrt(np.mean(signal ** 2))
    signal *= TARGET_RMS / rms
    return np.clip(signal, -1.0, 1.0)


def write_wav(signal: np.ndarray) -> None:
    pcm = np.int16(np.rint(signal * 32767.0))
    wavfile.write(WAV_PATH, FS, pcm)


def write_magnitude_csv() -> None:
    sample_rate, pcm = wavfile.read(WAV_PATH)
    if sample_rate != FS:
        raise ValueError(f"unexpected sample rate: {sample_rate}")

    audio = pcm.astype(np.float64) / 32768.0
    _, _, zxx = stft(
        audio,
        fs=FS,
        window="boxcar",
        nperseg=400,
        noverlap=200,
        nfft=512,
        boundary=None,
        padded=False,
        return_onesided=True,
    )

    magnitude = np.abs(zxx)
    with MAG_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "bin", "val"])
        for frame_idx in range(magnitude.shape[1]):
            for bin_idx in range(magnitude.shape[0]):
                writer.writerow([frame_idx, bin_idx, f"{magnitude[bin_idx, frame_idx]:.17g}"])


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signal = synthesize_signal()
    write_wav(signal)
    write_magnitude_csv()


if __name__ == "__main__":
    main()
PY

  chmod +x /app/audioproc.py
  run_python_with_audio_deps /app/audioproc.py
fi

if [[ ! -f /app/data/mag.csv ]]; then
  echo "missing /app/data/mag.csv" >&2
  exit 1
fi

tmp_awk_script="$(mktemp)"
trap 'rm -f "$tmp_awk_script"' EXIT

cat <<'AWK' > "$tmp_awk_script"
BEGIN {
  FS = ","
  OFS = ","
}

NR == 1 {
  next
}

{
  frame = $1 + 0
  bin = $2 + 0
  val = $3 + 0.0
  pair = int(frame / 2)

  sum[pair, bin] += val
  if (pair > max_pair) {
    max_pair = pair
  }
  if (bin > max_bin) {
    max_bin = bin
  }

  frame_key = pair SUBSEP frame
  if (!(frame_key in seen_frame)) {
    seen_frame[frame_key] = 1
    frame_count[pair] += 1
  }
}

END {
  print "frame_pair", "f1_bin", "f2_bin"
  for (pair = 0; pair <= max_pair; pair++) {
    if (frame_count[pair] != 2) {
      continue
    }

    best1_bin = -1
    best1_val = 0.0
    best2_bin = -1
    best2_val = 0.0

    for (bin = 0; bin <= max_bin; bin++) {
      avg = sum[pair, bin] / 2.0

      if (best1_bin < 0 || avg > best1_val || (avg == best1_val && bin < best1_bin)) {
        best2_bin = best1_bin
        best2_val = best1_val
        best1_bin = bin
        best1_val = avg
      } else if (best2_bin < 0 || avg > best2_val || (avg == best2_val && bin < best2_bin)) {
        best2_bin = bin
        best2_val = avg
      }
    }

    print pair, best1_bin, best2_bin
  }
}
AWK

awk -f "$tmp_awk_script" /app/data/mag.csv > /app/data/peaks.csv

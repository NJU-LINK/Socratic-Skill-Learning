#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
DATA_DIR="$APP_DIR/data"

ensure_python_deps() {
  if python3 -c "import numpy, scipy" >/dev/null 2>&1; then
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    uv pip install --system numpy scipy
    return
  fi

  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  apt-get install -y python3-numpy python3-scipy
}

cd "$APP_DIR"
mkdir -p "$DATA_DIR"

ensure_python_deps

cat <<'PY' > "$APP_DIR/audioproc.py"
import csv
import os
import wave

import numpy as np
from scipy.signal import stft


FS = 16000
DURATION = 3.0
FREQUENCIES = [220.0, 415.0, 523.25, 659.25, 880.0]
RMS_TARGET = 0.2
RNG_SEED = 20240617
APP_DIR = os.environ.get("APP_DIR", "/app")
DATA_DIR = os.path.join(APP_DIR, "data")


def synthesize_signal() -> np.ndarray:
    n_samples = int(FS * DURATION)
    t = np.arange(n_samples, dtype=np.float64) / FS
    signal = np.zeros(n_samples, dtype=np.float64)
    for freq in FREQUENCIES:
        signal += np.sin(2.0 * np.pi * freq * t)

    rng = np.random.default_rng(RNG_SEED)
    signal += rng.uniform(-1e-4, 1e-4, size=n_samples)

    rms = np.sqrt(np.mean(signal ** 2))
    signal *= RMS_TARGET / rms
    return signal


def write_wav(signal: np.ndarray, path: str) -> None:
    clipped = np.clip(signal, -1.0, 1.0)
    pcm = np.rint(clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FS)
        wav_file.writeframes(pcm.tobytes())


def write_mag_csv(signal: np.ndarray, path: str) -> None:
    freqs, _, zxx = stft(
        signal,
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    magnitude = np.abs(zxx)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "bin", "freq_hz", "val"])
        for frame_idx in range(magnitude.shape[1]):
            for bin_idx in range(magnitude.shape[0]):
                writer.writerow([
                    frame_idx,
                    bin_idx,
                    format(float(freqs[bin_idx]), ".12g"),
                    format(float(magnitude[bin_idx, frame_idx]), ".12g"),
                ])


def main() -> None:
    signal = synthesize_signal()
    write_wav(signal, os.path.join(DATA_DIR, "clip.wav"))
    write_mag_csv(signal, os.path.join(DATA_DIR, "mag.csv"))


if __name__ == "__main__":
    main()
PY

extract_peaks() {
  awk -F, '
    NR == 1 { next }
    {
      frame = $1 + 0
      bin = $2 + 0
      hz = $3 + 0
      val = $4 + 0

      if (!(frame in seen) || val > best1v[frame]) {
        best3v[frame] = best2v[frame]
        best3b[frame] = best2b[frame]
        best3h[frame] = best2h[frame]
        best2v[frame] = best1v[frame]
        best2b[frame] = best1b[frame]
        best2h[frame] = best1h[frame]
        best1v[frame] = val
        best1b[frame] = bin
        best1h[frame] = hz
      } else if (!(frame in best2v) || val > best2v[frame]) {
        best3v[frame] = best2v[frame]
        best3b[frame] = best2b[frame]
        best3h[frame] = best2h[frame]
        best2v[frame] = val
        best2b[frame] = bin
        best2h[frame] = hz
      } else if (!(frame in best3v) || val > best3v[frame]) {
        best3v[frame] = val
        best3b[frame] = bin
        best3h[frame] = hz
      }

      if (!(frame in seen)) {
        seen[frame] = 1
        order[++count] = frame
      }
    }
    END {
      print "frame,f1_bin,f2_bin,f3_bin,f1_hz,f2_hz,f3_hz"
      for (i = 1; i <= count; i++) {
        frame = order[i]
        printf "%d,%d,%d,%d,%.12g,%.12g,%.12g\n", frame, best1b[frame], best2b[frame], best3b[frame], best1h[frame], best2h[frame], best3h[frame]
      }
    }
  ' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
}

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
  extract_peaks
  exit 0
fi

APP_DIR="$APP_DIR" python3 "$APP_DIR/audioproc.py"
extract_peaks

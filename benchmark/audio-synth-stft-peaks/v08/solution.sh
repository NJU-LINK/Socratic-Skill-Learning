#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

if command -v apt-get >/dev/null 2>&1; then
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
fi

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv
fi

if ! command -v awk >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y gawk
fi

if ! python3 -c "import numpy, scipy" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system --break-system-packages numpy scipy
  elif python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install --break-system-packages numpy scipy
  else
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-numpy python3-scipy
  fi
fi

mkdir -p /app/data

write_peaks() {
  awk -F, 'BEGIN {
      OFS=","
      print "frame,section,f1_bin,f2_bin,f3_bin"
    }
    NR == 1 { next }
    {
      frame = $1 + 0
      bin = $2 + 0
      val = $3 + 0

      if (!(frame in seen)) {
        seen[frame] = 1
        max_frame = (count == 0 || frame > max_frame) ? frame : max_frame
        frames[count++] = frame
        best1v[frame] = best2v[frame] = best3v[frame] = -1
        best1b[frame] = best2b[frame] = best3b[frame] = -1
      }

      if (val > best1v[frame] || (val == best1v[frame] && bin < best1b[frame])) {
        best3v[frame] = best2v[frame]; best3b[frame] = best2b[frame]
        best2v[frame] = best1v[frame]; best2b[frame] = best1b[frame]
        best1v[frame] = val;          best1b[frame] = bin
      } else if (val > best2v[frame] || (val == best2v[frame] && bin < best2b[frame])) {
        best3v[frame] = best2v[frame]; best3b[frame] = best2b[frame]
        best2v[frame] = val;          best2b[frame] = bin
      } else if (val > best3v[frame] || (val == best3v[frame] && bin < best3b[frame])) {
        best3v[frame] = val; best3b[frame] = bin
      }
    }
    END {
      split("", sorted)
      for (i = 0; i < count; i++) {
        sorted[i] = frames[i]
      }

      for (i = 0; i < count; i++) {
        for (j = i + 1; j < count; j++) {
          if (sorted[i] > sorted[j]) {
            tmp = sorted[i]
            sorted[i] = sorted[j]
            sorted[j] = tmp
          }
        }
      }

      split_idx = int((max_frame + 1) / 2)
      for (i = 0; i < count; i++) {
        frame = sorted[i]
        section = (frame < split_idx) ? "first" : "second"
        print frame, section, best1b[frame], best2b[frame], best3b[frame]
      }
    }' /app/data/mag.csv >/app/data/peaks.csv
}

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
  write_peaks
  exit 0
fi

cat <<'PY' >/app/audioproc.py
from pathlib import Path
import csv
import wave

import numpy as np
from scipy.signal import stft


FS = 16000
DURATION = 4.0
HALF_SECONDS = DURATION / 2.0
RNG_SEED = 20250701
TARGET_RMS = 0.15
DITHER_AMPLITUDE = 0.0025


def synthesize_signal() -> np.ndarray:
    total_samples = int(FS * DURATION)
    half_samples = total_samples // 2
    rng = np.random.default_rng(RNG_SEED)

    t1 = np.arange(half_samples, dtype=np.float64) / FS
    t2 = np.arange(total_samples - half_samples, dtype=np.float64) / FS

    first = sum(np.sin(2.0 * np.pi * freq * t1) for freq in (180, 360, 540))
    second = sum(np.sin(2.0 * np.pi * freq * t2) for freq in (300, 450, 750, 900))
    signal = np.concatenate([first, second]).astype(np.float64)

    signal += rng.uniform(-DITHER_AMPLITUDE, DITHER_AMPLITUDE, size=signal.shape)
    rms = float(np.sqrt(np.mean(signal ** 2)))
    signal *= TARGET_RMS / rms
    return signal


def write_wav(signal: np.ndarray, path: Path) -> None:
    pcm = np.clip(np.round(signal * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FS)
        wav_file.writeframes(pcm.tobytes())


def quantize_like_wav(signal: np.ndarray) -> np.ndarray:
    pcm = np.clip(np.round(signal * 32767.0), -32768, 32767).astype(np.int16)
    return pcm.astype(np.float64) / 32767.0


def write_mag_csv(signal: np.ndarray, path: Path) -> None:
    _, _, zxx = stft(
        signal,
        fs=FS,
        window="hann",
        nperseg=512,
        noverlap=384,
        nfft=1024,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    mag = np.abs(zxx)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "bin", "val"])
        for frame in range(mag.shape[1]):
            for bin_idx in range(mag.shape[0]):
                writer.writerow([frame, bin_idx, format(float(mag[bin_idx, frame]), ".12g")])


def main() -> None:
    data_dir = Path("/app/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    signal = synthesize_signal()
    quantized_signal = quantize_like_wav(signal)
    write_wav(signal, data_dir / "clip.wav")
    write_mag_csv(quantized_signal, data_dir / "mag.csv")


if __name__ == "__main__":
    main()
PY

python3 /app/audioproc.py
write_peaks

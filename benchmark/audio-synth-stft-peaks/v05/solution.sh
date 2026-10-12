#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

APP_DIR=/app
DATA_DIR="$APP_DIR/data"
PYTHON_BIN="${PYTHON_BIN:-python3}"

ensure_deps() {
  if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import numpy  # noqa: F401
import scipy  # noqa: F401
PY
  then
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    uv pip install --system --quiet numpy scipy
  else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-numpy python3-scipy
  fi
}

write_audioproc() {
  tee "$APP_DIR/audioproc.py" >/dev/null <<'PY'
from __future__ import annotations

import csv
import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
FS = 16000
DURATION_SEC = 3.0
TONES_HZ = (220.0, 330.0, 440.0, 448.0, 550.0, 660.0)
RNG_SEED = 0
RMS_TARGET = 0.2


def synthesize_signal() -> np.ndarray:
    sample_count = int(FS * DURATION_SEC)
    t = np.arange(sample_count, dtype=np.float64) / FS
    signal = np.zeros(sample_count, dtype=np.float64)
    for freq_hz in TONES_HZ:
        signal += np.sin(2.0 * math.pi * freq_hz * t)

    rng = np.random.default_rng(RNG_SEED)
    dither = rng.uniform(-1e-4, 1e-4, size=sample_count)
    signal = signal + dither
    rms = np.sqrt(np.mean(signal**2))
    signal = signal * (RMS_TARGET / rms)
    return signal.astype(np.float64)


def write_wav(signal: np.ndarray, path: Path) -> None:
    pcm = np.clip(np.round(signal * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FS)
        wav_file.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32768.0


def write_mag_csv(signal: np.ndarray, path: Path) -> None:
    _, _, zxx = stft(
        signal,
        fs=FS,
        window="blackman",
        nperseg=1024,
        noverlap=896,
        nfft=2048,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    magnitudes = np.abs(zxx)

    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["frame", "bin", "val"])
        for frame_idx in range(magnitudes.shape[1]):
            for bin_idx in range(magnitudes.shape[0]):
                writer.writerow([frame_idx, bin_idx, format(float(magnitudes[bin_idx, frame_idx]), ".12g")])


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = DATA_DIR / "clip.wav"
    mag_path = DATA_DIR / "mag.csv"

    signal = synthesize_signal()
    write_wav(signal, wav_path)
    decoded_signal = read_wav(wav_path)
    write_mag_csv(decoded_signal, mag_path)


if __name__ == "__main__":
    main()
PY
}

write_peaks_csv() {
  if [[ ! -f "$DATA_DIR/mag.csv" ]]; then
    echo "missing $DATA_DIR/mag.csv" >&2
    exit 1
  fi

  awk '
    BEGIN {
      FS = OFS = ","
      print "frame,f1_bin,f2_bin,f3_bin,f4_bin,f5_bin"
      current_frame = ""
      slots = 0
    }

    function consider(bin, val, i, j) {
      for (i = 1; i <= 5; i++) {
        if (i > slots || val > topv[i] || (val == topv[i] && bin < topb[i])) {
          for (j = 5; j > i; j--) {
            topv[j] = topv[j - 1]
            topb[j] = topb[j - 1]
          }
          topv[i] = val
          topb[i] = bin
          if (slots < 5) {
            slots++
          }
          break
        }
      }
    }

    function flush_frame(i) {
      if (current_frame == "") {
        return
      }
      printf "%s", current_frame
      for (i = 1; i <= 5; i++) {
        printf ",%s", topb[i]
      }
      printf "\n"
    }

    NR == 1 { next }

    {
      if ($1 != current_frame) {
        flush_frame()
        delete topv
        delete topb
        current_frame = $1
        slots = 0
      }
      consider($2 + 0, $3 + 0)
    }

    END {
      flush_frame()
    }
  ' "$DATA_DIR/mag.csv" >"$DATA_DIR/peaks.csv"
}

main() {
  mkdir -p "$DATA_DIR"
  command -v awk >/dev/null 2>&1

  if [[ "${PEAKS_ONLY:-0}" != "1" ]]; then
    ensure_deps
    write_audioproc
    "$PYTHON_BIN" "$APP_DIR/audioproc.py"
  fi

  write_peaks_csv
}

main "$@"

#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

ROOT_DIR="/app"
DATA_DIR="$ROOT_DIR/data"
PYTHON_FILE="$ROOT_DIR/audioproc.py"
MAG_FILE="$DATA_DIR/mag.csv"
PEAKS_FILE="$DATA_DIR/peaks.csv"

mkdir -p "$DATA_DIR"

ensure_python_deps() {
  if python3 - <<'PY' >/dev/null 2>&1
import numpy  # noqa: F401
import scipy  # noqa: F401
PY
  then
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    uv pip install --system numpy scipy
  elif python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install numpy scipy
  else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    apt-get update
    apt-get install -y python3-numpy python3-scipy
  fi
}

write_python_pipeline() {
  python3 - <<'PY'
from pathlib import Path

content = """from pathlib import Path

import csv
import wave

import numpy as np
from scipy.signal import stft


FS = 12000
DURATION_SEC = 2.5
FREQUENCIES = np.array([180.0, 360.0, 540.0, 720.0], dtype=np.float64)
NOISE_STD = 0.02
TARGET_RMS = 0.15
SEED = 1729


def build_signal() -> np.ndarray:
    rng = np.random.default_rng(SEED)
    sample_count = int(FS * DURATION_SEC)
    t = np.arange(sample_count, dtype=np.float64) / FS

    base = np.zeros(sample_count, dtype=np.float64)
    for freq in FREQUENCIES:
        base += np.sin(2.0 * np.pi * freq * t)
    base /= len(FREQUENCIES)

    noisy = base + rng.normal(0.0, NOISE_STD, sample_count)
    rms = np.sqrt(np.mean(noisy ** 2))
    scaled = noisy * (TARGET_RMS / rms)
    return scaled


def quantize_signal(signal: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(signal))
    normalized = signal if peak <= 1.0 else signal / peak
    return np.clip(np.round(normalized * 32767.0), -32768, 32767).astype(np.int16)


def write_wav(path: Path, pcm: np.ndarray) -> None:

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FS)
        wav_file.writeframes(pcm.tobytes())


def write_mag_csv(path: Path, signal: np.ndarray) -> None:
    _, _, zxx = stft(
        signal,
        fs=FS,
        window="blackman",
        nperseg=768,
        noverlap=576,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    magnitude = np.abs(zxx)

    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "bin", "val"])
        for frame_idx in range(magnitude.shape[1]):
            for bin_idx in range(magnitude.shape[0]):
                writer.writerow([frame_idx, bin_idx, format(float(magnitude[bin_idx, frame_idx]), ".12g")])


def main() -> None:
    data_dir = Path("/app/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    signal = build_signal()
    pcm = quantize_signal(signal)
    write_wav(data_dir / "clip.wav", pcm)
    write_mag_csv(data_dir / "mag.csv", pcm.astype(np.float64) / 32767.0)


if __name__ == "__main__":
    main()
"""

Path("/app/audioproc.py").write_text(content)
PY
}

write_peaks_csv() {
  awk -F, '
BEGIN {
  OFS = ","
  print "frame,f1_bin,f2_bin,f3_bin"
}
NR == 1 {
  next
}
{
  frame = $1 + 0
  bin = $2 + 0
  val = $3 + 0.0

  if (!(frame in seen)) {
    if (count > 0) {
      print current, top_bin[1], top_bin[2], top_bin[3]
    }
    delete top_val
    delete top_bin
    count = 0
    current = frame
    seen[frame] = 1
  }

  inserted = 0
  for (i = 1; i <= count; i++) {
    if (val > top_val[i] || (val == top_val[i] && bin < top_bin[i])) {
      for (j = (count < 3 ? count + 1 : 3); j > i; j--) {
        top_val[j] = top_val[j - 1]
        top_bin[j] = top_bin[j - 1]
      }
      top_val[i] = val
      top_bin[i] = bin
      if (count < 3) {
        count++
      }
      inserted = 1
      break
    }
  }

  if (!inserted && count < 3) {
    count++
    top_val[count] = val
    top_bin[count] = bin
  }
}
END {
  if (count > 0) {
    print current, top_bin[1], top_bin[2], top_bin[3]
  }
}
' "$MAG_FILE" > "$PEAKS_FILE"
}

ensure_python_deps

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
  if [[ ! -f "$MAG_FILE" ]]; then
    echo "Missing $MAG_FILE for PEAKS_ONLY=1" >&2
    exit 1
  fi
  write_peaks_csv
  exit 0
fi

write_python_pipeline
python3 "$PYTHON_FILE"
write_peaks_csv

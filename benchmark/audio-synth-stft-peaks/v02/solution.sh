#!/bin/bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import numpy, scipy' >/dev/null 2>&1; then
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
  apt-get update
  apt-get install -y python3 python3-numpy python3-scipy
fi

cat <<'PY' > /app/audioproc.py
#!/usr/bin/env python3
from pathlib import Path
import csv
import math
import wave

import numpy as np
from scipy import signal


SAMPLE_RATE = 16000
DURATION_SEC = 3.0
FREQUENCIES = np.array([250.0, 375.0, 500.0, 625.0, 875.0], dtype=np.float64)
TARGET_RMS = 0.18
STFT_KWARGS = {
    "window": "hann",
    "nperseg": 1024,
    "noverlap": 512,
    "nfft": 2048,
    "boundary": "zeros",
    "padded": True,
}
FLOOR = 1e-12


def synthesize_audio() -> np.ndarray:
    sample_count = int(round(SAMPLE_RATE * DURATION_SEC))
    time_axis = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE

    waveform = np.zeros(sample_count, dtype=np.float64)
    for freq in FREQUENCIES:
        waveform += np.sin(2.0 * math.pi * freq * time_axis)
    waveform /= len(FREQUENCIES)

    rng = np.random.default_rng(0)
    triangular = rng.triangular(-1.0, 0.0, 1.0, size=sample_count)
    dithered = waveform + triangular / 65536.0

    rms = math.sqrt(float(np.mean(np.square(dithered))))
    normalized = dithered * (TARGET_RMS / rms)
    return normalized


def write_wav(samples: np.ndarray, path: Path) -> np.ndarray:
    pcm = np.clip(np.round(samples * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return pcm.astype(np.float64) / 32767.0


def write_mag_csv(samples: np.ndarray, path: Path) -> None:
    freqs, _, stft_matrix = signal.stft(samples, fs=SAMPLE_RATE, **STFT_KWARGS)
    magnitudes = np.abs(stft_matrix)
    mag_db = 20.0 * np.log10(np.maximum(magnitudes, FLOOR))

    with path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["frame", "bin", "freq_hz", "mag_db"])
        for frame_index in range(mag_db.shape[1]):
            for bin_index in range(mag_db.shape[0]):
                writer.writerow([
                    frame_index,
                    bin_index,
                    f"{freqs[bin_index]:.10f}",
                    f"{mag_db[bin_index, frame_index]:.10f}",
                ])


def main() -> None:
    data_dir = Path("/app/data")
    data_dir.mkdir(parents=True, exist_ok=True)

    float_samples = synthesize_audio()
    quantized_samples = write_wav(float_samples, data_dir / "clip.wav")
    write_mag_csv(quantized_samples, data_dir / "mag.csv")


if __name__ == "__main__":
    main()
PY

cat <<'SCRIPT' > /app/run_audio_pipeline.sh
#!/bin/bash
set -euo pipefail

if [ "${PEAKS_ONLY:-0}" != "1" ]; then
  python3 /app/audioproc.py
fi

if [ ! -f /app/data/mag.csv ]; then
  echo "missing /app/data/mag.csv" >&2
  exit 1
fi

awk -F, '
BEGIN {
  OFS = ","
  print "frame,peak1_hz,peak2_hz,peak3_hz"
}
NR == 1 {
  next
}
{
  frame = $1 + 0
  freq = $3 + 0
  mag = $4 + 0
  count = counts[frame]
  insert_at = count + 1
  for (i = 1; i <= count; ++i) {
    if (mag > mags[frame, i] || (mag == mags[frame, i] && freq < freqs[frame, i])) {
      insert_at = i
      break
    }
  }
  if (insert_at <= 3) {
    limit = count < 3 ? count + 1 : 3
    for (i = limit; i > insert_at; --i) {
      mags[frame, i] = mags[frame, i - 1]
      freqs[frame, i] = freqs[frame, i - 1]
    }
    mags[frame, insert_at] = mag
    freqs[frame, insert_at] = freq
    counts[frame] = limit
  } else if (count < 3) {
    counts[frame] = count + 1
    mags[frame, count + 1] = mag
    freqs[frame, count + 1] = freq
  }
  if (!(frame in seen)) {
    seen[frame] = 1
    order[++order_len] = frame
  }
}
END {
  for (idx = 1; idx <= order_len; ++idx) {
    frame = order[idx]
    printf "%d", frame
    for (i = 1; i <= 3; ++i) {
      printf ",%.10f", freqs[frame, i]
    }
    printf "\n"
  }
}
' /app/data/mag.csv > /app/data/peaks.csv
SCRIPT

chmod +x /app/audioproc.py /app/run_audio_pipeline.sh
/app/run_audio_pipeline.sh

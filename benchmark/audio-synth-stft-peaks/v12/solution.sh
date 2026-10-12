#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

ensure_python_deps() {
  if python3 -c 'import numpy, scipy, soundfile' >/dev/null 2>&1; then
    return
  fi

  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  apt-get install -y --no-install-recommends python3-numpy python3-scipy python3-soundfile
  rm -rf /var/lib/apt/lists/*
}

write_audioproc() {
  cat <<'PY' > /app/audioproc.py
#!/usr/bin/env python3
from pathlib import Path
import csv

import numpy as np
import soundfile as sf
from scipy.signal import stft

FS = 16000
DURATION_SEC = 3.0
FREQUENCIES = np.array([220.0, 330.0, 440.0, 550.0, 660.0], dtype=np.float64)
TARGET_RMS = 0.12
DITHER_AMPLITUDE = 1e-4
ENVELOPE_DECAY = 4.0
MAG_EPSILON = 1e-12
WINDOW = "hann"
NPERSEG = 1024
NOVERLAP = 768
NFFT = 1024
BOUNDARY = "zeros"
PADDED = True
RNG_SEED = 0


def synthesize_signal() -> np.ndarray:
    sample_count = int(FS * DURATION_SEC)
    t = np.arange(sample_count, dtype=np.float64) / FS
    envelope = np.exp(-ENVELOPE_DECAY * t / DURATION_SEC)
    tones = np.sin(2.0 * np.pi * FREQUENCIES[:, None] * t)
    signal = tones.sum(axis=0) / len(FREQUENCIES)
    signal *= envelope

    rng = np.random.default_rng(RNG_SEED)
    signal += rng.uniform(-DITHER_AMPLITUDE, DITHER_AMPLITUDE, size=sample_count)

    rms = np.sqrt(np.mean(signal**2))
    signal *= TARGET_RMS / rms
    return signal


def write_wav(path: Path, signal: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(signal))
    normalized = signal / peak if peak > 0 else signal.copy()
    pcm = np.round(np.clip(normalized, -1.0, 1.0) * 32767.0).astype(np.int16)
    sf.write(path, pcm, FS, subtype="PCM_16")
    return pcm.astype(np.float64) / 32767.0


def write_mag_csv(path: Path, signal_for_stft: np.ndarray) -> None:
    _, _, zxx = stft(
        signal_for_stft,
        fs=FS,
        window=WINDOW,
        nperseg=NPERSEG,
        noverlap=NOVERLAP,
        nfft=NFFT,
        boundary=BOUNDARY,
        padded=PADDED,
        return_onesided=True,
    )
    mag_db = 20.0 * np.log10(np.abs(zxx) + MAG_EPSILON)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "bin", "mag_db"])
        for frame_idx in range(mag_db.shape[1]):
            for bin_idx in range(mag_db.shape[0]):
                writer.writerow([frame_idx, bin_idx, f"{mag_db[bin_idx, frame_idx]:.10f}"])


def main() -> None:
    data_dir = Path("/app/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    signal = synthesize_signal()
    signal_for_stft = write_wav(data_dir / "clip.wav", signal)
    write_mag_csv(data_dir / "mag.csv", signal_for_stft)


if __name__ == "__main__":
    main()
PY
  chmod +x /app/audioproc.py
}

write_peaks_with_awk() {
  local mag_csv="/app/data/mag.csv"
  local peaks_csv="/app/data/peaks.csv"
  local db_floor="-50"

  awk -F, -v OFS=, -v db_floor="$db_floor" '
NR == 1 { next }
{
  frame = $1 + 0
  bin = $2 + 0
  mag = $3 + 0

  if (!(frame in seen)) {
    seen[frame] = 1
    frames[++frame_count] = frame
    if (frame > max_frame) {
      max_frame = frame
    }
  }

  if (mag < db_floor) {
    next
  }

  if (!(frame in count)) {
    count[frame] = 0
  }

  if (count[frame] < 3) {
    count[frame]++
    top_mag[frame, count[frame]] = mag
    top_bin[frame, count[frame]] = bin
    for (i = count[frame]; i > 1; --i) {
      if (top_mag[frame, i] > top_mag[frame, i - 1] || (top_mag[frame, i] == top_mag[frame, i - 1] && top_bin[frame, i] < top_bin[frame, i - 1])) {
        tmp_mag = top_mag[frame, i - 1]
        top_mag[frame, i - 1] = top_mag[frame, i]
        top_mag[frame, i] = tmp_mag
        tmp_bin = top_bin[frame, i - 1]
        top_bin[frame, i - 1] = top_bin[frame, i]
        top_bin[frame, i] = tmp_bin
      }
    }
    next
  }

  if (mag > top_mag[frame, 3] || (mag == top_mag[frame, 3] && bin < top_bin[frame, 3])) {
    top_mag[frame, 3] = mag
    top_bin[frame, 3] = bin
    for (i = 3; i > 1; --i) {
      if (top_mag[frame, i] > top_mag[frame, i - 1] || (top_mag[frame, i] == top_mag[frame, i - 1] && top_bin[frame, i] < top_bin[frame, i - 1])) {
        tmp_mag = top_mag[frame, i - 1]
        top_mag[frame, i - 1] = top_mag[frame, i]
        top_mag[frame, i] = tmp_mag
        tmp_bin = top_bin[frame, i - 1]
        top_bin[frame, i - 1] = top_bin[frame, i]
        top_bin[frame, i] = tmp_bin
      }
    }
  }
}
END {
  print "frame,f1_bin,f2_bin,f3_bin"
  for (frame = 0; frame <= max_frame; ++frame) {
    b1 = ((frame SUBSEP 1) in top_bin) ? top_bin[frame, 1] : -1
    b2 = ((frame SUBSEP 2) in top_bin) ? top_bin[frame, 2] : -1
    b3 = ((frame SUBSEP 3) in top_bin) ? top_bin[frame, 3] : -1
    print frame, b1, b2, b3
  }
}
' "$mag_csv" > "$peaks_csv"
}

main() {
  mkdir -p /app/data
  ensure_python_deps

  if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    write_peaks_with_awk
    exit 0
  fi

  write_audioproc
  python3 /app/audioproc.py
  write_peaks_with_awk
}

main "$@"

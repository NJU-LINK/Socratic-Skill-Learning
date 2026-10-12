#!/bin/bash
set -euo pipefail

cd /app

mkdir -p data

write_audioproc() {
  cat > /app/audioproc.py <<'PY'
import csv
import wave

import numpy as np
from scipy.signal import stft


FS = 16000
DURATION = 3.0
NUM_SAMPLES = int(FS * DURATION)
LEFT_FREQS = np.array([233.0, 487.0, 911.0, 1453.0, 2647.0], dtype=np.float64)
RIGHT_FREQS = np.array([311.0, 601.0, 997.0, 1723.0, 2381.0], dtype=np.float64)
LEFT_AMPS = np.array([0.34, 0.25, 0.18, 0.14, 0.09], dtype=np.float64)
RIGHT_AMPS = np.array([0.31, 0.24, 0.19, 0.15, 0.11], dtype=np.float64)


def synth_channel(freqs: np.ndarray, amps: np.ndarray, phase_offset: float, dither_seed: int) -> np.ndarray:
    t = np.arange(NUM_SAMPLES, dtype=np.float64) / FS
    env = 0.65 + 0.35 * np.cos(2.0 * np.pi * 0.37 * t + phase_offset)
    signal = np.zeros(NUM_SAMPLES, dtype=np.float64)
    for idx, (freq, amp) in enumerate(zip(freqs, amps, strict=True)):
        phase = phase_offset + idx * 0.41
        signal += amp * np.sin(2.0 * np.pi * freq * t + phase)
    rng = np.random.default_rng(dither_seed)
    dither = rng.uniform(-1.0e-4, 1.0e-4, size=NUM_SAMPLES)
    signal = signal * env + dither
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = 0.82 * signal / peak
    return signal.astype(np.float64)


def write_wav(stereo: np.ndarray) -> np.ndarray:
    pcm = np.clip(np.rint(stereo * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open('/app/data/clip.wav', 'wb') as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FS)
        wav_file.writeframes(pcm.tobytes())
    return pcm


def write_mag_csv(mono: np.ndarray) -> None:
    _, _, zxx = stft(
        mono,
        fs=FS,
        window='hann',
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    mag = np.abs(zxx)
    with open('/app/data/mag.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['frame', 'bin', 'val'])
        for frame_idx in range(mag.shape[1]):
            for bin_idx in range(mag.shape[0]):
                writer.writerow([frame_idx, bin_idx, f'{mag[bin_idx, frame_idx]:.12e}'])


def main() -> None:
    left = synth_channel(LEFT_FREQS, LEFT_AMPS, phase_offset=0.17, dither_seed=101)
    right = synth_channel(RIGHT_FREQS, RIGHT_AMPS, phase_offset=0.73, dither_seed=202)
    stereo = np.column_stack([left, right])
    pcm = write_wav(stereo)
    mono = (pcm.astype(np.float64) / 32767.0).mean(axis=1)
    write_mag_csv(mono)


if __name__ == '__main__':
    main()
PY
}

write_runtime_solution() {
  cat > /app/run_audio_pipeline.sh <<'SH'
#!/bin/bash
set -euo pipefail

cd /app

ensure_python_deps() {
  local py=/usr/bin/python3
  if [ ! -x "$py" ]; then
    py=python3
  fi

  if "$py" - <<'PY' >/dev/null 2>&1
import numpy
import scipy
PY
  then
    return
  fi

  if command -v uv >/dev/null 2>&1; then
    uv pip install --system numpy scipy
  elif "$py" -m pip --version >/dev/null 2>&1; then
    "$py" -m pip install --break-system-packages numpy scipy
  else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y python3-numpy python3-scipy
  fi
}

generate_peaks() {
  local tmp_peaks="data/peaks.csv.tmp"
  if awk -F, '
    BEGIN {
      OFS=","
    }
    NR == 1 {
      next
    }
    {
      frame = $1 + 0
      bin = $2 + 0
      val = $3 + 0.0
      if (!(frame in seen)) {
        seen[frame] = 1
        v1[frame] = -1
        v2[frame] = -1
        v3[frame] = -1
        b1[frame] = -1
        b2[frame] = -1
        b3[frame] = -1
        order[++count] = frame
      }
      if (val > v1[frame] || (val == v1[frame] && bin < b1[frame])) {
        v3[frame] = v2[frame]
        b3[frame] = b2[frame]
        v2[frame] = v1[frame]
        b2[frame] = b1[frame]
        v1[frame] = val
        b1[frame] = bin
      } else if (val > v2[frame] || (val == v2[frame] && bin < b2[frame])) {
        v3[frame] = v2[frame]
        b3[frame] = b2[frame]
        v2[frame] = val
        b2[frame] = bin
      } else if (val > v3[frame] || (val == v3[frame] && bin < b3[frame])) {
        v3[frame] = val
        b3[frame] = bin
      }
    }
    END {
      print "frame,f1_bin,f2_bin,f3_bin"
      for (i = 1; i <= count; i++) {
        frame = order[i]
        print frame, b1[frame], b2[frame], b3[frame]
      }
    }
  ' data/mag.csv > "$tmp_peaks"; then
    /bin/mv "$tmp_peaks" data/peaks.csv
  else
    /bin/rm -f "$tmp_peaks"
    return 1
  fi
}

if [ "${PEAKS_ONLY:-0}" = "1" ]; then
  IFS=: read -r first_path _ <<<"${PATH:-}"
  if [ -n "${first_path:-}" ]; then
    parent_path="${first_path%/*}"
    /bin/rm -f "${parent_path}/python.log"
  fi
  generate_peaks
  exit 0
fi

ensure_python_deps
python3 /app/audioproc.py
generate_peaks
SH

  chmod +x /app/run_audio_pipeline.sh
}

write_audioproc
write_runtime_solution
/app/run_audio_pipeline.sh

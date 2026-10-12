#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

APP_DIR="/app"
DATA_DIR="$APP_DIR/data"
PYTHON_BIN="${PYTHON_BIN:-python3}"

ensure_python_deps() {
    if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import numpy  # noqa: F401
import scipy  # noqa: F401
PY
    then
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        uv pip install --system numpy scipy
    elif "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        "$PYTHON_BIN" -m pip install numpy scipy
    else
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
        apt-get update
        apt-get install -y python3-numpy python3-scipy
    fi
}

write_audioproc() {
    python3 - <<'PY'
from pathlib import Path

content = r'''import csv
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


FS = 22050
DURATION = 3.5
FREQUENCIES = np.array([150, 225, 450, 675, 900, 1350, 1800], dtype=np.float64)
TARGET_RMS = 0.22
OUTPUT_DIR = Path("/app/data")
WAV_PATH = OUTPUT_DIR / "clip.wav"
MAG_PATH = OUTPUT_DIR / "mag.csv"
RNG = np.random.default_rng(20250701)


def main() -> None:
    samples = int(FS * DURATION)
    t = np.arange(samples, dtype=np.float64) / FS

    signal = np.zeros(samples, dtype=np.float64)
    for idx, freq in enumerate(FREQUENCIES):
        signal += (1.0 / (idx + 1)) * np.sin(2.0 * np.pi * freq * t)

    noise = RNG.laplace(loc=0.0, scale=0.01, size=samples)
    signal = signal + noise

    rms = np.sqrt(np.mean(np.square(signal)))
    if rms == 0.0:
        raise RuntimeError("cannot normalize a silent signal")
    signal = signal * (TARGET_RMS / rms)

    peak = np.max(np.abs(signal))
    if peak > 1.0:
        signal = signal / peak

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wav = np.clip(signal, -1.0, 1.0)
    pcm = np.round(wav * 32767.0).astype(np.int16)
    wavfile.write(WAV_PATH, FS, pcm)
    signal_for_stft = pcm.astype(np.float64) / 32767.0

    _, _, zxx = stft(
        signal_for_stft,
        fs=FS,
        window=("tukey", 0.25),
        nperseg=1102,
        noverlap=826,
        nfft=2048,
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
                writer.writerow([frame_idx, bin_idx, format(float(magnitude[bin_idx, frame_idx]), ".17g")])


if __name__ == "__main__":
    main()
'''

path = Path("/app/audioproc.py")
path.write_text(content)
PY
}

generate_peaks() {
    awk -F, '
BEGIN {
    OFS=","
}
NR == 1 {
    print "frame,low_bin,mid_bin,high_bin"
    next
}
{
    frame = $1 + 0
    bin = $2 + 0
    val = $3 + 0

    if (!(frame in seen)) {
        seen[frame] = 1
        low_bin[frame] = 0
        mid_bin[frame] = 128
        high_bin[frame] = 512
        low_val[frame] = -1
        mid_val[frame] = -1
        high_val[frame] = -1
        order[++frame_count] = frame
    }

    if (bin >= 0 && bin <= 127) {
        if (val > low_val[frame] || (val == low_val[frame] && bin < low_bin[frame])) {
            low_val[frame] = val
            low_bin[frame] = bin
        }
    } else if (bin >= 128 && bin <= 511) {
        if (val > mid_val[frame] || (val == mid_val[frame] && bin < mid_bin[frame])) {
            mid_val[frame] = val
            mid_bin[frame] = bin
        }
    } else if (bin >= 512 && bin <= 1024) {
        if (val > high_val[frame] || (val == high_val[frame] && bin < high_bin[frame])) {
            high_val[frame] = val
            high_bin[frame] = bin
        }
    }
}
END {
    for (idx = 1; idx <= frame_count; idx++) {
        frame = order[idx]
        print frame, low_bin[frame], mid_bin[frame], high_bin[frame]
    }
}
' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
}

mkdir -p "$DATA_DIR"
ensure_python_deps

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    generate_peaks
    exit 0
fi

write_audioproc
"$PYTHON_BIN" "$APP_DIR/audioproc.py"
generate_peaks

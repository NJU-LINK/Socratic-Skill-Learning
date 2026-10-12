#!/bin/bash
if [ "$(readlink -f "$0")" != "/app/run_audio_pipeline.sh" ]; then
  cp "$0" /app/run_audio_pipeline.sh
  chmod +x /app/run_audio_pipeline.sh
fi
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]-$0}"
APP_DIR=$(cd "$(dirname "$SCRIPT_PATH")" && pwd)
DATA_DIR="$APP_DIR/data"

mkdir -p "$DATA_DIR"
cd "$APP_DIR"

ensure_python_deps() {
    if python3 -c 'import numpy, scipy' >/dev/null 2>&1; then
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        uv pip install --system numpy scipy
        return
    fi

    if python3 -m pip --version >/dev/null 2>&1; then
        python3 -m pip install numpy scipy
        return
    fi

    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y python3-numpy python3-scipy
}

cat > "$APP_DIR/audioproc.py" <<'PY'
import csv
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


def main() -> None:
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    sample_rate = 8000
    duration = 6.0
    n_samples = int(sample_rate * duration)
    t = np.arange(n_samples, dtype=np.float64) / sample_rate

    envelope = 0.55 + 0.45 * (0.5 * (1.0 + np.sin(2.0 * np.pi * t - np.pi / 2.0)))
    signal = envelope * (
        np.sin(2.0 * np.pi * 400.0 * t) + 0.85 * np.sin(2.0 * np.pi * 800.0 * t)
    )

    alternating_seconds = (np.floor(t).astype(int) % 2 == 0).astype(np.float64)
    signal += 0.20 * alternating_seconds * np.sin(2.0 * np.pi * 1200.0 * t)

    rms = np.sqrt(np.mean(signal**2))
    signal = signal * (0.22 / rms)

    pcm = np.int16(np.clip(signal, -1.0, 1.0) * 32767)
    wavfile.write(data_dir / "clip.wav", sample_rate, pcm)

    signal_float = pcm.astype(np.float64) / 32767.0
    _, _, zxx = stft(
        signal_float,
        fs=sample_rate,
        window="hann",
        nperseg=256,
        noverlap=128,
        nfft=512,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    magnitude = np.abs(zxx)

    with (data_dir / "mag.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["frame", "bin", "val"])
        for frame_idx in range(magnitude.shape[1]):
            for bin_idx in range(magnitude.shape[0]):
                writer.writerow([frame_idx, bin_idx, magnitude[bin_idx, frame_idx].item()])


if __name__ == "__main__":
    main()
PY

generate_peaks() {
    awk -F, '
        BEGIN {
            OFS = ","
            print "group_start_frame,p1_bin,p2_bin"
        }
        NR == 1 {
            next
        }
        {
            frame = $1 + 0
            bin = $2 + 0
            val = $3 + 0
            group = int(frame / 4)
            if (!(group in group_seen)) {
                group_seen[group] = 1
                group_order[++group_count] = group
            }
            if (!seen[group, frame]) {
                seen[group, frame] = 1
                frame_count[group]++
            }
            sum[group, bin] += val
            if (!(bin in bin_seen)) {
                bin_seen[bin] = 1
                bins[++bin_count] = bin
            }
        }
        END {
            for (gidx = 1; gidx <= group_count; gidx++) {
                group = group_order[gidx]
                best1_bin = -1
                best2_bin = -1
                best1_val = -1
                best2_val = -1
                for (bidx = 1; bidx <= bin_count; bidx++) {
                    bin = bins[bidx]
                    avg = sum[group, bin] / frame_count[group]
                    if (avg > best1_val || (avg == best1_val && (best1_bin < 0 || bin < best1_bin))) {
                        best2_val = best1_val
                        best2_bin = best1_bin
                        best1_val = avg
                        best1_bin = bin
                    } else if (avg > best2_val || (avg == best2_val && (best2_bin < 0 || bin < best2_bin))) {
                        best2_val = avg
                        best2_bin = bin
                    }
                }
                print group * 4, best1_bin, best2_bin
            }
        }
    ' "$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"
}

if [[ "${PEAKS_ONLY:-0}" == "1" ]]; then
    generate_peaks
    exit 0
fi

ensure_python_deps
python3 "$APP_DIR/audioproc.py"
generate_peaks

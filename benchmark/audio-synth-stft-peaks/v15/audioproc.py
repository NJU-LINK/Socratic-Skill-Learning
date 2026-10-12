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

    # A smooth repeating envelope keeps the pair of tones deterministic.
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

import csv
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import stft


def find_app_dir() -> Path:
    candidates = [Path("/app"), Path(__file__).resolve().parents[1]]
    for candidate in candidates:
        if (candidate / "run_audio_pipeline.sh").exists() and (candidate / "data").exists():
            return candidate
    return Path(__file__).resolve().parents[1]


APP_DIR = find_app_dir()
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"


def run_solution(*, peaks_only: bool = False) -> None:
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    subprocess.run([str(SOLUTION)], cwd=APP_DIR, env=env, check=True)


def read_csv_rows(path: Path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def mag_csv_to_array(path: Path, shape: tuple[int, int]) -> np.ndarray:
    rows = read_csv_rows(path)
    assert rows[0].keys() == {"frame", "bin", "val"}
    assert len(rows) == shape[0] * shape[1]

    actual = np.empty(shape, dtype=np.float64)
    row_index = 0
    for frame_idx in range(shape[1]):
        for bin_idx in range(shape[0]):
            row = rows[row_index]
            assert int(row["frame"]) == frame_idx
            assert int(row["bin"]) == bin_idx
            actual[bin_idx, frame_idx] = float(row["val"])
            row_index += 1
    return actual


def compute_expected_peaks(magnitude: np.ndarray):
    expected = []
    for group_start in range(0, magnitude.shape[1], 4):
        group_mag = magnitude[:, group_start : group_start + 4]
        frame_count = group_mag.shape[1]
        averaged = group_mag.sum(axis=1) / frame_count
        ranked = sorted(
            ((averaged[bin_idx], bin_idx) for bin_idx in range(magnitude.shape[0])),
            key=lambda item: (-item[0], item[1]),
        )
        expected.append(
            {
                "group_start_frame": str(group_start),
                "p1_bin": str(ranked[0][1]),
                "p2_bin": str(ranked[1][1]),
            }
        )
    return expected


def expected_signal() -> np.ndarray:
    sample_rate = 8000
    t = np.arange(sample_rate * 6, dtype=np.float64) / sample_rate
    envelope = 0.55 + 0.225 * (1.0 - np.cos(2.0 * np.pi * t))
    signal = envelope * (
        np.sin(2.0 * np.pi * 400.0 * t)
        + 0.85 * np.sin(2.0 * np.pi * 800.0 * t)
    )
    active = (np.floor(t).astype(int) % 2 == 0).astype(np.float64)
    signal += 0.20 * active * np.sin(2.0 * np.pi * 1200.0 * t)
    signal *= 0.22 / np.sqrt(np.mean(signal**2))
    return signal


@pytest.fixture(autouse=True)
def clean_outputs():
    for path in [DATA_DIR / "clip.wav", DATA_DIR / "mag.csv", DATA_DIR / "peaks.csv"]:
        if path.exists():
            path.unlink()
    yield


def test_full_pipeline_creates_required_artifacts_and_keeps_peaks_out_of_python():
    run_solution()

    assert SOLUTION.exists()
    assert (APP_DIR / "audioproc.py").exists()
    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert (DATA_DIR / "peaks.csv").exists()
    assert "peaks.csv" not in (APP_DIR / "audioproc.py").read_text(encoding="utf-8")


def test_wav_matches_public_synthesis_contract():
    run_solution()

    sr, samples = wavfile.read(DATA_DIR / "clip.wav")
    assert sr == 8000
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    assert len(samples) == 48000

    signal = samples.astype(np.float64) / 32767.0
    rms = np.sqrt(np.mean(signal**2))
    assert rms == pytest.approx(0.22, abs=5e-4)

    np.testing.assert_allclose(signal, expected_signal(), rtol=0.0, atol=2.0 / 32767.0)


def test_mag_csv_matches_independent_stft_of_generated_wav():
    run_solution()

    sr, samples = wavfile.read(DATA_DIR / "clip.wav")
    signal = samples.astype(np.float64) / 32767.0
    _, _, zxx = stft(
        signal,
        fs=8000,
        window="hann",
        nperseg=256,
        noverlap=128,
        nfft=512,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    expected_mag = np.abs(zxx)

    actual_mag = mag_csv_to_array(DATA_DIR / "mag.csv", expected_mag.shape)
    np.testing.assert_allclose(actual_mag, expected_mag, rtol=1e-12, atol=1e-12)


def test_grouped_peaks_match_independent_top_two_calculation():
    run_solution()

    sr, samples = wavfile.read(DATA_DIR / "clip.wav")
    signal = samples.astype(np.float64) / 32767.0
    _, _, zxx = stft(
        signal,
        fs=sr,
        window="hann",
        nperseg=256,
        noverlap=128,
        nfft=512,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    expected_mag = np.abs(zxx)
    expected_peaks = compute_expected_peaks(expected_mag)
    peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")
    assert peaks_rows == expected_peaks


def test_peaks_only_uses_existing_mag_csv():
    DATA_DIR.mkdir(exist_ok=True)
    mag_path = DATA_DIR / "mag.csv"
    mag_path.write_text(
        "frame,bin,val\n"
        "0,0,1\n"
        "0,1,9\n"
        "0,2,2\n"
        "1,0,8\n"
        "1,1,1\n"
        "1,2,3\n"
        "2,0,7\n"
        "2,1,2\n"
        "2,2,4\n"
        "3,0,6\n"
        "3,1,3\n"
        "3,2,5\n"
        "4,0,1\n"
        "4,1,2\n"
        "4,2,10\n"
        "5,0,2\n"
        "5,1,3\n"
        "5,2,9\n"
        "6,0,3\n"
        "6,1,8\n"
        "6,2,1\n"
        "7,0,4\n"
        "7,1,7\n"
        "7,2,2\n",
        encoding="utf-8",
    )

    run_solution(peaks_only=True)

    assert not (DATA_DIR / "clip.wav").exists()
    peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")
    assert peaks_rows == [
        {"group_start_frame": "0", "p1_bin": "0", "p2_bin": "1"},
        {"group_start_frame": "4", "p1_bin": "2", "p2_bin": "1"},
    ]


def test_solution_invokes_plain_awk():
    text = SOLUTION.read_text(encoding="utf-8")
    assert "awk -F," in text
    assert "/usr/bin/awk" not in text
    assert "gawk" not in text

from __future__ import annotations

import csv
import math
import os
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"


def run_solution(peaks_only: bool = False) -> None:
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    else:
        env.pop("PEAKS_ONLY", None)
    subprocess.run([str(SOLUTION)], cwd=APP_DIR, env=env, check=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_wav() -> np.ndarray:
    with wave.open(str(DATA_DIR / "clip.wav"), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() == 64000
        return np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16).astype(np.float64) / 32767.0


def compute_ground_truth(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    _, times, zxx = stft(
        samples,
        fs=16000,
        window="hann",
        nperseg=512,
        noverlap=384,
        nfft=1024,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    return times, np.abs(zxx)


def load_mag_array(path: Path) -> np.ndarray:
    rows = read_csv(path)
    assert rows

    frames = sorted({int(row["frame"]) for row in rows})
    bins = sorted({int(row["bin"]) for row in rows})
    assert frames == list(range(len(frames)))
    assert bins == list(range(len(bins)))
    assert len(rows) == len(frames) * len(bins)

    mag = np.empty((len(bins), len(frames)), dtype=np.float64)
    seen: set[tuple[int, int]] = set()
    for row in rows:
        frame = int(row["frame"])
        bin_idx = int(row["bin"])
        key = (frame, bin_idx)
        assert key not in seen
        seen.add(key)
        mag[bin_idx, frame] = float(row["val"])

    return mag


def top_bins_from_mag(mag: np.ndarray) -> dict[int, list[int]]:
    return {
        frame: [int(bin_idx) for bin_idx in np.argsort(-mag[:, frame], kind="stable")[:3]]
        for frame in range(mag.shape[1])
    }


def expected_section(times: np.ndarray, frame: int) -> str:
    return "first" if float(times[frame]) < 2.0 else "second"


def nearest_bins(freqs: list[int], fs: int = 16000, nfft: int = 1024) -> set[int]:
    return {int(round(freq * nfft / fs)) for freq in freqs}


@pytest.fixture(scope="module")
def pipeline_state() -> dict[str, object]:
    run_solution()

    samples = load_wav()
    times, expected_mag = compute_ground_truth(samples)
    mag = load_mag_array(DATA_DIR / "mag.csv")
    peaks_rows = read_csv(DATA_DIR / "peaks.csv")
    return {
        "samples": samples,
        "times": times,
        "expected_mag": expected_mag,
        "mag": mag,
        "peaks_rows": peaks_rows,
    }


def test_pipeline_artifacts_exist(pipeline_state: dict[str, object]) -> None:
    assert pipeline_state
    assert (APP_DIR / "audioproc.py").exists()
    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert (DATA_DIR / "peaks.csv").exists()


def test_wav_contract(pipeline_state: dict[str, object]) -> None:
    samples = pipeline_state["samples"]
    assert isinstance(samples, np.ndarray)
    rms = math.sqrt(float(np.mean(samples**2)))
    assert abs(rms - 0.15) <= 0.002


def test_magnitude_matches_ground_truth(pipeline_state: dict[str, object]) -> None:
    mag = pipeline_state["mag"]
    expected_mag = pipeline_state["expected_mag"]
    assert isinstance(mag, np.ndarray)
    assert isinstance(expected_mag, np.ndarray)
    assert mag.shape == expected_mag.shape
    assert np.allclose(mag, expected_mag, rtol=1e-7, atol=1e-10)


def test_peaks_cover_frames_and_match_top_bins(pipeline_state: dict[str, object]) -> None:
    mag = pipeline_state["mag"]
    peaks_rows = pipeline_state["peaks_rows"]
    assert isinstance(mag, np.ndarray)
    assert isinstance(peaks_rows, list)
    assert peaks_rows
    observed_frames = list(range(mag.shape[1]))
    peak_frames = [int(row["frame"]) for row in peaks_rows]
    assert peak_frames == observed_frames

    expected_top = top_bins_from_mag(mag)
    for row in peaks_rows:
        frame = int(row["frame"])
        top3 = [int(row["f1_bin"]), int(row["f2_bin"]), int(row["f3_bin"])]
        assert top3 == expected_top[frame]


def test_piecewise_sections_and_peak_families(pipeline_state: dict[str, object]) -> None:
    times = pipeline_state["times"]
    expected_mag = pipeline_state["expected_mag"]
    peaks_rows = pipeline_state["peaks_rows"]
    assert isinstance(times, np.ndarray)
    assert isinstance(expected_mag, np.ndarray)
    assert isinstance(peaks_rows, list)
    expected_top = top_bins_from_mag(expected_mag)
    first_family = nearest_bins([180, 360, 540])
    second_family = nearest_bins([300, 450, 750, 900])

    frames = list(range(expected_mag.shape[1]))
    first_frames = [frame for frame in frames if 0.5 <= float(times[frame]) < 1.5]
    second_frames = [frame for frame in frames if 2.5 <= float(times[frame]) < 3.5]
    assert first_frames
    assert second_frames

    for row in peaks_rows:
        frame = int(row["frame"])
        assert row["section"] == expected_section(times, frame)

    for frame in first_frames:
        top3 = expected_top[frame]
        assert len(set(top3) & first_family) >= 2
        assert len(set(top3) & second_family) <= 1

    for frame in second_frames:
        top3 = expected_top[frame]
        assert len(set(top3) & second_family) >= 2
        assert len(set(top3) & first_family) <= 1


def test_peaks_only_reuses_existing_mag_csv() -> None:
    run_solution()
    original_mag = (DATA_DIR / "mag.csv").read_bytes()

    audio_proc = APP_DIR / "audioproc.py"
    clip = DATA_DIR / "clip.wav"
    if audio_proc.exists():
        audio_proc.unlink()
    if clip.exists():
        clip.unlink()
    (DATA_DIR / "peaks.csv").unlink()

    run_solution(peaks_only=True)

    assert not audio_proc.exists()
    assert not clip.exists()
    assert (DATA_DIR / "mag.csv").read_bytes() == original_mag

    mag = load_mag_array(DATA_DIR / "mag.csv")
    peaks_rows = read_csv(DATA_DIR / "peaks.csv")
    expected_top = top_bins_from_mag(mag)
    split_idx = mag.shape[1] // 2

    for row in peaks_rows:
        frame = int(row["frame"])
        assert [int(row["f1_bin"]), int(row["f2_bin"]), int(row["f3_bin"])] == expected_top[frame]
        assert row["section"] == ("first" if frame < split_idx else "second")

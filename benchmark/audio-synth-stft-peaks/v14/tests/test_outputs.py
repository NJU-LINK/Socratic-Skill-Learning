import csv
import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import stft


APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"
FS = 16000
DURATION = 3.0
FREQUENCIES = [220.0, 415.0, 523.25, 659.25, 880.0]
RMS_TARGET = 0.2


def run_solution(*, peaks_only=False):
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    subprocess.run([str(SOLUTION)], cwd=APP_DIR, check=True, env=env)


def synthesize_reference_signal():
    n_samples = int(FS * DURATION)
    t = np.arange(n_samples, dtype=np.float64) / FS
    signal = np.zeros(n_samples, dtype=np.float64)
    for freq in FREQUENCIES:
        signal += np.sin(2.0 * np.pi * freq * t)

    rng = np.random.default_rng(20240617)
    signal += rng.uniform(-1e-4, 1e-4, size=n_samples)
    signal *= RMS_TARGET / np.sqrt(np.mean(signal ** 2))
    return signal


def load_mag_rows():
    with (DATA_DIR / "mag.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def load_peaks_rows():
    with (DATA_DIR / "peaks.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def top3_from_frame(frame_rows):
    sorted_rows = sorted(frame_rows, key=lambda row: float(row["val"]), reverse=True)
    return sorted_rows[:3]


def test_python_stage_stops_at_mag_csv_and_solution_uses_awk_for_peaks():
    run_solution()

    audioproc_path = APP_DIR / "audioproc.py"
    solution_text = SOLUTION.read_text(encoding="utf-8")
    audioproc_text = audioproc_path.read_text(encoding="utf-8")
    peaks_path = DATA_DIR / "peaks.csv"

    assert "awk -F," in solution_text
    assert '"$DATA_DIR/mag.csv" > "$DATA_DIR/peaks.csv"' in solution_text
    assert "PEAKS_ONLY" in solution_text
    assert "peaks.csv" not in audioproc_text

    peaks_path.unlink()
    subprocess.run(["python3", str(audioproc_path)], cwd=APP_DIR, check=True, env=os.environ.copy())

    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert not peaks_path.exists()


def test_pipeline_outputs_expected_files_and_audio_properties():
    run_solution()

    assert (APP_DIR / "audioproc.py").exists()
    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert (DATA_DIR / "peaks.csv").exists()

    with wave.open(str(DATA_DIR / "clip.wav"), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == FS
        assert wav_file.getnframes() == int(FS * DURATION)
        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)

    audio_f = audio.astype(np.float64) / 32767.0
    rms = math.sqrt(float(np.mean(audio_f ** 2)))
    assert abs(rms - RMS_TARGET) <= 0.0025


def test_mag_csv_matches_center_padded_scipy_stft_and_schema():
    run_solution()
    rows = load_mag_rows()
    assert rows
    assert list(rows[0].keys()) == ["frame", "bin", "freq_hz", "val"]

    signal = synthesize_reference_signal()
    freqs, _, zxx = stft(
        signal,
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    magnitude = np.abs(zxx)

    expected_row_count = magnitude.shape[0] * magnitude.shape[1]
    assert len(rows) == expected_row_count
    assert magnitude.shape[1] > 90

    frame_count = max(int(row["frame"]) for row in rows) + 1
    bin_count = max(int(row["bin"]) for row in rows) + 1
    assert frame_count == magnitude.shape[1]
    assert bin_count == magnitude.shape[0] == 513

    for row in rows[:30] + rows[-30:]:
        frame = int(row["frame"])
        bin_idx = int(row["bin"])
        assert math.isclose(float(row["freq_hz"]), float(freqs[bin_idx]), rel_tol=0.0, abs_tol=1e-9)
        assert math.isclose(float(row["val"]), float(magnitude[bin_idx, frame]), rel_tol=0.0, abs_tol=1e-9)


def test_peaks_csv_contains_true_top_three_bins_and_matching_hz():
    run_solution()
    mag_rows = load_mag_rows()
    peaks_rows = load_peaks_rows()
    assert peaks_rows
    assert list(peaks_rows[0].keys()) == [
        "frame",
        "f1_bin",
        "f2_bin",
        "f3_bin",
        "f1_hz",
        "f2_hz",
        "f3_hz",
    ]

    grouped = {}
    for row in mag_rows:
        grouped.setdefault(int(row["frame"]), []).append(row)

    assert len(peaks_rows) == len(grouped)

    for peak_row in peaks_rows:
        frame = int(peak_row["frame"])
        winners = top3_from_frame(grouped[frame])
        expected_bins = [int(winner["bin"]) for winner in winners]
        expected_hz = [float(winner["freq_hz"]) for winner in winners]

        actual_bins = [int(peak_row[f"f{i}_bin"]) for i in range(1, 4)]
        actual_hz = [float(peak_row[f"f{i}_hz"]) for i in range(1, 4)]

        assert actual_bins == expected_bins
        for got, want in zip(actual_hz, expected_hz):
            assert math.isclose(got, want, rel_tol=0.0, abs_tol=1e-9)


def test_peaks_only_regenerates_peaks_without_touching_other_outputs(tmp_path):
    run_solution()

    mag_path = DATA_DIR / "mag.csv"
    clip_path = DATA_DIR / "clip.wav"
    peaks_path = DATA_DIR / "peaks.csv"

    mag_before = mag_path.read_bytes()
    clip_before = clip_path.read_bytes()
    original_peaks = peaks_path.read_text(encoding="utf-8")

    backup = tmp_path / "mag_backup.csv"
    shutil.copyfile(mag_path, backup)
    peaks_path.unlink()

    run_solution(peaks_only=True)

    assert peaks_path.exists()
    assert mag_path.read_bytes() == mag_before
    assert clip_path.read_bytes() == clip_before
    assert peaks_path.read_text(encoding="utf-8") == original_peaks

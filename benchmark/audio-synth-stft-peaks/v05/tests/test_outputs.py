from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
import time
import wave
from pathlib import Path

import numpy as np


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION_PATH = APP_DIR / "run_audio_pipeline.sh"
WAV_PATH = DATA_DIR / "clip.wav"
MAG_PATH = DATA_DIR / "mag.csv"
PEAKS_PATH = DATA_DIR / "peaks.csv"
AUDIOPROC_PATH = APP_DIR / "audioproc.py"
FS = 16000
DURATION_SEC = 3.0
TONES_HZ = np.array([220.0, 330.0, 440.0, 448.0, 550.0, 660.0], dtype=np.float64)
RMS_TARGET = 0.2


def cleanup_outputs() -> None:
    if AUDIOPROC_PATH.exists():
        AUDIOPROC_PATH.unlink()
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)


def run_solution(*, peaks_only: bool = False) -> None:
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    subprocess.run(
        ["/bin/bash", str(SOLUTION_PATH)],
        cwd=APP_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def read_pcm() -> tuple[int, int, int, bytes]:
    with wave.open(str(WAV_PATH), "rb") as wav_file:
        return (
            wav_file.getnchannels(),
            wav_file.getsampwidth(),
            wav_file.getframerate(),
            wav_file.readframes(wav_file.getnframes()),
        )


def test_solution_builds_required_artifacts_and_keeps_peaks_out_of_python() -> None:
    cleanup_outputs()
    run_solution()

    assert SOLUTION_PATH.exists()
    assert AUDIOPROC_PATH.exists()
    assert WAV_PATH.exists()
    assert MAG_PATH.exists()
    assert PEAKS_PATH.exists()

    solution_text = SOLUTION_PATH.read_text()
    audioproc_text = AUDIOPROC_PATH.read_text()
    assert "awk" in solution_text
    assert "peaks.csv" not in audioproc_text


def test_wav_has_required_pcm_shape_rms_and_tones() -> None:
    cleanup_outputs()
    run_solution()

    channels, sample_width, sample_rate, raw_frames = read_pcm()
    assert channels == 1
    assert sample_width == 2
    assert sample_rate == FS
    assert len(raw_frames) == 3 * sample_rate * sample_width

    samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(samples**2)))
    assert 0.198 <= rms <= 0.202

    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)
    strongest_bins = np.argsort(spectrum)[-32:]
    strongest_freqs = freqs[strongest_bins]
    for tone in TONES_HZ:
        assert any(abs(freq - tone) <= 1.0 for freq in strongest_freqs), tone


def test_seeded_synthesis_is_deterministic_across_full_runs() -> None:
    cleanup_outputs()
    run_solution()

    wav_hash = hashlib.sha256(WAV_PATH.read_bytes()).hexdigest()
    cleanup_outputs()
    run_solution()
    assert hashlib.sha256(WAV_PATH.read_bytes()).hexdigest() == wav_hash


def test_mag_csv_matches_blackman_stft_of_generated_clip() -> None:
    cleanup_outputs()
    run_solution()

    from scipy.signal import stft

    _, _, sample_rate, raw_frames = read_pcm()
    samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float64) / 32768.0

    with MAG_PATH.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        assert reader.fieldnames == ["frame", "bin", "val"]
        rows = list(reader)

    _, _, zxx = stft(
        samples,
        fs=sample_rate,
        window="blackman",
        nperseg=1024,
        noverlap=896,
        nfft=2048,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    reference = np.abs(zxx)
    expected_frames = reference.shape[1]
    expected_bins = reference.shape[0]

    assert len(rows) == expected_frames * expected_bins

    actual = {(int(row["frame"]), int(row["bin"])): float(row["val"]) for row in rows}
    assert len(actual) == len(rows)

    expected_keys = {
        (frame_idx, bin_idx)
        for frame_idx in range(expected_frames)
        for bin_idx in range(expected_bins)
    }
    assert set(actual) == expected_keys

    for frame_idx in range(expected_frames):
        for bin_idx in range(expected_bins):
            assert abs(actual[(frame_idx, bin_idx)] - float(reference[bin_idx, frame_idx])) < 2e-4


def test_peaks_csv_has_true_top_five_bins() -> None:
    cleanup_outputs()
    run_solution()

    with MAG_PATH.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        by_frame: dict[int, list[tuple[float, int]]] = {}
        for row in reader:
            frame = int(row["frame"])
            by_frame.setdefault(frame, []).append((float(row["val"]), int(row["bin"])))

    expected_rows = []
    for frame in sorted(by_frame):
        ordered = sorted(by_frame[frame], key=lambda item: (-item[0], item[1]))[:5]
        expected_rows.append([str(frame)] + [str(bin_idx) for _, bin_idx in ordered])

    with PEAKS_PATH.open(newline="") as csv_file:
        reader = csv.reader(csv_file)
        rows = list(reader)

    assert rows[0] == ["frame", "f1_bin", "f2_bin", "f3_bin", "f4_bin", "f5_bin"]
    assert rows[1:] == expected_rows


def test_peaks_only_reuses_mag_without_touching_wav_or_stft() -> None:
    cleanup_outputs()
    run_solution()

    original_wav_hash = hashlib.sha256(WAV_PATH.read_bytes()).hexdigest()
    original_mag_hash = hashlib.sha256(MAG_PATH.read_bytes()).hexdigest()
    original_wav_mtime = WAV_PATH.stat().st_mtime_ns
    original_mag_mtime = MAG_PATH.stat().st_mtime_ns
    original_peaks_hash = hashlib.sha256(PEAKS_PATH.read_bytes()).hexdigest()

    PEAKS_PATH.unlink()
    time.sleep(1.1)
    run_solution(peaks_only=True)

    assert hashlib.sha256(WAV_PATH.read_bytes()).hexdigest() == original_wav_hash
    assert hashlib.sha256(MAG_PATH.read_bytes()).hexdigest() == original_mag_hash
    assert WAV_PATH.stat().st_mtime_ns == original_wav_mtime
    assert MAG_PATH.stat().st_mtime_ns == original_mag_mtime
    assert hashlib.sha256(PEAKS_PATH.read_bytes()).hexdigest() == original_peaks_hash

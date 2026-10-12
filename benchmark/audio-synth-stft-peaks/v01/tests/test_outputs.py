import csv
import math
import os
import stat
import subprocess
import textwrap
import wave
from pathlib import Path

import numpy as np
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"
MAG_PATH = DATA_DIR / "mag.csv"
PEAKS_PATH = DATA_DIR / "peaks.csv"
WAV_PATH = DATA_DIR / "clip.wav"

FS = 12000
DURATION_SEC = 2.5
SAMPLE_COUNT = int(FS * DURATION_SEC)
EXPECTED_FRAMES = 153
EXPECTED_BINS = 513
REQUIRED_FREQS = np.array([180.0, 360.0, 540.0, 720.0])


def run_solution(env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run([str(SOLUTION)], check=True, env=merged_env, cwd=APP_DIR)


def read_wav_signal(path: Path):
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == FS
        assert wav_file.getsampwidth() == 2
        frames = wav_file.readframes(wav_file.getnframes())
        signal = np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32767.0
        return wav_file.getnframes(), signal


def read_mag_rows(path: Path):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def read_peaks(path: Path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def expected_top_bins(magnitude: np.ndarray):
    result = []
    for frame in range(magnitude.shape[1]):
        order = sorted(range(magnitude.shape[0]), key=lambda idx: (-magnitude[idx, frame], idx))[:3]
        result.append(order)
    return result


def fit_required_tones(signal: np.ndarray):
    t = np.arange(signal.size, dtype=np.float64) / FS
    columns = []
    for freq in REQUIRED_FREQS:
        phase = 2.0 * np.pi * freq * t
        columns.append(np.sin(phase))
        columns.append(np.cos(phase))
    design = np.column_stack(columns)
    coeffs, _, _, _ = np.linalg.lstsq(design, signal, rcond=None)
    fitted = design @ coeffs
    amplitudes = np.hypot(coeffs[0::2], coeffs[1::2])
    residual = signal - fitted
    return amplitudes, residual


def dominant_fft_frequencies(signal: np.ndarray, top_k: int):
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / FS)
    spectrum[0] = 0.0
    top_indices = np.argsort(spectrum)[-top_k:]
    return sorted(freqs[top_indices])


def test_full_pipeline_outputs_expected_files_and_shapes():
    run_solution()

    assert WAV_PATH.exists()
    assert MAG_PATH.exists()
    assert PEAKS_PATH.exists()
    assert (APP_DIR / "audioproc.py").exists()

    frame_count, signal = read_wav_signal(WAV_PATH)
    assert frame_count == SAMPLE_COUNT

    rms = math.sqrt(float(np.mean(signal ** 2)))
    assert abs(rms - 0.15) <= 0.002

    mag_rows = read_mag_rows(MAG_PATH)
    assert len(mag_rows) == EXPECTED_FRAMES * EXPECTED_BINS
    assert list(mag_rows[0].keys()) == ["frame", "bin", "val"]
    assert mag_rows[0]["frame"] == "0"
    assert mag_rows[0]["bin"] == "0"
    assert mag_rows[-1]["frame"] == str(EXPECTED_FRAMES - 1)
    assert mag_rows[-1]["bin"] == str(EXPECTED_BINS - 1)

    peaks_rows = read_peaks(PEAKS_PATH)
    assert len(peaks_rows) == EXPECTED_FRAMES
    assert list(peaks_rows[0].keys()) == ["frame", "f1_bin", "f2_bin", "f3_bin"]
    for idx, row in enumerate(peaks_rows):
        assert int(row["frame"]) == idx


def test_synthesized_wav_matches_required_tones_noise_and_rms():
    run_solution()

    frame_count, signal = read_wav_signal(WAV_PATH)
    assert frame_count == SAMPLE_COUNT

    rms = math.sqrt(float(np.mean(signal ** 2)))
    assert abs(rms - 0.15) <= 0.002

    dominant_freqs = dominant_fft_frequencies(signal, top_k=4)
    assert dominant_freqs == sorted(REQUIRED_FREQS.tolist())

    amplitudes, residual = fit_required_tones(signal)
    assert np.all(amplitudes > 0.08)
    assert float(np.max(amplitudes) / np.min(amplitudes)) < 1.15

    residual_std = float(np.std(residual))
    assert 0.004 <= residual_std <= 0.02

    centered = residual - np.mean(residual)
    skew = float(np.mean(centered**3) / (np.std(centered) ** 3))
    excess_kurtosis = float(np.mean(centered**4) / (np.std(centered) ** 4) - 3.0)
    assert abs(skew) < 0.2
    assert abs(excess_kurtosis) < 0.8


def test_mag_csv_and_peak_bins_match_scipy_blackman_stft():
    run_solution()

    _, signal = read_wav_signal(WAV_PATH)
    _, _, zxx = stft(
        signal,
        fs=FS,
        window="blackman",
        nperseg=768,
        noverlap=576,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    magnitude = np.abs(zxx)
    assert magnitude.shape == (EXPECTED_BINS, EXPECTED_FRAMES)

    mag_rows = read_mag_rows(MAG_PATH)
    for sample_idx in [0, 1, EXPECTED_BINS - 1, EXPECTED_BINS, EXPECTED_BINS + 7, len(mag_rows) - 1]:
        row = mag_rows[sample_idx]
        frame = int(row["frame"])
        bin_idx = int(row["bin"])
        val = float(row["val"])
        assert math.isclose(val, float(magnitude[bin_idx, frame]), rel_tol=1e-6, abs_tol=1e-9)

    expected_peaks = expected_top_bins(magnitude)
    peaks_rows = read_peaks(PEAKS_PATH)
    for frame, row in enumerate(peaks_rows):
        actual = [int(row["f1_bin"]), int(row["f2_bin"]), int(row["f3_bin"])]
        assert actual == expected_peaks[frame]


def test_peaks_only_mode_uses_existing_mag_csv_and_rewrites_peaks():
    run_solution()

    original_mag = MAG_PATH.read_text()
    rows = read_mag_rows(MAG_PATH)
    modified_rows = [rows[0], rows[1], rows[2], rows[3]]
    modified_rows[0]["val"] = "1.0"
    modified_rows[1]["bin"] = "20"
    modified_rows[1]["val"] = "9.0"
    modified_rows[2]["bin"] = "10"
    modified_rows[2]["val"] = "7.0"
    modified_rows[3]["bin"] = "30"
    modified_rows[3]["val"] = "5.0"

    with MAG_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame", "bin", "val"])
        writer.writeheader()
        writer.writerows(modified_rows)
        for row in rows[4:]:
            writer.writerow(row)

    before_wav = WAV_PATH.read_bytes()
    run_solution(env={"PEAKS_ONLY": "1"})

    assert MAG_PATH.read_text() != original_mag
    assert WAV_PATH.read_bytes() == before_wav

    peaks_rows = read_peaks(PEAKS_PATH)
    assert peaks_rows[0] == {"frame": "0", "f1_bin": "20", "f2_bin": "10", "f3_bin": "30"}


def test_peaks_only_mode_invokes_awk_from_shell_path(tmp_path):
    run_solution()

    rows = read_mag_rows(MAG_PATH)
    with MAG_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["frame", "bin", "val"])
        writer.writeheader()
        writer.writerow({"frame": "0", "bin": "11", "val": "100"})
        writer.writerow({"frame": "0", "bin": "7", "val": "90"})
        writer.writerow({"frame": "0", "bin": "4", "val": "80"})
        writer.writerow({"frame": "0", "bin": "1", "val": "70"})
        for row in rows[4:]:
            writer.writerow(row)

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    awk_log = tmp_path / "awk.log"
    awk_stub = stub_dir / "awk"
    awk_stub.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -euo pipefail
            printf 'called\n' >> {awk_log!s}
            /usr/bin/awk "$@"
            """
        )
    )
    awk_stub.chmod(awk_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = {"PEAKS_ONLY": "1", "PATH": f"{stub_dir}:{os.environ['PATH']}"}
    run_solution(env=env)

    assert awk_log.read_text() == "called\n"
    peaks_rows = read_peaks(PEAKS_PATH)
    assert peaks_rows[0] == {"frame": "0", "f1_bin": "11", "f2_bin": "7", "f3_bin": "4"}



def test_full_pipeline_final_peaks_file_comes_from_awk_on_path(tmp_path):
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    awk_log = tmp_path / "awk.log"
    awk_stub = stub_dir / "awk"
    awk_stub.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -euo pipefail
            printf 'full-pipeline\n' >> {awk_log!s}
            printf 'frame,f1_bin,f2_bin,f3_bin\n'
            printf '0,501,401,301\n'
            printf '1,502,402,302\n'
            """
        )
    )
    awk_stub.chmod(awk_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    run_solution(env={"PATH": f"{stub_dir}:{os.environ['PATH']}"})

    assert awk_log.read_text() == "full-pipeline\n"
    assert PEAKS_PATH.read_text() == "frame,f1_bin,f2_bin,f3_bin\n0,501,401,301\n1,502,402,302\n"
    assert MAG_PATH.exists()
    assert WAV_PATH.exists()

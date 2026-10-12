import csv
import math
import os
import shutil
import stat
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy import signal


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION_SCRIPT = APP_DIR / "run_audio_pipeline.sh"
AUDIOPROC_SCRIPT = APP_DIR / "audioproc.py"
EXPECTED_FREQS = np.array([250.0, 375.0, 500.0, 625.0, 875.0], dtype=np.float64)
EXPECTED_RATE = 16000
EXPECTED_SECONDS = 3.0
EXPECTED_RMS = 0.18
FLOOR = 1e-12
STFT_KWARGS = {
    "window": "hann",
    "nperseg": 1024,
    "noverlap": 512,
    "nfft": 2048,
    "boundary": "zeros",
    "padded": True,
}


def run_solution(env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run([str(SOLUTION_SCRIPT)], check=True, env=merged_env)


def load_pcm_from_wav(path: Path):
    with wave.open(str(path), "rb") as wav_file:
        params = {
            "channels": wav_file.getnchannels(),
            "width": wav_file.getsampwidth(),
            "rate": wav_file.getframerate(),
            "frames": wav_file.getnframes(),
        }
        pcm = np.frombuffer(wav_file.readframes(params["frames"]), dtype=np.int16)
    return params, pcm.astype(np.float64) / 32767.0


def read_csv_rows(path: Path):
    with path.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def expected_top3(samples: np.ndarray):
    freqs, _, stft_matrix = signal.stft(samples, fs=EXPECTED_RATE, **STFT_KWARGS)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(stft_matrix), FLOOR))
    expected = []
    for frame_index in range(mag_db.shape[1]):
        ranking = sorted(
            range(mag_db.shape[0]),
            key=lambda idx: (-mag_db[idx, frame_index], freqs[idx]),
        )[:3]
        expected.append((frame_index, [float(freqs[idx]) for idx in ranking]))
    return freqs, mag_db, expected


def test_pipeline_outputs_and_scripts_exist():
    run_solution()
    for path in [SOLUTION_SCRIPT, AUDIOPROC_SCRIPT, DATA_DIR / "clip.wav", DATA_DIR / "mag.csv", DATA_DIR / "peaks.csv"]:
        assert path.exists(), f"missing {path}"

    for path in [SOLUTION_SCRIPT, AUDIOPROC_SCRIPT]:
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{path} is not executable"


def test_clip_wav_matches_audio_contract():
    run_solution()
    params, samples = load_pcm_from_wav(DATA_DIR / "clip.wav")

    assert params == {
        "channels": 1,
        "width": 2,
        "rate": EXPECTED_RATE,
        "frames": int(EXPECTED_RATE * EXPECTED_SECONDS),
    }

    rms = math.sqrt(float(np.mean(np.square(samples))))
    assert abs(rms - EXPECTED_RMS) < 5e-5

    freqs, spectrum = signal.periodogram(samples, fs=EXPECTED_RATE, scaling="spectrum")
    prominent = freqs[np.argsort(spectrum)[-10:]]
    for expected_freq in EXPECTED_FREQS:
        assert np.min(np.abs(prominent - expected_freq)) <= 1.0


def test_mag_csv_matches_independent_stft_calculation():
    run_solution()
    params, samples = load_pcm_from_wav(DATA_DIR / "clip.wav")
    rows = read_csv_rows(DATA_DIR / "mag.csv")
    freqs, mag_db, _ = expected_top3(samples)

    assert list(rows[0].keys()) == ["frame", "bin", "freq_hz", "mag_db"]
    assert len(rows) == mag_db.shape[0] * mag_db.shape[1]

    frame_count = mag_db.shape[1]
    bin_count = mag_db.shape[0]

    sample_indices = [0, 1, bin_count - 1, bin_count, len(rows) // 2, len(rows) - 1]
    for idx in sample_indices:
        row = rows[idx]
        frame_index = int(row["frame"])
        bin_index = int(row["bin"])
        assert 0 <= frame_index < frame_count
        assert 0 <= bin_index < bin_count
        assert abs(float(row["freq_hz"]) - float(freqs[bin_index])) < 1e-9
        assert abs(float(row["mag_db"]) - float(mag_db[bin_index, frame_index])) < 1e-6

    assert all(np.isfinite(float(row["mag_db"])) for row in rows)


def test_peaks_csv_contains_true_top_three_frequencies():
    run_solution()
    _, samples = load_pcm_from_wav(DATA_DIR / "clip.wav")
    rows = read_csv_rows(DATA_DIR / "peaks.csv")
    _, _, expected = expected_top3(samples)

    assert list(rows[0].keys()) == ["frame", "peak1_hz", "peak2_hz", "peak3_hz"]
    assert len(rows) == len(expected)

    for row, (frame_index, peaks) in zip(rows, expected):
        assert int(row["frame"]) == frame_index
        actual = [float(row[f"peak{i}_hz"]) for i in range(1, 4)]
        for got, want in zip(actual, peaks):
            assert abs(got - want) < 1e-6


def test_audioproc_only_writes_clip_and_mag():
    run_solution()
    peaks_path = DATA_DIR / "peaks.csv"
    peaks_path.unlink()

    subprocess.run(["python3", str(AUDIOPROC_SCRIPT)], check=True)

    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert not peaks_path.exists()


def test_peaks_only_uses_existing_mag_csv_and_path_awk(tmp_path: Path):
    run_solution()
    mag_path = DATA_DIR / "mag.csv"
    peaks_path = DATA_DIR / "peaks.csv"
    original_mag = mag_path.read_bytes()
    original_peaks = peaks_path.read_text()
    clip_before = (DATA_DIR / "clip.wav").read_bytes()

    sentinel_rows = [
        ["frame", "bin", "freq_hz", "mag_db"],
        ["0", "0", "111.0", "1.0"],
        ["0", "1", "222.0", "3.0"],
        ["0", "2", "333.0", "2.0"],
        ["0", "3", "444.0", "0.0"],
    ]
    with mag_path.open("w", newline="") as csv_file:
        csv.writer(csv_file).writerows(sentinel_rows)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_awk_log = tmp_path / "awk.log"
    fake_awk = fake_bin / "awk"
    real_awk = shutil.which("awk", path=os.environ["PATH"])
    assert real_awk is not None
    fake_awk.write_text(
        "#!/bin/bash\n"
        f"printf 'fake awk invoked\\n' >> {str(fake_awk_log)!r}\n"
        f"exec {real_awk!r} \"$@\"\n"
    )
    fake_awk.chmod(0o755)

    env = {
        "PEAKS_ONLY": "1",
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    run_solution(env=env)

    assert fake_awk_log.exists(), "solution did not resolve awk from PATH"
    assert (DATA_DIR / "clip.wav").read_bytes() == clip_before
    assert mag_path.read_bytes() != original_mag
    assert read_csv_rows(peaks_path) == [
        {"frame": "0", "peak1_hz": "222.0000000000", "peak2_hz": "333.0000000000", "peak3_hz": "111.0000000000"}
    ]
    assert peaks_path.read_text() != original_peaks

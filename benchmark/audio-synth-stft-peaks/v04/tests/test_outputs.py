import csv
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
CLIP_PATH = DATA_DIR / "clip.wav"
MAG_PATH = DATA_DIR / "mag.csv"
PEAKS_PATH = DATA_DIR / "peaks.csv"
AUDIOPROC_PATH = APP_DIR / "audioproc.py"


def run_solution(*, peaks_only: bool = False) -> None:
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    else:
        env.pop("PEAKS_ONLY", None)
    subprocess.run(["/bin/bash", "/app/run_audio_pipeline.sh"], check=True, cwd=APP_DIR, env=env)


def run_solution_with_fake_awk(*, peaks_only: bool = False) -> tuple[str, list[tuple[int, int, int]]]:
    env = os.environ.copy()
    if peaks_only:
        env["PEAKS_ONLY"] = "1"
    else:
        env.pop("PEAKS_ONLY", None)

    sentinel_rows = [
        (91, 7, 3),
        (92, 5, 1),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        log_path = tmp_path / "awk.log"
        wrapper_path = tmp_path / "awk"
        wrapper_path.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            f"printf 'awk %s\\n' \"$*\" >> {str(log_path)!r}\n"
            "printf 'frame_pair,f1_bin,f2_bin\\n'\n"
            "printf '91,7,3\\n'\n"
            "printf '92,5,1\\n'\n"
        )
        wrapper_path.chmod(0o755)
        env["PATH"] = f"{tmpdir}:{env['PATH']}"

        subprocess.run(["/bin/bash", "/app/run_audio_pipeline.sh"], check=True, cwd=APP_DIR, env=env)

        return log_path.read_text(), sentinel_rows


def read_mag_matrix(path: Path) -> np.ndarray:
    rows = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append((int(row["frame"]), int(row["bin"]), float(row["val"])))

    frame_count = max(frame for frame, _, _ in rows) + 1
    bin_count = max(bin_idx for _, bin_idx, _ in rows) + 1
    matrix = np.zeros((frame_count, bin_count), dtype=np.float64)
    for frame, bin_idx, val in rows:
        matrix[frame, bin_idx] = val
    return matrix


def read_peaks_rows(path: Path) -> list[tuple[int, int, int]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            (int(row["frame_pair"]), int(row["f1_bin"]), int(row["f2_bin"]))
            for row in reader
        ]


def expected_pair_peaks(matrix: np.ndarray) -> list[tuple[int, int, int]]:
    rows = []
    for pair_idx in range(matrix.shape[0] // 2):
        avg = (matrix[2 * pair_idx] + matrix[2 * pair_idx + 1]) / 2.0
        top_bins = sorted(range(avg.shape[0]), key=lambda bin_idx: (-avg[bin_idx], bin_idx))[:2]
        rows.append((pair_idx, top_bins[0], top_bins[1]))
    return rows


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_pipeline_matches_reference_stft_and_pair_peaks() -> None:
    run_solution()

    assert AUDIOPROC_PATH.exists()
    assert CLIP_PATH.exists()
    assert MAG_PATH.exists()
    assert PEAKS_PATH.exists()

    sample_rate, pcm = wavfile.read(CLIP_PATH)
    assert sample_rate == 8000
    assert pcm.dtype == np.int16
    assert pcm.ndim == 1
    assert pcm.shape[0] == 40000

    audio = pcm.astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert abs(rms - 0.12) < 5e-4

    mag = read_mag_matrix(MAG_PATH)
    _, _, zxx = stft(
        audio,
        fs=8000,
        window="boxcar",
        nperseg=400,
        noverlap=200,
        nfft=512,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    reference_mag = np.abs(zxx).T

    assert mag.shape == reference_mag.shape
    assert np.allclose(mag, reference_mag, rtol=1e-12, atol=1e-12)

    expected = expected_pair_peaks(mag)
    actual = read_peaks_rows(PEAKS_PATH)
    assert actual == expected
    assert len(actual) == mag.shape[0] // 2


def test_audioproc_only_writes_clip_and_mag() -> None:
    run_solution()

    PEAKS_PATH.unlink()
    subprocess.run(["python3", str(AUDIOPROC_PATH)], check=True, cwd=APP_DIR)

    assert CLIP_PATH.exists()
    assert MAG_PATH.exists()
    assert not PEAKS_PATH.exists()


def test_peaks_only_reuses_mag_and_respects_tie_breaking() -> None:
    run_solution()

    original_clip_hash = file_hash(CLIP_PATH)
    original_mag_hash = file_hash(MAG_PATH)

    custom_rows = [
        (0, 0, 1.0),
        (0, 1, 5.0),
        (0, 2, 1.0),
        (0, 3, 5.0),
        (1, 0, 1.0),
        (1, 1, 3.0),
        (1, 2, 1.0),
        (1, 3, 3.0),
        (2, 0, 4.0),
        (2, 1, 4.0),
        (2, 2, 2.0),
        (2, 3, 0.0),
        (3, 0, 2.0),
        (3, 1, 2.0),
        (3, 2, 6.0),
        (3, 3, 0.0),
    ]

    with MAG_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "bin", "val"])
        writer.writerows(custom_rows)
    custom_mag_hash = file_hash(MAG_PATH)

    PEAKS_PATH.unlink(missing_ok=True)
    run_solution(peaks_only=True)

    assert file_hash(CLIP_PATH) == original_clip_hash
    assert custom_mag_hash != original_mag_hash
    assert file_hash(MAG_PATH) == custom_mag_hash

    assert read_peaks_rows(PEAKS_PATH) == [
        (0, 1, 3),
        (1, 2, 0),
    ]


def test_solution_uses_awk_output_for_final_peaks_csv_in_full_and_peaks_only_modes() -> None:
    full_log, sentinel_rows = run_solution_with_fake_awk()
    assert "awk " in full_log
    assert str(MAG_PATH) in full_log
    assert read_peaks_rows(PEAKS_PATH) == sentinel_rows

    run_solution()
    peaks_only_log, sentinel_rows = run_solution_with_fake_awk(peaks_only=True)
    assert "awk " in peaks_only_log
    assert str(MAG_PATH) in peaks_only_log
    assert read_peaks_rows(PEAKS_PATH) == sentinel_rows

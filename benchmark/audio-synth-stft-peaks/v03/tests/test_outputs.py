import csv
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"


def run_solution(env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run(["bash", str(APP_DIR / "run_audio_pipeline.sh")], check=True, env=merged_env)


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def install_awk_wrapper(tmp_path):
    real_awk = shutil.which("awk")
    assert real_awk is not None

    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    log_path = tmp_path / "awk.log"
    wrapper_path = wrapper_dir / "awk"
    wrapper_path.write_text(
        "#!/bin/sh\n"
        "printf 'awk %s\\n' \"$*\" >> \"$AWK_LOG\"\n"
        f"exec {real_awk} \"$@\"\n"
    )
    wrapper_path.chmod(0o755)
    return wrapper_dir, log_path


def compute_expected_peaks(rows):
    grouped = {}
    order = []
    for row in rows:
        frame = int(row["frame"])
        bin_idx = int(row["bin"])
        value = float(row["val"])
        if frame not in grouped:
            grouped[frame] = {
                "low": (-1.0, 0),
                "mid": (-1.0, 128),
                "high": (-1.0, 512),
            }
            order.append(frame)

        if 0 <= bin_idx <= 127:
            bucket = "low"
        elif 128 <= bin_idx <= 511:
            bucket = "mid"
        elif 512 <= bin_idx <= 1024:
            bucket = "high"
        else:
            continue

        best_val, best_bin = grouped[frame][bucket]
        if value > best_val or (value == best_val and bin_idx < best_bin):
            grouped[frame][bucket] = (value, bin_idx)

    expected = []
    for frame in order:
        expected.append(
            {
                "frame": str(frame),
                "low_bin": str(grouped[frame]["low"][1]),
                "mid_bin": str(grouped[frame]["mid"][1]),
                "high_bin": str(grouped[frame]["high"][1]),
            }
        )
    return expected


def test_pipeline_outputs_and_grouped_peaks():
    run_solution()

    audioproc = APP_DIR / "audioproc.py"
    wav_path = DATA_DIR / "clip.wav"
    mag_path = DATA_DIR / "mag.csv"
    peaks_path = DATA_DIR / "peaks.csv"

    assert audioproc.exists()
    assert wav_path.exists()
    assert mag_path.exists()
    assert peaks_path.exists()

    rate, samples = wavfile.read(wav_path)
    assert rate == 22050
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    assert samples.shape[0] == int(22050 * 3.5)

    mag_rows = read_csv(mag_path)
    peaks_rows = read_csv(peaks_path)
    assert mag_rows
    assert peaks_rows
    assert set(mag_rows[0].keys()) == {"frame", "bin", "val"}
    assert set(peaks_rows[0].keys()) == {"frame", "low_bin", "mid_bin", "high_bin"}

    expected = compute_expected_peaks(mag_rows)
    assert peaks_rows == expected


def test_solution_invokes_awk_via_path(tmp_path):
    wrapper_dir, log_path = install_awk_wrapper(tmp_path)
    run_solution(
        env={
            "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
            "AWK_LOG": str(log_path),
        }
    )

    assert log_path.exists()
    log_text = log_path.read_text()
    assert log_text.strip()
    assert log_text.count("awk ") == 1


def test_stft_matches_required_configuration():
    run_solution()

    rate, samples = wavfile.read(DATA_DIR / "clip.wav")
    signal = samples.astype(np.float64) / 32767.0
    _, _, zxx = stft(
        signal,
        fs=rate,
        window=("tukey", 0.25),
        nperseg=1102,
        noverlap=826,
        nfft=2048,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    expected = np.abs(zxx)

    mag_rows = read_csv(DATA_DIR / "mag.csv")
    frames = max(int(row["frame"]) for row in mag_rows) + 1
    bins = max(int(row["bin"]) for row in mag_rows) + 1
    observed = np.zeros((bins, frames), dtype=np.float64)
    for row in mag_rows:
        observed[int(row["bin"]), int(row["frame"])] = float(row["val"])

    assert observed.shape == expected.shape
    np.testing.assert_allclose(observed, expected, rtol=1e-6, atol=1e-9)


def test_peaks_only_uses_existing_mag_csv(tmp_path):
    run_solution()

    original_mag = DATA_DIR / "mag.csv"
    backup_mag = DATA_DIR / "mag.original.csv"
    shutil.copyfile(original_mag, backup_mag)

    custom_mag = """frame,bin,val
0,0,1.5
0,7,1.5
0,127,0.4
0,128,0.8
0,300,2.2
0,511,2.2
0,512,0.1
0,900,3.5
0,1024,3.5
1,5,0.7
1,126,0.9
1,200,4.0
1,400,1.0
1,700,1.2
1,900,1.3
"""
    original_mag.write_text(custom_mag)

    peaks_before = (DATA_DIR / "peaks.csv").read_text()
    clip_before = (DATA_DIR / "clip.wav").read_bytes()
    wrapper_dir, log_path = install_awk_wrapper(tmp_path)
    run_solution(
        env={
            "PEAKS_ONLY": "1",
            "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
            "AWK_LOG": str(log_path),
        }
    )

    assert (DATA_DIR / "clip.wav").read_bytes() == clip_before
    assert backup_mag.read_text() != original_mag.read_text()
    assert (DATA_DIR / "peaks.csv").read_text() != peaks_before
    assert log_path.exists()
    assert log_path.read_text().strip()

    peaks_rows = read_csv(DATA_DIR / "peaks.csv")
    assert peaks_rows == [
        {"frame": "0", "low_bin": "0", "mid_bin": "300", "high_bin": "900"},
        {"frame": "1", "low_bin": "126", "mid_bin": "200", "high_bin": "900"},
    ]


def test_audioproc_only_writes_clip_and_mag():
    run_solution()

    clip_path = DATA_DIR / "clip.wav"
    mag_path = DATA_DIR / "mag.csv"
    peaks_path = DATA_DIR / "peaks.csv"

    clip_path.unlink(missing_ok=True)
    mag_path.unlink(missing_ok=True)
    peaks_path.unlink(missing_ok=True)

    subprocess.run(["python3", str(APP_DIR / "audioproc.py")], check=True)

    assert clip_path.exists()
    assert mag_path.exists()
    assert not peaks_path.exists()

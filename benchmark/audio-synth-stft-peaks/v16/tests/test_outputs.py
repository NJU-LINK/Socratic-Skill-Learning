import csv
import math
import os
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"
FS = 16000
SAMPLES = int(3.0 * FS)
LEFT_FREQS = [220.0, 440.0, 660.0]
RIGHT_FREQS = [330.0, 550.0, 770.0]


def run_solution(env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run([str(SOLUTION)], check=True, cwd=APP_DIR, env=merged_env)


def load_mag_rows():
    with (DATA_DIR / "mag.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_peaks_rows():
    with (DATA_DIR / "peaks.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def frame_bin_maps(rows):
    left = {}
    right = {}
    total = {}
    for row in rows:
        key = (int(row["frame"]), int(row["bin"]))
        left[key] = float(row["left_val"])
        right[key] = float(row["right_val"])
        total[key] = float(row["total_val"])
    return left, right, total


def expected_top_bins(total_by_key):
    per_frame = {}
    for (frame, bin_idx), value in total_by_key.items():
        per_frame.setdefault(frame, []).append((value, bin_idx))
    expected = {}
    for frame, values in per_frame.items():
        values.sort(key=lambda item: (-item[0], item[1]))
        expected[frame] = [bin_idx for _, bin_idx in values[:3]]
    return expected


def test_pipeline_outputs_match_spec():
    run_solution()

    clip_path = DATA_DIR / "clip.wav"
    mag_path = DATA_DIR / "mag.csv"
    peaks_path = DATA_DIR / "peaks.csv"
    audioproc_path = APP_DIR / "audioproc.py"

    assert clip_path.exists()
    assert mag_path.exists()
    assert peaks_path.exists()
    assert audioproc_path.exists()

    sample_rate, samples = wavfile.read(clip_path)
    assert sample_rate == FS
    assert samples.dtype == np.int16
    assert samples.shape == (SAMPLES, 2)

    float_samples = samples.astype(np.float64) / 32767.0
    left = float_samples[:, 0]
    right = float_samples[:, 1]

    left_rms = math.sqrt(np.mean(left ** 2))
    right_rms = math.sqrt(np.mean(right ** 2))
    assert abs(left_rms - 0.18) <= 0.0025
    assert abs(right_rms - 0.18) <= 0.0025

    freqs = np.fft.rfftfreq(SAMPLES, d=1 / FS)
    left_spec = np.abs(np.fft.rfft(left))
    right_spec = np.abs(np.fft.rfft(right))

    for freq in LEFT_FREQS:
        idx = np.argmin(np.abs(freqs - freq))
        assert left_spec[idx] > right_spec[idx] * 8

    for freq in RIGHT_FREQS:
        idx = np.argmin(np.abs(freqs - freq))
        assert right_spec[idx] > left_spec[idx] * 8


def test_mag_csv_matches_channelwise_stft():
    run_solution()
    rows = load_mag_rows()

    assert rows
    assert list(rows[0].keys()) == ["frame", "bin", "left_val", "right_val", "total_val"]

    sample_rate, samples = wavfile.read(DATA_DIR / "clip.wav")
    assert sample_rate == FS
    float_samples = samples.astype(np.float64) / 32767.0

    _, _, z_left = stft(
        float_samples[:, 0],
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    _, _, z_right = stft(
        float_samples[:, 1],
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )

    mag_left = np.abs(z_left)
    mag_right = np.abs(z_right)
    expected_rows = mag_left.shape[0] * mag_left.shape[1]
    assert len(rows) == expected_rows

    probe_points = [
        (0, 14),
        (0, 21),
        (5, 35),
        (20, 49),
        (50, 42),
    ]
    for frame, bin_idx in probe_points:
        row = rows[frame * mag_left.shape[0] + bin_idx]
        left_val = float(row["left_val"])
        right_val = float(row["right_val"])
        total_val = float(row["total_val"])
        assert int(row["frame"]) == frame
        assert int(row["bin"]) == bin_idx
        assert left_val == pytest.approx(mag_left[bin_idx, frame], rel=1e-4, abs=5e-5)
        assert right_val == pytest.approx(mag_right[bin_idx, frame], rel=1e-4, abs=5e-5)
        assert total_val == pytest.approx(
            mag_left[bin_idx, frame] + mag_right[bin_idx, frame], rel=1e-4, abs=5e-5
        )


def test_peaks_only_uses_mag_csv_ranking_and_channel_label():
    run_solution()
    original_mag = (DATA_DIR / "mag.csv").read_text(encoding="utf-8")

    custom_mag = "".join(
        [
            "frame,bin,left_val,right_val,total_val\n",
            "0,2,2.0,10.0,12.0\n",
            "0,9,7.0,1.0,8.0\n",
            "0,4,0.5,6.5,7.0\n",
            "0,1,9.0,0.0,6.0\n",
            "1,6,5.0,2.0,7.0\n",
            "1,3,0.0,6.2,6.2\n",
            "1,8,4.0,1.0,5.0\n",
            "1,5,0.1,4.5,4.6\n",
        ]
    )
    (DATA_DIR / "mag.csv").write_text(custom_mag, encoding="utf-8")

    try:
        clip_path = DATA_DIR / "clip.wav"
        if clip_path.exists():
            clip_path.unlink()

        run_solution(env={"PEAKS_ONLY": "1"})
        peaks = load_peaks_rows()
        assert peaks == [
            {"frame": "0", "f1_bin": "2", "f2_bin": "9", "f3_bin": "4", "dominant_channel": "R"},
            {"frame": "1", "f1_bin": "6", "f2_bin": "3", "f3_bin": "8", "dominant_channel": "L"},
        ]
        assert not clip_path.exists()
    finally:
        (DATA_DIR / "mag.csv").write_text(original_mag, encoding="utf-8")


def test_peak_bins_match_true_top3_from_generated_mag():
    run_solution()
    mag_rows = load_mag_rows()
    peaks_rows = load_peaks_rows()
    left_by_key, right_by_key, total_by_key = frame_bin_maps(mag_rows)
    expected = expected_top_bins(total_by_key)

    assert len(peaks_rows) == len(expected)
    for row in peaks_rows:
        frame = int(row["frame"])
        expected_bins = expected[frame]
        actual_bins = [int(row["f1_bin"]), int(row["f2_bin"]), int(row["f3_bin"])]
        assert actual_bins == expected_bins

        top_key = (frame, actual_bins[0])
        expected_channel = "L" if left_by_key[top_key] > right_by_key[top_key] else "R"
        assert row["dominant_channel"] == expected_channel


def test_implementation_boundary_uses_awk_and_keeps_python_off_peaks_csv():
    run_solution()

    audioproc_text = (APP_DIR / "audioproc.py").read_text(encoding="utf-8")

    original_mag = (DATA_DIR / "mag.csv").read_text(encoding="utf-8")
    custom_mag = "".join(
        [
            "frame,bin,left_val,right_val,total_val\n",
            "0,2,2.0,10.0,12.0\n",
            "0,9,7.0,1.0,8.0\n",
            "0,4,0.5,6.5,7.0\n",
            "0,1,9.0,0.0,6.0\n",
            "1,6,5.0,2.0,7.0\n",
            "1,3,0.0,6.2,6.2\n",
            "1,8,4.0,1.0,5.0\n",
            "1,5,0.1,4.5,4.6\n",
        ]
    )
    wrapper_dir = APP_DIR / "test-bin"
    wrapper_dir.mkdir(exist_ok=True)
    wrapper_path = wrapper_dir / "awk"
    awk_log = DATA_DIR / "awk-invoked.log"
    sentinel_output = "".join(
        [
            "frame,f1_bin,f2_bin,f3_bin,dominant_channel\n",
            "7,101,55,12,L\n",
            "8,202,88,44,R\n",
        ]
    )

    wrapper_path.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -euo pipefail
            printf 'called\n' >> {awk_log}
            printf '%s' '{sentinel_output}'
            """
        ),
        encoding="utf-8",
    )
    wrapper_path.chmod(0o755)

    lowered_audioproc = audioproc_text.lower()
    assert "peaks.csv" not in lowered_audioproc
    assert "mag.csv" in lowered_audioproc
    assert "subprocess" not in lowered_audioproc
    assert "os.system" not in lowered_audioproc
    assert "awk" not in lowered_audioproc

    (DATA_DIR / "mag.csv").write_text(custom_mag, encoding="utf-8")
    if awk_log.exists():
        awk_log.unlink()

    try:
        clip_path = DATA_DIR / "clip.wav"
        if clip_path.exists():
            clip_path.unlink()

        run_solution(
            env={
                "PEAKS_ONLY": "1",
                "PATH": f"{wrapper_dir}:{os.environ['PATH']}",
            }
        )

        assert awk_log.exists()
        assert awk_log.read_text(encoding="utf-8").strip() == "called"
        assert not clip_path.exists()
        assert (DATA_DIR / "peaks.csv").read_text(encoding="utf-8") == sentinel_output
    finally:
        (DATA_DIR / "mag.csv").write_text(original_mag, encoding="utf-8")
        if awk_log.exists():
            awk_log.unlink()
        if wrapper_path.exists():
            wrapper_path.unlink()
        if wrapper_dir.exists():
            wrapper_dir.rmdir()

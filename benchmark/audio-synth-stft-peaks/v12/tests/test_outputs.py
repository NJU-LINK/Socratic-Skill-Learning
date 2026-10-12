import csv
import hashlib
import os
import subprocess
import textwrap
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import stft


APP_DIR = Path("/app")
DATA_DIR = APP_DIR / "data"
SOLUTION = APP_DIR / "run_audio_pipeline.sh"
EPSILON = 1e-12
DB_FLOOR = -50.0
FS = 16000
DURATION_SEC = 3.0
TARGET_RMS = 0.12


def run_solution(env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run([str(SOLUTION)], check=True, cwd=APP_DIR, env=merged_env)


def run_solution_with_awk_wrapper(tmp_path, env=None, sentinel_output=None):
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    log_path = tmp_path / "awk.log"
    wrapper_path = wrapper_dir / "awk"
    sentinel_stdout = ""
    if sentinel_output is not None:
        sentinel_stdout = textwrap.indent(sentinel_output, "" * 0)
    wrapper_path.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf 'awk invoked\n' >> {log_path}
            if [ -n "{int(sentinel_output is not None)}" ] && [ "{int(sentinel_output is not None)}" -eq 1 ]; then
                cat <<'EOF'
{sentinel_stdout}EOF
                exit 0
            fi
            exec /usr/bin/awk "$@"
            """
        ),
        encoding="utf-8",
    )
    wrapper_path.chmod(0o755)

    merged_env = os.environ.copy()
    merged_env["PATH"] = f"{wrapper_dir}:{merged_env['PATH']}"
    if env:
        merged_env.update(env)

    run_solution(env=merged_env)
    return log_path


def sentinel_peak_rows():
    return [
        {"frame": "0", "f1_bin": "111", "f2_bin": "222", "f3_bin": "333"},
        {"frame": "1", "f1_bin": "444", "f2_bin": "555", "f3_bin": "666"},
    ]


def sentinel_peak_csv_text():
    rows = ["frame,f1_bin,f2_bin,f3_bin"]
    for row in sentinel_peak_rows():
        rows.append(
            ",".join([row["frame"], row["f1_bin"], row["f2_bin"], row["f3_bin"]])
        )
    return "\n".join(rows) + "\n"


def read_csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def expected_peak_rows(mag_rows):
    grouped = {}
    for row in mag_rows:
        frame = int(row["frame"])
        grouped.setdefault(frame, [])
        mag_db = float(row["mag_db"])
        if mag_db >= DB_FLOOR:
            grouped[frame].append((mag_db, int(row["bin"])))

    peak_rows = []
    max_frame = max(grouped)
    for frame in range(max_frame + 1):
        ranked = sorted(grouped.get(frame, []), key=lambda item: (-item[0], item[1]))[:3]
        bins = [bin_idx for _, bin_idx in ranked]
        bins.extend([-1] * (3 - len(bins)))
        peak_rows.append(
            {
                "frame": str(frame),
                "f1_bin": str(bins[0]),
                "f2_bin": str(bins[1]),
                "f3_bin": str(bins[2]),
            }
        )
    return peak_rows


def synth_reference_signal():
    sample_count = int(FS * DURATION_SEC)
    t = np.arange(sample_count, dtype=np.float64) / FS
    envelope = np.exp(-4.0 * t / DURATION_SEC)
    freqs = np.array([220.0, 330.0, 440.0, 550.0, 660.0], dtype=np.float64)
    signal = np.sin(2.0 * np.pi * freqs[:, None] * t).sum(axis=0) / len(freqs)
    signal *= envelope
    rng = np.random.default_rng(0)
    signal += rng.uniform(-1e-4, 1e-4, size=sample_count)
    signal *= TARGET_RMS / np.sqrt(np.mean(signal**2))
    peak = np.max(np.abs(signal))
    pcm = np.round(np.clip(signal / peak, -1.0, 1.0) * 32767.0).astype(np.int16)
    return pcm.astype(np.float64) / 32767.0


def test_full_pipeline_outputs_expected_files_and_shapes():
    run_solution()

    assert (APP_DIR / "audioproc.py").exists()
    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert (DATA_DIR / "peaks.csv").exists()

    samples, sr = sf.read(DATA_DIR / "clip.wav")
    assert sr == FS
    assert samples.ndim == 1
    assert len(samples) == int(FS * DURATION_SEC)
    expected_samples = synth_reference_signal()
    assert np.allclose(samples.astype(np.float64), expected_samples, atol=1 / 32767)

    mag_rows = read_csv_rows(DATA_DIR / "mag.csv")
    peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")

    assert list(mag_rows[0]) == ["frame", "bin", "mag_db"]
    assert list(peaks_rows[0]) == ["frame", "f1_bin", "f2_bin", "f3_bin"]
    assert len(mag_rows) == 189 * 513
    assert len(peaks_rows) == 189


def test_mag_csv_matches_centered_db_stft_reference():
    run_solution()

    mag_rows = read_csv_rows(DATA_DIR / "mag.csv")
    signal_for_stft = synth_reference_signal()
    _, _, zxx = stft(
        signal_for_stft,
        fs=FS,
        window="hann",
        nperseg=1024,
        noverlap=768,
        nfft=1024,
        boundary="zeros",
        padded=True,
        return_onesided=True,
    )
    expected = 20.0 * np.log10(np.abs(zxx) + EPSILON)

    expected_rows = []
    for frame_idx in range(expected.shape[1]):
        for bin_idx in range(expected.shape[0]):
            expected_rows.append((frame_idx, bin_idx, expected[bin_idx, frame_idx]))

    assert len(mag_rows) == len(expected_rows)
    for row, (frame_idx, bin_idx, mag_db) in zip(mag_rows, expected_rows):
        assert int(row["frame"]) == frame_idx
        assert int(row["bin"]) == bin_idx
        assert abs(float(row["mag_db"]) - mag_db) < 1e-6


def test_peaks_csv_matches_thresholded_top_three_bins():
    run_solution()

    mag_rows = read_csv_rows(DATA_DIR / "mag.csv")
    peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")
    assert peaks_rows == expected_peak_rows(mag_rows)
    assert any("-1" in (row["f1_bin"], row["f2_bin"], row["f3_bin"]) for row in peaks_rows)


def test_solution_invokes_awk_at_runtime_in_full_pipeline(tmp_path):
    log_path = run_solution_with_awk_wrapper(tmp_path, sentinel_output=sentinel_peak_csv_text())

    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8").count("awk invoked\n") >= 1
    peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")
    assert peaks_rows == sentinel_peak_rows()


def test_audioproc_only_writes_clip_and_mag_not_peaks():
    run_solution()

    peaks_path = DATA_DIR / "peaks.csv"
    if peaks_path.exists():
        peaks_path.unlink()

    subprocess.run(["python3", str(APP_DIR / "audioproc.py")], check=True, cwd=APP_DIR)

    assert (DATA_DIR / "clip.wav").exists()
    assert (DATA_DIR / "mag.csv").exists()
    assert not peaks_path.exists()


def test_solution_invokes_awk_at_runtime_in_peaks_only_mode(tmp_path):
    run_solution()

    peaks_path = DATA_DIR / "peaks.csv"
    if peaks_path.exists():
        peaks_path.unlink()

    log_path = run_solution_with_awk_wrapper(
        tmp_path,
        env={"PEAKS_ONLY": "1"},
        sentinel_output=sentinel_peak_csv_text(),
    )

    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8").count("awk invoked\n") >= 1
    peaks_rows = read_csv_rows(peaks_path)
    assert peaks_rows == sentinel_peak_rows()


def test_peaks_only_reuses_existing_mag_csv_without_regenerating_audio_or_mag():
    run_solution()

    clip_hash_before = hashlib.sha256((DATA_DIR / "clip.wav").read_bytes()).hexdigest()
    mag_hash_before = hashlib.sha256((DATA_DIR / "mag.csv").read_bytes()).hexdigest()
    peaks_path = DATA_DIR / "peaks.csv"
    peaks_path.unlink()

    subprocess.run(
        [str(SOLUTION)],
        check=True,
        cwd=APP_DIR,
        env={**os.environ.copy(), "PEAKS_ONLY": "1"},
    )

    clip_hash_after = hashlib.sha256((DATA_DIR / "clip.wav").read_bytes()).hexdigest()
    mag_hash_after = hashlib.sha256((DATA_DIR / "mag.csv").read_bytes()).hexdigest()
    assert clip_hash_after == clip_hash_before
    assert mag_hash_after == mag_hash_before
    assert peaks_path.exists()


def test_peaks_only_requires_awk_generated_output_from_supplied_mag_csv():
    run_solution()

    mag_csv = DATA_DIR / "mag.csv"
    clip_path = DATA_DIR / "clip.wav"
    original_mag = mag_csv.read_text(encoding="utf-8")
    original_clip = clip_path.read_bytes()

    custom_mag = "".join(
        [
            "frame,bin,mag_db\n",
            "0,5,-40\n",
            "0,2,-40\n",
            "0,6,-49\n",
            "0,9,-55\n",
            "1,1,-80\n",
            "2,10,-50\n",
            "2,9,-50\n",
            "2,8,-50\n",
            "2,7,-50\n",
        ]
    )
    mag_csv.write_text(custom_mag, encoding="utf-8")
    if (DATA_DIR / "peaks.csv").exists():
        (DATA_DIR / "peaks.csv").unlink()

    try:
        run_solution(env={"PEAKS_ONLY": "1"})
        peaks_rows = read_csv_rows(DATA_DIR / "peaks.csv")
        assert peaks_rows == [
            {"frame": "0", "f1_bin": "2", "f2_bin": "5", "f3_bin": "6"},
            {"frame": "1", "f1_bin": "-1", "f2_bin": "-1", "f3_bin": "-1"},
            {"frame": "2", "f1_bin": "7", "f2_bin": "8", "f3_bin": "9"},
        ]
    finally:
        mag_csv.write_text(original_mag, encoding="utf-8")
        clip_path.write_bytes(original_clip)

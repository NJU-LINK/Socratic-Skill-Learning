import csv
import os
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import find_peaks
from scipy.signal import stft


APP_DIR = Path('/app')
DATA_DIR = APP_DIR / 'data'


def run_solution(*, peaks_only=False):
    env = os.environ.copy()
    if peaks_only:
        env['PEAKS_ONLY'] = '1'
    subprocess.run(['bash', '/app/run_audio_pipeline.sh'], check=True, cwd=APP_DIR, env=env)


def load_stereo_float(path: Path) -> np.ndarray:
    with wave.open(str(path), 'rb') as wav_file:
        assert wav_file.getnchannels() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() == 48000
        frames = wav_file.readframes(wav_file.getnframes())
    pcm = np.frombuffer(frames, dtype=np.int16).reshape(-1, 2)
    return pcm.astype(np.float64) / 32767.0


def load_mag_rows(path: Path):
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def grouped_mag_rows(mag_path: Path):
    grouped = {}
    for row in load_mag_rows(mag_path):
        grouped.setdefault(int(row['frame']), []).append((int(row['bin']), float(row['val'])))
    return grouped


def assert_top3_bins_allowing_ties(entries, chosen_bins):
    assert len(chosen_bins) == 3
    assert len(set(chosen_bins)) == 3

    values_by_bin = {bin_idx: value for bin_idx, value in entries}
    ranked_values = sorted(values_by_bin.values(), reverse=True)
    threshold = ranked_values[2]

    chosen_values = [values_by_bin[bin_idx] for bin_idx in chosen_bins]
    assert chosen_values[0] >= chosen_values[1] >= chosen_values[2]
    assert all(value >= threshold for value in chosen_values)

    strictly_higher = {bin_idx for bin_idx, value in entries if value > threshold}
    assert strictly_higher.issubset(set(chosen_bins))


def dominant_peak_summary(channel):
    windowed = channel * np.hanning(channel.size)
    mag = np.abs(np.fft.rfft(windowed))
    peaks, _ = find_peaks(mag, prominence=mag.max() * 0.05, distance=30)
    ordered = peaks[np.argsort(mag[peaks])[::-1]]
    top5 = ordered[:5]
    mask = np.zeros_like(mag, dtype=bool)
    for peak in top5:
        lo = max(0, peak - 3)
        hi = min(mag.size, peak + 4)
        mask[lo:hi] = True
    return {
        'peak_count': len(peaks),
        'cluster_energy_ratio': float(mag[mask].sum() / mag.sum()),
        'freq_bins': top5,
        'magnitudes': mag,
    }


def test_pipeline_writes_deterministic_five_tone_stereo_wav_and_expected_mag_csv():
    run_solution()

    clip = DATA_DIR / 'clip.wav'
    mag = DATA_DIR / 'mag.csv'
    peaks = DATA_DIR / 'peaks.csv'
    assert clip.exists()
    assert mag.exists()
    assert peaks.exists()

    stereo = load_stereo_float(clip)
    assert stereo.shape == (48000, 2)
    assert not np.allclose(stereo[:, 0], stereo[:, 1])

    first_run = stereo.copy()
    run_solution()
    second_run = load_stereo_float(clip)
    assert np.array_equal(first_run, second_run)

    left_summary = dominant_peak_summary(stereo[:, 0])
    right_summary = dominant_peak_summary(stereo[:, 1])
    assert left_summary['peak_count'] == 5
    assert right_summary['peak_count'] == 5
    assert left_summary['cluster_energy_ratio'] > 0.97
    assert right_summary['cluster_energy_ratio'] > 0.97
    assert set(left_summary['freq_bins']).isdisjoint(set(right_summary['freq_bins']))

    residual_left = stereo[:, 0] - np.mean(stereo[:, 0])
    residual_right = stereo[:, 1] - np.mean(stereo[:, 1])
    assert np.std(residual_left) > 0.05
    assert np.std(residual_right) > 0.05

    mono = stereo.mean(axis=1)
    _, _, zxx = stft(
        mono,
        fs=16000,
        window='hann',
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
        return_onesided=True,
    )
    expected_mag = np.abs(zxx)

    rows = load_mag_rows(mag)
    assert len(rows) == expected_mag.shape[0] * expected_mag.shape[1]

    sample_points = [
        (0, 0),
        (0, 17),
        (1, 55),
        (expected_mag.shape[1] // 2, 123),
        (expected_mag.shape[1] - 1, expected_mag.shape[0] - 1),
    ]
    for frame_idx, bin_idx in sample_points:
        row = rows[frame_idx * expected_mag.shape[0] + bin_idx]
        assert int(row['frame']) == frame_idx
        assert int(row['bin']) == bin_idx
        assert float(row['val']) == pytest.approx(expected_mag[bin_idx, frame_idx], rel=1e-9, abs=1e-12)


def test_peaks_csv_matches_true_top3_bins_per_frame():
    run_solution()

    expected = grouped_mag_rows(DATA_DIR / 'mag.csv')
    with (DATA_DIR / 'peaks.csv').open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == len(expected)
    for row in rows:
        frame = int(row['frame'])
        assert int(row['frame']) == frame
        assert_top3_bins_allowing_ties(
            expected[frame],
            [int(row['f1_bin']), int(row['f2_bin']), int(row['f3_bin'])],
        )


def test_peaks_only_uses_existing_mag_csv_without_rebuilding_audio_files():
    run_solution()

    clip = DATA_DIR / 'clip.wav'
    mag = DATA_DIR / 'mag.csv'
    original_clip = clip.read_bytes()

    custom_rows = [
        {'frame': '0', 'bin': '8', 'val': '0.30'},
        {'frame': '0', 'bin': '2', 'val': '0.90'},
        {'frame': '0', 'bin': '4', 'val': '0.70'},
        {'frame': '0', 'bin': '1', 'val': '0.70'},
        {'frame': '0', 'bin': '6', 'val': '0.20'},
        {'frame': '1', 'bin': '5', 'val': '0.10'},
        {'frame': '1', 'bin': '9', 'val': '0.80'},
        {'frame': '1', 'bin': '3', 'val': '0.50'},
        {'frame': '1', 'bin': '4', 'val': '0.80'},
        {'frame': '1', 'bin': '0', 'val': '0.05'},
    ]
    with mag.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['frame', 'bin', 'val'])
        writer.writeheader()
        writer.writerows(custom_rows)

    run_solution(peaks_only=True)

    assert clip.read_bytes() == original_clip
    assert load_mag_rows(mag) == custom_rows

    with (DATA_DIR / 'peaks.csv').open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    for row in rows:
        frame = int(row['frame'])
        entries = [(int(item['bin']), float(item['val'])) for item in custom_rows if int(item['frame']) == frame]
        assert_top3_bins_allowing_ties(
            entries,
            [int(row['f1_bin']), int(row['f2_bin']), int(row['f3_bin'])],
        )


def test_solution_uses_real_path_resolved_awk_for_peak_generation_in_both_modes(tmp_path):
    run_solution()

    clip = DATA_DIR / 'clip.wav'
    mag = DATA_DIR / 'mag.csv'
    peaks = DATA_DIR / 'peaks.csv'
    real_awk = subprocess.run(
        ['bash', '-lc', 'command -v awk'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    real_python3 = subprocess.run(
        ['bash', '-lc', 'command -v python3'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    wrapper_dir = tmp_path / 'bin'
    wrapper_dir.mkdir()
    awk_log = tmp_path / 'awk.log'
    python_log = tmp_path / 'python.log'
    awk_wrapper = wrapper_dir / 'awk'
    python_wrapper = wrapper_dir / 'python3'
    awk_wrapper.write_text(
        "#!/bin/bash\n"
        f"echo invoked >> {awk_log}\n"
        f"exec {real_awk} \"$@\"\n",
        encoding='utf-8',
    )
    python_wrapper.write_text(
        "#!/bin/bash\n"
        f"echo invoked >> {python_log}\n"
        f"exec {real_python3} \"$@\"\n",
        encoding='utf-8',
    )
    awk_wrapper.chmod(0o755)
    python_wrapper.chmod(0o755)

    env = os.environ.copy()
    env['PATH'] = str(wrapper_dir)

    clip.unlink(missing_ok=True)
    mag.unlink(missing_ok=True)
    peaks.unlink(missing_ok=True)
    subprocess.run([str(python_wrapper), '/app/audioproc.py'], check=True, cwd=APP_DIR, env=env)
    assert clip.exists()
    assert mag.exists()
    assert not peaks.exists()

    custom_rows = [
        {'frame': '0', 'bin': '8', 'val': '0.30'},
        {'frame': '0', 'bin': '2', 'val': '0.90'},
        {'frame': '0', 'bin': '4', 'val': '0.70'},
        {'frame': '0', 'bin': '1', 'val': '0.70'},
        {'frame': '0', 'bin': '6', 'val': '0.20'},
    ]
    with mag.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['frame', 'bin', 'val'])
        writer.writeheader()
        writer.writerows(custom_rows)
    peaks.unlink(missing_ok=True)
    env['PEAKS_ONLY'] = '1'
    subprocess.run(['/bin/bash', '/app/run_audio_pipeline.sh'], check=True, cwd=APP_DIR, env=env)

    assert awk_log.read_text(encoding='utf-8').strip() == 'invoked'
    assert not python_log.exists()
    assert peaks.exists()

    with peaks.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert_top3_bins_allowing_ties(
        [(int(item['bin']), float(item['val'])) for item in custom_rows],
        [int(rows[0]['f1_bin']), int(rows[0]['f2_bin']), int(rows[0]['f3_bin'])],
    )

    del env['PEAKS_ONLY']
    awk_log.unlink()
    python_log.unlink(missing_ok=True)
    clip.unlink(missing_ok=True)
    mag.unlink(missing_ok=True)
    peaks.unlink(missing_ok=True)

    subprocess.run(['/bin/bash', '/app/run_audio_pipeline.sh'], check=True, cwd=APP_DIR, env=env)
    assert python_log.read_text(encoding='utf-8').strip() == 'invoked'
    assert awk_log.read_text(encoding='utf-8').strip() == 'invoked'
    assert clip.exists()
    assert mag.exists()
    assert peaks.exists()

    awk_wrapper.write_text(
        "#!/bin/bash\n"
        "exit 97\n",
        encoding='utf-8',
    )
    awk_wrapper.chmod(0o755)
    python_log.unlink(missing_ok=True)
    peaks.unlink(missing_ok=True)

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(['/bin/bash', '/app/run_audio_pipeline.sh'], check=True, cwd=APP_DIR, env=env)
    assert python_log.read_text(encoding='utf-8').strip() == 'invoked'
    assert not peaks.exists()

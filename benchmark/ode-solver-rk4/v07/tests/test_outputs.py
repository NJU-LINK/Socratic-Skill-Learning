import csv
import math
import subprocess
from pathlib import Path

import pytest


APP_DIR = Path('/app')
OUTPUT_DIR = APP_DIR / 'output'
PROBLEM_PATH = APP_DIR / 'ode_problem.py'
SOLUTION_PATH = APP_DIR / 'ode_solve.py'
CALL_LOG_PATH = OUTPUT_DIR / 'rhs_calls.log'


def _write_problem(t0, t1, y0, eval_ts, rhs_source):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if CALL_LOG_PATH.exists():
        CALL_LOG_PATH.unlink()

    PROBLEM_PATH.write_text(
        "import math\n"
        f"t0 = {t0!r}\n"
        f"t1 = {t1!r}\n"
        f"y0 = {y0!r}\n"
        f"eval_ts = {eval_ts!r}\n"
        f"_CALL_LOG = {str(CALL_LOG_PATH)!r}\n\n"
        "def rhs(t, y):\n"
        "    with open(_CALL_LOG, 'a', encoding='utf-8') as f:\n"
        "        f.write(f'{t:.17g}\\n')\n"
        f"    return {rhs_source}\n",
        encoding='utf-8',
    )


def _reference_values(rhs, t0, t1, y0, eval_ts):
    h_ref = (t1 - t0) / 12000.0
    t = t0
    y = y0
    values = []

    def rk4_step(cur_t, cur_y, h):
        k1 = rhs(cur_t, cur_y)
        k2 = rhs(cur_t + 0.5 * h, cur_y + 0.5 * h * k1)
        k3 = rhs(cur_t + 0.5 * h, cur_y + 0.5 * h * k2)
        k4 = rhs(cur_t + h, cur_y + h * k3)
        return cur_y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    for target_t in eval_ts:
        while target_t - t > 0.0:
            h = min(h_ref, target_t - t)
            y = rk4_step(t, y, h)
            t += h
            if t > target_t:
                t = target_t
        values.append(y)
        t = target_t

    return values


def _run_solver():
    assert SOLUTION_PATH.exists(), 'expected /app/ode_solve.py to exist'
    subprocess.run(['python3', str(SOLUTION_PATH)], cwd=str(APP_DIR), check=True)


def _read_solution_rows():
    solution_csv = OUTPUT_DIR / 'solution.csv'
    assert solution_csv.exists(), 'expected /app/output/solution.csv to be written'
    with solution_csv.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert rows, 'solution.csv should contain at least one data row'
    return rows


def _assert_problem_case(case):
    _write_problem(case['t0'], case['t1'], case['y0'], case['eval_ts'], case['rhs_source'])
    _run_solver()

    rows = _read_solution_rows()
    assert [field.strip() for field in rows[0].keys()] == ['t', 'y']
    assert len(rows) == len(case['eval_ts'])

    ref_values = _reference_values(case['rhs'], case['t0'], case['t1'], case['y0'], case['eval_ts'])
    written_ts = [float(row['t']) for row in rows]
    written_ys = [float(row['y']) for row in rows]

    for written_t, expected_t in zip(written_ts, case['eval_ts']):
        assert abs(written_t - expected_t) <= 1e-12, (written_t, expected_t)

    max_abs_err = max(abs(actual - expected) for actual, expected in zip(written_ys, ref_values))
    assert max_abs_err <= 1e-5, max_abs_err

    call_times = [float(line) for line in CALL_LOG_PATH.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert call_times, 'rhs should have been called at least once'
    assert call_times == sorted(call_times), 'rhs call times must be non-decreasing'

    h_max = (case['t1'] - case['t0']) / 200.0
    max_gap = max(b - a for a, b in zip(call_times, call_times[1:])) if len(call_times) > 1 else 0.0
    assert max_gap <= (h_max / 2.0) + 1e-12, max_gap

    for target_t in case['eval_ts']:
        assert any(abs(call_t - target_t) <= 1e-12 for call_t in call_times), target_t

    assert len(call_times) <= 1600, len(call_times)


@pytest.mark.parametrize(
    'case',
    [
        {
            't0': 0.0,
            't1': 2.2,
            'y0': 0.15,
            'eval_ts': [0.002, 0.005, 0.008, 0.012, 0.017, 0.73, 1.41, 2.182, 2.191, 2.196, 2.199, 2.2],
            'rhs_source': '0.24 * math.sin(0.9 * t + 0.1) - 0.31 * y + 0.08 * (y / (1.0 + y * y)) + 0.05 * math.cos(1.7 * t - 0.2 * y)',
            'rhs': lambda t, y: 0.24 * math.sin(0.9 * t + 0.1) - 0.31 * y + 0.08 * (y / (1.0 + y * y)) + 0.05 * math.cos(1.7 * t - 0.2 * y),
        },
        {
            't0': -0.4,
            't1': 1.7,
            'y0': -0.2,
            'eval_ts': [-0.398, -0.391, -0.382, -0.374, 0.16, 0.93, 1.676, 1.691, 1.697, 1.699, 1.7],
            'rhs_source': '0.18 * math.cos(1.3 * t - 0.2) - 0.22 * y + 0.07 * (y / (1.0 + 0.5 * y * y)) + 0.04 * math.sin(0.6 * t + 0.3 * y)',
            'rhs': lambda t, y: 0.18 * math.cos(1.3 * t - 0.2) - 0.22 * y + 0.07 * (y / (1.0 + 0.5 * y * y)) + 0.04 * math.sin(0.6 * t + 0.3 * y),
        },
    ],
)
def test_boundary_clustered_schedule_accuracy_and_audit(case):
    _assert_problem_case(case)

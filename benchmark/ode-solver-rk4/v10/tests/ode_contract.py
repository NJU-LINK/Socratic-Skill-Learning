from __future__ import annotations

import csv
import hashlib
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APP_DIR = Path("/app")
PROBLEM_PATH = APP_DIR / "ode_problem.py"
SOLVER_PATH = APP_DIR / "ode_solve.py"
OUTPUT_PATH = APP_DIR / "output" / "solution.csv"
IMPORT_LOG = APP_DIR / "output" / "_ode_contract_imports.log"
AUDIT_RUNNER = APP_DIR / "_ode_contract_runner.py"

DENIED_IMPORTS = {
    "diffrax",
    "jax",
    "scipy",
    "sympy",
    "tensorflow",
    "torch",
    "torchdiffeq",
}
DENIED_SOURCE_MARKERS = DENIED_IMPORTS | {"odeint", "solve_ivp"}


@dataclass(frozen=True)
class OdeCase:
    name: str
    t0: float
    t1: float
    y0: float
    eval_ts: tuple[float, ...]
    rhs_expression: str
    constants: dict[str, Any] = field(default_factory=dict)
    step_divisor: int = 200
    accuracy: float = 1e-5
    reference_refinement: int = 40
    max_calls_factor: float = 8.0
    max_calls_slack: int = 32
    require_predecessor: bool = True
    require_rhs_at_t0: bool = False


@dataclass(frozen=True)
class OdeResult:
    rows: tuple[tuple[float, float], ...]
    call_times: tuple[float, ...]
    reference_values: tuple[float, ...]
    minimum_steps: int


def _safe_name(name: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in name)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _problem_source(case: OdeCase, call_log: Path) -> str:
    return (
        "from __future__ import annotations\n\n"
        "import math\n"
        "from pathlib import Path\n\n"
        f"t0 = {case.t0!r}\n"
        f"t1 = {case.t1!r}\n"
        f"y0 = {case.y0!r}\n"
        f"eval_ts = {list(case.eval_ts)!r}\n"
        f"_CONSTANTS = {case.constants!r}\n"
        f"_CALL_LOG = Path({str(call_log)!r})\n\n"
        "def rhs(t, y):\n"
        "    _CALL_LOG.parent.mkdir(parents=True, exist_ok=True)\n"
        "    with _CALL_LOG.open('a', encoding='utf-8') as handle:\n"
        "        handle.write(f'{float(t):.17g}\\n')\n"
        "    c = _CONSTANTS\n"
        f"    return float({case.rhs_expression})\n"
    )


def _reference_values(case: OdeCase) -> tuple[float, ...]:
    h_max = (case.t1 - case.t0) / float(case.step_divisor)
    h_ref = h_max / float(case.reference_refinement)
    rhs_code = compile(case.rhs_expression, f"<rhs:{case.name}>", "eval")

    def raw_rhs(t: float, y: float) -> float:
        value = eval(
            rhs_code,
            {"__builtins__": {}, "math": math},
            {"c": case.constants, "t": float(t), "y": float(y)},
        )
        return float(value)

    t = float(case.t0)
    y = float(case.y0)
    values: list[float] = []

    for target in case.eval_ts:
        tolerance = 1e-15 * max(1.0, abs(target))
        while t < target - tolerance:
            h = min(h_ref, target - t)
            k1 = raw_rhs(t, y)
            k2 = raw_rhs(t + 0.5 * h, y + 0.5 * h * k1)
            k3 = raw_rhs(t + 0.5 * h, y + 0.5 * h * k2)
            k4 = raw_rhs(t + h, y + h * k3)
            y += (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
            t += h
            if abs(target - t) <= tolerance:
                t = target
        values.append(y)

    return tuple(values)


def _minimum_steps(case: OdeCase) -> int:
    h_max = (case.t1 - case.t0) / float(case.step_divisor)
    current = float(case.t0)
    steps = 0
    for target in case.eval_ts:
        distance = max(0.0, float(target) - current)
        if distance:
            steps += math.ceil(distance / h_max - 1e-12)
        current = float(target)
    return steps


def _write_audit_runner() -> None:
    AUDIT_RUNNER.write_text(
        "from __future__ import annotations\n"
        "import atexit\n"
        "import runpy\n"
        "import sys\n"
        f"_IMPORT_LOG = {str(IMPORT_LOG)!r}\n"
        "def _write_imports():\n"
        "    names = sorted({name.split('.')[0] for name in sys.modules})\n"
        "    with open(_IMPORT_LOG, 'w', encoding='utf-8') as handle:\n"
        "        handle.write('\\n'.join(names))\n"
        "atexit.register(_write_imports)\n"
        "runpy.run_path('/app/ode_solve.py', run_name='__main__')\n",
        encoding="utf-8",
    )


def _read_rows() -> tuple[tuple[float, float], ...]:
    assert OUTPUT_PATH.exists(), "solver did not create /app/output/solution.csv"
    with OUTPUT_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["t", "y"], "solution.csv header must be exactly t,y"
        raw_rows = list(reader)
    rows = tuple((float(row["t"]), float(row["y"])) for row in raw_rows)
    assert all(math.isfinite(t) and math.isfinite(y) for t, y in rows)
    return rows


def evaluate_case(case: OdeCase) -> OdeResult:
    assert case.t0 < case.t1
    assert case.eval_ts
    assert all(case.t0 <= target <= case.t1 for target in case.eval_ts)
    assert all(left < right for left, right in zip(case.eval_ts, case.eval_ts[1:]))
    assert case.reference_refinement >= 8
    assert SOLVER_PATH.exists(), "expected the agent artifact /app/ode_solve.py"

    output_dir = OUTPUT_PATH.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    call_log = output_dir / f"_ode_contract_calls_{_safe_name(case.name)}.log"
    for path in (OUTPUT_PATH, call_log, IMPORT_LOG):
        path.unlink(missing_ok=True)
    shutil.rmtree(APP_DIR / "__pycache__", ignore_errors=True)

    PROBLEM_PATH.write_text(_problem_source(case, call_log), encoding="utf-8")
    problem_hash = _sha256(PROBLEM_PATH)
    _write_audit_runner()

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP_DIR)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(AUDIT_RUNNER)],
        cwd=APP_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert _sha256(PROBLEM_PATH) == problem_hash, "solver modified ode_problem.py"

    rows = _read_rows()
    call_times = tuple(
        float(line)
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    references = _reference_values(case)
    minimum_steps = _minimum_steps(case)

    assert len(rows) == len(case.eval_ts), "expected exactly one output row per eval_t"
    for index, ((written_t, written_y), target, expected_y) in enumerate(
        zip(rows, case.eval_ts, references)
    ):
        assert abs(written_t - target) <= 1e-12, f"row {index} did not preserve eval_t"
        assert abs(written_y - expected_y) <= case.accuracy, (
            f"{case.name}: row {index} error {abs(written_y - expected_y):.3e} "
            f"exceeds {case.accuracy:.1e}"
        )

    assert call_times, "solver never called ode_problem.rhs"
    assert all(
        left <= right + 1e-15 for left, right in zip(call_times, call_times[1:])
    ), "rhs call times must be non-decreasing"
    assert all(case.t0 - 1e-12 <= value <= case.t1 + 1e-12 for value in call_times)

    h_max = (case.t1 - case.t0) / float(case.step_divisor)
    max_gap = max((right - left for left, right in zip(call_times, call_times[1:])), default=0.0)
    assert max_gap <= 0.5 * h_max + 1e-12, (
        f"{case.name}: rhs stage gap {max_gap} exceeded h_max/2"
    )

    for target in case.eval_ts:
        if abs(target - case.t0) <= 1e-15 and not case.require_rhs_at_t0:
            continue
        landing_index = next(
            (
                index
                for index, call_time in enumerate(call_times)
                if abs(call_time - target) <= 1e-12
            ),
            None,
        )
        assert landing_index is not None, f"{case.name}: rhs never landed at {target}"
        if case.require_predecessor and target > case.t0 + 1e-15:
            assert landing_index > 0
            predecessor = call_times[landing_index - 1]
            assert predecessor < target - 1e-15
            assert target - predecessor <= 0.5 * h_max + 1e-12

    call_cap = math.floor(case.max_calls_factor * minimum_steps) + case.max_calls_slack
    assert len(call_times) <= call_cap, (
        f"{case.name}: {len(call_times)} rhs calls exceeded budget {call_cap}"
    )

    imports = set(IMPORT_LOG.read_text(encoding="utf-8").split())
    assert DENIED_IMPORTS.isdisjoint(imports), (
        f"forbidden ODE stack imported: {sorted(DENIED_IMPORTS & imports)}"
    )
    source = SOLVER_PATH.read_text(encoding="utf-8").lower()
    assert not [marker for marker in DENIED_SOURCE_MARKERS if marker in source], (
        "solver source names a forbidden black-box ODE stack"
    )

    return OdeResult(rows, call_times, references, minimum_steps)

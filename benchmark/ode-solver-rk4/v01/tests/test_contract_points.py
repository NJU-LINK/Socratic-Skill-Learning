from __future__ import annotations

import csv
import hashlib
import math
import os
import subprocess
import sys
from functools import cache
from pathlib import Path


APP = Path("/app")
PROBLEM = APP / "ode_problem.py"
SOLVER = APP / "ode_solve.py"
OUTPUT = APP / "output" / "solution.csv"
DENIED_SOURCE_MARKERS = {
    "diffrax",
    "jax",
    "odeint",
    "scipy",
    "solve_ivp",
    "sympy",
    "tensorflow",
    "torch",
    "torchdiffeq",
}


@cache
def _baseline_run() -> tuple[subprocess.CompletedProcess[str], str]:
    assert SOLVER.exists(), "expected the agent artifact /app/ode_solve.py"
    PROBLEM.write_text(
        "import math\n"
        "t0 = 0.0\n"
        "t1 = 1.0\n"
        "y0 = 0.25\n"
        "eval_ts = [0.125, 0.5, 1.0]\n\n"
        "def rhs(t, y):\n"
        "    return math.sin(t) - 0.1 * y\n",
        encoding="utf-8",
    )
    problem_hash = hashlib.sha256(PROBLEM.read_bytes()).hexdigest()
    OUTPUT.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(SOLVER)],
        cwd=APP,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return completed, problem_hash


def test_solver_runs_without_mutating_the_public_problem() -> None:
    completed, problem_hash = _baseline_run()
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert hashlib.sha256(PROBLEM.read_bytes()).hexdigest() == problem_hash


def test_baseline_output_has_the_declared_finite_schema() -> None:
    completed, _ = _baseline_run()
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert OUTPUT.exists(), "solver did not create /app/output/solution.csv"
    with OUTPUT.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["t", "y"]
        rows = list(reader)
    assert rows
    assert all(
        math.isfinite(float(row["t"])) and math.isfinite(float(row["y"]))
        for row in rows
    )


def test_solver_source_does_not_delegate_to_a_black_box_ode_stack() -> None:
    assert SOLVER.exists(), "expected the agent artifact /app/ode_solve.py"
    source = SOLVER.read_text(encoding="utf-8").lower()
    found = sorted(marker for marker in DENIED_SOURCE_MARKERS if marker in source)
    assert not found, f"solver delegates to forbidden ODE stack(s): {found}"

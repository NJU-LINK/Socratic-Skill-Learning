from __future__ import annotations

import importlib.util
from pathlib import Path


SOLVER = Path("/app/solve.py")


def test_solver_exposes_callable_run() -> None:
    assert SOLVER.exists(), "/app/solve.py not found"
    spec = importlib.util.spec_from_file_location("submitted_solver_contract", SOLVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "run", None)), "solve.py must define callable run()"

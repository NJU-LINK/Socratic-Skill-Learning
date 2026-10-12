#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/ode_solve.py
from __future__ import annotations

import csv
from pathlib import Path

import ode_problem


def rk4_step(t: float, y: float, h: float) -> float:
    half = 0.5 * h
    k1 = ode_problem.rhs(t, y)
    k2 = ode_problem.rhs(t + half, y + half * k1)
    k3 = ode_problem.rhs(t + half, y + half * k2)
    k4 = ode_problem.rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve() -> None:
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]
    h_max = (t1 - t0) / 400.0

    t = t0
    rows: list[tuple[float, float]] = []

    for target in eval_ts:
        while t < target:
            h = min(h_max, target - t)
            y = rk4_step(t, y, h)
            t += h
        rows.append((target, y))

    output_path = Path("/app/output/solution.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    solve()
PY

chmod +x /app/ode_solve.py

# Verification may run this script before the harness creates /app/ode_problem.py.
if [ -f /app/ode_problem.py ]; then
  python3 /app/ode_solve.py
fi

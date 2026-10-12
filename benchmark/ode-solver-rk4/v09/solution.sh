#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/ode_solve.py
#!/usr/bin/env python3
import csv
import math
from pathlib import Path

import ode_problem


def rk4_step(t, y, h):
    rhs = ode_problem.rhs
    half = 0.5 * h
    k1 = rhs(t, y)
    k2 = rhs(t + half, y + half * k1)
    k3 = rhs(t + half, y + half * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]
    h_max = (t1 - t0) / 300.0

    t = t0
    rows = []
    eps = 1e-15

    for target in eval_ts:
        if target < t - 1e-12:
            raise ValueError("eval_ts must be non-decreasing relative to solver state")
        while target - t > eps:
            h = min(h_max / 2.0, target - t)
            y = rk4_step(t, y, h)
            t += h
            if abs(t - target) <= 1e-14:
                t = target
        rows.append((target, y))

    output_dir = Path("/app/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "solution.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    solve()
PY

chmod +x /app/ode_solve.py

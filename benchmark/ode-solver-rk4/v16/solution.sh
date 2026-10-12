#!/bin/bash
set -euo pipefail

mkdir -p /app/output

cat > /app/ode_solve.py <<'PY'
import csv
from pathlib import Path

import ode_problem


def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + 0.5 * h, y + 0.5 * h * k1)
    k3 = rhs(t + 0.5 * h, y + 0.5 * h * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]
    h_max = (t1 - t0) / 200.0
    if not t0 < t1:
        raise ValueError("expected t0 < t1")
    if h_max <= 0.0:
        raise ValueError("expected positive h_max")

    t = t0
    rows = []
    for target in eval_ts:
        if target < t - 1e-15:
            raise ValueError("eval_ts must be nondecreasing from current state")
        while target - t > 1e-15:
            h = min(h_max, target - t)
            y = rk4_step(ode_problem.rhs, t, y, h)
            t += h
            if t > target and t - target < 1e-12:
                t = target
        t = target
        rows.append((target, y))

    output_path = Path("/app/output/solution.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "y"])
        for target, value in rows:
            writer.writerow([f"{target:.17g}", f"{value:.17g}"])


if __name__ == "__main__":
    solve()
PY

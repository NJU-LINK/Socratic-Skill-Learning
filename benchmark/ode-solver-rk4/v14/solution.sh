#!/bin/bash
set -euo pipefail

app_dir="${APP_DIR:-$(pwd)}"
mkdir -p "$app_dir/output"

cat > "$app_dir/ode_solve.py" <<'PY'
from pathlib import Path
import csv

import ode_problem


def rk4_step(t, y, h):
    f = ode_problem.rhs
    k1 = f(t, y)
    k2 = f(t + 0.5 * h, y + 0.5 * h * k1)
    k3 = f(t + 0.5 * h, y + 0.5 * h * k2)
    k4 = f(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]
    h_max = (t1 - t0) / 200.0

    t = t0
    rows = []
    for target in eval_ts:
        while t + 1e-15 < target:
            next_t = target if target - t <= h_max else t + h_max
            h = next_t - t
            y = rk4_step(t, y, h)
            t = next_t
        rows.append((target, y))

    output_path = Path(__file__).resolve().parent / "output" / "solution.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    solve()
PY

chmod +x "$app_dir/ode_solve.py"

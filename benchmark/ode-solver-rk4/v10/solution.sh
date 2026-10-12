#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
mkdir -p "$APP_DIR/output"

cat <<'PY' > "$APP_DIR/ode_solve.py"
from __future__ import annotations

import csv
import math
import os

import ode_problem


APP_DIR = os.environ.get("APP_DIR", "/app")


def rk4_step(t: float, y: float, h: float) -> float:
    k1 = ode_problem.rhs(t, y)
    k2 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k1)
    k3 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k2)
    k4 = ode_problem.rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def integrate_to_targets() -> list[tuple[float, float]]:
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]
    h_max = (t1 - t0) / 200.0

    t = t0
    rows: list[tuple[float, float]] = []
    for target_t in eval_ts:
        delta = target_t - t
        if delta < 0.0:
            raise ValueError("eval_ts must be strictly increasing")
        if delta == 0.0:
            rows.append((target_t, y))
            continue

        n_steps = max(1, math.ceil(delta / h_max))
        h = delta / n_steps
        for _ in range(n_steps):
            y = rk4_step(t, y, h)
            t += h
        t = target_t
        rows.append((target_t, y))

    return rows


def main() -> None:
    rows = integrate_to_targets()
    with open(os.path.join(APP_DIR, "output", "solution.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
PY

if [ -f "$APP_DIR/ode_problem.py" ]; then
    python3 "$APP_DIR/ode_solve.py"
fi

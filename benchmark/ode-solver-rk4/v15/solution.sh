#!/usr/bin/env bash
set -euo pipefail

cat > /app/ode_solve.py <<'PY'
from __future__ import annotations

import csv
from pathlib import Path

import ode_problem


def rk4_step(t: float, y: float, h: float) -> float:
    rhs = ode_problem.rhs
    half = 0.5 * h
    k1 = rhs(t, y)
    k2 = rhs(t + half, y + half * k1)
    k3 = rhs(t + half, y + half * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def main() -> None:
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    targets = [float(value) for value in ode_problem.eval_ts]
    h_max = (t1 - t0) / 800.0

    t = t0
    rows: list[tuple[float, float]] = []
    for target in targets:
        tolerance = 1e-15 * max(1.0, abs(target))
        while t < target - tolerance:
            h = min(h_max, target - t)
            y = rk4_step(t, y, h)
            t += h
            if abs(target - t) <= tolerance:
                t = target
        if abs(target - t0) <= tolerance:
            ode_problem.rhs(target, y)
        rows.append((target, y))

    output_dir = Path("/app/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "solution.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
PY

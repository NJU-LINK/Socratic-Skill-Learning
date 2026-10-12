#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/ode_solve.py
from __future__ import annotations

import csv
from pathlib import Path

import ode_problem


def rk4_step(t: float, y: float, h: float) -> tuple[float, float]:
    k1 = ode_problem.rhs(t, y)
    k2 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k1)
    k3 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k2)
    k4 = ode_problem.rhs(t + h, y + h * k3)
    return t + h, y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve() -> None:
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]

    h_max = (t1 - t0) / 200.0
    t = t0
    rows: list[tuple[float, float]] = []

    for eval_t in eval_ts:
        while eval_t - t > 1e-15:
            h = min(h_max, eval_t - t)
            t, y = rk4_step(t, y, h)
            if t > eval_t and t - eval_t > 1e-12:
                raise RuntimeError(f"overshot eval_t {eval_t} from {t}")
            if abs(t - eval_t) <= 1e-12:
                t = eval_t
        rows.append((eval_t, y))

    output_path = Path("/app/output/solution.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["t", "y"])
        writer.writerows(rows)


if __name__ == "__main__":
    solve()
PY

mkdir -p /app/output
cp /app/ode_solve.py /app/output/ode_solve_source.py
cat <<'SH' > /app/output/solution.sh
#!/bin/bash
set -euo pipefail
cd /app
cp /app/output/ode_solve_source.py /app/ode_solve.py
python3 /app/ode_solve.py
SH
chmod +x /app/output/solution.sh

if [ -f /app/ode_problem.py ]; then
  /app/output/solution.sh
fi

#!/bin/bash
set -euo pipefail

cat <<'PY' > /app/ode_solve.py
import csv
import os

import ode_problem


def rk4_step(t, y, h):
    k1 = ode_problem.rhs(t, y)
    k2 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k1)
    k3 = ode_problem.rhs(t + 0.5 * h, y + 0.5 * h * k2)
    k4 = ode_problem.rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def main():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y = float(ode_problem.y0)
    eval_ts = [float(t) for t in ode_problem.eval_ts]

    h_max = (t1 - t0) / 200.0
    t = t0
    rows = []

    for target_t in eval_ts:
        while target_t - t > 0.0:
            h = min(h_max, target_t - t)
            y = rk4_step(t, y, h)
            t += h
        rows.append((target_t, y))
        t = target_t

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['t', 'y'])
        writer.writerows(rows)


if __name__ == '__main__':
    main()
PY

chmod +x /app/ode_solve.py

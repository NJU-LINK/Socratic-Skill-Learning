#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

script = '''#!/usr/bin/env python3
import csv
import math
from pathlib import Path

from ode_problem import eval_ts, rhs, t0, t1, y0


def rk4_step(t: float, y: float, h: float) -> float:
    half = 0.5 * h
    k1 = rhs(t, y)
    k2 = rhs(t + half, y + half * k1)
    k3 = rhs(t + half, y + half * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve() -> None:
    t = float(t0)
    y = float(y0)
    targets = [float(value) for value in eval_ts]
    h_max = (float(t1) - float(t0)) / 200.0
    rows = []

    for target in targets:
        if target < t:
            raise ValueError('eval_ts must be non-decreasing and stay ahead of the solver')

        if math.isclose(target, t, rel_tol=0.0, abs_tol=1e-15):
            t = target
            rows.append((target, y))
            continue

        remaining = target - t
        steps = max(1, math.ceil((remaining / h_max) - 1e-15))
        for step_index in range(steps):
            h = (target - t) / float(steps - step_index)
            y = rk4_step(t, y, h)
            t += h

        t = target
        rows.append((target, y))

    output_path = Path('/app/output/solution.csv')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['t', 'y'])
        for target, value in rows:
            writer.writerow([format(target, '.17g'), format(value, '.17g')])


if __name__ == '__main__':
    solve()
'''

Path('/app/ode_solve.py').write_text(script)
PY

chmod +x /app/ode_solve.py

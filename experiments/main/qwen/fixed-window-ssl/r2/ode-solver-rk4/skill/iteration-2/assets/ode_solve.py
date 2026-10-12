"""
Reference implementation: Tiny numeric IVP solver using RK4 with segment-based
fixed-step integration.

Integrates dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0,
landing exactly on each requested eval_t without interpolation.

CRITICAL: For the last step of each segment, explicitly compute h_last = eval_t - current_t
to ensure non-decreasing rhs call times. Without this, floating-point accumulation can cause
the last k4 call to be slightly > eval_t, violating monotonicity when the next segment starts.

Usage:
  1. Place this file at /app/ode_solve.py
  2. Ensure /app/ode_problem.py exists with: t0, t1, y0, eval_ts, rhs
  3. Run: python /app/ode_solve.py
  4. Output: /app/output/solution.csv with header t,y

Adaptation notes for family variants:
  - h_max formula: change `interval / 200.0` if the task spec gives a different ceiling
  - Everything else is invariant across the ode-solver-rk4 family
"""

import math
import os
import csv

from ode_problem import t0, t1, y0, eval_ts, rhs


def rk4_step(f, t, y, h):
    """One step of classical 4th-order Runge-Kutta.
    
    Butcher tableau:
      0   |
      1/2 | 1/2
      1/2 | 0    1/2
      1   | 0    0    1
      ----+----------------
          | 1/6  1/3  1/3  1/6
    """
    k1 = f(t, y)
    k2 = f(t + h / 2.0, y + h / 2.0 * k1)
    k3 = f(t + h / 2.0, y + h / 2.0 * k2)
    k4 = f(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    # Hard ceiling on substep size — adapt divisor if task spec changes
    interval = t1 - t0
    h_max = interval / 200.0

    results = []

    current_t = float(t0)
    current_y = float(y0)

    for eval_t in eval_ts:
        # Segment from current_t to eval_t
        seg_len = eval_t - current_t

        if seg_len < 0:
            raise ValueError(
                f"eval_ts not strictly increasing: {eval_t} < {current_t}"
            )

        if seg_len == 0.0:
            # Already at this eval_t (e.g., eval_t == t0)
            results.append((eval_t, current_y))
            continue

        # Number of substeps: minimum N such that seg_len / N <= h_max
        N = max(1, math.ceil(seg_len / h_max))
        h = seg_len / N

        # Advance N substeps of RK4
        for i in range(N):
            if i == N - 1:
                # CRITICAL: Last step — explicitly compute h to land exactly on eval_t
                # This ensures current_t + h_last = eval_t exactly (no accumulated drift)
                # and guarantees non-decreasing rhs call times across segment boundaries
                h_last = eval_t - current_t
                current_y = rk4_step(rhs, current_t, current_y, h_last)
                current_t = eval_t  # Now exactly equal
            else:
                current_y = rk4_step(rhs, current_t, current_y, h)
                current_t = current_t + h

        results.append((eval_t, current_y))

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])


if __name__ == "__main__":
    solve()

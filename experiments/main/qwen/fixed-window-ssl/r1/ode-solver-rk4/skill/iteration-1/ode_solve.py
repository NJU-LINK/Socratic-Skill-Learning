"""
Reference implementation: Fixed-step RK4 IVP solver with exact landing.

Solves dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0.
Outputs y at each eval_t using segment-divide strategy:
  - Partition [t0, t1] at each eval_t
  - For each segment, choose n = ceil(seg_length / h_max) uniform substeps
  - Step size h = seg_length / n  (≤ h_max, divides segment exactly)
  - Snap t_curr to target after each segment to eliminate FP drift

This satisfies:
  - Hard step ceiling: h ≤ h_max by construction
  - Exact landing: last step of each segment ends at eval_t exactly
  - Uniform spacing within segments (no tiny clamp remainder)
  - Sample efficiency: total steps ≤ (t1-t0)/h_max + len(eval_ts)
  - Accuracy: RK4 O(h⁴) global error; with h_max=(t1-t0)/200, error ~1e-10

Usage:
  1. Place ode_problem.py in /app/ with: t0, t1, y0, eval_ts, rhs
  2. Run: python ode_solve.py
  3. Output: /app/output/solution.csv with header t,y
"""

import os
import csv
import math
from ode_problem import t0, t1, y0, eval_ts, rhs


def rk4_step(t, y, h):
    """
    Classical 4th-order Runge-Kutta step.

    Butcher tableau:
        0   |
        1/2 | 1/2
        1/2 | 0    1/2
        1   | 0    0    1
        ----+------------------
            | 1/6  1/3  1/3  1/6

    Args:
        t: current time
        y: current state
        h: step size

    Returns:
        y at t + h
    """
    k1 = rhs(t, y)
    k2 = rhs(t + h / 2.0, y + h * k1 / 2.0)
    k3 = rhs(t + h / 2.0, y + h * k2 / 2.0)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    """
    Integrate the IVP and write solution.csv.

    Strategy:
    - For each segment [t_prev, eval_t]:
        n = max(1, ceil(seg_length / h_max))
        h = seg_length / n
        Take n uniform RK4 steps of size h
        Snap t_curr to eval_t (drift elimination)
    - Emit (eval_t, y_curr) for each target
    """
    # Step ceiling: hard upper bound on substep size
    h_max = (t1 - t0) / 200.0

    t_curr = t0
    y_curr = y0
    results = []

    for target in eval_ts:
        seg = target - t_curr

        # Skip degenerate segments (target ≈ current position)
        if seg < 1e-15:
            results.append((target, y_curr))
            continue

        # Compute number of uniform substeps that divide this segment exactly
        n = max(1, math.ceil(seg / h_max))
        h = seg / n  # guaranteed ≤ h_max

        # Integrate through the segment
        for _ in range(n):
            y_curr = rk4_step(t_curr, y_curr, h)
            t_curr += h

        # Eliminate floating-point drift by snapping to exact target
        t_curr = target

        # Record result using exact target time (not accumulated t_curr)
        results.append((target, y_curr))

    # Write output CSV
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "y"])
        for t, y in results:
            w.writerow([t, y])


if __name__ == "__main__":
    solve()

"""
Segment-based exact-landing RK4 IVP solver.

Reference implementation for the ode-solver-rk4 skill family.
Copy this file to /app/ode_solve.py when solving instances.

Solves dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0.
Outputs solution at each eval_t by landing exactly on those times.
"""
import os
import csv
import math
import ode_problem as prob


def rk4_step(f, t, y, h):
    """Standard 4th-order Runge-Kutta single step."""
    k1 = f(t, y)
    k2 = f(t + h * 0.5, y + h * 0.5 * k1)
    k3 = f(t + h * 0.5, y + h * 0.5 * k2)
    k4 = f(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    """
    Main solver routine.
    
    Algorithm:
    1. Build target sequence from eval_ts (skip t0 if present)
    2. For each segment between consecutive targets:
       - Compute minimum steps: n = ceil(gap / h_max)
       - Set uniform step size: h = gap / n
       - Take n-1 uniform RK4 steps
       - Clamp final step to land exactly on target
    3. Write output CSV with exact eval_t values
    """
    t0 = prob.t0
    t1 = prob.t1
    y0 = prob.y0
    eval_ts = list(prob.eval_ts)

    os.makedirs("/app/output", exist_ok=True)

    # Hard ceiling on substep size
    h_max = (t1 - t0) / 200.0

    # Build target times: all eval_ts, but skip any that equal t0
    # (we already start at t0 with y0)
    targets = []
    initial_recorded = False
    rows = []

    for te in eval_ts:
        if not initial_recorded and abs(te - t0) < 1e-15:
            rows.append((te, y0))
            initial_recorded = True
        else:
            targets.append(te)

    t_cur = t0
    y_cur = y0

    for t_target in targets:
        gap = t_target - t_cur
        if gap <= 1e-15:
            # Already at or past this target
            rows.append((t_target, y_cur))
            continue

        # Minimum number of uniform substeps to respect h_max
        n = max(1, math.ceil(gap / h_max - 1e-12))
        h = gap / n

        # Take n-1 uniform steps
        for _ in range(n - 1):
            y_cur = rk4_step(prob.rhs, t_cur, y_cur, h)
            t_cur += h

        # Final step: clamp to land exactly on t_target
        h_last = t_target - t_cur
        y_cur = rk4_step(prob.rhs, t_cur, y_cur, h_last)
        t_cur = t_target  # exact

        # Record using the exact eval_t value
        rows.append((t_target, y_cur))

    with open("/app/output/solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "y"])
        for t_val, y_val in rows:
            w.writerow([repr(t_val), repr(y_val)])


solve()

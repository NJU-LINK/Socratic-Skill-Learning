"""
Reference RK4 IVP solver implementation.
This is the canonical solver that embodies the skill's procedure.
Adapt h_max and other parameters per task specification.

Key design decisions:
1. Uniform steps within each segment for efficiency and exact landing
2. Base-relative time computation to prevent floating-point drift
3. Consistent time expressions (t_base + (i+1)*h) for k4 and next step's k1
   to ensure non-decreasing rhs call times
4. Last step k4 at exact target time for exact landing
5. Robust handling of edge cases (closely-spaced eval_ts, boundary-proximal targets)
"""
import os
import csv
import math
import sys

sys.path.insert(0, "/app")
import ode_problem


def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = list(ode_problem.eval_ts)  # Make a copy to avoid mutation
    rhs = ode_problem.rhs

    # Hard ceiling on step size (adjust per task specification)
    h_max = (t1 - t0) / 200.0

    results = []
    t_current = t0
    y_current = y0
    
    # Epsilon for floating-point comparisons
    # Used in ceil() to prevent overshooting due to rounding
    eps_ceil = 1e-12
    
    # Threshold for detecting zero-length segments
    # Must be small enough to not skip legitimate short segments
    # but large enough to catch floating-point noise
    zero_threshold = 1e-15

    for target in eval_ts:
        segment_length = target - t_current

        # Handle zero-length or near-zero-length segment
        if segment_length <= zero_threshold:
            # Record current state at target
            results.append((target, y_current))
            t_current = target
            continue

        # Compute uniform step count
        # Use max(1, ...) to ensure at least one step even for very short segments
        n_steps = max(1, math.ceil(segment_length / h_max - eps_ceil))
        h = segment_length / n_steps

        # Take n_steps uniform RK4 steps
        t_base = t_current
        for i in range(n_steps):
            t_step = t_base + i * h  # base-relative step start

            # Determine end time for this step
            # CRITICAL: Use same expression as next step's t_step to ensure
            # non-decreasing call times. For last step, use target exactly.
            if i < n_steps - 1:
                t_end = t_base + (i + 1) * h
            else:
                t_end = target

            # RK4 step with k4 at t_end (not t_step + h)
            k1 = rhs(t_step, y_current)
            k2 = rhs(t_step + h * 0.5, y_current + h * k1 * 0.5)
            k3 = rhs(t_step + h * 0.5, y_current + h * k2 * 0.5)
            k4 = rhs(t_end, y_current + h * k3)
            y_current = y_current + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

        # Snap to target to ensure exact landing
        t_current = target
        results.append((target, y_current))

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w") as f:
        f.write("t,y\n")
        for t_val, y_val in results:
            f.write(f"{t_val},{y_val}\n")


if __name__ == "__main__":
    solve()

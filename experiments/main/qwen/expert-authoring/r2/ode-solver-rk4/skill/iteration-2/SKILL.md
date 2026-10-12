---
name: ode-solver-rk4
description: >
  Solve scalar initial-value problems dy/dt = rhs(t, y) using classical
  fourth-order Runge-Kutta (RK4) with fixed-step advance, exact landing on
  requested evaluation times, and output to CSV. Handles varying RHS dynamics,
  evaluation schedules, and integration constraints without black-box ODE libraries.
---

# ODE Solver — RK4 with Exact Landing

## Problem Family

Write a script (`/app/ode_solve.py`) that integrates a scalar IVP:

```
dy/dt = rhs(t, y),   y(t0) = y0,   t ∈ [t0, t1]
```

The problem module (`/app/ode_problem.py`) is provided at runtime and exports:

| Symbol    | Type                        | Purpose                               |
|-----------|-----------------------------|---------------------------------------|
| `t0`      | float                       | Start of integration interval         |
| `t1`      | float                       | End of integration interval           |
| `y0`      | float                       | Initial condition y(t0)               |
| `eval_ts` | list[float]                 | Strictly increasing output times in [t0, t1] |
| `rhs`     | callable `(t, y) -> float`  | Right-hand side (always import and call this) |

**Never modify `ode_problem.py`.** Always import `rhs` from it.

Output: write `/app/output/solution.csv` with header `t,y` and one row per `eval_t`.

## Invariants (Across All Variants)

1. **Method**: Classical RK4 — four function evaluations per step, O(h⁴) local accuracy.
2. **Step ceiling**: Every substep `h ≤ h_max` where `h_max` is derived from the interval (seed: `(t1 - t0) / 200`).
3. **Exact landing**: The final substep before each `eval_t` must be clamped so the step ends exactly at `eval_t`. No interpolation.
4. **Non-decreasing call times**: All calls to `rhs(t, y)` must have non-decreasing `t`. Tests may enforce this with zero or near-zero tolerance.
5. **No black-box solvers**: No SciPy/SymPy integrators, torchdiffeq, diffrax, JAX, TensorFlow, etc.
6. **Accuracy target**: Max absolute error at eval_ts ≤ 5e-6 vs. a fine reference.
7. **Efficiency**: Minimise rhs evaluations; the test enforces a sample-efficiency cap.

## Axes of Variation

### `rhs_dynamics` — RHS shape and stiffness
- Smooth, bounded, non-stiff scalar functions.
- May have time-varying coefficients, nonlinear terms, mixed linear+nonlinear.
- Stronger curvature demands smaller effective steps; RK4 with h_max = (t1-t0)/200 handles typical non-stiff cases comfortably within 5e-6.

### `evaluation_schedule` — Distribution of eval_ts
- Count: from a handful to hundreds of output times.
- Spacing: uniform, clustered, gapped, or mixed.
- Boundary proximity: eval_ts may lie very close to t0 or t1.
- Tests may include a "transient growth window" — a burst of closely-spaced eval_ts within a narrow sub-interval.
- Strategy must handle all layouts without special-casing.

### `integration_constraints` — Step ceiling and efficiency budgets
- h_max formula may change (e.g., `/200`, `/500`).
- Efficiency cap may be tighter or looser.
- Landing tolerance may be stricter.
- The solver naturally adapts: smaller h_max → more steps; segment-based approach minimises step count for any given h_max.

## Solution Strategy: Segment-Based RK4

### Core idea

Process the integration interval as a sequence of **segments**, one per eval_t:

```
segment i: [t_current, eval_ts[i]]
```

Within each segment, take **uniform steps** whose size is the largest value ≤ h_max that divides the segment evenly:

```
dt       = eval_t - t_current
n_steps  = max(1, ceil(dt / h_max))
h        = dt / n_steps          # uniform, guaranteed ≤ h_max
```

After completing all steps in a segment, **snap** `t = eval_t` to eliminate floating-point drift, then record `(eval_t, y)`.

### Critical: clamp k4 time to eval_t

Within each RK4 step, the k4 evaluation calls `rhs(t + h, ...)`. Due to floating-point accumulation in `t += h`, the value `t + h` can exceed `eval_t` by 1-3 ULPs (~1e-16 to ~1e-15) on the last step of a segment. This makes the logged call time at k4 slightly past `eval_t`. After the snap `t = eval_t`, the next segment's first rhs call is at `eval_t`, which is **less** than the overshoot — a non-decreasing violation.

**Fix**: Clamp the k4 time to `min(t + h, eval_t)` inside the RK4 step:

```python
def rk4_step(f, t, y, h, t_max):
    k1 = f(t, y)
    k2 = f(t + h / 2, y + h / 2 * k1)
    k3 = f(t + h / 2, y + h / 2 * k2)
    k4 = f(min(t + h, t_max), y + h * k3)   # clamp to t_max
    return y + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)
```

This ensures no rhs call ever evaluates past the segment boundary. The y-update still uses the full step size `h` (not the clamped time), so accuracy is unaffected.

### Why this works

- **Exact landing**: `n_steps * h = dt` in exact arithmetic; the snap removes float drift.
- **Efficiency**: `ceil(dt / h_max)` is the minimum number of steps of size ≤ h_max to cover the segment. No wasted evaluations.
- **Non-decreasing calls (within step)**: `t ≤ t + h/2 ≤ min(t + h, eval_t)`.
- **Non-decreasing calls (cross-step)**: k4 of step i is at `min(t_i + h, eval_t) ≤ eval_t`. After `t += h`, k1 of step i+1 is at `t_{i+1} ≥ min(t_i + h, eval_t)`.
- **Non-decreasing calls (cross-segment)**: Last call of segment is at `≤ eval_t` (clamped). After snap, first call of next segment is at `eval_t`. No overshoot.
- **Accuracy**: RK4 with h ≤ (t1-t0)/200 gives errors ~O(h⁴) ≈ 1e-9 or better for smooth non-stiff problems, well within 5e-6.

### Full solver template

```python
import math
import os
from ode_problem import t0, t1, y0, eval_ts, rhs


def rk4_step(f, t, y, h, t_max):
    k1 = f(t, y)
    k2 = f(t + h / 2, y + h / 2 * k1)
    k3 = f(t + h / 2, y + h / 2 * k2)
    k4 = f(min(t + h, t_max), y + h * k3)
    return y + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)


def solve():
    h_max = (t1 - t0) / 200.0

    t = t0
    y = y0
    results = []

    for eval_t in eval_ts:
        dt = eval_t - t
        if dt <= 1e-15:
            results.append((eval_t, y))
            continue

        n_steps = max(1, math.ceil(dt / h_max))
        h = dt / n_steps

        for _ in range(n_steps):
            y = rk4_step(rhs, t, y, h, eval_t)
            t += h

        t = eval_t          # snap to exact landing
        results.append((eval_t, y))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w") as fout:
        fout.write("t,y\n")
        for t_val, y_val in results:
            fout.write(f"{t_val},{y_val}\n")


if __name__ == "__main__":
    solve()
```

## Adapting to Constraint Variations

| Variation | Adaptation |
|-----------|------------|
| Different `h_max` formula (e.g., `/500`) | Change the divisor in `h_max = (t1 - t0) / N`. Read the task spec for N. |
| Tighter accuracy (e.g., 1e-8) | Reduce h_max further or use the same formula — RK4 at `/200` already gives ~1e-9 for smooth problems. |
| Loose efficiency cap | No change needed; segment-based approach is already near-optimal. |
| Many dense eval_ts | Handled automatically — each short segment takes 1 step. |
| eval_t at t0 | `dt ≤ 1e-15` branch emits `(eval_t, y0)` with zero rhs calls. |
| eval_t near t1 | Last segment covers `[prev_eval, t1]`; clamping lands exactly on t1. |
| Transient growth window | Dense eval_ts in a narrow band create many small segments; clamping ensures monotonicity. |

## Verification Checklist

Run these checks mentally or with quick prints before submitting:

1. **File exists**: `/app/output/solution.csv` is created with header `t,y`.
2. **Row count**: Number of data rows equals `len(eval_ts)`.
3. **t-values match**: Each written `t` equals the corresponding `eval_t` to ~1e-12.
4. **Non-decreasing rhs calls**: All calls to `rhs` use non-decreasing `t` (tests may check with zero tolerance).
5. **No overshoot**: No rhs call uses `t` beyond the current `eval_t` (k4 is clamped).
6. **Accuracy**: Spot-check a few outputs against a known or high-precision reference.
7. **Efficiency**: Total rhs calls ≈ 4 × Σ ceil(segment_dt / h_max). For the seed (200-step budget), expect ~800 calls for widely spaced eval_ts.
8. **ode_problem.py unchanged**: The file is imported, never modified.

## Common Pitfalls

- **Floating-point monotonicity (CRITICAL)**: `t += h` accumulation causes `t + h` to exceed `eval_t` by 1-3 ULPs on the last step. Always clamp k4's time argument to `min(t + h, eval_t)`. Without this, tests enforcing non-decreasing rhs call times will fail.
- **Interpolation**: Do NOT take a step past eval_t and interpolate back. Always clamp the last step.
- **Drifting t**: Accumulating `t += h` drifts due to float arithmetic. Always snap `t = eval_t` after each segment.
- **Zero-step segments**: When `eval_t ≈ t_current`, skip integration (dt ≤ 1e-15) to avoid a zero-size step that divides by zero or wastes calls.
- **Variable-step methods**: Do not use adaptive Runge-Kutta (Dormand-Prince, etc.) — the task requires fixed-step style.
- **Index-based t computation**: Do NOT compute `t = t_start + i * h` as an alternative to `t += h`. This creates a DIFFERENT monotonicity problem: `(t_start + i*h) + h ≠ t_start + (i+1)*h` in floating point, making k4 of step i differ from k1 of step i+1. Always use `t += h` with clamped k4.
- **Overshooting**: The k4 clamp ensures no rhs call goes past eval_t. Never step past eval_t without clamping.
- **Importing scipy.integrate or similar**: Forbidden. Use only the hand-written RK4.

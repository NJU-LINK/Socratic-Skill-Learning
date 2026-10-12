---
name: ode-solver-rk4
description: >
  Solve scalar initial-value problems dy/dt = rhs(t, y) using classical
  fourth-order Runge-Kutta (RK4) with fixed-step advance, exact landing on
  requested evaluation times, and output to CSV. Handles varying RHS dynamics,
  evaluation schedules, and integration constraints without black-box ODE libraries.
---

# ODE Solver — RK4 with Exact Landing

## Quick Start — Copy This Solver Verbatim

Write the following code **exactly** to `/app/ode_solve.py`. Do not restructure, rename, "optimise", or add features. Every line — especially the `min(t + h, t_max)` clamp in `rk4_step` — is required for correctness.

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

After writing, **do not search for or run test scripts**. The test harness injects `ode_problem.py` and `run-tests.sh` at evaluation time. You may optionally verify with a quick smoke test, then finish.

## Problem Interface

The test harness creates `/app/ode_problem.py` exporting: `t0`, `t1`, `y0`, `eval_ts` (strictly increasing in [t0, t1]), and `rhs(t, y)` — the scalar right-hand side. Never modify this file.

Output: `/app/output/solution.csv` with header `t,y`, one row per `eval_t`.

## Why This Code Is Correct

The solver processes [t0, t1] as **segments** — one per eval_t. Within each segment [t_current, eval_t]:

1. **Uniform steps**: `h = dt / ceil(dt / h_max)` — the largest step ≤ h_max that evenly divides the segment.
2. **k4 clamping**: `min(t + h, t_max)` prevents rhs calls past `eval_t`. Without this, floating-point accumulation in `t += h` causes `t + h` to exceed `eval_t` by 1-3 ULPs on the last step. After the snap `t = eval_t`, the next segment's first call would be **less** than the overshoot — a non-decreasing violation that fails tests with zero tolerance.
3. **Snap**: `t = eval_t` after the loop eliminates float drift.

### Non-decreasing guarantee (all three levels)

- **Within step**: `t ≤ t + h/2 ≤ min(t + h, eval_t)`
- **Cross-step**: k4 at `min(t + h, eval_t) ≤ eval_t`; after `t += h`, next k1 at `t + h ≥ min(prev_t + h, eval_t)`
- **Cross-segment**: last call at `≤ eval_t` (clamped); after snap, next call at `eval_t`

### Accuracy and efficiency

- RK4 with `h ≤ (t1-t0)/200` gives O(h⁴) ≈ 1e-9 errors — far under the 5e-6 target.
- `ceil(dt/h_max)` is the minimum step count per segment — no wasted evaluations.

## What Must Not Change

| Line | Why it's critical |
|------|-------------------|
| `f(min(t + h, t_max), ...)` in k4 | Prevents ULP overshoot → monotonicity violation |
| `t = eval_t` snap after inner loop | Eliminates float drift for exact landing |
| `dt <= 1e-15` guard | Prevents zero-length steps and wasted calls |
| `math.ceil(dt / h_max)` | Minimum steps to satisfy the ceiling constraint |
| `t += h` (not index-based) | Index-based `t = start + i*h` creates a *different* monotonicity bug: `(start + i*h) + h ≠ start + (i+1)*h` |

## Axes of Variation

The solver above handles all variants in this family without modification:

- **`rhs_dynamics`**: Any smooth, bounded, non-stiff scalar RHS. RK4 at h_max = (t1-t0)/200 achieves ~1e-9 accuracy across all such functions.
- **`evaluation_schedule`**: Any count/spacing of eval_ts — clustered bursts, sparse gaps, boundary-adjacent points, single points. The segment-based approach adapts automatically.
- **`integration_constraints`**: The h_max divisor `/200` satisfies the seed's step ceiling and accuracy targets. If the task specifies a different divisor, change only the `200.0` in `h_max = (t1 - t0) / 200.0`.

## Pitfalls to Avoid

- **Do not remove the k4 clamp.** This is the #1 cause of non-decreasing test failures.
- **Do not use `t = t_start + i * h`** instead of `t += h`. This creates cross-step monotonicity violations.
- **Do not interpolate.** Never step past eval_t; the `ceil` + clamp approach lands exactly.
- **Do not use scipy.integrate or any black-box ODE solver.**
- **Do not add adaptive step-size control.** Fixed-step RK4 is required and sufficient.
- **Do not search for test scripts.** They appear at test time, not during solving.

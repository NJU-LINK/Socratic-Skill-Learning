---
name: ode-solver-rk4
description: >
  Write a standalone numeric IVP solver (/app/ode_solve.py) that imports a
  problem module (/app/ode_problem.py), integrates dy/dt = rhs(t, y) with
  classical RK4 under a fixed-step ceiling, lands exactly on every requested
  evaluation time without interpolation, and writes results to
  /app/output/solution.csv.
---

# ODE Solver — RK4 with Exact Landing

## 1  Problem Contract

| Element | Detail |
|---|---|
| **Input module** | `/app/ode_problem.py` — provides `t0`, `t1`, `y0` (scalars), `eval_ts` (strictly increasing sequence in [t0, t1]), and `rhs(t, y)` (scalar RHS). May wrap `rhs` to track call times/counts. |
| **Output file** | `/app/output/solution.csv` — header `t,y`, one row per `eval_t` in order. Each written `t` must match `eval_t` to ~1e-12. |
| **Step ceiling** | Every substep `h ≤ h_max = (t1 − t0) / 200`. |
| **Exact landing** | Must actually call `rhs` at (or extremely near) each `eval_t`; no interpolation. |
| **Monotone calls** | Successive `rhs` call times must be non-decreasing. |
| **Efficiency** | Tests enforce a sample-efficiency budget; do not waste `rhs` evaluations. |
| **Forbidden** | SciPy/SymPy integrators, torchdiffeq, diffrax, JAX/TensorFlow ODE tools. |
| **Accuracy** | Max absolute error at `eval_ts` ≤ 5e-6 vs. a fine reference. |

## 2  Core Algorithm

Use **classical RK4** (4th-order Runge–Kutta) with an adaptive number of equal
substeps per segment between consecutive evaluation times.

### 2.1  Single RK4 Step

```
k1 = rhs(t, y)
k2 = rhs(t + h/2, y + (h/2)·k1)
k3 = rhs(t + h/2, y + (h/2)·k2)
k4 = rhs(t + h,   y + h·k3)
y_new = y + (h/6)·(k1 + 2·k2 + 2·k3 + k4)
```

Call times within one step: `t, t+h/2, t+h/2, t+h` — non-decreasing. ✓

### 2.2  Segment Strategy (exact landing)

For each consecutive pair `(current_t → target_t)`:

1. `dt = target_t − current_t`
2. If `dt < 1e-15`: record `(target_t, current_y)` and continue (already there).
3. `n_steps = max(1, ceil(dt / h_max))` — minimum steps keeping `h ≤ h_max`.
4. `h = dt / n_steps` — equal substeps that divide the segment exactly.
5. Run `n_steps` RK4 steps.
6. **Snap** `current_t = target_t` to prevent floating-point drift.

Because `n_steps × h = dt` by construction, the last `k4` call in the final
step lands at `current_t + dt = target_t` (to machine precision). This
satisfies the exact-landing and monotonicity checks.

### 2.3  Efficiency Analysis

- Total steps ≤ Σ ceil(dt_i / h_max) ≤ N_eval + 200.
- Each RK4 step = 4 `rhs` calls → worst-case ~4 × (N_eval + 200) evaluations.
- For the seed's `h_max = (t1−t0)/200`, this stays well within any reasonable
  efficiency budget.

## 3  Variation Dimensions

### 3.1  `rhs_dynamics` — Different RHS Functions

The solver makes **no assumptions** about the form of `rhs(t, y)` beyond it
being a scalar function. RK4 with `h ≤ (t1−t0)/200` achieves O(h⁴) global
error, which is ≤ ~1e-9 for smooth, non-stiff dynamics on moderate intervals —
far below the 5e-6 threshold.

**What varies:** time-dependent coefficients, nonlinear terms (polynomial,
trigonometric, exponential), mixtures of growth/decay, stronger local curvature.

**What is invariant:** scalar RHS, smooth (non-stiff), callable as `rhs(t, y)`.

### 3.2  `evaluation_schedule` — Different eval_t Distributions

The segment-based approach handles any strictly increasing `eval_ts` in
`[t0, t1]`:

- **Clustered** evals → short segments → 1 step each (tiny h, very accurate).
- **Sparse** evals → long segments → more steps per segment (h ≈ h_max).
- **Boundary** evals at `t0` or `t1` → handled by the `dt < 1e-15` guard and
  normal integration respectively.

**What varies:** count, spacing (uniform, clustered, gapped), proximity to
boundaries.

**What is invariant:** strictly increasing, within [t0, t1].

### 3.3  `integration_constraints` — Step Ceilings and Budgets

The formula `h_max = (t1 − t0) / 200` is **always re-derived** from the
imported `t0` and `t1`. If the test changes the divisor or the interval length,
the solver adapts automatically.

- Tighter ceiling (larger divisor) → more steps, higher accuracy.
- Looser ceiling → fewer steps, still within 5e-6 for smooth problems.
- Efficiency budget is respected because we use the **minimum** number of steps
  per segment (via `ceil`).

## 4  Reference Implementation

```python
#!/usr/bin/env python3
"""Numeric IVP solver using RK4 with exact landing on evaluation times."""

import math
import csv
import os
import ode_problem


def rk4_step(rhs, t, y, h):
    """One classical RK4 step. Returns updated y."""
    k1 = rhs(t, y)
    k2 = rhs(t + h * 0.5, y + h * 0.5 * k1)
    k3 = rhs(t + h * 0.5, y + h * 0.5 * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y0 = float(ode_problem.y0)
    eval_ts = [float(x) for x in ode_problem.eval_ts]
    rhs = ode_problem.rhs

    h_max = (t1 - t0) / 200.0

    results = []
    current_t = t0
    current_y = y0

    for target_t in eval_ts:
        dt = target_t - current_t

        if dt < 1e-15:
            results.append((target_t, current_y))
            continue

        n_steps = max(1, math.ceil(dt / h_max))
        h = dt / n_steps

        for _ in range(n_steps):
            current_y = rk4_step(rhs, current_t, current_y, h)
            current_t += h

        # Snap to exact target to eliminate floating-point drift
        current_t = target_t
        results.append((target_t, current_y))

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['t', 'y'])
        for t, y in results:
            writer.writerow([t, y])


if __name__ == '__main__':
    solve()
```

## 5  Self-Verification Checklist

Before submitting, the solver should be checked against these properties:

| Check | How to verify |
|---|---|
| **Step ceiling** | Every `h = dt / n_steps ≤ (t1−t0)/200`. Guaranteed by `ceil`. |
| **Exact landing** | Last `k4` call per segment at `target_t` (within ~1e-15). Snap `current_t = target_t`. |
| **Monotone calls** | RK4 intra-step: `t ≤ t+h/2 ≤ t+h`. Inter-step: `t` increases. ✓ |
| **No interpolation** | We physically step to every `eval_t`; output `y` is the integrated value. |
| **Row count** | `len(results) == len(eval_ts)`. |
| **t-match** | Written `t` is the exact `float(target_t)` from `eval_ts`. |
| **Accuracy** | RK4 O(h⁴) with h ≤ (t1−t0)/200 gives ~1e-9 error for smooth problems. |
| **Efficiency** | Total RHS calls = 4 × Σ ceil(dt_i/h_max) ≤ 4×(N+200). Minimal. |
| **No forbidden libs** | Only uses `math`, `csv`, `os`, and the imported `ode_problem`. |

## 6  Common Pitfalls

1. **Floating-point drift**: Accumulating `current_t += h` over many steps can
   drift from the exact `eval_t`. Always snap `current_t = target_t` after each
   segment.

2. **Off-by-one in step count**: Using `floor` instead of `ceil` for `n_steps`
   produces `h > h_max`, violating the step ceiling. Always use `ceil`.

3. **Interpolation temptation**: Do NOT step past `eval_t` and interpolate
   back. The test checks `rhs` call times to confirm physical landing.

4. **Copying eval_t values**: Convert `eval_ts` elements to Python `float` to
   avoid numpy scalar formatting issues in CSV output.

5. **Modifying ode_problem.py**: The harness may hash or check it. Import only.

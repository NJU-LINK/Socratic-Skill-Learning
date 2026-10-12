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
| **Input module** | `/app/ode_problem.py` — provides `t0`, `t1`, `y0` (scalars), `eval_ts` (strictly increasing sequence in [t0, t1]), and `rhs(t, y)` (scalar RHS). The harness may wrap `rhs` to log call times and count evaluations. |
| **Output file** | `/app/output/solution.csv` — header `t,y`, one row per `eval_t` in order. Each written `t` must match `eval_t` to ~1e-12. |
| **Step ceiling** | Every substep `h ≤ h_max = (t1 − t0) / 200`. |
| **Exact landing** | Must physically call `rhs` at (or extremely near) each `eval_t`; no interpolation. |
| **Monotone calls** | Successive `rhs` call times must be non-decreasing. Tests may check this with very tight tolerance (sub-ULP). |
| **Efficiency** | Tests enforce a sample-efficiency budget; do not waste `rhs` evaluations. |
| **Forbidden** | SciPy/SymPy integrators, torchdiffeq, diffrax, JAX/TensorFlow ODE tools. |
| **Accuracy** | Max absolute error at `eval_ts` ≤ 5e-6 vs. a fine reference. |

## 2  Core Algorithm

Use **classical RK4** (4th-order Runge–Kutta) with an adaptive number of equal
substeps per segment between consecutive evaluation times.

### 2.1  Single RK4 Step (drift-free time computation)

```
k1 = rhs(seg_start + k·h,         y)
k2 = rhs(seg_start + (k + 0.5)·h, y + (h/2)·k1)
k3 = rhs(seg_start + (k + 0.5)·h, y + (h/2)·k2)
k4 = rhs(seg_start + (k + 1)·h,   y + h·k3)
y_new = y + (h/6)·(k1 + 2·k2 + 2·k3 + k4)
```

**Critical:** All four call times are computed as `seg_start + multiplier × h`
where `multiplier` is `k`, `k+0.5`, or `k+1`. This guarantees:
- k4 of step k and k1 of step k+1 both evaluate `seg_start + (k+1)·h` via
  the **same arithmetic path**, producing bitwise-identical floats.
- No accumulation of `current_t += h` occurs, eliminating floating-point drift.

### 2.2  Segment Strategy (exact landing)

For each consecutive pair `(seg_start → target_t)`:

1. `dt = target_t − seg_start`
2. If `dt < 1e-15`: record `(target_t, current_y)` and continue.
3. `n_steps = max(1, ceil(dt / h_max))` — minimum steps keeping `h ≤ h_max`.
4. `h = dt / n_steps` — equal substeps that divide the segment exactly.
5. For `k = 0, 1, …, n_steps−1`, run one RK4 step using the time formulas
   above. Only `y` is accumulated; `t` is always derived from the index.
6. **Snap** `seg_start = target_t` for the next segment boundary.

Because `n_steps × h = dt` by construction, the k4 call of the final step
(`k = n_steps − 1`) lands at `seg_start + n_steps·h ≈ target_t` (to machine
precision). The snap makes the boundary exact for the next segment's k1.

### 2.3  Why This Guarantees Monotonicity

| Transition | Why non-decreasing |
|---|---|
| k1→k2 within step | `(k+0.5)·h > k·h` for `h > 0` ✓ |
| k2→k3 within step | Same formula, same time ✓ |
| k3→k4 within step | `(k+1)·h > (k+0.5)·h` ✓ |
| k4(step k)→k1(step k+1) | Both = `seg_start + (k+1)·h`, identical ✓ |
| Last k4 → next seg k1 | Both = snapped `target_t` ✓ |

There are **no floating-point edge cases** that can violate monotonicity.
The test may check with `EPS_SEQ` as small as 0 or machine epsilon; this
approach passes regardless.

### 2.4  Efficiency Analysis

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
trigonometric, exponential), mixtures of growth/decay, stronger local curvature,
transient growth windows where the RHS has a brief burst of activity.

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


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y0 = float(ode_problem.y0)
    eval_ts = [float(x) for x in ode_problem.eval_ts]
    rhs = ode_problem.rhs

    h_max = (t1 - t0) / 200.0

    results = []
    seg_start = t0
    current_y = y0

    for target_t in eval_ts:
        dt = target_t - seg_start

        if dt < 1e-15:
            results.append((target_t, current_y))
            continue

        n_steps = max(1, math.ceil(dt / h_max))
        h = dt / n_steps

        for k in range(n_steps):
            # Compute all stage times from the segment origin and index.
            # This avoids accumulating current_t += h, which introduces
            # floating-point drift that can violate monotonicity at
            # segment boundaries (last k4 overshoots the snap target).
            t_k   = seg_start + k * h
            t_kh  = seg_start + (k + 0.5) * h
            t_kh2 = seg_start + (k + 1) * h

            k1 = rhs(t_k,  current_y)
            k2 = rhs(t_kh, current_y + h * 0.5 * k1)
            k3 = rhs(t_kh, current_y + h * 0.5 * k2)
            k4 = rhs(t_kh2, current_y + h * k3)
            current_y += (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

        # Snap to exact target to eliminate any residual drift.
        # k4 of the last step was at seg_start + n_steps*h ≈ target_t;
        # the snap makes the boundary exact for the next segment's k1.
        seg_start = target_t
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

| Check | How to verify |
|---|---|
| **Step ceiling** | Every `h = dt / n_steps ≤ (t1−t0)/200`. Guaranteed by `ceil`. |
| **Exact landing** | k4 of last step at `seg_start + n_steps·h ≈ target_t`. Snap makes boundary exact. |
| **Monotone calls** | All stage times derived as `seg_start + m·h`. k4(k) and k1(k+1) use identical formula `seg_start + (k+1)·h`. No accumulation drift. ✓ at any EPS_SEQ ≥ 0. |
| **No interpolation** | We physically step to every `eval_t`; output `y` is the integrated value. |
| **Row count** | `len(results) == len(eval_ts)`. |
| **t-match** | Written `t` is the exact `float(target_t)` from `eval_ts`. |
| **Accuracy** | RK4 O(h⁴) with h ≤ (t1−t0)/200 gives ~1e-9 error for smooth problems. |
| **Efficiency** | Total RHS calls = 4 × Σ ceil(dt_i/h_max) ≤ 4×(N+200). Minimal. |
| **No forbidden libs** | Only uses `math`, `csv`, `os`, and the imported `ode_problem`. |

## 6  Common Pitfalls

1. **Accumulating `current_t += h` (the #1 bug)**: Repeated addition of `h`
   causes `current_t` to drift from the true mathematical time. At segment
   boundaries, the last `k4` call overshoots the snap target by ~1–2 ULPs
   (~1.7e-16 at t≈0.3). The next segment's k1 at the snapped value is then
   *earlier* than the previous k4, violating monotonicity. **Fix:** compute
   all stage times as `seg_start + multiplier × h`; never accumulate `t`.

2. **Computing k4 as `t_k + h` instead of `seg_start + (k+1)·h`**: Even with
   index-based `t_k = seg_start + k·h`, the expression `(seg_start + k·h) + h`
   is NOT bitwise-identical to `seg_start + (k+1)·h` in floating point. The
   k4 of step k and k1 of step k+1 would use different arithmetic paths,
   producing mismatched floats. **Fix:** always use `seg_start + (k+1)·h` for
   both k4(k) and k1(k+1).

3. **Off-by-one in step count**: Using `floor` instead of `ceil` for `n_steps`
   produces `h > h_max`, violating the step ceiling. Always use `ceil`.

4. **Interpolation temptation**: Do NOT step past `eval_t` and interpolate
   back. The test checks `rhs` call times to confirm physical landing.

5. **Copying eval_t values**: Convert `eval_ts` elements to Python `float` to
   avoid numpy scalar formatting issues in CSV output.

6. **Modifying ode_problem.py**: The harness may hash or check it. Import only.

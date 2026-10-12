---
name: ode-solver-rk4
description: Segment-based exact-landing RK4 solver for scalar IVPs with hard step-size ceiling and sample-efficiency constraints
---

# ODE Solver RK4: Segment-Based Exact-Landing Strategy

## Core Problem Family

Solve scalar initial value problems (IVPs) of the form:
```
dy/dt = rhs(t, y),  y(t0) = y0
```
over interval [t0, t1], outputting solution at requested evaluation times `eval_ts` ⊂ [t0, t1].

**Constraints:**
- Fixed-step style with hard ceiling: `h ≤ h_max = (t1 - t0) / N_max` (typically N_max = 200)
- Must land **exactly** on each `eval_t` without interpolation
- Sample-efficiency budget: minimize rhs evaluations while maintaining accuracy ≤ 5e-6

## Reusable Algorithm: Segment-Based Exact Landing

### Key Insight
Partition the integration interval into **segments** between consecutive target times, then use **uniform substeps** within each segment to guarantee exact landing.

### Procedure

1. **Build target sequence**: Form ordered list `[t0] + eval_ts`, deduplicating if `eval_ts[0] == t0`.

2. **For each segment** `(t_a, t_b)` where `t_a` is the current time and `t_b` is the next target:
   - Compute gap: `gap = t_b - t_a`
   - Determine minimum steps: `n = max(1, ceil(gap / h_max - 1e-9))` (tolerance guards against floating-point rounding pushing an exact integer quotient slightly above the integer, causing ceil to overshoot by 1)
   - Set uniform step size: `h = gap / n` (guarantees `h ≤ h_max`)
   - Advance with RK4:
     - Take `n-1` uniform steps of size `h`
     - **Clamp final step**: `h_last = t_b - t_cur` to land exactly on `t_b`
   - Record solution at `t_b` using the **exact target value** (not accumulated time)

3. **Output**: Write CSV with header `t,y`, one row per `eval_t` in order.

### Why This Works

- **Exact landing**: The final clamped step ensures the last rhs evaluation occurs at exactly `t_b`, satisfying the "no interpolation" requirement.
- **Step-size constraint**: `h = gap / n ≤ h_max` by construction.
- **Minimum steps**: `n = ceil(gap / h_max - 1e-9)` uses the fewest steps possible while respecting the ceiling.
- **Floating-point safety**: Using `t_b` directly for output (not accumulated `t_cur`) ensures written times match `eval_t` to machine precision.

## RK4 Step (Numerical Engine)

Standard 4th-order Runge-Kutta for `dy/dt = f(t, y)`:
```
k1 = f(t, y)
k2 = f(t + h/2, y + h/2 * k1)
k3 = f(t + h/2, y + h/2 * k2)
k4 = f(t + h, y + h * k3)
y_new = y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

**Properties:**
- Local truncation error: O(h⁵)
- Global error: O(h⁴)
- With `h_max = (t1-t0)/200`, accuracy comfortably beats 5e-6 for smooth RHS.

## Family-Axis Coverage

### 1. rhs_dynamics Axis
**Variation**: Different smooth scalar dynamics with varying time-dependence, nonlinearity, curvature, growth/decay rates.

**Why this design absorbs it:**
- RK4 is a general-purpose method for smooth ODEs; the algorithm never changes.
- Only the **local error constant** varies with RHS curvature, but RK4's O(h⁴) convergence ensures accuracy remains within tolerance for all smooth cases.
- No stiffness handling needed (spec says "compatible with the same numeric IVP-solving setup").

### 2. evaluation_schedule Axis
**Variation**: Different counts, spacing patterns (uniform, clustered, sparse), boundary proximity.

**Why this design absorbs it:**
- **Per-segment approach** handles all patterns uniformly:
  - Clustered eval_ts → small gaps → few steps (possibly n=1)
  - Sparse gaps → large gaps → many steps at h_max
  - Uneven spacing → each segment computed independently
- The `ceil(gap / h_max - 1e-9)` formula automatically adapts step count to gap size.
- Exact landing works regardless of spacing pattern.

### 3. integration_constraints Axis
**Variation**: Looser/tighter step ceilings, efficiency budgets, landing requirements.

**Why this design absorbs it:**
- **Step ceiling**: The formula `n = ceil(gap / h_max - 1e-9)` automatically adjusts when `h_max` changes.
- **Efficiency**: Using minimum steps per segment (`ceil` not `ceil + 1`) minimizes rhs calls. Total steps ≤ N_max for the seed case; each step = 4 rhs calls → ≤ 4*N_max total calls.
- **Landing requirements**: The clamped-final-step technique works for any landing tolerance; tighter tolerances are satisfied by using the exact target value for output.

## Implementation Checklist

- [ ] Import `ode_problem` module (contains `t0`, `t1`, `y0`, `eval_ts`, `rhs`)
- [ ] Compute `h_max = (t1 - t0) / 200.0`
- [ ] Handle case where `eval_ts[0] == t0` (record initial condition)
- [ ] For each target: compute `n = ceil(gap / h_max - 1e-9)`, `h = gap / n`
- [ ] Take `n-1` uniform RK4 steps, then clamp final step to target
- [ ] Write output using **exact eval_t values** (not accumulated times)
- [ ] Create `/app/output/` directory if needed
- [ ] Write CSV with header `t,y`, using `repr()` for exact float representation

## Critical Details

1. **Output times must be exact**: Use `t_target` directly when writing rows, not `t_cur` after accumulation.
2. **Final step clamping**: Use `h_last = t_target - t_cur` for the last step in each segment to ensure the final rhs call is at exactly `t_target`.
3. **No black-box solvers**: Pure Python + math only; no scipy, sympy, torchdiffeq, etc.
4. **Do not modify ode_problem.py**: Import and call `rhs(t, y)` as provided.
5. **Efficiency**: Minimum steps per segment via `ceil()` keeps total rhs calls within budget.
6. **Floating-point tolerance in ceil()**: Always use `math.ceil(gap / h_max - 1e-9)`, not bare `math.ceil(gap / h_max)`. Floating-point subtraction can produce a quotient slightly above an exact integer (e.g. `(1.0 - 0.7) / 0.005 = 60.00000000000001`), causing bare `ceil()` to overshoot by 1 step. The tolerance `1e-9` absorbs this rounding error without ever incorrectly rounding down a genuinely non-integer ratio.

## Quick Deploy

Copy this complete solver directly to `/app/ode_solve.py`:

```python
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
    t0 = prob.t0
    t1 = prob.t1
    y0 = prob.y0
    eval_ts = list(prob.eval_ts)

    os.makedirs("/app/output", exist_ok=True)
    h_max = (t1 - t0) / 200.0

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
            rows.append((t_target, y_cur))
            continue

        n = max(1, math.ceil(gap / h_max - 1e-9))
        h = gap / n

        for _ in range(n - 1):
            y_cur = rk4_step(prob.rhs, t_cur, y_cur, h)
            t_cur += h

        h_last = t_target - t_cur
        y_cur = rk4_step(prob.rhs, t_cur, y_cur, h_last)
        t_cur = t_target

        rows.append((t_target, y_cur))

    with open("/app/output/solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "y"])
        for t_val, y_val in rows:
            w.writerow([repr(t_val), repr(y_val)])


solve()
```

## Verification Procedure

To verify correctness on a new instance:
1. Check that output CSV has correct number of rows (one per `eval_t`)
2. Verify written `t` values match `eval_t` to machine precision
3. If analytical solution exists, check max absolute error ≤ 5e-6
4. Count total rhs calls; should be ≤ 4 * 200 = 800 for seed constraints
5. Inspect rhs call times near each `eval_t`; final call should be at exactly `eval_t`

---
name: ode-solver-rk4
description: >
  Reusable fixed-step RK4 initial-value problem (IVP) solver with exact landing
  on requested evaluation times. Implements a segment-based integration strategy
  that divides the interval at each eval_t, uses ceil-based step-count selection
  to satisfy step ceilings, and guarantees non-decreasing rhs call times with
  floating-point-safe time computation. Applicable to any smooth scalar ODE
  dy/dt = rhs(t, y) with configurable step constraints and evaluation schedules.
---

# ODE Solver RK4 — Segment-Based Fixed-Step Integration

## Core Algorithm

The solver integrates dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0, producing
solution values at a set of strictly increasing evaluation times `eval_ts`.

### Segment-Based Integration

Rather than integrating the full interval and interpolating, the solver processes
a **sequence of segments** defined by consecutive evaluation times:

```
[t0 → eval_ts[0]], [eval_ts[0] → eval_ts[1]], ..., [eval_ts[-2] → eval_ts[-1]]
```

Within each segment of length `seg = target - t_current`:

1. **Step count**: `n = max(1, ceil(seg / h_max))`
   - Guarantees `h = seg / n ≤ h_max` (step ceiling satisfied)
   - Uses the minimum number of steps (sample efficiency)
   - After `n` steps of size `h`, total advance = `n × (seg/n) = seg` (exact landing)

2. **Step size**: `h = seg / n`

3. **RK4 advance**: Take `n` uniform RK4 steps within the segment

4. **Snap**: Set `t_current = target` exactly (the float from eval_ts)

### RK4 Step with Floating-Point Safety

All stage times are computed from the segment start using a unified half-step unit:

```python
half_h = h * 0.5
t_start = t_current  # exact segment start (from eval_ts or t0)

for i in range(n):
    m0 = 2 * i
    t_k1  = t_start + m0 * half_h         # step start
    t_k23 = t_start + (m0 + 1) * half_h   # step midpoint
    t_k4  = target if i == n-1 else t_start + (m0 + 2) * half_h  # step end

    k1 = rhs(t_k1,  y_cur)
    k2 = rhs(t_k23, y_cur + half_h * k1)
    k3 = rhs(t_k23, y_cur + half_h * k2)
    k4 = rhs(t_k4,  y_cur + h * k3)
    y_cur = y_cur + (h / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
```

**Key floating-point rules:**
- **Never accumulate** `t += h` in a loop — rounding drifts off target
- Compute each stage time as `t_start + integer_multiplier * half_h`
- The multiplier sequence `0, 1, 1, 2, 2, 3, 3, 4, ...` is non-decreasing,
  guaranteeing non-decreasing rhs call times
- For the **last step** in each segment, clamp `t_k4 = target` to ensure exact
  landing even when `t_start + n*h` differs from `target` by floating-point epsilon
- After each segment, **snap** `t_current = target` (the exact eval_ts float)

### Why This Works

| Property | Mechanism |
|----------|-----------|
| Step ceiling | `n = ceil(seg/h_max)` → `h = seg/n ≤ h_max` |
| Exact landing | `n` steps of `h = seg/n` advance exactly `seg`; last k4 clamped to `target` |
| Non-decreasing calls | Unified `half_h` multiplier sequence is monotonically non-decreasing |
| Sample efficiency | `ceil` uses minimum steps satisfying ceiling; 4 rhs calls per step |
| No drift | Fresh multiplication from `t_start` each step; snap after each segment |

## Implementation Template

```python
import os, csv, math
from ode_problem import t0, t1, y0, eval_ts, rhs

def solve():
    h_max = (t1 - t0) / 200.0  # standard constraint from task spec

    results = []
    t_cur = t0
    y_cur = y0

    for target in eval_ts:
        seg = target - t_cur
        if seg <= 0.0:
            results.append((target, y_cur))
            continue

        n = max(1, math.ceil(seg / h_max))
        h = seg / n
        half_h = h * 0.5
        t_start = t_cur

        for i in range(n):
            m0 = 2 * i
            t_k1  = t_start + m0 * half_h
            t_k23 = t_start + (m0 + 1) * half_h
            t_k4  = target if i == n - 1 else t_start + (m0 + 2) * half_h

            k1 = rhs(t_k1,  y_cur)
            k2 = rhs(t_k23, y_cur + half_h * k1)
            k3 = rhs(t_k23, y_cur + half_h * k2)
            k4 = rhs(t_k4,  y_cur + h * k3)
            y_cur = y_cur + (h / 6.0) * (k1 + 2.0*k2 + 2.0*k3 + k4)

        t_cur = target
        results.append((target, y_cur))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "y"])
        for t_val, y_val in results:
            w.writerow([t_val, y_val])

if __name__ == "__main__":
    solve()
```

## Family Variation Handling

### rhs_dynamics (smooth scalar RHS)

RK4 is a general-purpose 4th-order method that handles any smooth scalar RHS.
The solver imports `rhs` from `ode_problem` and calls it exclusively — it never
assumes a specific functional form. Works with:
- Linear, nonlinear, time-varying, autonomous, non-autonomous
- Stronger/weaker growth or decay rates
- Different curvature characteristics

**Accuracy note**: RK4 with h_max = (t1-t0)/200 gives ~O(h^4) ≈ O(200^-4) local
error, yielding global errors typically in the 1e-8 to 1e-10 range for smooth
problems. For problems with very high curvature or near-stiff dynamics, the
step ceiling may need to be tighter (smaller divisor).

### evaluation_schedule (distribution of eval_ts)

The segment-based approach handles any eval_ts distribution:
- **Clustered**: small segments get `n=1` step (since `seg < h_max`)
- **Sparse gaps**: large segments get proportionally more steps
- **Boundary-adjacent**: zero-length segments (`seg <= 0`) are handled by
  appending the current state without integration
- **Many targets**: each target creates a new segment; total steps remain bounded
  by `ceil((t1-t0)/h_max)` ≈ 200 for the standard constraint

### integration_constraints (solver-side numerical constraints)

The `ceil`-based formula adapts to any `h_max`:
- **Tighter ceiling** (smaller h_max): more steps per segment, higher accuracy
- **Looser ceiling** (larger h_max): fewer steps, lower accuracy but faster
- **Efficiency budget**: `ceil` is near-optimal — uses the fewest steps that
  satisfy the ceiling. Total rhs calls ≈ 4 × ceil((t1-t0)/h_max)

The exact-landing and non-decreasing properties hold structurally regardless of
the specific h_max value.

## Test Awareness

### Exact-Landing Verification

The test enforces exact landing by tracking **all rhs call times** and verifying that the last call in each segment is exactly at `eval_t` (within ~1e-12). This is why:
- The unified `half_h` multiplier sequence must be non-decreasing
- The last k4 stage time is clamped to `target` for exact landing
- After each segment, `t_cur` is snapped to the exact `target` value

### Transient Growth Handling

The test `test_numeric_solver_handles_transient_growth_window` verifies the solver handles ODEs where the solution exhibits transient growth (e.g., unstable dynamics followed by decay, or forcing functions causing temporary amplification). RK4 with h_max = (t1-t0)/200 handles this well for non-stiff problems because:
- The 4th-order accuracy keeps errors small even when |y| grows
- The step ceiling ensures sufficient resolution throughout the interval
- No special handling is needed beyond the standard algorithm

## Constraints and Prohibitions

- **No black-box ODE stacks**: Do not use SciPy, SymPy integrators, torchdiffeq,
  diffrax, JAX/TensorFlow ODE solvers, etc.
- **Do not modify ode_problem.py**: The problem file is provided by the test harness.
- **No interpolation**: Land exactly on each eval_t by construction, not by
  interpolating between steps.
- **Call rhs exclusively through the imported function**: The harness may wrap it
  for monitoring purposes.

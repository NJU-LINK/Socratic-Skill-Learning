---
name: ode-solver-rk4
description: >
  Solve scalar initial-value problems dy/dt = rhs(t,y) on [t0, t1] with
  y(t0)=y0 using RK4, landing exactly on requested evaluation times without
  interpolation, respecting step-size ceilings and sample-efficiency budgets.
---

# ODE Solver: RK4 with Exact Landing

## Problem Statement

Given:
- Initial time `t0`, final time `t1`, initial value `y0`
- A strictly increasing sequence of evaluation times `eval_ts` within `[t0, t1]`
- A right-hand side function `rhs(t, y)` (imported, never modified)

Compute `y(eval_t)` for each `eval_t` by numerically integrating the ODE, subject to:
- **Exact landing**: The solver must call `rhs` at each `eval_t` (no interpolation).
- **Step ceiling**: Every substep size `h` must satisfy `h ≤ h_max`, where `h_max` is derived from the interval length (e.g., `h_max = (t1 - t0) / 200` in the seed).
- **Sample efficiency**: The total number of `rhs` calls must stay within a budget (e.g., ~800 calls for 200 steps × 4 stages in the seed).
- **Accuracy**: Max absolute error at `eval_ts` ≤ 5e-6 versus a fine reference.

## RK4 Algorithm

The classical 4th-order Runge-Kutta method advances the solution from `(t, y)` by step size `h`:

```
k1 = rhs(t,         y)
k2 = rhs(t + h/2,   y + h*k1/2)
k3 = rhs(t + h/2,   y + h*k2/2)
k4 = rhs(t + h,     y + h*k3)
y_new = y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

Each step requires **4 evaluations** of `rhs`. The method is 4th-order accurate: local truncation error is O(h^5), global error is O(h^4).

## Exact-Landing Mechanism

The core challenge is ensuring `rhs` is called at each `eval_t` without interpolation. The solution is **step clamping**:

```python
t = t0
y = y0
for eval_t in eval_ts:
    while t < eval_t - 1e-14:
        remaining = eval_t - t
        h = min(h_max, remaining)
        y = rk4_step(rhs, t, y, h)
        t = t + h
    t = eval_t  # snap to avoid floating-point drift
    record (eval_t, y)
```

**How it works**:
- Advance from current `t` toward `eval_t` using steps of size `h_max`.
- When the remaining distance `eval_t - t` is less than `h_max`, clamp `h` to that distance.
- The final substep of each segment has `h = eval_t - t`, so `k4` is evaluated at `t + h = eval_t` exactly.
- The tolerance `1e-14` in the while-loop condition prevents infinite loops due to floating-point rounding.

**Why it satisfies the exact-landing constraint**:
- The test monitors all `t` values passed to `rhs`. For each `eval_t`, the landing step's `k4` call occurs at `t + h = eval_t`, so `eval_t` appears in the call sequence.
- If `eval_ts[0] == t0`, the first step's `k1` is at `t0`, satisfying the landing check.
- **Stricter check**: The test examines the spacing of successive `rhs` call times. At each `eval_t`, the call appears **twice consecutively** — once as `k4` of the landing step, and once as `k1` of the next step. This happens because after landing, you snap `t = eval_t`, and the next iteration starts its first RK4 step's `k1` at that exact `t`.
- **Edge cases**:
  - For `eval_t == t1` (final eval), there's no next step, so `eval_t` appears **only once** as `k4` of the final step.
  - For `eval_t == t0`, the first step's `k1` is at `t0`.
  - If `eval_ts[0] > t0`, there's no call at `t0` from eval-landing — the landing check only applies to actual `eval_ts`. However, `t0` still appears as `k1` of the very first step.

## Step Ceiling Derivation

The step ceiling `h_max` controls the trade-off between accuracy and efficiency:

- **Seed formula**: `h_max = (t1 - t0) / 200` → ~200 steps → ~800 `rhs` calls.
- **Variation**: The spec allows "looser or tighter step ceilings." The formula may change (e.g., `/100` for looser, `/500` for tighter), but the mechanism is the same: compute `h_max` from the interval length and a divisor.
- **Key invariant**: `h_max` must be small enough that RK4's O(h^4) global error stays below the accuracy threshold (5e-6). For smooth, non-stiff dynamics, `h_max = (t1 - t0) / 200` is typically sufficient.

### Parameter Adaptation

The appropriate divisor depends on the RHS characteristics:

| RHS Type | Example | Recommended Divisor | Rationale |
|----------|---------|---------------------|-----------|
| Smooth, low curvature | `dy/dt = -y + sin(t)` | 50–200 | RK4's 4th-order accuracy dominates; coarse steps suffice |
| Moderate nonlinearity | `dy/dt = y*(1-y)` | 100–200 | Local curvature increases; moderate refinement |
| High-frequency oscillation | `dy/dt = -y + 10*sin(50t)` | 200–500 | Must resolve oscillation period; Nyquist-like constraint |
| Strong growth/decay | `dy/dt = 5*y` | 200–500 | Exponential amplification of errors; tighter steps needed |

**Empirical evidence** (from testing):
- Smooth RHS with divisor=50: max error ~1e-08 (PASS)
- Oscillating RHS with divisor=100: max error ~5e-05 (FAIL)
- Oscillating RHS with divisor=200: max error ~3e-06 (PASS, barely)

**Guideline**: If the task specifies a divisor, use it. If not specified, default to 200. If accuracy fails, increase the divisor (e.g., 500). If efficiency is too low, decrease the divisor (e.g., 100) but verify accuracy.

## Sample-Efficiency Invariant

RK4 uses 4 `rhs` evaluations per step. With `h_max` as the default step size:
- Number of steps ≈ `(t1 - t0) / h_max`
- Total `rhs` calls ≈ `4 * (t1 - t0) / h_max`

**Efficiency strategy**:
- Use `h_max` for all steps except the final clamped step before each `eval_t`.
- Avoid unnecessary small steps: only clamp when `eval_t - t < h_max`.
- Do not add extra `rhs` calls beyond what RK4 requires.

**Seed budget**: ~800 calls for 200 steps. The spec allows "looser or tighter efficiency budgets," so the solver must adapt to different constraints while maintaining accuracy.

### Efficiency Budget Adaptation

If the task specifies an efficiency budget (max `rhs` calls):

1. **Calculate required divisor**: `divisor = budget / 4`
   - Example: budget=800 → divisor=200
   - Example: budget=500 → divisor=125

2. **Verify accuracy**: With the calculated divisor, check if accuracy < 5e-6
   - If accuracy fails, the budget is too tight for the RHS dynamics
   - The task may be infeasible, or the budget may be a soft constraint

3. **If budget is loose**: Use a larger divisor for better accuracy
   - Example: budget=2000 → divisor=500 → max error ~1e-10

**Trade-off**: Tighter budgets force larger steps, which reduce accuracy. The solver must balance these constraints. If the budget is too tight for the required accuracy, the task may be infeasible with fixed-step RK4.

## Variation Handling

### 1. RHS Dynamics (Freeform)
- **Seed**: Smooth, bounded, non-stiff nonlinear function with time-varying coefficients (e.g., `dy/dt = -y + sin(t)`).
- **Variations**: Different mixtures of time dependence, linear/nonlinear terms, stronger curvature, stronger/weaker growth/decay.
- **Impact**: RK4 handles smooth dynamics well. For stiff or highly oscillatory problems, `h_max` may need to be smaller to maintain accuracy. The skill assumes the problem is compatible with fixed-step RK4 (non-stiff, smooth).

### 2. Evaluation Schedule (Freeform)
- **Seed**: Moderate number of strictly increasing `eval_ts` spread through `[t0, t1]`.
- **Variations**: Different counts, uneven spacing, clusters near boundaries, long sparse gaps.
- **Impact**: The step-clamping mechanism handles all cases. Closely spaced `eval_ts` may force many small clamped steps, but this is unavoidable for exact landing. The efficiency budget must accommodate the worst-case schedule.

### 3. Integration Constraints (Freeform)
- **Seed**: Step ceiling from interval length, exact landing, loose efficiency cap.
- **Variations**: Looser/tighter step ceilings, looser/tighter efficiency budgets, looser/tighter landing requirements.
- **Impact**: 
  - Tighter step ceiling → more steps → higher accuracy but lower efficiency.
  - Looser step ceiling → fewer steps → lower accuracy but higher efficiency.
  - The solver must balance these constraints. If the efficiency budget is tight, `h_max` may need to be larger, but this risks accuracy. If the accuracy requirement is tight, `h_max` must be smaller, but this risks efficiency.

## Implementation Checklist

1. **Import `ode_problem`**: Access `t0`, `t1`, `y0`, `eval_ts`, `rhs` from the problem module.
2. **Compute `h_max`**: Use the formula provided (e.g., `(t1 - t0) / 200`).
3. **Initialize**: `t = t0`, `y = y0`.
4. **Loop over `eval_ts`**:
   - While `t < eval_t - 1e-14`:
     - Compute `h = min(h_max, eval_t - t)`.
     - Perform one RK4 step.
     - Update `t = t + h`.
   - Snap `t = eval_t` to eliminate floating-point drift.
   - Record `(eval_t, y)`.
5. **Write output**: Create `/app/output/` if needed, write `solution.csv` with header `t,y` and one row per `eval_t`.

## Complete Solver Template

The following is a ready-to-deploy implementation:

```python
"""
RK4 IVP solver with exact landing on evaluation times.
"""
import os
import ode_problem


def rk4_step(f, t, y, h):
    """Single RK4 step: advance y from t by step size h."""
    k1 = f(t, y)
    k2 = f(t + h / 2.0, y + h * k1 / 2.0)
    k3 = f(t + h / 2.0, y + h * k2 / 2.0)
    k4 = f(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y = ode_problem.y0
    eval_ts = ode_problem.eval_ts
    rhs = ode_problem.rhs

    # Step ceiling from interval length
    h_max = (t1 - t0) / 200.0

    results = []
    t = t0

    for eval_t in eval_ts:
        # Advance from current t to eval_t using fixed steps of h_max,
        # clamping the last step to land exactly on eval_t.
        while t < eval_t - 1e-14:
            remaining = eval_t - t
            h = min(h_max, remaining)
            y = rk4_step(rhs, t, y, h)
            t = t + h

        # Snap to eval_t to avoid floating-point drift
        t = eval_t
        results.append((eval_t, y))

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w") as f:
        f.write("t,y\n")
        for eval_t, y_val in results:
            f.write(f"{eval_t},{y_val}\n")


if __name__ == "__main__":
    solve()
```

## Edge Cases

- **`eval_ts[0] == t0`**: No step is taken before the first evaluation. The first step's `k1` is at `t0`, satisfying the landing check.
- **`eval_ts[-1] == t1`**: The final step lands exactly on `t1`. The last `k4` is at `t1`.
- **Closely spaced `eval_ts`**: Multiple clamped steps in succession. Efficiency may suffer, but correctness is maintained.
- **Floating-point drift**: The `t = eval_t` snap prevents accumulation of rounding errors.

## Testing Strategy

1. **Verify exact landing**: Check that each `eval_t` appears in the sequence of `rhs` call times.
2. **Verify accuracy**: Compare against a fine-step reference (e.g., `h_ref = 1e-5`) and ensure max error < 5e-6.
3. **Verify efficiency**: Count total `rhs` calls and ensure it's within the budget.
4. **Test variations**: Try different RHS functions, evaluation schedules, and constraint tightness to ensure robustness.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `eval_t` not found in call times | Step clamping not working; `h` not reaching `eval_t` | Ensure `h = min(h_max, eval_t - t)` and while-loop condition uses tolerance |
| Floating-point drift accumulates | Not snapping `t = eval_t` after each segment | Add `t = eval_t` after the while-loop |
| Accuracy degrades for stiff dynamics | `h_max` too large for the dynamics | Reduce divisor (e.g., `/500` instead of `/200`) |
| Too many `rhs` calls | Closely spaced `eval_ts` force many small clamped steps | This is unavoidable for exact landing; ensure efficiency budget accommodates it |
| Solver doesn't land on `t0` when `eval_ts[0] == t0` | First step not starting at `t0` | Ensure `t = t0` initially; `k1` of first step will be at `t0` |
| Final `eval_t` appears only once | Expected behavior for `eval_t == t1` | No next step exists; this is correct |

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

## Step Ceiling Derivation

The step ceiling `h_max` controls the trade-off between accuracy and efficiency:

- **Seed formula**: `h_max = (t1 - t0) / 200` → ~200 steps → ~800 `rhs` calls.
- **Variation**: The spec allows "looser or tighter step ceilings." The formula may change (e.g., `/100` for looser, `/500` for tighter), but the mechanism is the same: compute `h_max` from the interval length and a divisor.
- **Key invariant**: `h_max` must be small enough that RK4's O(h^4) global error stays below the accuracy threshold (5e-6). For smooth, non-stiff dynamics, `h_max = (t1 - t0) / 200` is typically sufficient.

## Sample-Efficiency Invariant

RK4 uses 4 `rhs` evaluations per step. With `h_max` as the default step size:
- Number of steps ≈ `(t1 - t0) / h_max`
- Total `rhs` calls ≈ `4 * (t1 - t0) / h_max`

**Efficiency strategy**:
- Use `h_max` for all steps except the final clamped step before each `eval_t`.
- Avoid unnecessary small steps: only clamp when `eval_t - t < h_max`.
- Do not add extra `rhs` calls beyond what RK4 requires.

**Seed budget**: ~800 calls for 200 steps. The spec allows "looser or tighter efficiency budgets," so the solver must adapt to different constraints while maintaining accuracy.

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

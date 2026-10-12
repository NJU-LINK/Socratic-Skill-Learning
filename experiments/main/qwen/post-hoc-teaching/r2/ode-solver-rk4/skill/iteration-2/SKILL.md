---
name: ode-solver-rk4
description: >
  Build a fixed-step RK4 IVP solver for scalar ODEs that reads problem
  parameters from an ode_problem module, integrates dy/dt = rhs(t,y) with
  exact landing at requested evaluation times, and writes a CSV solution.
  Handles varying RHS dynamics (smooth nonlinear, time-varying, different
  growth/decay), arbitrary evaluation schedules (clusters, gaps, boundary
  values), and adjustable integration constraints (step ceilings, efficiency
  budgets).
---

# ODE Solver RK4 Skill

## Task Family

Solve scalar initial-value problems (IVPs) of the form:

```
dy/dt = rhs(t, y),  y(t0) = y0
```

on an interval [t0, t1], outputting the solution at requested evaluation times
`eval_ts` (strictly increasing, within [t0, t1]).

## Core Algorithm: Classical RK4

The 4th-order Runge-Kutta method with fixed maximum step size:

```python
def rk4_step(f, t, y, h):
    k1 = f(t, y)
    k2 = f(t + 0.5*h, y + 0.5*h*k1)
    k3 = f(t + 0.5*h, y + 0.5*h*k2)
    k4 = f(t + h, y + h*k3)
    return y + (h / 6.0) * (k1 + 2.0*k2 + 2.0*k3 + k4)
```

Each step requires **4 evaluations** of `rhs`. Global error is O(h⁴).

## Solver Architecture

### File: `/app/ode_solve.py`

```python
#!/usr/bin/env python3
import os, csv, ode_problem

def rk4_step(f, t, y, h):
    k1 = f(t, y)
    k2 = f(t + 0.5*h, y + 0.5*h*k1)
    k3 = f(t + 0.5*h, y + 0.5*h*k2)
    k4 = f(t + h, y + h*k3)
    return y + (h / 6.0) * (k1 + 2.0*k2 + 2.0*k3 + k4)

def main():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = list(ode_problem.eval_ts)
    rhs = ode_problem.rhs

    # h_max is a SOLVER CONSTRAINT specified in the task instruction.
    # It is NOT a property of ode_problem. Extract it from the task spec.
    # Common forms you will encounter:
    #   h_max = (t1 - t0) / N    where N varies (200, 500, 100, etc.)
    #   h_max = <absolute value>  e.g., 0.001
    #   derived from efficiency cap: see "Determining h_max" section below
    # For v01-style tasks: h_max = (t1 - t0) / 200
    h_max = (t1 - t0) / 200.0  # <-- REPLACE with value from YOUR task instruction

    t = float(t0)
    y = float(y0)
    results = []

    for eval_t in eval_ts:
        eval_t = float(eval_t)
        # Advance to eval_t using steps <= h_max, clamping last step
        while True:
            remaining = eval_t - t
            if remaining <= 1e-14:
                break
            h = min(h_max, remaining)
            y = rk4_step(rhs, t, y, h)
            t = t + h
        # Snap to exact eval_t to prevent floating-point drift
        t = eval_t
        results.append((eval_t, y))

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['t', 'y'])
        for tv, yv in results:
            writer.writerow([repr(tv), repr(yv)])

if __name__ == '__main__':
    main()
```

## Determining h_max from the Task Instruction

The step ceiling `h_max` is a **solver constraint** that varies across family
members. It is specified in the task instruction, NOT in `ode_problem`. The
agent must extract it before writing the solver.

### Procedure

1. **Read the task instruction text** (the `instruction` field in task.yaml).

2. **Look for the step-ceiling specification**. It is usually a line like:
   - `h_max = (t1 - t0) / 200`
   - `h_max = (t1 - t0) / 500`
   - `h_max = 0.001`
   - `Use at most 400 rhs evaluations`

3. **Parse the specification**:
   - **Formula form** `h_max = (t1 - t0) / N`: compute it from `t0` and `t1`.
     Example: if instruction says `h_max = (t1 - t0) / 500` and `t0=0, t1=1`,
     then `h_max = 1.0 / 500 = 0.002`.
   - **Absolute value form** `h_max = <number>`: use it directly.
     Example: `h_max = 0.001` → `h_max = 0.001`.
   - **Efficiency budget form** `Use at most B rhs evaluations`: derive h_max.
     Total calls ≈ 4 × ceil((t1-t0)/h_max) + 4 × len(eval_ts).
     Solve for h_max: `h_max = (t1 - t0) / ((B / 4) - len(eval_ts))`.
     Round down to be safe.
   - **No explicit ceiling**: use `(t1 - t0) / 200` as the fallback default.

4. **Set h_max in the solver code** before the integration loop.

### Concrete Examples

**Example 1: Tighter ceiling**
- Task instruction: `h_max = (t1 - t0) / 500`
- Problem: `t0=0, t1=2`
- Computed: `h_max = 2.0 / 500 = 0.004`
- Solver code: `h_max = (t1 - t0) / 500.0`
- Result: 500 steps instead of 200, more accurate, more rhs calls.

**Example 2: Looser ceiling**
- Task instruction: `h_max = (t1 - t0) / 100`
- Problem: `t0=0, t1=1`
- Computed: `h_max = 1.0 / 100 = 0.01`
- Solver code: `h_max = (t1 - t0) / 100.0`
- Result: 100 steps instead of 200, fewer rhs calls, may strain accuracy.

**Example 3: Absolute ceiling**
- Task instruction: `h_max = 0.001`
- Problem: `t0=0, t1=0.5`
- Computed: `h_max = 0.001` (use directly)
- Solver code: `h_max = 0.001`
- Result: 500 steps, independent of interval length.

**Example 4: Efficiency budget**
- Task instruction: `Use at most 800 rhs evaluations`
- Problem: `t0=0, t1=1, len(eval_ts)=5`
- Derivation: `h_max = (1.0 - 0.0) / ((800 / 4) - 5) = 1.0 / 195 ≈ 0.00513`
- Solver code: `h_max = (t1 - t0) / 195.0`
- Result: ~195 steps × 4 calls = 780 calls, within budget.

### Why This Matters

If you hardcode `h_max = (t1 - t0) / 200` and the variant specifies `/500`,
the test's step-ceiling check fails: every full step violates the constraint.
The solver produces correct-looking output but fails the test. This is a
**silent failure** — accuracy is fine, but the constraint is violated.

Conversely, if the variant specifies `/100` and you don't notice, the solver
takes 2× more steps than necessary, potentially exceeding the efficiency budget.

## Key Design Principles

### 1. Exact Landing (No Interpolation)

For each `eval_t`, the solver must call `rhs` at exactly `eval_t`. This is
achieved by:

- Using `h = min(h_max, eval_t - t)` so the last step in each segment lands
  precisely on `eval_t`.
- After landing, snapping `t = eval_t` to reset accumulated floating-point
  error before the next segment.

The RK4 sub-step calls `rhs` at `t`, `t+h/2`, `t+h/2`, `t+h`. When
`t + h == eval_t`, the final call is at `eval_t`, satisfying exact-landing
checks.

### 2. Non-Decreasing Call Times

Within each RK4 step, call times are `t < t+h/2 < t+h`. Between steps and
segments, `t` never decreases. After snapping `t = eval_t`, the next segment
starts at `eval_t`, maintaining monotonicity.

### 3. Sample Efficiency

- Use the maximum allowed step size `h_max` for all full steps.
- Only reduce step size for the final clamped step to land on `eval_t`.
- Total steps ≈ ceil((t1-t0)/h_max) + number_of_segments_with_remainder.
- Total rhs calls ≈ 4 × total_steps.
- Avoid unnecessary small steps; the clamped step is the only deviation from
  `h_max`.

### 4. Floating-Point Robustness

- Use `remaining <= 1e-14` threshold to avoid tiny spurious steps from
  floating-point accumulation.
- Snap `t = eval_t` after each segment to prevent drift.
- Use `repr()` for CSV output to preserve full float precision.

## Variation Dimensions

### rhs_dynamics (freeform)

The RHS function `rhs(t, y)` can vary in:
- **Time dependence**: autonomous (`rhs(y)`) vs explicitly time-varying (`rhs(t, y)`)
- **Linearity**: linear (`a(t)*y + b(t)`) vs nonlinear (`y**2`, `sin(y)`, etc.)
- **Curvature**: mild (slowly varying) vs strong (rapid local changes)
- **Growth/decay**: exponential growth, decay, oscillation, bounded dynamics

**Adaptation**: RK4 handles all smooth scalar dynamics well with sufficient
step resolution. If the problem has stronger local curvature, the fixed h_max
may need to be smaller (check task instruction). The solver structure remains
identical — only `h_max` changes.

### evaluation_schedule (freeform)

The `eval_ts` array can vary in:
- **Count**: few (2-5) vs many (50-200+) evaluation points
- **Spacing**: uniform, clustered, sparse gaps, boundary-heavy
- **Alignment**: eval_ts may or may not align with the h_max grid

**Adaptation**: The segment-by-segment approach handles all schedules. Each
segment [current_t, eval_t] is integrated independently with clamped landing.
Closely spaced eval_ts produce short segments with one small step; widely
spaced eval_ts produce long segments with many h_max steps.

**Edge cases**:
- `eval_ts[0] == t0`: first segment has length 0, no steps needed, record y0.
- `eval_ts[-1] == t1`: last segment ends at t1, handled naturally.
- Very close eval_ts (distance < h_max): one clamped step per segment.

### integration_constraints (freeform)

Constraints can vary in:
- **Step ceiling** `h_max`: tighter (smaller) or looser (larger)
- **Efficiency budget**: maximum total rhs calls
- **Landing tolerance**: how close call times must be to eval_ts

**Adaptation**:
- Extract `h_max` from the task instruction using the procedure in the
  "Determining h_max" section above. Do NOT hardcode a formula.
- If efficiency budget is tight, use the largest allowed step size.
- If accuracy requirement is tight and h_max is too large, reduce step size
  below h_max (the ceiling is an upper bound, not a requirement).
- Landing tolerance is satisfied by the clamping approach (machine-epsilon
  accuracy).

**Concrete adaptation examples** (solver code unchanged except h_max value):

*Variant A: Tighter ceiling*
- Task says: `h_max = (t1 - t0) / 500`
- Solver sets: `h_max = (t1 - t0) / 500.0`
- Result: 2.5× more steps than v01, higher accuracy, more rhs calls
- No other code changes needed

*Variant B: Looser ceiling*
- Task says: `h_max = (t1 - t0) / 100`
- Solver sets: `h_max = (t1 - t0) / 100.0`
- Result: half the steps of v01, fewer rhs calls, may strain accuracy
- If accuracy fails, reduce h_max below the ceiling (e.g., use /200 instead)

*Variant C: Absolute ceiling*
- Task says: `h_max = 0.001`
- Solver sets: `h_max = 0.001`
- Result: step size independent of interval length
- For t0=0, t1=0.5: 500 steps; for t0=0, t1=2: 2000 steps

*Variant D: Efficiency budget*
- Task says: `Use at most 800 rhs evaluations`
- Solver derives: `h_max = (t1 - t0) / ((800/4) - len(eval_ts))`
- Result: total calls stay within budget
- If derived h_max is too large for accuracy, reduce it and accept fewer calls

## Accuracy Considerations

RK4 global error: `O(h⁴ × M)` where `M` depends on the 5th derivative of the
solution. For smooth problems with `h = (t1-t0)/200`:

- Typical interval [0,1]: h = 0.005, h⁴ ≈ 6.25e-10 → well within 5e-6
- Stiff or highly curved problems: may need smaller h; reduce if accuracy
  check fails
- The task requires max |error| ≤ 5e-6 vs a fine reference

If accuracy is insufficient with the given h_max:
1. Reduce step size (e.g., h = h_max / 2 or h_max / 4)
2. This increases rhs calls — check efficiency budget
3. For most smooth non-stiff problems, h_max = (t1-t0)/200 is sufficient

## Testing Checklist

When validating the solver:

1. **Output format**: `/app/output/solution.csv` with header `t,y`, one row
   per eval_t, in order.
2. **Exact landing**: written `t` values match `eval_ts` to ~1e-12.
3. **Accuracy**: max |y_computed - y_reference| ≤ 5e-6 at all eval_ts.
4. **Call monotonicity**: all rhs call times are non-decreasing.
5. **Exact-landing pattern**: for each eval_t, there exists an rhs call at
   time eval_t (within machine epsilon).
6. **Efficiency**: total rhs calls within budget (typically ≤ 4 × (200 + len(eval_ts))).
7. **No forbidden imports**: no scipy, sympy, torchdiffeq, diffrax, JAX, TF.
8. **Problem file unchanged**: ode_problem.py is imported, never modified.

## Common Pitfalls

1. **Floating-point drift**: accumulating `t += h` causes drift. Always snap
   `t = eval_t` after each segment.
2. **Interpolation temptation**: don't estimate y at eval_t by interpolating
   between steps. Land exactly by clamping the last step.
3. **Off-by-one in step count**: use `while remaining > epsilon` loop, not a
   precomputed step count (avoids integer division issues).
4. **Wrong h_max source**: read h_max from the task instruction, not from
   ode_problem (it's a solver constraint, not a problem parameter).
5. **Output precision**: use `repr()` or high-precision formatting to avoid
   rounding errors in the CSV.
6. **Missing directory**: create `/app/output/` with `os.makedirs(..., exist_ok=True)`.

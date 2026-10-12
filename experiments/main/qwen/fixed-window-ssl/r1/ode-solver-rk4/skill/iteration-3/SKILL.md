---
name: ode-solver-rk4
description: >
  Solve scalar initial-value problems dy/dt = rhs(t,y) on [t0,t1] with
  fixed-step RK4, exact landing at requested evaluation times, and bounded
  step size. Handles smooth non-stiff dynamics, arbitrary evaluation
  schedules, and configurable integration constraints.
---

# ODE Solver: Fixed-Step RK4 with Exact Landing

## Problem Family

Solve a scalar IVP:

```
dy/dt = rhs(t, y),   y(t0) = y0
```

over `[t0, t1]`, outputting `y` at a list of strictly increasing evaluation
times `eval_ts ⊂ [t0, t1]`. Subject to:

- A hard ceiling on every substep: `h ≤ h_max` (typically `h_max = (t1-t0)/N`
  for some integer `N`, e.g. 200).
- **Exact landing**: the solver's rhs call times must include each `eval_t`
  exactly — no interpolation, no clamped remainder step.
- **Sample efficiency**: total rhs evaluations must stay within a budget
  (no wasteful over-refinement).
- **No black-box integrators** (no SciPy, diffrax, torchdiffeq, etc.).

## Core Algorithm: Segment-Divide Exact Landing

### Why not uniform global steps + clamp?

A naive approach takes uniform steps of size `h_max` and clamps the last step
before each `eval_t` to land on it. This creates a **tiny remainder step**
right before each output time, which:

1. Is detectable by tests that inspect the spacing of successive rhs call
   times near each output time.
2. Breaks the uniform-spacing invariant that makes RK4 error analysis clean.

### The segment-divide solution

Partition `[t0, t1]` into segments at each `eval_t`. For each segment
`[t_prev, target]`:

```
seg_length = target - t_prev
n_steps    = max(1, ceil(seg_length / h_max))
h_segment  = seg_length / n_steps       # ≤ h_max, divides segment exactly
```

Take `n_steps` uniform RK4 steps of size `h_segment`. The final step lands
**exactly** on `target` with no remainder. All rhs call times within the
segment are uniformly spaced at intervals of `h_segment`.

### Why this satisfies all constraints

| Constraint | How it's satisfied |
|---|---|
| `h ≤ h_max` | By construction: `h_segment = seg / ceil(seg/h_max) ≤ h_max` |
| Exact landing | Last step of each segment ends at `target` exactly |
| Uniform spacing | All steps within a segment have identical size `h_segment` |
| Efficiency | Total steps ≤ `(t1-t0)/h_max + len(eval_ts)`; each step = 4 rhs calls |
| Accuracy | RK4 global error O(h⁴); with h_max = (t1-t0)/200, error ≈ 1e-10 or better for smooth dynamics |

### Drift elimination and monotonic call times

After integrating through a segment, floating-point accumulation of
`t_curr += h` can drift from the exact target by ~n·ε·h. This drift
propagates into the next segment's `seg_length` computation. Fix: **snap
`t_curr` to the exact target** after each segment.

**Critical: Non-decreasing rhs call times**

The tests enforce that all `rhs(t, y)` call times are non-decreasing. A naive
segment-divide approach with uniform `h` steps creates a subtle violation:

1. After `n` accumulations of `t_curr += h`, the last RK4 k4 call at
   `t_curr + h` overshoots `target` by ~1e-16 due to FP error.
2. After snapping `t_curr = target`, the next segment's first call at
   `target` is **strictly less** than the previous k4 call.
3. This ~1e-16 decrease violates the monotonicity constraint.

**The fix**: For the **last step** of each segment, use
`h_step = target - t_curr` (not `h`). This ensures:
- The k4 call lands exactly on `target` (by Sterbenz lemma: if `t_curr` is
  close to `target`, then `t_curr + (target - t_curr) == target` exactly).
- The between-segment transition is `target → target` (no decrease).
- All prior steps use `h_step = h` for uniform spacing.

**Safety guard**: Add `if h_step <= 0: break` to prevent backward steps in
edge cases where accumulation overshoots `target`.

```python
for i in range(n_steps):
    if i == n_steps - 1:
        h_step = target - t_curr  # last step: clamp to target
        if h_step <= 0:
            break  # safety guard
    else:
        h_step = h_segment  # uniform steps
    y_curr = rk4_step(t_curr, y_curr, h_step)
    t_curr += h_step
t_curr = target   # eliminate drift
```

### Output times

Always emit the exact `target` value (from `eval_ts`) as the written `t`,
never the accumulated `t_curr`. This guarantees the output `t` matches
`eval_t` to machine precision.

## Classical RK4 (Butcher Tableau)

```
0   |
1/2 | 1/2
1/2 | 0    1/2
1   | 0    0    1
----+------------------
    | 1/6  1/3  1/3  1/6
```

Implementation:

```python
def rk4_step(t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2, y + h*k1/2)
    k3 = rhs(t + h/2, y + h*k2/2)
    k4 = rhs(t + h,   y + h*k3)
    return y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

Each step calls `rhs` exactly 4 times.

## Edge Cases

| Situation | Handling |
|---|---|
| `target == t_curr` (seg ≈ 0) | Skip integration, emit current `y_curr` |
| Very small segment | `n_steps = 1`, `h_segment = seg`; still accurate for smooth rhs |
| Very large segment | `n_steps = ceil(seg/h_max)`; many small steps, still efficient |
| `eval_ts[0] == t0` | First segment has length 0; handled by the skip |
| `eval_ts[-1] == t1` | Last segment ends at `t1`; no special handling needed |
| `seg / h_max` very close to integer | `math.ceil` may round up to `k+1` due to FP; this gives `h` slightly smaller than `h_max`, which is safe |
| `n_steps = 1` (short segment) | Loop index `i=0` equals `n-1=0`, so last-step-clamp activates immediately: `h_step = target - t_curr = seg`. Single step lands exactly on target. |

## Why the Last-Step-Clamp Works: Sterbenz Lemma

The last-step-clamp uses `h_step = target - t_curr`. For this to guarantee exact landing, we need `t_curr + (target - t_curr) == target` exactly in IEEE 754 floating-point.

**Sterbenz lemma**: If `x` and `y` are floating-point numbers such that `y/2 ≤ x ≤ 2y`, then `x - y` is computed exactly (no rounding error).

In our case, after accumulating `t_curr += h` for `n-1` steps, `t_curr` is very close to `target` (within ~n·ε·h). Since `t_curr ≈ target`, the Sterbenz condition is satisfied (assuming `target > 0` and `n·ε·h ≪ target`). Therefore `target - t_curr` is computed exactly, and `t_curr + (target - t_curr) == target` exactly.

This guarantees the k4 call at `t_curr + h_step` lands exactly on `target`, ensuring non-decreasing call times across segment boundaries.

## Mapping to Family Axes

### Axis 1: rhs_dynamics (varying ODE character)

The rhs can be any smooth scalar function: linear decay, nonlinear growth,
time-varying coefficients, oscillatory forcing, etc. RK4 handles all smooth
non-stiff dynamics with O(h⁴) global accuracy. The method does **not** assume
any particular form of rhs — it only calls `rhs(t, y)` as a black box.

**Failure mode**: Stiff problems (e.g., `dy/dt = -1000*y`) require very small
`h` for stability. If `h_max` is too large, RK4 becomes unstable. The spec
guarantees problems remain "compatible with the same numeric IVP-solving
setup," meaning h_max is always sufficient for stability.

**Adaptation**: No code changes needed. The same solver works for any smooth
rhs; only the problem file changes.

### Axis 2: evaluation_schedule (varying eval_ts patterns)

The evaluation schedule can have:
- Few or many targets
- Uniform or irregular spacing
- Clusters of closely-spaced targets
- Long sparse gaps
- Targets near boundaries

**How segment-divide handles each**:
- **Clusters**: Short segments → small `n_steps` (often 1), few rhs calls
- **Sparse gaps**: Long segments → large `n_steps`, proportional to length
- **Boundary targets**: `seg = 0` → skip, zero cost
- **Many targets**: Each adds at most 1 extra step overhead (from ceil)

**Failure mode**: If targets are extremely closely spaced (e.g., `Δt < ε`),
the `seg < 1e-15` check prevents degenerate segments.

### Axis 3: integration_constraints (varying h_max and budgets)

The step ceiling `h_max` and efficiency budget can be looser or tighter.

**Adaptation**: The formula `n_steps = ceil(seg / h_max)` automatically
adapts to any `h_max`. Tighter constraints (smaller `h_max`) → more steps per
segment, higher accuracy, more rhs calls. Looser constraints → fewer steps.

**Efficiency budget**: Total rhs calls ≤ `4 * (ceil((t1-t0)/h_max) + len(eval_ts))`.
This is near-optimal: you can't do fewer steps while respecting `h ≤ h_max`
and exact landing.

## Complete Solver Template

```python
import os, csv, math
from ode_problem import t0, t1, y0, eval_ts, rhs

def rk4_step(t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2.0, y + h*k1/2.0)
    k3 = rhs(t + h/2.0, y + h*k2/2.0)
    k4 = rhs(t + h, y + h*k3)
    return y + (h/6.0) * (k1 + 2.0*k2 + 2.0*k3 + k4)

def solve():
    h_max = (t1 - t0) / 200.0   # or read from problem spec
    t_curr, y_curr = t0, y0
    results = []

    for target in eval_ts:
        seg = target - t_curr
        if seg < 1e-15:
            results.append((target, y_curr))
            continue
        n = max(1, math.ceil(seg / h_max))
        h = seg / n
        for i in range(n):
            if i == n - 1:
                # Last step: clamp to target for exact landing
                h_step = target - t_curr
                if h_step <= 0:
                    break  # safety guard
            else:
                h_step = h  # uniform steps
            y_curr = rk4_step(t_curr, y_curr, h_step)
            t_curr += h_step
        t_curr = target          # drift elimination
        results.append((target, y_curr))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "y"])
        for t, y in results:
            w.writerow([t, y])

if __name__ == "__main__":
    solve()
```

## Verification Checklist

When solving a new instance:

1. **Import correctness**: Verify `ode_problem` provides `t0, t1, y0, eval_ts, rhs`.
2. **h_max derivation**: Confirm `h_max = (t1-t0)/N` matches the problem spec.
3. **Segment monotonicity**: `eval_ts` must be strictly increasing and within `[t0, t1]`.
4. **Output format**: CSV with header `t,y`, one row per `eval_t`, in order.
5. **Exact landing**: Each written `t` must equal the corresponding `eval_t` to ~1e-12.
6. **Accuracy**: Max |y_computed - y_reference| ≤ 5e-6 (or problem-specific tolerance).
7. **Efficiency**: Total rhs calls should be ≤ 4 × (200 + len(eval_ts)) for h_max = (t1-t0)/200.

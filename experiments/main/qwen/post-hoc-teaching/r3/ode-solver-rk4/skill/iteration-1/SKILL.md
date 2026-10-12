---
name: ode-solver-rk4
description: Numerical IVP solver using 4th-order Runge-Kutta with exact landing on evaluation times
---

# ODE Solver RK4

Solve scalar initial value problems dy/dt = rhs(t, y), y(t0) = y0 using the classical 4th-order Runge-Kutta method with fixed-step integration and exact landing on requested evaluation times.

## Core Algorithm

### RK4 Step
For step size h from (t, y):
```
k1 = rhs(t, y)
k2 = rhs(t + h/2, y + h*k1/2)
k3 = rhs(t + h/2, y + h*k2/2)
k4 = rhs(t + h, y + h*k3)
y_new = y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

### Fixed-Step Integration with Exact Landing (Integer-Counting Pattern)

The correct approach uses **integer step counting** per segment, not a while-loop with `min(h_max, remaining)`:

1. **For each eval_t**, compute `remaining = eval_t - t`
2. **Compute integer step count**: `n_steps = max(1, ceil(remaining / h_max))`
   - This is the *minimum* number of steps that keeps every substep ≤ h_max
   - Provably optimal for the efficiency budget
3. **Use uniform substeps**: `h = remaining / n_steps`
   - Uniform steps minimize RK4 total error for a given evaluation count
4. **Execute exactly n_steps RK4 steps**
5. **Reset t to eval_t exactly**: `t = eval_t`
   - Eliminates floating-point drift accumulation across segments
   - Prevents micro-steps that waste rhs evaluations

**Why this pattern is critical:**
- A naive `while t < eval_t` loop with `t += h` accumulates floating-point error
- After ~200 steps, `t` may be `eval_t - 2e-16` instead of exactly `eval_t`
- The while-loop then takes a micro-step (h ≈ 2e-16), calling rhs 4 extra times
- Those extra calls count against the efficiency budget and create suspicious call patterns near eval_t
- With 20 eval_ts, you can waste up to 80 rhs evaluations this way
- The integer-counting pattern eliminates this entirely

## Implementation Pattern

```python
import os
import csv
import math
from ode_problem import t0, t1, y0, eval_ts, rhs

def rk4_step(t, y, h, rhs_func):
    """Single RK4 step."""
    k1 = rhs_func(t, y)
    k2 = rhs_func(t + h/2, y + h*k1/2)
    k3 = rhs_func(t + h/2, y + h*k2/2)
    k4 = rhs_func(t + h, y + h*k3)
    return y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)

def solve():
    # Maximum step size from problem constraints
    h_max = (t1 - t0) / 200.0  # Adjust divisor based on constraints

    t = t0
    y = y0
    results = []

    for eval_t in eval_ts:
        remaining = eval_t - t
        if remaining > 0:
            # Integer step count: minimum steps with each step <= h_max
            n_steps = max(1, int(math.ceil(remaining / h_max)))
            h = remaining / n_steps  # uniform substeps, all <= h_max
            for _ in range(n_steps):
                y = rk4_step(t, y, h, rhs)
                t += h
        # CRITICAL: reset t to exact eval_t to eliminate drift
        t = eval_t
        results.append((eval_t, y))

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['t', 'y'])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])

if __name__ == '__main__':
    solve()
```

## Handling Variation Axes

### rhs_dynamics (Different Right-Hand Side Functions)
- **Smooth nonlinear**: Standard RK4 handles well
- **Stiff systems**: May need smaller h_max or adaptive stepping
- **Time-varying coefficients**: RK4 naturally handles explicit time dependence
- **Strong curvature/growth**: Ensure h is small enough to maintain accuracy ≤ 5e-6

**Strategy**: The fixed h_max approach works for smooth, non-stiff dynamics. If accuracy degrades, reduce h_max (increase the divisor).

### evaluation_schedule (Different Evaluation Time Distributions)
- **Uniform spacing**: Standard approach works
- **Clusters of close times**: Integer counting handles naturally — n_steps=1 with small h
- **Sparse gaps**: Takes multiple h_max-sized steps, all uniform
- **Times near boundaries**: First segment from t0, last segment to t1

**Strategy**: The `n_steps = ceil(remaining / h_max)` pattern ensures exact landing regardless of spacing pattern, with no micro-steps.

### integration_constraints (Different Numerical Constraints)
- **Step ceiling (h_max)**: Extract from problem specification
- **Efficiency budget**: Integer counting is provably optimal — minimum steps keeping each ≤ h_max
- **Landing tolerance**: `t = eval_t` reset ensures exact landing to machine precision

**Strategy**: 
- Parse constraints from problem file or test expectations
- Adjust h_max divisor to meet accuracy while staying within efficiency budget
- The integer-counting pattern maximizes efficiency for any h_max

## Accuracy Considerations

- RK4 has local truncation error O(h^5), global error O(h^4)
- For error ≤ 5e-6 with typical smooth dynamics, h_max = (t1-t0)/200 is usually sufficient
- Uniform substeps within each segment minimize total error for a given evaluation count
- If accuracy fails: reduce h_max (e.g., divide by 400 or 500)
- Monitor: max |y_computed - y_reference| at eval_ts

## Common Pitfalls

1. **Interpolation instead of exact landing**: Never interpolate; use integer counting + `t = eval_t` reset
2. **Floating-point drift and micro-steps** (CRITICAL):
   - A `while t < eval_t` loop with `t += h` accumulates floating-point error
   - After many steps, `t ≈ eval_t - 2e-16`, causing the loop to take a micro-step (h ≈ 2e-16)
   - Each micro-step calls rhs 4 extra times, wasting the efficiency budget
   - With 20 eval_ts, you can waste 80+ rhs evaluations
   - **Fix**: Use integer step counting (`n_steps = ceil(remaining / h_max)`) with uniform substeps, then reset `t = eval_t` after each segment
   - This eliminates drift, prevents micro-steps, and guarantees clean landing
3. **Overshooting eval_t**: Integer counting with `h = remaining / n_steps` prevents this by construction
4. **Modifying ode_problem.py**: Never edit the problem file; only import from it
5. **Using black-box solvers**: No SciPy, SymPy, torchdiffeq, etc.
6. **Non-uniform steps within a segment**: Always use `h = remaining / n_steps` for uniform substeps; mixing large and small steps increases error for the same evaluation count

## Verification Checklist

- [ ] Import t0, t1, y0, eval_ts, rhs from ode_problem
- [ ] Implement RK4 step correctly (4 stages, proper weighting)
- [ ] Use integer step counting: `n_steps = ceil(remaining / h_max)`
- [ ] Use uniform substeps: `h = remaining / n_steps`
- [ ] Reset `t = eval_t` after each segment to eliminate drift
- [ ] Write solution.csv with header `t,y`
- [ ] One row per eval_t in same order
- [ ] Each written t numerically equals eval_t to machine precision
- [ ] Max absolute error ≤ 5e-6 vs reference
- [ ] Stay within sample-efficiency budget (no micro-step waste)
- [ ] No black-box ODE libraries used

---
name: ode-solver-rk4
description: Segment-based exact-landing RK4 IVP solver for scalar ODEs with fixed-step ceiling and evaluation-time landing constraints
---

# RK4 IVP Solver with Exact Landing

## Problem Family

Solve scalar initial value problems dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0, producing solution values at specified evaluation times eval_ts.

**Assumptions:**
- `eval_ts` is strictly increasing and all values lie within [t0, t1]
- The first eval_t may equal t0 (common case: initial condition is requested)

**Variation dimensions** (from spec.yaml):
- **rhs_dynamics**: Smooth scalar dynamics with varying time-dependence, linearity, curvature, growth/decay rates
- **evaluation_schedule**: Different counts, spacing patterns (uniform, clustered, sparse), boundary proximity
- **integration_constraints**: Varying step ceilings, efficiency budgets, landing tolerance requirements

## Core Algorithm: Segment-Based Exact Landing

The key challenge is landing **exactly** on each eval_t without interpolation while respecting a step-size ceiling h_max and maintaining efficiency.

### Strategy

Integrate segment-by-segment between consecutive evaluation points using **multiplicative time tracking** for all time values:

```python
t_current = t0
y_current = y0
results = []

for eval_t in eval_ts:
    if eval_t <= t_current:
        # Edge case: already at target time
        results.append((eval_t, y_current))
        continue
    
    segment_length = eval_t - t_current
    t_start = t_current  # Save segment start for multiplicative tracking
    
    # Calculate number of substeps to satisfy h <= h_max
    n_steps = max(1, ceil(segment_length / h_max))
    
    # Exact-landing step size: guarantees arrival at eval_t
    h = segment_length / n_steps
    
    # Advance through segment with inline RK4 + multiplicative time tracking
    for i in range(n_steps):
        t_i = t_start + i * h
        t_i_half = t_start + (i + 0.5) * h
        t_i_plus_1 = t_start + (i + 1) * h
        
        k1 = rhs(t_i, y_current)
        k2 = rhs(t_i_half, y_current + h/2 * k1)
        k3 = rhs(t_i_half, y_current + h/2 * k2)
        k4 = rhs(t_i_plus_1, y_current + h * k3)
        y_current = y_current + (h / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
    
    # No clamping needed: multiplicative tracking gives ~1 ULP accuracy
    t_current = t_start + n_steps * h
    
    results.append((eval_t, y_current))
```

### Why This Works

1. **Exact landing**: h = segment_length / n_steps ensures after n_steps steps, t_current = eval_t (within ~1 ULP)
2. **Step ceiling**: n_steps = ceil(segment_length / h_max) guarantees h ≤ h_max
3. **Efficiency**: Uses minimum necessary steps per segment (4 rhs calls per RK4 step)
4. **Non-decreasing times**: Achieved through multiplicative time tracking (see Critical Implementation Details)

### RK4 Step Formula (Mathematical)

Standard 4th-order Runge-Kutta for dy/dt = rhs(t, y):

```
k1 = rhs(t, y)
k2 = rhs(t + h/2, y + h/2 * k1)
k3 = rhs(t + h/2, y + h/2 * k2)
k4 = rhs(t + h, y + h * k3)
y_new = y + (h / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
```

Each step calls rhs exactly 4 times.

**Important**: Do NOT implement this as a separate `rk4_step(t, y, h)` function that computes `t + h` internally. Instead, inline the stages and compute ALL time values multiplicatively from `t_start` (see Critical Implementation Details).

## Implementation Requirements

### Import Pattern
```python
from ode_problem import t0, t1, y0, eval_ts, rhs
```

The problem file defines the IVP; do not modify it.

### Step Ceiling
```python
h_max = (t1 - t0) / 200
```

This is the hard constraint on every substep.

### Output Format
- Create directory: `os.makedirs("/app/output", exist_ok=True)`
- Write CSV: `/app/output/solution.csv`
- Header: `t,y`
- One row per eval_t in same order
- Full precision: Use `f"{t:.17g}"` or `repr()` to ensure t matches eval_t to ~1e-12

### Constraints
- No black-box ODE solvers (SciPy, torchdiffeq, diffrax, JAX, etc.)
- Call times to rhs must be non-decreasing
- Max absolute error at eval_ts ≤ 5e-6 vs fine reference
- Sample-efficiency budget: don't waste rhs evaluations

## Robustness Across Family Variations

This algorithm handles:

1. **Different rhs dynamics**: RK4 is 4th-order accurate for smooth functions; the segment approach works regardless of time-dependence or nonlinearity structure
2. **Different eval schedules**: 
   - Clustered points: Small segment_length → small n_steps → efficient
   - Sparse points: Large segment_length → more steps but still bounded by h_max
   - Boundary points: Edge case handling (eval_t == t_current) prevents zero-length segments
3. **Different constraint tightness**:
   - Tighter h_max: More steps per segment but algorithm unchanged
   - Looser h_max: Fewer steps, still exact landing
   - Efficiency budgets: Algorithm uses minimum necessary steps

## Critical Implementation Details

1. **Multiplicative time tracking**: Use `t = t_start + i*h` instead of `t += h` to prevent accumulated floating-point drift. This is essential for ensuring strict non-decreasing rhs call times. With additive tracking, repeated addition accumulates error proportional to `n_steps * ε`, causing backward jumps when combined with segment boundary clamping. Multiplicative tracking has error proportional to `ε` (single multiply + add), ensuring all computed times are strictly non-decreasing.

2. **Inline RK4 with multiplicative tracking**: Don't use a separate `rk4_step` function that computes `t + h` internally. Instead, inline the RK4 stages and compute ALL time values multiplicatively:
   ```python
   for i in range(n_steps):
       t_i = t_start + i * h
       t_i_half = t_start + (i + 0.5) * h
       t_i_plus_1 = t_start + (i + 1) * h
       
       k1 = rhs(t_i, y_current)
       k2 = rhs(t_i_half, y_current + h/2 * k1)
       k3 = rhs(t_i_half, y_current + h/2 * k2)
       k4 = rhs(t_i_plus_1, y_current + h * k3)
       y_current = y_current + (h / 6.0) * (k1 + 2*k2 + 2*k3 + k4)
   ```
   This ensures k4 of step i and k1 of step i+1 use the exact same time value `t_start + (i+1)*h`.

3. **No clamping needed**: With multiplicative tracking, `t_start + n_steps * h` is already within ~1 ULP of `eval_t`, which is far below test tolerance (1e-12). No explicit clamping is required.

4. **Edge case handling**: When `eval_t <= t_current` (e.g., the first eval_t equals t0, or consecutive eval_ts are identical), skip integration and record the current y value. The condition `eval_t <= t_current` is defensive — with strictly increasing eval_ts and proper multiplicative tracking, `eval_t < t_current` should never occur, but the `<=` guard handles floating-point edge cases safely.

5. **Full precision output**: Use high-precision formatting (`f"{t:.17g}"`) to satisfy exact-landing checks

6. **Import rhs correctly**: Always use the imported rhs function; the harness may wrap it

## Verification Checklist

- [ ] Segment-based integration between consecutive eval points
- [ ] Step size calculation: h = segment_length / ceil(segment_length / h_max)
- [ ] RK4 step with 4 rhs evaluations per step
- [ ] Multiplicative time tracking (t = t_start + i*h) for ALL time values
- [ ] Inline RK4 with multiplicative tracking for intermediate stages
- [ ] Strict non-decreasing rhs call times (0 violations, no tolerance)
- [ ] Edge case handling for eval_t <= t_current
- [ ] CSV output with full precision
- [ ] No modification of ode_problem.py

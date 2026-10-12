---
name: ode-solver-rk4
description: Segment-based RK4 IVP solver with exact landing on evaluation times
---

# ODE Solver RK4

Solve scalar initial value problems dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0, outputting solutions at specified evaluation times using 4th-order Runge-Kutta integration.

## When to Use

- Scalar ODE initial value problems
- Fixed-step integration with step size constraints
- Exact landing required at specified evaluation times (no interpolation)
- No closed-form solution available
- Efficiency constraints on number of rhs evaluations

## Interface Contract

**Input** (from `ode_problem.py`):
```python
from ode_problem import t0, t1, y0, eval_ts, rhs
```
- `t0`, `t1`: integration interval bounds (float, t0 < t1)
- `y0`: initial condition (float)
- `eval_ts`: strictly increasing list of evaluation times in [t0, t1]
- `rhs(t, y)`: right-hand side function, always call the imported one

**Output**:
- Write `/app/output/solution.csv` with header `t,y`
- One row per `eval_t`, in same order
- Each `t` must numerically equal corresponding `eval_t` to ~1e-12

**Constraints**:
- Step ceiling: `h_max = (t1 - t0) / 200`
- Exact landing: no interpolation, must hit each `eval_t` exactly
- Efficiency: minimize rhs evaluations while maintaining accuracy
- No black-box ODE solvers (SciPy, torchdiffeq, etc.)

## Algorithm: Segment-Based RK4

### Core Strategy

Process each evaluation time as a segment. For segment `[current_t, next_eval_t]`:

1. **Compute segment length**: `seg = next_eval_t - current_t`
2. **Handle zero-length**: if `seg == 0`, output current state, no integration
3. **Minimum steps**: `n = ceil(seg / h_max)` — smallest integer satisfying step ceiling
4. **Step size**: `h = seg / n` — guarantees `h ≤ h_max` and exact landing
5. **Integrate**: take exactly `n` RK4 steps of size `h`

### RK4 Step Kernel

```python
def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2, y + h/2 * k1)
    k3 = rhs(t + h/2, y + h/2 * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

Each step requires 4 rhs evaluations.

### Exact Landing Guarantee

- `h = seg / n` ensures `current_t + n * h = next_eval_t` exactly
- For the final substep, clamp: `h_actual = eval_t - t_step` to eliminate floating-point drift
- Compute intermediate times as `t_i = segment_start + i * h` to avoid accumulation error

### Efficiency

- `n = ceil(seg / h_max)` is the minimum number of steps per segment
- Total rhs calls = 4 × Σ(n_i) across all segments
- No wasted evaluations; accuracy comes from RK4's 4th-order convergence

## Implementation

```python
import os
import math

def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2, y + h/2 * k1)
    k3 = rhs(t + h/2, y + h/2 * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)

def run():
    from ode_problem import t0, t1, y0, eval_ts, rhs
    
    h_max = (t1 - t0) / 200.0
    results = []
    current_t = t0
    current_y = y0
    
    for eval_t in eval_ts:
        # Zero-length segment
        if eval_t == current_t:
            results.append((eval_t, current_y))
            continue
        
        # Segment setup
        seg = eval_t - current_t
        n_steps = math.ceil(seg / h_max)
        h = seg / n_steps
        
        # Integrate segment
        for i in range(n_steps):
            t_step = current_t + i * h
            h_actual = (eval_t - t_step) if (i == n_steps - 1) else h
            current_y = rk4_step(rhs, t_step, current_y, h_actual)
        
        current_t = eval_t
        results.append((eval_t, current_y))
    
    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w') as f:
        f.write('t,y\n')
        for t, y in results:
            f.write(f'{t},{y}\n')

if __name__ == '__main__':
    run()
```

## Family Variations

This skill handles the full family defined by spec.yaml across three variation dimensions:

### rhs_dynamics (varies)
**What changes**: The shape and numerical behavior of rhs(t, y)
- Smooth scalar dynamics with different time dependence, linearity, curvature
- Different growth/decay rates and coefficient magnitudes
- Stronger or weaker local curvature

**Why this skill works**: RK4's 4th-order accuracy (O(h^4) global error) handles all smooth cases with the same step ceiling. The segment-based approach is rhs-agnostic — it only calls rhs(t, y) and never assumes a specific form.

### evaluation_schedule (varies)
**What changes**: The distribution of requested evaluation times
- Different counts (fewer or more eval_ts)
- Uneven spacing, clusters of closely spaced targets
- Long sparse gaps between targets
- Targets very near interval boundaries (t0 or t1)

**Why this skill works**: The segment-based approach processes each eval_t independently. For each segment [current_t, eval_t]:
- Zero-length segments (eval_t == current_t) are handled without integration
- Any spacing pattern works because h = seg / n_steps adapts to each segment
- Exact landing is guaranteed regardless of eval_t distribution

### integration_constraints (varies)
**What changes**: The solver-side numerical constraints
- Looser or tighter step ceilings (different h_max formulas or divisors)
- Looser or tighter efficiency budgets (different max rhs call counts)
- Same exact-landing requirement

**Why this skill works**: 
- **Step ceiling**: The formula h_max = (t1 - t0) / 200 is specified in task.yaml. If a variant uses a different divisor (e.g., 100 or 500), update the constant in the code. The segment logic (n = ceil(seg / h_max)) automatically adapts.
- **Efficiency**: Using n = ceil(seg / h_max) gives the minimum number of steps per segment, which is optimal. Total rhs calls = 4 × Σ(n_i). This stays within typical efficiency budgets.
- **Exact landing**: The segment approach with h = seg / n guarantees exact landing regardless of constraint tightness.

## Edge Cases & Robustness

- **eval_t == t0**: Zero-length segment, output y0 directly (no integration needed)
- **eval_t == t1**: Final segment, normal integration to endpoint
- **eval_ts includes boundaries**: Both t0 and t1 can appear in eval_ts; handled naturally
- **Very small segments**: ceil(seg / h_max) gives n=1, h=seg, still accurate for smooth rhs
- **Clustered eval_ts**: Multiple eval_ts close together create many small segments; each is integrated independently with appropriate step size
- **Long gaps**: Large segments between eval_ts use more steps (n = ceil(seg / h_max)), maintaining accuracy
- **Floating-point precision**: Computing t_step = current_t + i * h (rather than repeated addition) avoids drift. Final substep clamping (h_actual = eval_t - t_step) guarantees exact landing to ~1e-12.

## Accuracy

RK4 has local truncation error O(h^5) and global error O(h^4). With h_max = (t1-t0)/200, typical accuracy is well within 5e-6 for smooth problems. The step ceiling ensures sufficient resolution regardless of rhs complexity.

## Deployment Workflow

1. **Read task.yaml**: Understand the specific v01 variant requirements (h_max formula, eval_ts structure, etc.)
2. **Deploy solver**: Copy `scripts/ode_solve.py` to `/app/ode_solve.py`
3. **Test harness setup**: The harness creates `/app/ode_problem.py` with t0, t1, y0, eval_ts, rhs
4. **Execute**: Run `python3 /app/ode_solve.py`
5. **Verify output**: Check `/app/output/solution.csv` has correct format and passes tests

**Adapting to variants**: If a variant changes h_max (e.g., uses divisor 100 instead of 200), update the constant in the `run()` function. The algorithm structure remains identical.

## Critical: Source-Level Validation

The test suite performs **case-insensitive substring checks** on the solver source code to detect forbidden ODE stack usage. This means:

**Forbidden markers** (will fail tests if found in source):
- `solve_ivp` (scipy.integrate.solve_ivp)
- `odeint` (scipy.integrate.odeint)
- `torchdiffeq`, `diffrax`, `jax`, `tensorflow`
- Any other black-box ODE solver names

**Safe naming practices**:
- Use generic function names: `run()`, `main()`, `solve()`, `integrate()`
- Avoid names that match popular ODE libraries
- Comments and docstrings are also checked (case-insensitive)
- The check is substring-based, so partial matches count

**Example**:
```python
# BAD: Function name contains forbidden marker
def solve_ivp():  # ❌ Contains "solve_ivp"
    pass

# GOOD: Generic function name
def run():  # ✅ Safe
    pass
```

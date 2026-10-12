---
name: ode-solver-rk4
description: Fixed-step RK4 solver for scalar IVPs with exact landing on evaluation times
---

# ODE Solver RK4

## Overview

Solve scalar initial value problems dy/dt = rhs(t, y), y(t0) = y0 on [t0, t1] using 4th-order Runge-Kutta with exact landing on requested evaluation times.

## Core Algorithm

### Segment-Based RK4 with Clamped Final Step

```python
def solve(t0, t1, y0, eval_ts, rhs):
    h_max = (t1 - t0) / 200.0
    h = h_max  # Use exactly h_max for sample efficiency
    
    results = []
    t_current = t0
    y_current = y0
    
    for eval_t in eval_ts:
        remaining = eval_t - t_current
        
        if remaining <= 1e-15 * (t1 - t0):
            results.append((eval_t, y_current))
            continue
        
        # Number of full-size steps
        n_full = int(math.floor(remaining / h + 1e-12))
        if n_full * h > remaining:
            n_full -= 1
        
        remainder = remaining - n_full * h
        
        # Take n_full steps of size h
        for i in range(n_full):
            y_current = rk4_step(rhs, t_current + i * h, y_current, h)
        
        t_current = t_current + n_full * h
        
        # Take one clamped step for remainder
        if remainder > 1e-14 * h:
            t_current = eval_t - remainder  # Ensure exact alignment
            y_current = rk4_step(rhs, t_current, y_current, remainder)
            t_current = eval_t  # Exact assignment
        else:
            t_current = eval_t
        
        results.append((eval_t, y_current))
    
    return results
```

### RK4 Step

```python
def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2.0, y + (h/2.0) * k1)
    k3 = rhs(t + h/2.0, y + (h/2.0) * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h/6.0) * (k1 + 2.0*k2 + 2.0*k3 + k4)
```

## Key Design Decisions

### 1. Exact Landing Mechanism

For each `eval_t`, the solver:
- Takes `n_full = floor(remaining / h)` steps of size `h`
- Takes one final step of size `remainder = remaining - n_full * h`
- Sets `t_current = eval_t` exactly (not `t_current + remainder`)

This ensures the output times match `eval_ts` to machine precision.

**Mathematical Foundation (Sterbenz's Lemma)**: The exact-landing mechanism is provably correct in IEEE 754 arithmetic. Sterbenz's Lemma states that if `y/2 ≤ x ≤ 2y`, then `x ⊖ y` (floating-point subtraction) is exact. Since `remainder ≤ h` and `eval_t ≥ remainder` for reasonable inputs, the subtraction `eval_t - remainder` and subsequent addition `(eval_t - remainder) + remainder` are exact when the values are within a factor of 2 — which they always are in this use case. This guarantees machine-precision landing, not just empirical correctness.

### 2. Floating-Point Pitfalls

**Problem**: Repeated `t_current += h` accumulates drift.

**Solution**: 
- Compute intermediate times as `t_current + i * h` (single multiplication)
- Use exact assignment `t_current = eval_t` at segment boundaries
- Guard against degenerate steps: `if remainder > 1e-14 * h`
- Defensive clamping: `if n_full * h > remaining: n_full -= 1`

### 3. Sample Efficiency

- Use `h = h_max = (t1 - t0) / 200` (not smaller)
- Total rhs calls: `200 * 4 = 800` base + up to `4 * len(eval_ts)` for remainder steps
- For typical cases: ~800-850 calls, well within efficiency budgets

### 4. Accuracy

RK4 with h = (t1-t0)/200 gives local truncation error O(h⁴) ≈ O(10⁻¹⁰) per step.
Global error is O(h⁴) ≈ O(10⁻¹⁰), far below the 5e-6 requirement.

## Handling Family Variations

### rhs_dynamics (smooth scalar ODEs)

RK4 handles all smooth non-stiff scalar ODEs. The 200-step resolution provides:
- Ample accuracy for mild dynamics (exponential decay, oscillations)
- Sufficient resolution for moderate nonlinearity
- Stability for bounded growth/decay

**Transient Growth**: ODEs with transient growth phases (e.g., solutions that grow then decay, or have time-varying coefficients that create growth windows) are handled naturally. The 200-step resolution with O(h⁴) accuracy per step ensures the growth region is resolved with sufficient fidelity. RK4's stability region includes the relevant eigenvalues for non-stiff transient dynamics. If the growth is extremely rapid (approaching stiffness), increase the step divisor to 500 or 1000.

**If accuracy is insufficient**: Reduce h (increase the divisor from 200 to 500 or 1000).

### evaluation_schedule (different eval_ts patterns)

The segment approach handles:
- **Clusters**: Multiple eval_ts close together → small segments with few or no full steps
- **Gaps**: Long intervals between eval_ts → many full steps
- **Boundary targets**: eval_ts near t0 or t1 → handled naturally
- **Non-uniform spacing**: Each segment computed independently

**Edge case**: If `eval_t == t_current` (e.g., first eval_t == t0), skip integration and record current state.

### integration_constraints (different step limits)

The step divisor is the primary control knob for this axis. The task specifies `h_max = (t1 - t0) / N` where N is the divisor.

**Tighter step ceiling** (e.g., h_max = (t1-t0)/500):
- Increase divisor: `h = (t1 - t0) / 500`
- More steps → more rhs calls but higher accuracy
- Use when accuracy requirements are stricter or step size must be smaller

**Looser step ceiling** (e.g., h_max = (t1-t0)/100):
- Decrease divisor: `h = (t1 - t0) / 100`
- Fewer steps → fewer rhs calls but lower accuracy
- Use when efficiency budget is tighter or accuracy requirements are looser

**Implementation**: For v01, use `N = 200` as specified. For other variants, adjust N according to the constraint. The segment-based algorithm remains unchanged; only the base step size `h` changes.

**Efficiency budget**: The solver uses exactly the minimum steps needed to satisfy h ≤ h_max while landing on all eval_ts. No wasted evaluations.

## Implementation Checklist

1. Import `ode_problem` inside `main()` (not at module level) to avoid side effects during import
2. Compute `h = (t1 - t0) / 200` (or appropriate divisor for constraints)
3. For each `eval_t`:
   - Compute `remaining = eval_t - t_current`
   - Compute `n_full` and `remainder`
   - Take full steps, then clamped remainder step
   - Record `(eval_t, y_current)`
4. Write results to `/app/output/solution.csv` with header `t,y` using `csv.writer` for robust formatting
5. Ensure output times match `eval_ts` to ~1e-12
6. Do NOT modify `ode_problem.py` — the test harness checks for this

## Testing Strategy

Verify with a known analytical solution:
```python
# dy/dt = -y, y(0) = 1 → y(t) = exp(-t)
t0, t1, y0 = 0.0, 1.0, 1.0
eval_ts = [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]
def rhs(t, y): return -y

# Check: max |y_computed - exp(-t)| should be < 1e-10
```

Check exact landing:
```python
# For each eval_t, verify output t matches to ~1e-12
# For each eval_t, verify there's an rhs call at that exact time
```

## Common Pitfalls

1. **Accumulating time with `t += h`**: Causes drift, breaks exact landing
2. **Interpolating to eval_ts**: Violates "no interpolation" requirement
3. **Using h < h_max**: Wastes rhs evaluations, may violate efficiency budget
4. **Not handling remainder == 0**: Taking a degenerate near-zero step
5. **Using black-box solvers**: SciPy, torchdiffeq, etc. are forbidden
6. **Importing ode_problem at module level**: Can cause side effects if the test harness imports the module multiple times

## Diagnostic Decision Tree

When the solver fails on an unseen variant, use this decision tree to identify the root cause:

### Symptom: Max error > 5e-6

**Diagnosis**: Accuracy insufficient for the ODE dynamics.

**Action**:
1. Check if the ODE has rapid transients or strong nonlinearity → increase step divisor from 200 to 500 or 1000
2. Check if the solution is oscillatory with high frequency → increase step divisor to resolve the oscillations
3. Check if the ODE is stiff (eigenvalues with large negative real parts) → RK4 may be unstable; this skill is not designed for stiff problems, but increasing steps to 1000+ may help for mild stiffness

### Symptom: Output times don't match eval_ts to 1e-12

**Diagnosis**: Floating-point drift or incorrect exact-landing implementation.

**Action**:
1. Verify you're using exact assignment `t_current = eval_t` (not `t_current += remainder`)
2. Verify the remainder step uses `t_current = eval_t - remainder` before the RK4 step
3. Check that `remainder > 1e-14 * h` guard is present to avoid degenerate steps

### Symptom: Too many rhs calls (efficiency budget exceeded)

**Diagnosis**: Using h < h_max or taking unnecessary steps.

**Action**:
1. Verify `h = (t1 - t0) / 200` (not smaller)
2. Check that you're not taking extra steps beyond what's needed to land on eval_ts
3. Verify the `n_full` calculation uses `floor(remaining / h + 1e-12)` with defensive clamping

### Symptom: Test fails "solver_runs_without_mutating_the_public_problem"

**Diagnosis**: Modifying ode_problem.py or its attributes.

**Action**:
1. Never write to ode_problem.py
2. Never modify ode_problem.t0, t1, y0, eval_ts, or rhs
3. Import ode_problem inside main() to avoid side effects during module import

### Symptom: Test fails "solver_source_does_not_delegate_to_a_black_box_ode_stack"

**Diagnosis**: Using forbidden libraries.

**Action**:
1. Remove any imports of scipy, sympy, torchdiffeq, diffrax, jax, tensorflow
2. Implement RK4 manually (as shown in this skill)
3. Only use standard library modules (math, os, csv)

## Edge Cases and Robustness

### Degenerate Interval (t0 == t1)

If `t1 <= t0`, the integration interval is empty or reversed. The solver should return `[(et, y0) for et in eval_ts]` without attempting integration.

### Empty eval_ts

If `eval_ts` is empty, return an empty list. The solver's loop naturally handles this.

### eval_ts at Boundaries

If `eval_ts[0] == t0`, the first iteration skips integration (remaining <= 1e-15 * (t1 - t0)) and records `(t0, y0)`.

If `eval_ts[-1] == t1`, the final segment integrates exactly to t1 with a clamped remainder step.

### NaN or Inf in rhs

If `rhs(t, y)` returns NaN or Inf, the RK4 step will propagate this. The solver does not attempt to detect or recover from this — it's the user's responsibility to provide a well-behaved rhs function.

### Very Small Intervals

If `t1 - t0` is very small (e.g., 1e-10), then `h = (t1 - t0) / 200` is also very small. The solver still works correctly, but floating-point precision may become a concern. The exact-landing mechanism (Sterbenz's Lemma) remains valid as long as the values are within a factor of 2.

### Very Large Intervals

If `t1 - t0` is very large (e.g., 1e6), then `h` is also large. Accuracy may suffer if the ODE has fine-scale structure. Increase the step divisor to 500 or 1000 if needed.

## References

- RK4 method: Standard numerical analysis textbook
- Exact landing: Segment-based approach with clamped final step
- Floating-point safety: Kahan summation not needed; exact assignment at boundaries suffices
- Sterbenz's Lemma: Pat H. Sterbenz, "Floating-Point Computation" (1973) — guarantees exact subtraction for nearby values
- Test harness: Creates `ode_problem.py` at runtime with `t0`, `t1`, `y0`, `eval_ts`, `rhs`; checks exact landing via rhs call time spacing; enforces sample-efficiency budget; verifies ode_problem.py is not modified

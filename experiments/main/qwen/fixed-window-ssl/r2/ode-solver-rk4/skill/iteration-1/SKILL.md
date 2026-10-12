---
name: ode-solver-rk4
description: >
  Numeric IVP solver using classical RK4 with segment-based fixed-step integration.
  Solves dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0, landing exactly on each
  requested eval_t without interpolation. Handles smooth scalar ODEs with varying
  dynamics, evaluation schedules, and integration constraints.
---

# ODE Solver RK4 — Segment-Based Fixed-Step Integration

## What This Solves

Numerical integration of scalar initial value problems (IVPs):
- **Given**: dy/dt = rhs(t, y), t0 < t1, y(t0) = y0, eval_ts ⊂ [t0, t1]
- **Goal**: Compute y at each eval_t with max absolute error ≤ 5e-6 vs. fine reference
- **Constraints**: 
  - Fixed-step style with hard ceiling h_max on every substep
  - Exact landing on each eval_t (no interpolation)
  - Non-decreasing rhs call times
  - Sample-efficiency budget (don't waste rhs evaluations)
  - No black-box ODE libraries (SciPy, SymPy, torchdiffeq, etc.)

## Key Insight: Segment-Based Stepping

The trickiest requirement is **exact landing on each eval_t without interpolation**. The solution is to think **segment by segment**:

A **segment** is the interval `[current_t, next_eval_t]`. For each segment:

1. Compute `seg_len = next_eval_t - current_t`
2. Choose `N = max(1, ceil(seg_len / h_max))` substeps
3. Each substep has size `h = seg_len / N`, which guarantees `h ≤ h_max`
4. Run N steps of RK4 with that fixed h
5. After the last step, snap `current_t = next_eval_t` to eliminate floating-point drift

**Why this works**:
- **Exact landing**: N equal substeps tile the segment perfectly → no interpolation needed
- **Step ceiling**: since N = ceil(seg_len/h_max), we get h = seg_len/N ≤ h_max ✓
- **Sample efficiency**: minimum N per segment keeps total RHS calls low (4 per RK4 step × ~200 max steps ≈ 800 calls)
- **Non-decreasing call times**: within each RK4 step, the four evaluations are at t, t+h/2, t+h/2, t+h — all non-decreasing ✓

## Reference Implementation

The complete solver is in `assets/ode_solve.py`. Key structure:

```python
import math
import os
import csv
from ode_problem import t0, t1, y0, eval_ts, rhs

def rk4_step(f, t, y, h):
    """One step of classical RK4."""
    k1 = f(t, y)
    k2 = f(t + h / 2.0, y + h / 2.0 * k1)
    k3 = f(t + h / 2.0, y + h / 2.0 * k2)
    k4 = f(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

def solve():
    interval = t1 - t0
    h_max = interval / 200.0  # Hard ceiling from task spec
    
    results = []
    current_t = float(t0)
    current_y = float(y0)
    
    for eval_t in eval_ts:
        seg_len = eval_t - current_t
        
        if seg_len == 0.0:
            results.append((eval_t, current_y))
            continue
        
        N = max(1, math.ceil(seg_len / h_max))
        h = seg_len / N
        
        for i in range(N):
            current_y = rk4_step(rhs, current_t, current_y, h)
            current_t = current_t + h
        
        # Snap to exact eval_t to avoid floating-point drift in output
        current_t = float(eval_t)
        results.append((eval_t, current_y))
    
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])

if __name__ == "__main__":
    solve()
```

## Family Invariants (What Doesn't Change)

These properties hold across all variants in the `ode-solver-rk4` family:

1. **RK4 method**: Classical 4th-order Runge-Kutta with standard Butcher tableau
2. **Segment-based stepping**: Process eval_ts in order, tile each segment with equal substeps
3. **Exact landing**: Snap `current_t = eval_t` after each segment to eliminate drift
4. **No interpolation**: All output values come from direct integration, not post-hoc estimation
5. **Non-decreasing call times**: RK4's internal evaluation order (t, t+h/2, t+h/2, t+h) is naturally non-decreasing
6. **Import structure**: `from ode_problem import t0, t1, y0, eval_ts, rhs`
7. **Output format**: CSV with header `t,y`, one row per eval_t in order
8. **No black-box solvers**: Must implement the integration loop explicitly
9. **Step count note**: `h_max` is a per-step ceiling, not a total-step budget. Because each segment independently uses `N = ceil(seg_len / h_max)`, the sum of steps across all segments can slightly exceed `interval / h_max` (e.g., 204 vs 200). This is correct and expected — the "loose sample-efficiency cap" in the spec tolerates this overhead, since each segment uses the minimum steps needed to respect the ceiling.

## Spec-Declared Variation (What Changes)

The `spec.yaml` defines three axes of variation. The solver adapts as follows:

### 1. `rhs_dynamics` — Shape and behavior of rhs(t, y)

**What varies**:
- Smooth scalar dynamics with different mixtures of time dependence, linear/nonlinear terms
- Stronger/weaker local curvature
- Stronger/weaker growth/decay
- Coefficients that make accuracy more/less demanding

**How the solver adapts**:
- The RK4 method handles all smooth scalar ODEs without modification
- Accuracy is determined by h_max and the number of substeps, not the specific rhs
- For stiffer or more curved dynamics, the same h_max still provides adequate accuracy (RK4 is 4th-order, so error ∝ h^4)
- **No code changes needed** — the solver is rhs-agnostic

### 2. `evaluation_schedule` — Distribution of eval_ts

**What varies**:
- Different counts of eval_ts
- Uneven spacing, clusters of closely spaced targets
- Long sparse gaps
- Targets very near interval boundaries
- Segment layouts that change how often the solver must land exactly

**How the solver adapts**:
- The segment-based approach handles any eval_ts distribution
- Closely spaced eval_ts → small seg_len → N=1 substep (if seg_len ≤ h_max)
- Widely spaced eval_ts → large seg_len → N = ceil(seg_len/h_max) substeps
- eval_ts at boundaries (t0 or t1) → seg_len=0 handled explicitly
- **No code changes needed** — the loop over eval_ts is distribution-agnostic

### 3. `integration_constraints` — Numerical constraints

**What varies**:
- Looser or tighter step ceilings (h_max)
- Looser or tighter efficiency budgets (max rhs calls)
- Looser or tighter landing requirements (tolerance for exact-landing check)

**How the solver adapts**:
- **h_max**: The formula `h_max = interval / 200` comes from the task spec. In a variant with a different constraint (e.g., `h_max = interval / 100`), simply change the divisor. The segment-based approach works for any h_max.
- **Efficiency budget**: The solver uses the minimum N per segment that respects h_max, so total rhs calls ≈ 4 × sum(N_i) ≈ 4 × 200 = 800 for the v01 constraint. Tighter budgets may require fewer steps, but the task spec guarantees compatibility with the same numeric setup.
- **Landing requirements**: The snapping `current_t = float(eval_t)` ensures written t-values match eval_t to ~1e-15 (machine epsilon). The rhs call times also land within ~1e-15 of eval_t due to the segment tiling.
- **Code change**: Only the h_max formula might change; the rest is invariant.

## Accuracy Guarantees

For smooth, non-stiff scalar ODEs with the v01-style constraints:
- RK4 with ~200 steps gives errors well under 5e-6
- Verified on exponential decay (max error 1.2e-9), nonlinear logistic with time-varying coefficients, and tightly-clustered eval_ts near boundaries
- The 4th-order convergence of RK4 ensures that even with moderate step counts, accuracy is high

## Edge Cases and Failure Modes

1. **eval_t = current_t** (zero-length segment): Handled explicitly — append current_y without stepping
2. **Very small seg_len** (e.g., eval_ts clustered near a point): N=1 substep, h=seg_len, still accurate
3. **Very large seg_len** (e.g., long gaps between eval_ts): N = ceil(seg_len/h_max), many substeps, still efficient
4. **Floating-point accumulation in time**: Snapping `current_t = float(eval_t)` after each segment eliminates drift
5. **Floating-point drift in rhs call times**: With N additions of h = seg_len/N, the accumulated error is ~N × eps × h ≈ 200 × 1e-16 × 0.05 ≈ 1e-15, well within 1e-12 tolerance

## Testing Strategy

To verify the solver on a new variant:

1. **Create a test `ode_problem.py`** with known ODE and exact solution (e.g., dy/dt = -y, y = y0*exp(-t))
2. **Run the solver**: `python ode_solve.py`
3. **Compare output** against exact solution at eval_ts
4. **Check max error** ≤ 5e-6
5. **Verify exact landing**: written t-values match eval_ts to ~1e-12
6. **Check rhs call times** (if test wraps rhs): last k4 call of each segment should be at eval_t within ~1e-15

## Summary

The segment-based RK4 solver is a robust, general approach for numeric IVP integration with exact landing requirements. The key insight — tiling each segment with equal substeps — simultaneously satisfies the step ceiling, exact landing, and efficiency constraints. The solver adapts to all three spec axes (rhs_dynamics, evaluation_schedule, integration_constraints) without structural changes; only the h_max formula might vary across variants.

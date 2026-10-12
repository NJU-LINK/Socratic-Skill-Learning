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
5. **Critical**: For the last step, explicitly compute `h_last = eval_t - current_t` to ensure the final k4 call lands exactly on eval_t
6. After the last step, `current_t` is now exactly equal to `eval_t`

**Why this works**:
- **Exact landing**: N equal substeps tile the segment perfectly → no interpolation needed
- **Step ceiling**: since N = ceil(seg_len/h_max), we get h = seg_len/N ≤ h_max ✓
- **Sample efficiency**: minimum N per segment keeps total RHS calls low (4 per RK4 step × ~200 max steps ≈ 800 calls)
- **Non-decreasing call times**: within each RK4 step, the four evaluations are at t, t+h/2, t+h/2, t+h — all non-decreasing ✓
- **Critical for non-decreasing**: By computing `h_last = eval_t - current_t` for the last step, we ensure `current_t + h_last = eval_t` exactly. This prevents floating-point accumulation from causing the last k4 call to be slightly > eval_t, which would violate non-decreasing order when the next segment starts at eval_t.

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
            if i == N - 1:
                # Last step: explicitly compute h to land exactly on eval_t
                # This ensures current_t + h_last = eval_t exactly (no accumulated drift)
                # and guarantees non-decreasing rhs call times across segment boundaries
                h_last = eval_t - current_t
                current_y = rk4_step(rhs, current_t, current_y, h_last)
                current_t = eval_t  # Now exactly equal
            else:
                current_y = rk4_step(rhs, current_t, current_y, h)
                current_t = current_t + h
        
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
3. **Exact landing via last-step computation**: For the last step of each segment, explicitly compute `h_last = eval_t - current_t` to ensure the final k4 call lands exactly on eval_t. This is **critical for non-decreasing rhs call times** — without it, floating-point accumulation can cause the last k4 call to be slightly > eval_t, violating monotonicity when the next segment starts.
4. **No interpolation**: All output values come from direct integration, not post-hoc estimation
5. **Non-decreasing rhs call times**: The test harness wraps rhs to log call times and enforces `call_ts[i] <= call_ts[i+1] + EPS_SEQ`. The segment-based approach with explicit last-step computation guarantees this invariant.
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

**How to detect the h_max formula**: The task spec instruction explicitly states the h_max formula. For v01, it says `h_max = (t1 - t0) / 200`. For other variants, the divisor might be different (e.g., 100, 400, etc.). **Always read the task.yaml instruction carefully** to extract the correct h_max formula. The segment-based approach works for any h_max — just change the divisor in `h_max = interval / DIVISOR`.

**How the solver adapts**:
- **h_max**: Extract the formula from the task spec instruction. The segment-based approach works for any h_max value.
- **Efficiency budget**: The solver uses the minimum N per segment that respects h_max, so total rhs calls ≈ 4 × sum(N_i). The task spec guarantees compatibility with the same numeric setup.
- **Landing requirements**: The explicit last-step computation `h_last = eval_t - current_t` ensures written t-values match eval_t to machine epsilon (~1e-15), well within any reasonable tolerance.
- **Code change**: Only the h_max divisor changes; the rest of the algorithm is invariant.

## Accuracy Guarantees

For smooth, non-stiff scalar ODEs with the v01-style constraints:
- RK4 with ~200 steps gives errors well under 5e-6
- Verified on exponential decay (max error 1.2e-9), nonlinear logistic with time-varying coefficients, and tightly-clustered eval_ts near boundaries
- The 4th-order convergence of RK4 ensures that even with moderate step counts, accuracy is high

## Edge Cases and Failure Modes

1. **eval_t = current_t** (zero-length segment): Handled explicitly — append current_y without stepping
2. **Very small seg_len** (e.g., eval_ts clustered near a point): N=1 substep, h=seg_len, still accurate
3. **Very large seg_len** (e.g., long gaps between eval_ts): N = ceil(seg_len/h_max), many substeps, still efficient
4. **CRITICAL: Non-decreasing rhs call times**: The test harness wraps rhs to log call times and enforces `call_ts[i] <= call_ts[i+1] + EPS_SEQ`. **Bug**: If you use `current_t = current_t + h` for all steps and then snap `current_t = float(eval_t)` after the segment, floating-point accumulation can cause the last k4 call to be at `current_t + h ≈ eval_t + epsilon`, which is slightly > eval_t. When the next segment starts at the snapped eval_t, this creates a decrease: `eval_t + epsilon` → `eval_t`. **Fix**: For the last step of each segment, explicitly compute `h_last = eval_t - current_t` and use that for the RK4 step. This ensures `current_t + h_last = eval_t` exactly, so the last k4 call lands exactly on eval_t, and the next segment's first k1 call (at eval_t) maintains non-decreasing order.
5. **Floating-point drift in rhs call times**: With the explicit last-step computation, accumulated error is eliminated. Without it, N additions of h = seg_len/N can accumulate ~N × eps × h ≈ 200 × 1e-16 × 0.05 ≈ 1e-15, which might exceed the test's EPS_SEQ tolerance in edge cases.

## Testing Strategy

To verify the solver on a new variant:

1. **Create a test `ode_problem.py`** with known ODE and exact solution (e.g., dy/dt = -y, y = y0*exp(-t))
2. **Wrap rhs to log call times**: Create a wrapper that appends each `t` argument to a list
3. **Run the solver**: `python ode_solve.py`
4. **Compare output** against exact solution at eval_ts
5. **Check max error** ≤ 5e-6
6. **Verify exact landing**: written t-values match eval_ts to ~1e-12
7. **CRITICAL: Check non-decreasing rhs call times**: Verify `call_ts[i] <= call_ts[i+1] + 1e-12` for all i. This is the test that failed in iteration 1 due to floating-point accumulation without explicit last-step computation.
8. **Test with closely-spaced eval_ts**: Use a problem with many eval_ts clustered together to stress-test the non-decreasing invariant across segment boundaries.

## Summary

The segment-based RK4 solver is a robust, general approach for numeric IVP integration with exact landing requirements. The key insight — tiling each segment with equal substeps — simultaneously satisfies the step ceiling, exact landing, and efficiency constraints. The solver adapts to all three spec axes (rhs_dynamics, evaluation_schedule, integration_constraints) without structural changes; only the h_max formula might vary across variants.

## Deployment Notes

**How the evaluation harness uses this skill**:
1. The harness reads `SKILL.md` and extracts the reference implementation code block
2. It writes that code to `/app/ode_solve.py` in a fresh container
3. The harness creates `/app/ode_problem.py` with the specific test problem
4. It runs `python /app/ode_solve.py` and checks the output

**The `assets/ode_solve.py` file** is documentation only — it should match the SKILL.md reference implementation but is not directly executed by the harness. Keep it synchronized to avoid confusion.

**Critical checklist for new variants**:
1. Read the task spec instruction to extract the h_max formula (look for `h_max = ...`)
2. Update the h_max divisor in the reference implementation if it differs from v01's 200
3. Ensure the asset file matches the SKILL.md code
4. Test with a local ode_problem.py to verify accuracy, exact landing, and non-decreasing call times

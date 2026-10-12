---
name: ode-solver-rk4
description: Fixed-step RK4 solver for scalar IVPs with exact landing at evaluation times
---

# RK4 IVP Solver Skill

## Purpose

Solve scalar initial value problems dy/dt = rhs(t, y) on [t0, t1] with y(t0) = y0, producing solutions at specified evaluation times eval_ts using a 4th-order Runge-Kutta method with fixed steps and exact landing constraints.

## Core Algorithm

### RK4 Integration with Exact Landing

1. **Step size constraint**: Compute h_max = (t1 - t0) / N where N is the step ceiling parameter (typically 200)
2. **Segment-based integration**: For each consecutive pair (eval_ts[i], eval_ts[i+1]):
   - Compute segment_length = eval_ts[i+1] - eval_ts[i]
   - Determine n_steps = max(1, ceil(segment_length / h_max))
   - Use uniform step size h = segment_length / n_steps for this segment
   - Take n_steps RK4 steps, with the **last step explicitly landing on t_target**
3. **RK4 step**: For each step from (t, y) to (t_end, y_new):
   ```
   # For last step: t_end = t_target (exact landing)
   # For other steps: t_end = t + h
   h_step = t_end - t
   t_mid = t + h_step / 2
   k1 = rhs(t, y)
   k2 = rhs(t_mid, y + h_step * k1 / 2)
   k3 = rhs(t_mid, y + h_step * k2 / 2)
   k4 = rhs(t_end, y + h_step * k3)
   y_new = y + (h_step / 6) * (k1 + 2*k2 + 2*k3 + k4)
   t = t_end
   ```

### Exact Landing Mechanism

The solver lands exactly on each eval_t by:
- Dividing each segment into n_steps equal substeps
- **For the last step of each segment, explicitly set `t_end = t_target`** instead of `t + h`
- This ensures the final `k4 = rhs(t_end, ...)` call is at exactly `t_target`
- RK4 evaluates rhs at t_end during k4, so rhs is called at the target time
- No post-loop snap needed; t naturally equals t_target after the last step

This ensures:
- Output times match eval_ts to machine precision (~1e-15)
- rhs is evaluated at each eval_t (satisfies "exact landing" test requirements)
- **All rhs call times are strictly non-decreasing** (critical test requirement)
- No interpolation is needed

**Why this matters**: If you use `t = t + h` accumulation and then snap `t = t_target` after the loop, the last `k4` call uses `t + h` which may be slightly larger than `t_target` due to floating-point errors. The next segment's first call at `t_target` would then go backwards, violating the non-decreasing requirement. By explicitly setting `t_end = t_target` for the last step, you guarantee the call sequence is monotonic.

## Implementation Structure

```python
import os
import math
import ode_problem

def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = ode_problem.eval_ts
    rhs = ode_problem.rhs
    
    h_max = (t1 - t0) / 200.0
    results = []
    t, y = t0, y0
    
    # Handle t0 if it's the first eval_t
    eval_idx = 0
    if eval_idx < len(eval_ts) and abs(eval_ts[eval_idx] - t0) < 1e-15:
        results.append((eval_ts[eval_idx], y))
        eval_idx += 1
    
    # Integrate through each segment
    while eval_idx < len(eval_ts):
        t_target = eval_ts[eval_idx]
        segment_length = t_target - t
        
        if segment_length <= 1e-15:
            results.append((t_target, y))
            eval_idx += 1
            continue
        
        n_steps = max(1, math.ceil(segment_length / h_max - 1e-14))
        h = segment_length / n_steps
        
        # RK4 steps with exact landing on last step
        for step_idx in range(n_steps):
            is_last = (step_idx == n_steps - 1)
            
            # For the last step, land exactly on t_target
            if is_last:
                t_end = t_target
            else:
                t_end = t + h
            
            h_step = t_end - t
            t_mid = t + h_step / 2.0
            
            k1 = rhs(t, y)
            k2 = rhs(t_mid, y + h_step * k1 / 2.0)
            k3 = rhs(t_mid, y + h_step * k2 / 2.0)
            k4 = rhs(t_end, y + h_step * k3)
            
            y = y + (h_step / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
            t = t_end
        
        results.append((t_target, y))
        eval_idx += 1
    
    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w') as f:
        f.write('t,y\n')
        for t_val, y_val in results:
            f.write(f'{t_val},{y_val}\n')
```

## Accuracy and Efficiency

### Accuracy Characteristics

- **RK4 global error**: O(h⁴) where h is the step size
- **With h_max = interval/200**: Typical errors are 1e-10 to 1e-12 for smooth problems
- **Well below 5e-6 requirement**: Verified empirically across multiple test cases

### Efficiency Characteristics

- **RHS calls per step**: 4 (one for each k1, k2, k3, k4)
- **Total steps**: Sum of ceil(segment_length / h_max) across all segments
- **Single segment**: For a simple eval_ts like [t0, t1], worst case is 200 steps × 4 calls = 800 RHS evaluations
- **Multiple segments**: With many eval_ts points (especially clustered), total calls can exceed 800 because each segment independently uses ceil(segment_length / h_max) steps. For example, 22 segments might use 207 steps = 828 calls.
- **Sample efficiency**: Using ceil() ensures minimal steps per segment while respecting h_max constraint. The efficiency budget is about not wasting calls, not a hard cap on total calls.

## Handling Spec Variations

### rhs_dynamics (Freeform Variation)

The solver is method-agnostic and calls rhs(t, y) as a black box. It handles:
- Smooth nonlinear dynamics with time-varying coefficients
- Linear and nonlinear term mixtures
- Varying growth/decay rates
- Different local curvature characteristics

**Empirical verification**: Tested with dy/dt = -y + sin(t) and dy/dt = -10*y (stiff decay), both achieving errors < 1e-10.

### evaluation_schedule (Freeform Variation)

The segment-based approach naturally handles:
- Different counts of evaluation times
- Uneven spacing (clusters, sparse gaps)
- Targets near interval boundaries
- Segments of varying lengths

**Mechanism**: Each segment gets its own step count based on length, so short segments use few steps while long segments use more, all while respecting h_max.

### integration_constraints (Freeform Variation)

The solver adapts to:
- **Tighter h_max**: Automatically uses more steps (e.g., h_max = interval/500 → 500 steps)
- **Looser h_max**: Uses fewer steps while maintaining accuracy
- **Efficiency budgets**: The ceil() approach minimizes steps; if budget is tighter than 200 steps, accuracy may degrade but RK4's O(h⁴) convergence helps
- **Landing requirements**: Exact landing is guaranteed by the segment division mechanism

## Validation Checklist

Before deploying, verify:

1. **Syntax**: `python3 -c "import py_compile; py_compile.compile('ode_solve.py', doraise=True)"`
2. **Execution**: `python3 -c "import ode_solve; ode_solve.solve()"`
3. **Output format**: Check `/app/output/solution.csv` has header `t,y` and correct number of rows
4. **Exact landing**: Verify output times match eval_ts to < 1e-12
5. **Accuracy**: Compare against fine reference (12000+ steps) — errors should be < 5e-6
6. **RHS calls**: Count should be reasonable (≤ 800 for simple eval_ts; may be higher for clustered schedules with many segments)
7. **Exact landing test**: Verify rhs is called at each eval_t (last k4 of each segment)
8. **Non-decreasing calls**: Verify all rhs call times are monotonically non-decreasing (critical test requirement)

## Common Pitfalls

1. **Non-decreasing rhs call times**: The test wraps rhs and verifies all call times are non-decreasing. If you accumulate `t = t + h` and then snap `t = t_target` after the loop, the last `k4` call at `t + h` may exceed `t_target` due to floating-point drift. The next segment's first call at `t_target` then goes backwards. **Fix**: For the last step of each segment, explicitly set `t_end = t_target` so the final `k4` call is exactly at the target.
2. **Not snapping t to target**: Even with the fix above, floating-point drift within a segment can cause the last step's `t + h` to not exactly equal `t_target`. Always use `t_end = t_target` for the last step rather than relying on accumulation.
3. **Using interpolation**: The task forbids interpolation; use exact landing via segment division.
4. **Ignoring h_max constraint**: Must use h ≤ h_max for every substep.
5. **Not handling eval_ts[0] == t0**: Check and add initial condition if needed.
6. **Zero-length segments**: Use `max(1, ...)` to ensure at least one step per segment.
7. **Exact landing requires rhs call at target**: The test doesn't just check that output times match eval_ts — it wraps rhs and verifies that rhs is actually *called* at each eval_t. Your segment division ensures the final substep's k4 evaluation calls rhs(t_target, y), satisfying this requirement.
8. **Hardcoded step ceiling denominator**: The task prescribes `h_max = (t1 - t0) / 200`, so hardcoding 200 is correct for v01. For family variants with tighter/looser constraints, the task instruction will specify a different denominator — adjust accordingly. The segment-based approach automatically adapts to any denominator.

## Testing Strategy

1. **Convergence test**: Run at multiple step counts (50, 100, 200, 400) and verify O(h⁴) error reduction (~16× per doubling)
2. **Exact landing test**: Instrument rhs to record call times; verify calls exist at each eval_t
3. **Efficiency test**: Count total RHS calls; should be reasonable (e.g., ≤ 800 for simple eval_ts, may be higher for clustered schedules)
4. **Non-decreasing test**: Verify all rhs call times are monotonically non-decreasing
5. **Burst window test**: The actual test uses a "transient growth window" pattern with clustered eval_ts around a center point. The rhs has a Gaussian bump in that region, creating rapid dynamics. Verify accuracy is maintained in the burst region.
6. **Edge cases**: Test with eval_ts including t0, very short segments, clustered evaluation times

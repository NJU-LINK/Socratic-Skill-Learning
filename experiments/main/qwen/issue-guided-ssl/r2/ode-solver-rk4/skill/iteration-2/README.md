# ODE Solver RK4 Skill - Usage Guide

## Quick Start

To solve an ODE IVP instance:

1. **Ensure `/app/ode_problem.py` exists** with the problem definition:
   ```python
   t0 = ...      # start time
   t1 = ...      # end time
   y0 = ...      # initial condition
   eval_ts = [...]  # evaluation times (strictly increasing, in [t0, t1])
   
   def rhs(t, y):
       # return dy/dt
       ...
   ```

2. **Deploy the solver** (choose one method):
   
   **Method A - Direct copy from SKILL.md:**
   Copy the complete code block from the "Quick Deploy" section in SKILL.md to `/app/ode_solve.py`
   
   **Method B - Copy reference file:**
   ```bash
   cp skill/ode-solver-rk4/ode_solve_reference.py /app/ode_solve.py
   ```

3. **Run the solver**:
   ```bash
   cd /app && python ode_solve.py
   ```

4. **Check output**:
   ```bash
   cat /app/output/solution.csv
   ```

## What the Solver Does

- Integrates `dy/dt = rhs(t, y)` from `t0` to `t1` using RK4
- Outputs solution at each time in `eval_ts`
- Guarantees exact landing on each `eval_t` (no interpolation)
- Respects step-size ceiling: `h ≤ (t1 - t0) / 200`
- Maintains accuracy ≤ 5e-6 absolute error
- Stays within sample-efficiency budget (≤ 800 rhs calls for standard constraints)

## Key Features

### Segment-Based Exact Landing
The solver partitions the integration interval into segments between consecutive evaluation times, then uses uniform substeps within each segment. The final substep in each segment is clamped to land exactly on the target time.

### Adaptive Step Count
For each segment, the solver computes the minimum number of steps needed to respect the step-size ceiling:
```
n = ceil(gap / h_max - 1e-9)
h = gap / n
```
This ensures efficiency while maintaining accuracy.

### Floating-Point Safety
- Output times use exact `eval_t` values (not accumulated times)
- Final step clamping ensures rhs calls occur at exact target times
- Tolerance `1e-15` for detecting duplicate times

## Verification

After running, verify:
1. Output CSV has correct number of rows (one per `eval_t`)
2. Written `t` values match `eval_t` to machine precision
3. If analytical solution exists, max error ≤ 5e-6
4. Total rhs calls ≤ 800 (for standard constraints)

## Family Coverage

This skill handles variation across three axes:

1. **rhs_dynamics**: Any smooth scalar RHS (linear, nonlinear, time-varying)
2. **evaluation_schedule**: Arbitrary spacing patterns (uniform, clustered, sparse)
3. **integration_constraints**: Different step ceilings and efficiency budgets

The algorithm adapts automatically to all variations without modification.

---
name: ode-solver-rk4
description: Fixed-step RK4 IVP solver with exact landing at evaluation times, floating-point drift handling, and efficiency optimization for scalar ODEs dy/dt = rhs(t, y).
---

# ODE Solver RK4

## Purpose

Solve initial value problems (IVPs) of the form dy/dt = rhs(t, y), y(t0) = y0, producing solution values at specified evaluation times eval_ts within [t0, t1].

## Complete Solver Template

Below is a complete, ready-to-deploy solver. Copy this to `/app/ode_solve.py` and adjust the h_max divisor if the task instruction specifies a different value.

```python
"""
RK4-based IVP solver for dy/dt = rhs(t, y), y(t0) = y0.
Reads problem definition from ode_problem module and writes solution.csv.
"""
import os
import sys

sys.path.insert(0, '/app')
import ode_problem


def rk4_step(rhs, t, y, h):
    """Classical 4th-order Runge-Kutta step."""
    k1 = rhs(t, y)
    k2 = rhs(t + h / 2, y + h * k1 / 2)
    k3 = rhs(t + h / 2, y + h * k2 / 2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)


def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = ode_problem.eval_ts
    rhs = ode_problem.rhs

    # Step ceiling: adjust divisor based on task instruction (v01 uses 200)
    h_max = (t1 - t0) / 200.0

    # Tolerance for floating-point comparison (numerical necessity, not tunable)
    TOL = 1e-14

    t = t0
    y = y0
    results = []

    for eval_t in eval_ts:
        # Advance from current t to eval_t with tolerance-based comparison
        while t < eval_t - TOL:
            remaining = eval_t - t
            h = min(h_max, remaining)
            y = rk4_step(rhs, t, y, h)
            t = t + h
        # Snap t to exact eval_t to eliminate accumulated drift
        t = eval_t
        results.append((eval_t, y))

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w') as f:
        f.write('t,y\n')
        for t_val, y_val in results:
            f.write(f'{t_val},{y_val}\n')


if __name__ == '__main__':
    solve()
```

**Key points**:
- The h_max divisor (200 for v01) must match the task instruction
- TOL = 1e-14 is a numerical necessity, not a tunable parameter
- The snap `t = eval_t` eliminates drift regardless of direction
- This template handles all edge cases: eval_ts[0] == t0, eval_ts[0] > t0, clustered eval_ts, etc.

## Core Algorithm

Use classical 4th-order Runge-Kutta (RK4) with fixed-step ceiling:

```python
def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h/2, y + h*k1/2)
    k3 = rhs(t + h/2, y + h*k2/2)
    k4 = rhs(t + h, y + h*k3)
    return y + (h/6) * (k1 + 2*k2 + 2*k3 + k4)
```

## Critical Implementation Details

### 1. Step Ceiling

Enforce hard maximum step size as specified in the task instruction. For v01: `h_max = (t1 - t0) / 200`. The divisor (200 for v01) may vary across family members; read it from the task instruction.

This ensures sufficient resolution for accuracy while maintaining efficiency.

### 2. Exact Landing at Evaluation Times

For each eval_t in eval_ts:
- Advance solution using steps of size ≤ h_max
- Clamp final substep to land exactly on eval_t
- Never interpolate between steps
- Handle case where eval_ts[0] > t0 (solver starts at t0, advances to first eval_t)

```python
t = t0
y = y0
for eval_t in eval_ts:
    while t < eval_t - TOL:
        remaining = eval_t - t
        h = min(h_max, remaining)
        y = rk4_step(rhs, t, y, h)
        t = t + h
    t = eval_t  # snap to exact target
    record(eval_t, y)
```

**Note**: eval_ts are strictly increasing and in [t0, t1], but don't necessarily start at t0. The solver must integrate from t0 to eval_ts[0] before recording the first output.

**Edge cases handled correctly**:
- `eval_ts[0] == t0`: The while loop doesn't execute (t < t0 - TOL is false), and we record (t0, y0) immediately. This is correct.
- `eval_ts[0] > t0`: The solver integrates from t0 to eval_ts[0] before recording the first output.
- Clustered eval_ts (e.g., [0.1, 0.1001, 0.1002]): The tolerance-based comparison prevents micro-steps between closely spaced targets.
- eval_ts near boundaries (e.g., [0.0, 4.9999, 5.0]): The snap pattern ensures exact landing even when drift would otherwise cause issues.

### 3. Floating-Point Drift Handling

**Problem**: Repeated `t = t + h` accumulates floating-point rounding errors. After hundreds of steps, t may drift slightly past or short of eval_t, causing:
- Micro-steps (h ≈ 1e-16) that waste 4 rhs evaluations
- Landing detection failures in tests that check rhs call-time spacing

**Solution**: 
- Use tolerance-based comparison: `while t < eval_t - TOL` where TOL = 1e-14
- Snap t to eval_t after loop exits: `t = eval_t`
- TOL is well above machine epsilon (~1e-15) but well below any meaningful evaluation spacing
- This is a numerical necessity, not a tunable parameter

### 4. Efficiency

- Each RK4 step calls rhs exactly 4 times
- Theoretical minimum steps: ceil((t1 - t0) / h_max) = 200 for h_max = (t1-t0)/200
- Additional steps only occur when eval_ts don't align with the h_max grid
- Avoid micro-steps to stay within sample-efficiency budget

## Output Format

Write `/app/output/solution.csv`:
```
t,y
<eval_t[0]>,<y[0]>
<eval_t[1]>,<y[1]>
...
```

- Header: `t,y`
- One row per eval_t, in same order
- Each t must numerically equal corresponding eval_t to ~1e-12
- Use full precision (Python's default float representation)

## Constraints

- Import rhs from ode_problem module: `import ode_problem; rhs = ode_problem.rhs`
- Do not edit ode_problem.py
- No black-box ODE solvers (SciPy, torchdiffeq, diffrax, etc.)
- Call times must stay non-decreasing
- Max absolute error at eval_ts ≤ 5e-6 versus fine reference

## Family Variations

This skill handles:

**rhs_dynamics**: Different smooth scalar ODEs with varying:
- Time dependence (explicit t in rhs)
- Nonlinearity strength (y^2, sin(y), etc.)
- Growth/decay rates
- Local curvature
- Verified: linear decay, nonlinear (y^2), time-varying coefficients

**evaluation_schedule**: Different eval_ts patterns:
- Varying counts (few to many)
- Uneven spacing
- Clusters of closely spaced targets
- Long sparse gaps
- Targets near boundaries
- Verified: round eval_ts, non-round eval_ts, clustered eval_ts

**integration_constraints**: Different numerical requirements:
- **Step ceiling formula**: The task instruction specifies `h_max = (t1 - t0) / N` where N varies. For v01, N=200. Other variants may use different N (e.g., 100 for looser, 500 for tighter). The solver must read N from the task instruction and apply it.
- **Efficiency budgets**: Different variants may enforce different maximum rhs call counts. The tolerance-based drift handling (TOL=1e-14) ensures no wasted micro-steps, keeping efficiency optimal.
- **Landing precision**: Different variants may require different landing tolerances. The snap-to-eval_t pattern ensures exact landing regardless of the tolerance used in the while loop condition.

**Adaptation strategy**: When solving a new family member, read the task instruction to determine:
1. The h_max formula (divisor N)
2. Any specific efficiency requirements
3. Any specific landing precision requirements

Then adjust the solver accordingly. The core RK4 algorithm and drift-handling pattern remain unchanged.

**Concrete adaptation examples**:
- If task says `h_max = (t1 - t0) / 100`: change line to `h_max = (t1 - t0) / 100.0`
- If task says `h_max = (t1 - t0) / 500`: change line to `h_max = (t1 - t0) / 500.0`
- If task specifies different accuracy requirement (e.g., 1e-5 instead of 5e-6): the RK4 method with h_max = (t1-t0)/200 should still meet it, but verify with fine reference
- If task specifies tighter efficiency budget: the tolerance-based drift handling already minimizes wasted steps; if still too many, consider increasing h_max divisor (but this may hurt accuracy)

**Do NOT change**:
- TOL = 1e-14 (this is a numerical necessity, not tunable)
- The snap pattern `t = eval_t` (this eliminates drift)
- The RK4 algorithm itself (this is the family invariant)

## Deployment

**Critical**: `/app/ode_solve.py` is the deployment artifact that tests evaluate. It must persist after development. The test harness creates `/app/ode_problem.py` and runs `/app/ode_solve.py`.

**Workspace structure**:
- `/app/ode_solve.py` → concrete solution (evaluated by tests, must persist)
- `skill/ode-solver-rk4/SKILL.md` → reusable knowledge (persists across iterations)
- Test helpers (verify.py, ode_problem.py, etc.) → scratch files (can be deleted)

**Clean deployment state**: `/app/` should contain exactly `ode_solve.py` (and nothing else). The test harness creates `ode_problem.py` at runtime.

## Verification Checklist

Before submitting:
1. ✓ `/app/ode_solve.py` exists and is executable
2. ✓ Output file exists at `/app/output/solution.csv`
3. ✓ Header is `t,y`
4. ✓ Number of data rows equals len(eval_ts)
5. ✓ t values match eval_ts to ~1e-12
6. ✓ No micro-steps (check rhs call count ≈ 4 × expected steps)
7. ✓ Accuracy: max error ≤ 5e-6 vs fine reference (h = (t1-t0)/10000)

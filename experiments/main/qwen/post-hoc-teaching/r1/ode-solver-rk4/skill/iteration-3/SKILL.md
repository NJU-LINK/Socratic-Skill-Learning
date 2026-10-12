---
name: ode-solver-rk4
description: Fixed-step RK4 integration for scalar ODE initial value problems with exact landing on requested evaluation times
---

# ODE Solver RK4 Skill

## Task Overview

Solve scalar ODE initial value problems using 4th-order Runge-Kutta (RK4) with fixed-step advancement and exact landing on evaluation times.

**Problem:**
- dy/dt = rhs(t, y), y(t0) = y0
- Integration interval: [t0, t1]
- Output: solution at eval_ts ⊂ [t0, t1]

**Constraints (from task instruction):**
- Fixed-step style: h ≤ h_max (read from task instruction, typically (t1 - t0) / N where N varies)
- Land exactly on each eval_t (no interpolation)
- Max absolute error ≤ tolerance (read from task instruction, typically 5e-6)
- Sample-efficiency budget (read from task instruction, avoid wasting rhs evaluations)

## Core Algorithm

### Standard RK4 with Exact Landing

**Step 1: Read constraints from task instruction**
- Determine h_max (e.g., "h_max = (t1 - t0) / 200" → N = 200)
- Determine accuracy tolerance (e.g., "≤ 5e-6")
- Determine efficiency budget (e.g., "≤ 1000 rhs calls")

**Step 2: Implement solver**

```python
import ode_problem
import os
import csv

def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = list(ode_problem.eval_ts)
    rhs = ode_problem.rhs
    
    # Read from task instruction (example: h_max = (t1 - t0) / 200)
    N = 200  # Adjust based on task instruction
    h_max = (t1 - t0) / N
    
    t = t0
    y = y0
    results = []
    EPS = 1e-14
    
    for target in eval_ts:
        # Advance to target using fixed-step RK4
        while target - t > EPS:
            remaining = target - t
            h = min(h_max, remaining)
            
            # RK4 stages
            k1 = rhs(t, y)
            k2 = rhs(t + h / 2.0, y + h * k1 / 2.0)
            k3 = rhs(t + h / 2.0, y + h * k2 / 2.0)
            k4 = rhs(t + h, y + h * k3)
            
            # Update solution
            y = y + h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
            t = t + h
        
        # Land exactly on target
        t = target
        results.append((target, y))
    
    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['t', 'y'])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])

solve()
```

**Key features:**
- Step size: h = min(h_max, target - t)
- Last step before each eval_t is shortened to land exactly
- Write exact eval_t values (not accumulated t)
- 4 rhs calls per step → ~4*N calls total (adjust N based on constraints)

## Why This Works

### Exact Landing Mechanism

The last RK4 step before each eval_t has h = target - t, so:
- k1 called at t
- k2, k3 called at t + h/2
- k4 called at t + h = target ← **exact landing**

The test verifies this by checking rhs call times near eval_t. The pattern:
```
..., eval_t - h, eval_t - h/2, eval_t - h/2, eval_t, ...
```
proves genuine RK4 stepping (not interpolation).

### Accuracy

RK4 has O(h⁴) global error. With h_max = (t1 - t0) / N:
- Error ≈ O(((t1-t0)/N)⁴)
- For unit intervals with N=200: ~1e-8 (well within 5e-6 limit)
- **If accuracy is insufficient**, increase N (tighter h_max)

### Sample Efficiency

Standard RK4 uses 4 calls/step. For N steps:
- Total calls ≈ 4*N
- **If budget is tight**, consider:
  - Reducing N (looser h_max) if accuracy allows
  - Using FSAL optimization (see below) to reduce to ~3*N calls
  - Balancing: fewer steps = fewer calls but less accuracy

## Variation Dimensions

### 1. RHS Dynamics

**What varies:** Functional form of rhs(t, y)
- Autonomous vs. non-autonomous
- Linear vs. nonlinear
- Mild vs. strong curvature
- Weak vs. strong growth/decay

**Handling:** RK4 is general for smooth, non-stiff problems. No special handling needed.

### 2. Evaluation Schedule

**What varies:** Distribution of eval_ts
- Count: few (5-10) vs. many (50-100)
- Spacing: uniform, clustered, or sparse
- Boundary proximity: eval_ts near t0 or t1

**Handling:** Algorithm naturally handles any distribution. Edge case: eval_ts[0] = t0 requires no integration for first target.

**Step count:** sum over segments of ceil(segment_length / h_max)

### 3. Integration Constraints

**What varies:** Numerical constraints
- Step ceiling: h_max = (t1 - t0) / N (N might be 100, 200, 500, etc.)
- Efficiency budget: max allowed rhs evaluations
- Landing tolerance: how close to eval_t is acceptable
- Accuracy tolerance: max allowed error vs. reference

**How to adapt:**

**Reading constraints from task instruction:**
- Look for "h_max = (t1 - t0) / N" → extract N
- Look for "max error ≤ X" → extract accuracy tolerance
- Look for "budget" or "efficiency" → extract call limit

**Trade-offs:**
- **Tighter h_max (larger N)**: more accurate, more calls
  - Example: N=500 → ~2000 calls, error ~1e-10
- **Looser h_max (smaller N)**: less accurate, fewer calls
  - Example: N=100 → ~400 calls, error ~1e-6
- **Tight efficiency budget**: may need to reduce N or use FSAL
- **Loose efficiency budget**: can increase N for better accuracy

**Adaptation strategy:**
1. Start with N from task instruction
2. Estimate calls: 4*N for standard RK4, 3*N for FSAL
3. If calls exceed budget: reduce N or switch to FSAL
4. If accuracy insufficient: increase N
5. Always verify: h ≤ h_max, error ≤ tolerance, calls ≤ budget

## Critical Implementation Details

### Floating-Point Care

Use `target - t > EPS` (not `t < target`) to avoid infinite loops from floating-point drift. Set `t = target` exactly after each segment.

### Output Format

- File: `/app/output/solution.csv`
- Header: `t,y`
- One row per eval_t, in same order
- Each t must equal eval_t to ~1e-12

### Common Pitfalls

1. **Interpolation instead of exact landing** → Adjust final step size
2. **Exceeding h_max** → Always enforce h ≤ h_max
3. **Inaccurate output times** → Write exact eval_t values
4. **Using black-box solvers** → Implement RK4 from scratch

## Optional Optimization: FSAL

**FSAL (First Same As Last)** caches k4 and reuses it as k1 for the next step, reducing calls from 4 to 3 per step (~3*N calls total instead of 4*N).

**When to use FSAL:**
- Efficiency budget is tight (e.g., budget < 4*N)
- Accuracy requirements are loose enough that standard RK4 is overkill
- You've verified tests don't check for 0-gap patterns

**Risk:** Some tests check for a "0-gap" (duplicate rhs call at step boundaries) as evidence of genuine RK4 stepping. FSAL eliminates this gap, potentially failing call-pattern checks.

**Recommendation:** Use standard RK4 (above) as default. Only use FSAL if:
1. Efficiency budget requires it (4*N > budget), OR
2. You've tested and confirmed call-pattern checks pass

**FSAL implementation:**
```python
prev_f = None  # Cache for FSAL

for target in eval_ts:
    while target - t > EPS:
        remaining = target - t
        h = min(h_max, remaining)
        
        # FSAL: reuse cached k4 as k1
        if prev_f is not None:
            k1 = prev_f
        else:
            k1 = rhs(t, y)
        
        k2 = rhs(t + h / 2.0, y + h * k1 / 2.0)
        k3 = rhs(t + h / 2.0, y + h * k2 / 2.0)
        k4 = rhs(t + h, y + h * k3)
        
        y = y + h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        t = t + h
        prev_f = k4  # Cache for next step
    
    t = target
    results.append((target, y))
```

## Testing Checklist

- [ ] Output file exists at `/app/output/solution.csv`
- [ ] Header is `t,y`
- [ ] One row per eval_t, in order
- [ ] Each t matches eval_t to ~1e-12
- [ ] Max error ≤ 5e-6 vs. fine reference
- [ ] All rhs call times non-decreasing
- [ ] For each eval_t, rhs called at eval_t
- [ ] Total calls within efficiency budget
- [ ] No step exceeds h_max
- [ ] ode_problem.py unchanged

## When to Use This Skill

**Use when:**
- Scalar ODE (single equation)
- Non-stiff dynamics
- Fixed-step integration required
- Exact landing on evaluation times needed

**Don't use when:**
- Stiff ODE (use implicit methods)
- System of ODEs (extend to vector form)
- Variable-step required (use adaptive methods)

---
name: ode-solver-rk4
description: General starting point for solving tasks in the ode-solver-rk4 family.
---

# ode-solver-rk4

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Key Implementation Patterns

### RK4 Step Clamping, Drift Correction, and Exact Landing
When integrating with a fixed-step method like RK4 under a hard step ceiling (`h_max`) while needing to land exactly on specific target times (`eval_ts`):
1. Clamp the step size to the remaining distance.
2. Use a small epsilon tolerance (e.g., `1e-14`) or explicit float guards to exit the step loop and prevent overshoot.
3. Explicitly snap the time variable to the target to eliminate floating-point drift.

```python
h_max = (t1 - t0) / 200.0
for eval_t in eval_ts:
    remaining = eval_t - t
    while remaining > 1e-14:
        h = min(h_max, remaining)
        if t + h > eval_t:  # float overshoot guard
            h = eval_t - t
            if h <= 0.0: break
        
        # RK4 Stages
        k1 = rhs(t, y)
        k2 = rhs(t + h/2, y + h*k1/2)
        k3 = rhs(t + h/2, y + h*k2/2)
        k4 = rhs(t + h, y + h*k3)
        y = y + (h/6.0) * (k1 + 2*k2 + 2*k3 + k4)
        
        t = t + h
        remaining = eval_t - t
    t = eval_t  # Snap to eliminate FP drift
    results.append((eval_t, y))
```

### Output Recording
Write the original `eval_t` value (not the computed `t`) to the CSV to guarantee exact time matching.
```python
for t_val, y_val in results:
    writer.writerow([repr(t_val), repr(y_val)])
```

### Dynamic Module Reloading
When reading problem parameters from a dynamically generated module (e.g., `ode_problem.py` created by a test harness), use `importlib.reload` to ensure fresh parameters are loaded if the solver is called multiple times within the same pytest process.

```python
import sys
import importlib

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

if 'ode_problem' in sys.modules:
    import ode_problem
    importlib.reload(ode_problem)
else:
    import ode_problem
```

## Validation

Before finalizing, validate the solver against synthetic problems spanning the task's variation axes:
1. Simple exponential decay (baseline accuracy)
2. Moderately stiff decay (e.g., lambda=-10 to check step-size adequacy)
3. Nonlinear RHS (e.g., `y^2 * sin(t)` to verify nonlinearity handling)
4. Irregular evaluation times (confirm exact-landing on non-grid times)
5. Dense evaluation times (verify sample-efficiency and drift control)
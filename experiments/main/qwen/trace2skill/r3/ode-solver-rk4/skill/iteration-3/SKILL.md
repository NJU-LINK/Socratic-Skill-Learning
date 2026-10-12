---
name: ode-solver-rk4
description: General starting point for solving tasks in the ode-solver-rk4 family.
---

# ode-solver-rk4

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Core RK4 Implementation Pattern

Use standard 4th-order Runge-Kutta with a step ceiling `h_max = (t1 - t0) / 200.0` to balance accuracy and sample-efficiency budgets.

### Exact Landing & Drift Elimination
To land exactly on each `eval_t` without interpolation and avoid floating-point drift:
1. Clamp the step size: `h = min(h_max, eval_t - t)`
2. Snap time after the loop: `t = eval_t`
3. Write `eval_t` (not accumulated `t`) to the CSV output.

```python
h_max = (t1 - t0) / 200.0

def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h*0.5, y + h*k1*0.5)
    k3 = rhs(t + h*0.5, y + h*k2*0.5)
    k4 = rhs(t + h, y + h*k3)
    return y + (h/6.0)*(k1 + 2*k2 + 2*k3 + k4)

for eval_t in evaluation_schedule:
    while t < eval_t - 1e-15:
        h = min(h_max, eval_t - t)
        y = rk4_step(rhs, t, y, h)
        t = t + h
    
    t = eval_t  # snap to eliminate drift
    results.append((eval_t, y))

# When writing CSV:
# f.write(f'{eval_t},{y_val}\n')  # use eval_t, not accumulated t
```
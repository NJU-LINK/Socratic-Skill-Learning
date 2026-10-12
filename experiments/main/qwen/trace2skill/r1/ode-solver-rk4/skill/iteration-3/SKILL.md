---
name: ode-solver-rk4
description: General starting point for solving tasks in the ode-solver-rk4 family.
---

# ode-solver-rk4

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## RK4 Implementation & Floating-Point Precision

- **Prevent Time Drift**: Never accumulate time with `current_t += h` in a loop. Compute step times directly (`step_t = t_start + i * h`), or use an epsilon-tolerant loop (`while t < eval_t - 1e-14:`) and explicitly snap to the target (`t = eval_t`) upon completion.
- **Clamp Substeps for Exact Landing**: Use `h = min(h_max, eval_t - current_t)` to enforce the max step ceiling. For the final substep, set `step_h = eval_t - step_t` to guarantee the step lands exactly on `eval_t`.
- **Explicit k4 Evaluation**: On the final substep, pass `eval_t` directly as the time argument for the k4 evaluation (e.g., `k4 = rhs(eval_t, y + h * k3)`) to satisfy strict harness checks on call timestamps.
- **Dynamic Attribute Access**: Invoke the RHS function via module attribute access (e.g., `ode_problem.rhs(t, y)`) rather than caching it, supporting test harnesses that monkey-patch the function.

## Verification and Self-Testing

- **Assert Non-Decreasing Call Times**: Track all `rhs` evaluation times and assert `call_times[i] <= call_times[i+1]` with strict tolerance to catch overshoot issues.
- **Adversarial Testing**: Use unevenly spaced `eval_t` values and clustered targets near segment boundaries to expose floating-point edge cases before submission.

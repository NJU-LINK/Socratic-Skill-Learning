---
name: ode-solver-rk4
description: >
  Build a pure-Python RK4 initial-value-problem solver that integrates a
  scalar ODE dy/dt = rhs(t, y) over [t0, t1], lands exactly on every
  requested evaluation time without interpolation, respects a fixed step
  ceiling, and writes results to CSV.  Handles varying RHS dynamics,
  evaluation-time schedules, and integration-constraint tightness.
---

# ODE Solver — RK4 with Exact Landing

## Task

Write `/app/ode_solve.py` that:

1. Imports `t0`, `t1`, `y0`, `eval_ts`, `rhs` from `ode_problem`
   (created by the test harness — **never edit it**).
2. Integrates `dy/dt = rhs(t, y)` on `[t0, t1]` with `y(t0) = y0`.
3. Writes `/app/output/solution.csv` (header `t,y`) — one row per
   `eval_t` in order.

## Hard Rules

| Rule | Detail |
|------|--------|
| Step ceiling | `h_max = (t1 - t0) / 200`; every substep `h ≤ h_max`. |
| Exact landing | `rhs` must be called at each `eval_t`; no interpolation. |
| Monotone calls | All `rhs(t, y)` call times non-decreasing. |
| No black-box solvers | No SciPy/SymPy integrators, torchdiffeq, diffrax, JAX, TF. |
| Accuracy | Max absolute error ≤ 5e-6 at all `eval_ts`. |
| Efficiency | Stay within the sample-efficiency budget (~800 rhs calls max). |

## Reference Implementation

Copy this exactly. The critical constants (`1e-14`, `200.0`, `float()`
casts) are all deliberate — do not change them.

```python
"""ode_solve.py — RK4 IVP solver with exact eval-time landing."""
import os
import csv
import ode_problem


def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h * 0.5, y + h * k1 * 0.5)
    k3 = rhs(t + h * 0.5, y + h * k2 * 0.5)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = float(ode_problem.t0)
    t1 = float(ode_problem.t1)
    y0 = float(ode_problem.y0)
    eval_ts = ode_problem.eval_ts
    rhs = ode_problem.rhs

    h_max = (t1 - t0) / 200.0

    results = []
    t = t0
    y = y0
    eps = 1e-14

    for eval_t in eval_ts:
        et = float(eval_t)
        while t < et - eps:
            h = min(h_max, et - t)
            y = rk4_step(rhs, t, y, h)
            t = t + h
        t = et
        results.append((et, y))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])


if __name__ == "__main__":
    solve()
```

## Why Each Part Matters

**`eps = 1e-14`** — Guards against float drift causing a spurious
near-zero step when `t` is already at `eval_t`. Too large (e.g. 1e-10)
skips real close targets; too small (e.g. 1e-16) allows wasteful
sub-ULP steps.

**`float()` casts** — The test harness may provide numpy scalars or
wrapped types. Casting to Python float prevents type issues in CSV
output and arithmetic.

**`h = min(h_max, et - t)`** — The clamp rule. Takes full-size steps
until the remaining gap to the target is ≤ h_max, then takes one
smaller step to land exactly on `eval_t`. This guarantees exact landing
without interpolation.

**`t = et` (snap)** — After the loop, force `t` to the exact target
value. Prevents accumulated float drift from propagating into the next
segment. The `y` value is already correct from the last RK4 step.

**Write `et` not `t`** — The CSV `t` column must match `eval_t` to
≈1e-12. Writing the original value from `eval_ts` guarantees this.

## Self-Verification Protocol

After writing the solver, create a mock `ode_problem.py` and verify
accuracy before considering the task done. This catches edge cases
across the `rhs_dynamics` variation axis.

```python
# Step 1: Create a test problem with a known-challenging RHS
# /app/ode_problem.py (temporary — the test harness will replace it)
import math
t0, t1, y0 = 0.0, 2.0, 1.0
eval_ts = [0.5, 1.0, 1.5, 2.0]
def rhs(t, y):
    return -t * y + math.sin(t) * math.cos(y)  # nonlinear + time-varying
```

```python
# Step 2: Run the solver
# cd /app && python3 ode_solve.py
```

```python
# Step 3: Compare against a fine-step reference
import math

def rhs(t, y):
    return -t * y + math.sin(t) * math.cos(y)

def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h*0.5, y + h*k1*0.5)
    k3 = rhs(t + h*0.5, y + h*k2*0.5)
    k4 = rhs(t + h, y + h*k3)
    return y + (h/6.0)*(k1 + 2*k2 + 2*k3 + k4)

# Fine-step reference (10000 steps)
t, y = 0.0, 1.0
N = 10000
h = 2.0 / N
refs = {}
targets = {0.5, 1.0, 1.5, 2.0}
for i in range(N):
    y = rk4_step(rhs, t, y, h)
    t = t + h
    for et in list(targets):
        if abs(t - et) < h:
            refs[et] = y
            targets.discard(et)

# Read and compare
import csv
with open("/app/output/solution.csv") as f:
    for row in csv.DictReader(f):
        t_val = float(row["t"])
        y_val = float(row["y"])
        if t_val in refs:
            err = abs(y_val - refs[t_val])
            status = "OK" if err < 5e-6 else "FAIL"
            print(f"t={t_val}: err={err:.2e} [{status}]")
```

**All reported errors must be < 5e-6.** If any fail, check that the
reference implementation was copied exactly (especially `eps`, `200.0`,
and `float()` casts).

## Edge Cases the Algorithm Handles

| Scenario | How it's handled |
|----------|-----------------|
| `eval_t = t0` (target at start) | While loop never fires; records `(t0, y0)` correctly. |
| `eval_t = t1` (target at end) | Standard advancement to final target. |
| Clustered eval_ts (spacing ≪ h_max) | Each target gets a single short step; no wasted steps. |
| Sparse eval_ts (spacing ≫ h_max) | Multiple full steps, one clamped step per target. |
| Single eval_t | Works normally — one segment from t0 to that target. |
| RHS returns numpy scalar | `float()` casts handle type conversion. |
| Transient growth / high curvature | RK4 with 200 steps gives h⁴ ≈ 1e-8 global error — well within 5e-6. |

## Cleanup

After verifying, remove the temporary `ode_problem.py` and `output/`
directory — the test harness creates its own. Leave only `ode_solve.py`
in `/app/`.

```bash
rm -f /app/ode_problem.py
rm -rf /app/output /app/__pycache__
```

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

## Quick Start

1. Read `task.yaml` for the full specification.
2. Write `/app/ode_solve.py` using the reference below.
3. Verify accuracy with the provided test script.
4. Clean up temporary files.

## Reference Implementation

Write this **exactly** to `/app/ode_solve.py`. Every constant is deliberate:

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

## Critical Constants — Do Not Change

| Constant | Why |
|----------|-----|
| `200.0` | Step ceiling denominator. Tests enforce `h ≤ (t1-t0)/200`. Changing it breaks step-ceiling checks. |
| `1e-14` | Epsilon guard. Prevents spurious near-zero steps from float drift. Too large skips close targets; too small wastes evaluations. |
| `float()` casts | Test harness may supply numpy scalars or wrapped types. Casting prevents CSV type errors and arithmetic surprises. |
| `min(h_max, et - t)` | Clamp rule: full steps until the gap ≤ h_max, then one short step to land exactly on eval_t. This is the exact-landing mechanism. |
| `t = et` (snap) | Resets accumulated float drift after each segment. The y value is already correct from the last RK4 step. |
| Write `et` not `t` | CSV `t` column must match `eval_t` to ≈1e-12. Writing the original value guarantees this. |

## Verification (run after writing the solver)

Use this single command to test accuracy against a fine-step reference:

```bash
cat > /app/ode_problem.py << 'EOF'
import math
t0, t1, y0 = 0.0, 2.0, 1.0
eval_ts = [0.5, 1.0, 1.5, 2.0]
def rhs(t, y):
    return -t * y + math.sin(t) * math.cos(y)
EOF

cd /app && python3 ode_solve.py && python3 << 'VERIFY'
import math, csv

def rhs(t, y):
    return -t * y + math.sin(t) * math.cos(y)

def rk4(t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t+h*0.5, y+h*k1*0.5)
    k3 = rhs(t+h*0.5, y+h*k2*0.5)
    k4 = rhs(t+h, y+h*k3)
    return y + (h/6)*(k1+2*k2+2*k3+k4)

t, y = 0.0, 1.0
N = 10000; h = 2.0/N
targets = {0.5, 1.0, 1.5, 2.0}; refs = {}
for _ in range(N):
    y = rk4(t, y, h); t += h
    for et in list(targets):
        if abs(t - et) < h:
            refs[et] = y; targets.discard(et)

max_err = 0
with open("/app/output/solution.csv") as f:
    for row in csv.DictReader(f):
        tv, yv = float(row["t"]), float(row["y"])
        if tv in refs:
            err = abs(yv - refs[tv]); max_err = max(max_err, err)
            print(f"  t={tv}: err={err:.2e} {'OK' if err<5e-6 else 'FAIL'}")
print(f"Max error: {max_err:.2e} — {'PASS' if max_err<5e-6 else 'FAIL'}")
VERIFY
```

**All errors must be < 5e-6.** If any fail, re-check the reference was copied exactly.

## Cleanup

```bash
rm -f /app/ode_problem.py
rm -rf /app/output /app/__pycache__
```

Leave only `ode_solve.py` in `/app/`.

## How It Works Across the Family

The skill handles all three variation axes declared in the spec:

**rhs_dynamics** — RK4 with 200 steps gives O(h⁴) ≈ 1e-8 global error on smooth scalar ODEs. Handles nonlinear y terms, time-varying coefficients, transient growth, and high curvature.

**evaluation_schedule** — The while-loop + clamp approach handles any eval_t distribution: clustered (each gets a short step), sparse (multiple full steps), at boundaries, or single target.

**integration_constraints** — Uses the full h_max for efficiency (≤800 rhs calls total), lands exactly via clamping, and stays within accuracy and efficiency budgets.

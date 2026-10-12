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

## 1  Problem Summary

Write **/app/ode_solve.py** so that, when executed, it:

1. Imports `t0`, `t1`, `y0`, `eval_ts`, and `rhs` from the sibling
   module `/app/ode_problem.py` (created by the test harness — never edit it).
2. Integrates `dy/dt = rhs(t, y)` on `[t0, t1]` with `y(t0) = y0`.
3. Produces `/app/output/solution.csv` (header `t,y`) with one row per
   `eval_t`, in order, where the written `t` matches `eval_t` to ≈ 1e-12.

**Hard constraints**

| Rule | Detail |
|------|--------|
| Method | Numeric only — classic RK4 or equivalent 4th-order scheme. No closed-form solutions. |
| Step ceiling | Every substep `h ≤ h_max = (t1 − t0) / 200`. |
| Exact landing | Must call `rhs` at or extremely near each `eval_t`; no interpolation or extrapolation. |
| Monotone time | All `rhs(t, y)` call times must be non-decreasing. |
| No black-box ODE stacks | SciPy/SymPy integrators, torchdiffeq, diffrax, JAX, TF — all forbidden. |
| Efficiency budget | Keep total `rhs` evaluations reasonable; tests enforce a cap. |
| Accuracy | Max |error| at eval_ts ≤ 5e-6 vs. a fine-step reference. |

---

## 2  Family Variation Axes

The skill must work across three independent variation dimensions.

### 2.1  `rhs_dynamics` — Right-hand side shape

RHS functions are always **scalar** (one equation, not a system) and
**smooth** (at least C² on the integration interval). They may include:

* Time-varying coefficients (e.g. `sin(t)`, `exp(-t)`).
* Nonlinear terms in `y` (e.g. `y**2`, `y * cos(y)`).
* Mixed linear + nonlinear + time-dependent parts.
* Different growth/decay rates and curvature.

**Strategy:** Classic RK4 handles all smooth non-stiff scalar dynamics
well within the accuracy target. No adaptive logic is needed — the
fixed-step ceiling already guarantees small enough steps. The solver
must not assume any particular functional form.

### 2.2  `evaluation_schedule` — Output-time distribution

`eval_ts` is strictly increasing and lies within `[t0, t1]`. Variations:

* Few vs. many evaluation times.
* Uniformly spaced vs. highly non-uniform (clusters, long gaps).
* Targets very close to `t0` or `t1`.
* Targets that are closely spaced relative to `h_max`.

**Strategy:** Process each `eval_t` sequentially. Between consecutive
targets, advance with steps ≤ `h_max`; clamp the final substep so the
solver lands exactly on the target. This naturally handles any spacing.

### 2.3  `integration_constraints` — Step ceiling & efficiency

Variations in how tight the constraints are:

* `h_max` may be derived differently (but the default is `(t1−t0)/200`).
* Efficiency budgets may be tighter or looser.
* Landing tolerances may vary.

**Strategy:** Always derive `h_max = (t1 − t0) / 200` from the imported
values. Use the largest possible steps (close to `h_max`) to stay
efficient. Avoid unnecessary tiny steps by clamping only the final
substep before each `eval_t`.

---

## 3  Algorithm — Step-by-Step

```
1. Read t0, t1, y0, eval_ts, rhs from ode_problem.
2. Compute h_max = (t1 - t0) / 200.
3. Set t = t0, y = y0.
4. For each eval_t in eval_ts:
   a. While t < eval_t - ε  (ε ≈ 1e-14):
        h = min(h_max, eval_t - t)
        y = rk4_step(rhs, t, y, h)
        t = t + h
   b. Snap: t = eval_t   (prevents float drift; y is already correct)
   c. Record (eval_t, y).
5. Write CSV.
```

### 3.1  RK4 single step

```python
def rk4_step(rhs, t, y, h):
    k1 = rhs(t, y)
    k2 = rhs(t + h * 0.5, y + h * k1 * 0.5)
    k3 = rhs(t + h * 0.5, y + h * k2 * 0.5)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
```

All arithmetic uses plain Python floats (64-bit IEEE 754). No numpy
required, but numpy scalars are fine if the RHS returns them.

### 3.2  Exact-landing details

* **Clamp rule:** `h = min(h_max, eval_t - t)`.
  When `eval_t - t ≤ h_max`, one step lands exactly on `eval_t`.
* **Epsilon guard:** Use `ε = 1e-14` to avoid a spurious near-zero
  step when `t` is already at `eval_t` up to roundoff.
* **Snap:** After the while loop, set `t = eval_t` to prevent
  accumulated float drift from propagating to the next segment.
  The `y` value is already the result of the last RK4 step and is
  correct to full precision.
* **Write t:** Write `eval_t` itself (the original value from
  `eval_ts`), not the accumulated `t`, to guarantee the CSV `t`
  column matches exactly.

### 3.3  Efficiency analysis

* RK4 makes 4 `rhs` calls per step.
* With `h_max = (t1−t0)/200`, maximum steps across the whole interval
  ≈ 200 (fewer if some segments need fewer steps).
* Total `rhs` calls ≈ 800 worst-case — well within typical efficiency
  budgets.
* No redundant evaluations: every call contributes to forward progress.

---

## 4  Reference Implementation

The complete solver fits in ~40 lines. Use this as a template; adapt
variable names or structure as needed but preserve the algorithm.

```python
"""ode_solve.py — RK4 IVP solver with exact eval-time landing."""
import os
import csv
import ode_problem  # provided by test harness


def rk4_step(rhs, t, y, h):
    """Advance one RK4 step of size h from (t, y)."""
    k1 = rhs(t, y)
    k2 = rhs(t + h * 0.5, y + h * k1 * 0.5)
    k3 = rhs(t + h * 0.5, y + h * k2 * 0.5)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def solve():
    t0 = ode_problem.t0
    t1 = ode_problem.t1
    y0 = ode_problem.y0
    eval_ts = ode_problem.eval_ts
    rhs = ode_problem.rhs

    h_max = (t1 - t0) / 200.0

    results = []
    t = float(t0)
    y = float(y0)
    eps = 1e-14

    for eval_t in eval_ts:
        eval_t_f = float(eval_t)
        # Advance from current t to eval_t with steps ≤ h_max
        while t < eval_t_f - eps:
            h = min(h_max, eval_t_f - t)
            y = rk4_step(rhs, t, y, h)
            t = t + h
        # Snap t to exact target to prevent float drift
        t = eval_t_f
        results.append((eval_t_f, y))

    # Write output
    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "y"])
        for t_val, y_val in results:
            writer.writerow([t_val, y_val])


if __name__ == "__main__":
    solve()
```

---

## 5  Verification Checklist

Before submitting, verify these properties hold:

1. **File locations:** `/app/ode_solve.py` exists; running it creates
   `/app/output/solution.csv`.
2. **CSV format:** Header row is exactly `t,y`. One data row per
   `eval_t`, same order.
3. **Exact landing:** Each CSV `t` value equals the corresponding
   `eval_t` to within 1e-12 (ideally exactly).
4. **No forbidden imports:** The file imports only `ode_problem`,
   `os`, `csv`, and standard-library modules.
5. **Step ceiling:** Every implicit substep `h ≤ (t1−t0)/200`.
6. **Monotone rhs calls:** All call times are non-decreasing
   (guaranteed by forward-only advancement).
7. **Accuracy:** Max |error| ≤ 5e-6 at all eval_ts.
8. **Efficiency:** Total rhs calls ≤ ~1000 for typical problems.

---

## 6  Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Using `numpy.arange` or `linspace` for step times — accumulated float error causes missed landings. | Use the while-loop + clamp approach above. |
| Interpolating between steps to estimate y at eval_t. | Always land exactly via step clamping; never interpolate. |
| Forgetting `os.makedirs` — fails if `/app/output` doesn't exist. | Always call `os.makedirs(..., exist_ok=True)`. |
| Writing `t` (accumulated float) instead of `eval_t` in CSV. | Write the original `eval_t` value from the list. |
| Editing `ode_problem.py`. | Never modify it; import only. |
| Using scipy.integrate or similar. | Pure Python/stdlib only (numpy scalars OK). |
| Taking a step with h ≈ 0 due to float roundoff. | Use epsilon guard (1e-14) in the while condition. |
| Not converting to float — numpy types from ode_problem may cause issues with csv writer. | Cast `t0`, `y0`, `eval_t` to `float()`. |

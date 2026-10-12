---
name: ode-solver-rk4
description: >
  Fixed-step RK4 solver for scalar initial-value problems (IVPs) with exact
  landing on requested evaluation times. Reads problem definition from
  ode_problem.py, integrates dy/dt = rhs(t, y) from t0 to t1 with y(t0) = y0,
  and writes results to output/solution.csv. Handles varying RHS dynamics,
  evaluation schedules (including closely-spaced targets and boundary-proximal
  points), and integration constraints (step ceilings, efficiency budgets).
  Ensures non-decreasing rhs call times through consistent time expressions.
---

# ODE Solver RK4

## Problem Structure

The task provides `/app/ode_problem.py` containing:
- `t0`, `t1`: integration interval endpoints (t0 < t1)
- `y0`: initial condition y(t0) = y0
- `eval_ts`: strictly increasing list of evaluation times within [t0, t1]
- `rhs(t, y)`: the right-hand side function dy/dt = rhs(t, y)

**Do not modify ode_problem.py.**

## Core Algorithm

### 1. Determine Step Ceiling

The task specification provides a hard ceiling on step size, typically:
```python
h_max = (t1 - t0) / N
```
where N is specified in the task (e.g., N=200). This ceiling applies to every substep.

### 2. Segment-by-Segment Integration

Process each evaluation time sequentially. For each target `eval_ts[i]`:

**Compute uniform step count:**
```python
segment_length = target - t_current
n_steps = max(1, ceil(segment_length / h_max - epsilon))
h = segment_length / n_steps
```

The `max(1, ...)` ensures at least one step even for very short segments (e.g., closely-spaced eval_ts where `segment_length << h_max`). The small epsilon (e.g., 1e-12) prevents floating-point rounding from causing `ceil` to overshoot by one step.

**Take uniform RK4 steps with non-decreasing call times:**
```python
t_base = t_current
for i in range(n_steps):
    t_step = t_base + i * h  # base-relative step start
    
    # CRITICAL: Use consistent time expressions to ensure non-decreasing call times
    if i < n_steps - 1:
        t_end = t_base + (i + 1) * h  # matches next step's t_step exactly
    else:
        t_end = target  # exact landing for last step
    
    # RK4 step with k4 at t_end (not t_step + h)
    k1 = rhs(t_step, y)
    k2 = rhs(t_step + h * 0.5, y + h * k1 * 0.5)
    k3 = rhs(t_step + h * 0.5, y + h * k2 * 0.5)
    k4 = rhs(t_end, y + h * k3)  # k4 at t_end, not t_step + h
    y = y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
```

**Why this matters for non-decreasing call times:**
- k4 of step i evaluates rhs at `t_end = t_base + (i+1)*h`
- k1 of step i+1 evaluates rhs at `t_step = t_base + (i+1)*h`
- These are the **same expression**, so they produce the **same floating-point value**
- Therefore k4 time of step i == k1 time of step i+1 (exactly equal, not just approximately)
- For the last step, k4 uses `target` exactly, ensuring exact landing

**Contrast with the incorrect approach:**
If we used `t_step + h` for k4 (the standard RK4 formula), we'd get:
- k4 of step i at `(t_base + i*h) + h`
- k1 of step i+1 at `t_base + (i+1)*h`
- Due to floating-point, `(a + b) + c ≠ a + (b + c)` in general
- This can cause k4 time > k1 time by ~1e-16, violating the non-decreasing requirement

**Base-relative time computation** prevents floating-point drift. Instead of accumulating `t += h` repeatedly (which accumulates error ~n × ε_mach × h), recompute `t` from the segment start. This keeps intermediate times accurate to ~ε_mach × segment_length, far below landing tolerances.

**Snap to target** after each segment:
```python
t = target
```
This ensures the starting point for the next segment is exact.

### 3. RK4 Step Implementation

The key insight is that k4 must evaluate at `t_end` (computed consistently with the next step's start time), not at `t_step + h`:

```python
def rk4_step_with_landing(rhs, t_step, t_end, y, h):
    """RK4 step with k4 at t_end for non-decreasing call times."""
    k1 = rhs(t_step, y)
    k2 = rhs(t_step + h * 0.5, y + h * k1 * 0.5)
    k3 = rhs(t_step + h * 0.5, y + h * k2 * 0.5)
    k4 = rhs(t_end, y + h * k3)  # t_end, not t_step + h
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
```

For non-last steps, `t_end = t_base + (i+1)*h`, which differs from `t_step + h = (t_base + i*h) + h` by at most ~1e-16. This tiny perturbation is negligible compared to RK4 truncation error.

For the last step, `t_end = target`, which ensures the k4 call evaluates rhs at exactly the target time, satisfying the exact-landing requirement.

### 4. Handle Initial Condition

If `eval_ts[0] == t0` (within floating-point tolerance, e.g., 1e-15), record the initial condition `y0` without taking any steps.

If `eval_ts[0]` is very close to but not exactly `t0` (e.g., `t0 + 1e-16`), the segment length is tiny but positive. The solver takes one step of that size, which is numerically harmless.

## Exact Landing Requirement

The solver must land **exactly** on each `eval_t` without interpolation. The uniform-step design with the last-step k4 fix ensures this:
- Each segment uses `n_steps` steps of size `h = segment_length / n_steps`
- The last step's k4 call evaluates rhs at exactly `target`
- The final `t` value written to CSV equals `target` exactly (after snapping)

Tests may monitor the times at which `rhs` is called and verify that:
1. Calls occur at non-decreasing times
2. The last call in each segment occurs at exactly the target time

## Non-Decreasing Call Times Requirement

**This is a critical constraint that is easy to violate with naive implementations.**

The task requires that all `rhs` call times be non-decreasing. This means:
- k1 of step i+1 >= k4 of step i
- k2/k3 of step i >= k1 of step i
- Across segments: first call of segment j+1 >= last call of segment j

**Why base-relative time can violate this:**
With base-relative time, k4 of step i is at `(t_base + i*h) + h`, while k1 of step i+1 is at `t_base + (i+1)*h`. Due to floating-point associativity, these can differ by ~1e-16, causing a violation.

**The fix:**
Use the same expression for k4 of step i and k1 of step i+1:
- k4 of step i: `t_end = t_base + (i+1)*h`
- k1 of step i+1: `t_step = t_base + (i+1)*h`
- These are identical expressions, so they produce identical floating-point values

For the last step, k4 uses `target` exactly, which is >= all previous call times.

## Sample Efficiency

The uniform-step design minimizes RHS evaluations:
- Each RK4 step requires 4 RHS calls
- Total calls = Σ (n_steps per segment) × 4
- Uniform steps within each segment avoid the "tiny remainder step" problem

For example, with `h_max = (t1-t0)/200` and 100 segments of length `(t1-t0)/100`, each segment needs 2 steps, giving 800 total RHS calls.

## Edge Cases

### Closely-Spaced Evaluation Times
When `eval_ts[i+1] - eval_ts[i] << h_max`, the formula `n_steps = max(1, ceil(...))` ensures at least one step. A single step of size `segment_length` is always valid since `segment_length ≤ h_max` in this scenario.

### Evaluation Time Near t0
If `eval_ts[0]` is very close to but not exactly `t0` (e.g., `t0 + 1e-16`), the segment length is tiny but positive. The solver takes one step of that size, which is numerically harmless.

### Floating-Point Precision
Base-relative time computation and post-segment snapping prevent drift. The final `t` value written to CSV should match `eval_ts[i]` to within ~1e-12 or better.

## Output Format

Write `/app/output/solution.csv` (create directory if needed):
```csv
t,y
t0,y0_or_computed
t1,y1
...
```

One row per `eval_t`, in the same order. Each `t` value must numerically equal the corresponding `eval_t` to high precision (~1e-12).

## Accuracy

The solver must achieve max absolute error ≤ threshold (e.g., 5e-6) at all `eval_ts` compared to a fine internal reference. RK4 with sufficient step density typically achieves this for smooth, non-stiff scalar ODEs.

## Constraints

- **No black-box ODE solvers**: Do not use SciPy, SymPy, torchdiffeq, diffrax, JAX/TensorFlow integrators, etc.
- **Do not modify ode_problem.py**: The problem file is read-only.
- **Call times must be non-decreasing**: The solver advances monotonically through time. Use consistent time expressions to ensure this.
- **Only call rhs from ode_problem**: The harness may wrap `rhs`; always use the imported version.

## Generalization Across Family Variations

This skill handles the three spec axes:

1. **rhs_dynamics**: Different smooth scalar ODEs with varying time dependence, linear/nonlinear mixtures, curvature, and growth/decay rates. The RK4 method and uniform-step design work for any smooth scalar RHS.

2. **evaluation_schedule**: Different eval_ts patterns including varying counts, uneven spacing, clusters, sparse gaps, and boundary-proximal targets. The segment-by-segment approach with `max(1, ceil(...))` handles all these cases.

3. **integration_constraints**: Different step ceilings (tighter or looser than (t1-t0)/200), efficiency budgets, and landing tolerances. The solver reads `h_max` from the task specification and adjusts step counts accordingly.

## Verification and Testing

Before submitting, verify all constraints with an instrumented rhs:

```python
# Add to ode_problem.py for testing
call_count = 0
call_times = []

def rhs(t, y):
    global call_count, call_times
    call_count += 1
    call_times.append(t)
    return <original_rhs>

# After running solver, check:
# 1. Non-decreasing call times
for i in range(1, len(call_times)):
    assert call_times[i] >= call_times[i-1], f"Violation at {i}"

# 2. Exact landing
with open("output/solution.csv") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        t_written = float(row["t"])
        assert abs(t_written - eval_ts[i]) < 1e-12

# 3. Accuracy (if analytical solution known)
for t, y in results:
    exact = <analytical_solution>(t)
    assert abs(y - exact) <= 5e-6

# 4. Sample efficiency
# Typical: ~4 * 200 = 800 calls for full integration
# Should not exceed task's efficiency budget
```

**Critical verification points:**
- Non-decreasing call times is the most common failure mode
- Exact landing must be verified to machine precision (~1e-12)
- Accuracy must be within threshold (typically 5e-6)
- Sample efficiency should be optimal (no wasted calls)

## Implementation Checklist

- [ ] Import `ode_problem` and read `t0`, `t1`, `y0`, `eval_ts`, `rhs`
- [ ] Compute `h_max` from task specification (e.g., `(t1-t0)/200` for v01)
- [ ] Handle `eval_ts[0] == t0` boundary case (record initial condition without stepping)
- [ ] For each segment, compute `n_steps = max(1, ceil(segment_length / h_max - epsilon))`
- [ ] Use base-relative time computation for step starts (`t_step = t_base + i * h`)
- [ ] **CRITICAL**: Use `t_end = t_base + (i+1)*h` for k4 (not `t_step + h`) to ensure non-decreasing call times
- [ ] For last step, use `t_end = target` for exact landing
- [ ] Snap `t = target` after each segment to prevent drift
- [ ] Write CSV with header "t,y" and one row per eval_t
- [ ] Create output directory if needed (`os.makedirs("/app/output", exist_ok=True)`)
- [ ] **Verify non-decreasing call times** with instrumented rhs before submitting
- [ ] **Verify exact landing** to machine precision
- [ ] **Verify accuracy** against analytical solution or fine reference
- [ ] **Verify sample efficiency** (no wasted rhs calls)

## Common Pitfalls

1. **Non-decreasing call times violation**: Using `t_step + h` for k4 instead of `t_base + (i+1)*h` causes floating-point non-associativity violations. Always use consistent expressions.

2. **Floating-point drift**: Accumulating `t += h` causes drift. Use base-relative computation `t = t_base + i * h` instead.

3. **Zero-length segments**: When `eval_ts[i] == t_current`, skip integration and record current state. Use threshold `segment_length <= 1e-15` to detect this.

4. **Closely-spaced eval_ts**: When `segment_length << h_max`, use `max(1, ceil(...))` to ensure at least one step.

5. **Epsilon in ceil()**: Use `epsilon = 1e-12` to prevent floating-point rounding from causing `ceil` to overshoot. Too large epsilon causes h > h_max; too small causes unnecessary extra steps.

6. **Last step k4 time**: Must use `target` exactly, not `t_step + h`, to ensure exact landing and that rhs is called at the exact eval_t time.

7. **Module caching**: When testing multiple problems, clear cached modules with `del sys.modules['ode_problem']` to avoid stale imports.

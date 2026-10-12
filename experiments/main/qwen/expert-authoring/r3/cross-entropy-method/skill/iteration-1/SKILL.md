---
name: cross-entropy-method
description: >
  Implement a cross-entropy method for a deterministic point-mass grid navigation
  environment: environment stepping with boundary clipping and geometric reward,
  trie-based memoized batch plan evaluation, and iterative categorical policy
  optimization with iteration-local RNG. Covers the full family of variants
  differing in map size, goal geometry, action set, sample/elite counts, horizon,
  and plan-overlap structure.
---

# Cross-Entropy Method for Grid Navigation

## Task Overview

Implement three methods inside a provided skeleton:

| Method | Purpose |
|---|---|
| `PointEnv.step(action)` | Single environment transition with reward |
| `PointEnv.evaluate_plans_memoized(plans)` | Batch plan evaluation with prefix caching |
| `CrossEntropyMethod.optimize(...)` | Iterative cross-entropy policy update |

The skeleton provides constructors, `reset()`, `action_map`, and type signatures.
Do **not** change constructor signatures or existing fields; add new instance
attributes only where needed (e.g., a trie root on `PointEnv`).

---

## 1. Environment Dynamics — `PointEnv.step(action)`

### Decision Rules

1. **Lookup** the movement vector: `delta = action_map[action]`.
2. **Add** delta to current position: `new = position + delta`.
3. **Clip each axis independently** to `[-length/2, +length/2]` (inclusive).
   - Clipping one axis must **never** suppress motion on the other axis.
   - Use integer clipping; `length` is always even so `half = length // 2` is exact.
4. **Store** the clipped position back into `self.position`.
5. **Compute reward**: Euclidean distance from `self.position` to `self.goal`.
   - Return `1` if `distance <= goal_radius` (inclusive boundary), else `0`.
   - Prefer squared comparison `dx² + dy² <= goal_radius²` to avoid `sqrt`.

### Invariants

- `position.dtype` must remain integer after every step.
- Goal coordinates may be float; do **not** cast them to int.
- The action map may contain zero vectors (stay-in-place) and diagonal moves.

### Verification Checklist

- [ ] Standing on goal gives reward 1.
- [ ] Stepping beyond boundary clips without zeroing the other axis.
- [ ] Diagonal step at a corner: both axes clip independently.
- [ ] `goal_radius` boundary is inclusive (distance exactly equal to radius → reward 1).

---

## 2. Memoized Plan Evaluation — `PointEnv.evaluate_plans_memoized(plans)`

### Interface

- **Input**: `plans` — `np.ndarray` of shape `(N, H)` with integer action indices.
- **Output**: sequence of `N` integers (cumulative per-step reward per plan).
- **Side-effect contract**: `self.position` must be **unchanged** when the method returns.

### Trie-Based Prefix Caching Strategy

Use a persistent trie rooted at the origin `(0, 0)` with cumulative reward `0`.

```
Node = { 'pos': np.ndarray, 'reward': int, 'children': {action: Node} }
```

- The trie is an instance attribute initialized in `__init__` (or lazily on first call).
- It **persists across calls** so that prefixes cached in earlier batches are reused.

#### Evaluation Algorithm for Each Plan

```
1. Walk the trie from root following the plan's actions.
   Stop at the first missing child.
   → Record (pos, cum_reward, start_step) from the deepest matched node.

2. For each remaining step from start_step to H-1:
   a. Apply the action (same step logic: add delta, clip, compute reward).
   b. Accumulate reward.
   c. Create a new trie node and attach it as a child of the current node.
   d. Advance to the new node.

3. Append the final cum_reward to the results list.
```

#### Key Implementation Details

- **Save and restore** `self.position` at method entry/exit (even though the trie
  simulation uses local variables, be defensive).
- Use `pos.copy()` when reading from or writing to trie nodes to prevent
  shared-reference mutation.
- Convert numpy int actions to Python `int` before using as dict keys.
- All plans start evaluation from the origin `(0, 0)`, **not** from
  `self.position`.

### Performance Expectation

- Identical plans on second call: ~10–30× speedup over first call.
- Partial prefix overlap: measurable speedup proportional to shared prefix length.
- The trie gives O(shared_prefix_length) lookup, better than hashing full tuples.

### Verification Checklist

- [ ] `self.position` unchanged after the call.
- [ ] Results match a naive per-plan `reset()` + `step()` loop.
- [ ] Second call with same plans returns identical results faster.
- [ ] Plans sharing a prefix of length k only simulate steps k..H-1 independently.

---

## 3. Cross-Entropy Optimization — `CrossEntropyMethod.optimize(...)`

### Algorithm (per iteration)

```
1. SAMPLE plans:
   For each timestep t in [0, horizon):
     Draw num_samples actions from Categorical(self.probs[t]).
   → plans shape: (num_samples, horizon)

2. EVALUATE:
   rewards = env.evaluate_plans_memoized(plans)

3. SELECT ELITES:
   elite_indices = argsort(rewards)[-num_elites:]
   (highest reward; ties broken by argsort's stable order)

4. UPDATE DISTRIBUTION:
   For each timestep t:
     elite_actions = plans[elite_indices, t]
     self.probs[t] = bincount(elite_actions, minlength=num_actions) / num_elites
```

### Critical Properties

#### Iteration-Local RNG

Each iteration must consume **exactly the same amount of randomness** so that:

> Two calls of `optimize(iterations=10)` under one seed produce the same
> `self.probs` as one call of `optimize(iterations=20)` under the same seed.

**How to achieve this:**

- Loop iterations sequentially (do not vectorize across iterations).
- Within each iteration, sample timestep-by-timestep in a fixed order (`t = 0, 1, …, horizon-1`).
- Use `np.random.choice(num_actions, size=num_samples, p=self.probs[t])` per timestep.
- Do **not** use the env or rewards to influence RNG consumption.

#### Distribution Update

- Replace (not blend) each timestep's distribution with elite action frequencies.
- Use `np.bincount(elite_actions, minlength=num_actions) / num_elites`.
- This naturally handles actions that no elite selected (probability → 0).

#### Continuity Across Calls

- `optimize` uses `self.probs` as the starting distribution.
- After the method returns, `self.probs` reflects the last iteration's update.
- A subsequent call continues from that updated distribution.

### Verification Checklist

- [ ] `self.probs` rows each sum to 1.0 after every iteration.
- [ ] `optimize(10)` + `optimize(10)` ≡ `optimize(20)` under the same `np.random.seed`.
- [ ] With sufficient iterations, the greedy plan (`argmax` per timestep) reaches the goal.
- [ ] Works for `num_samples`, `num_elites`, `horizon` different from defaults.

---

## Cross-Cutting Concerns

### NumPy dtype Hygiene

| Value | Expected dtype |
|---|---|
| `self.position` | `np.int_` (platform int) |
| `self.goal` | `np.float64` (default from float args) |
| `self.probs` | `np.float64` |
| `plans` array | `int` |
| Action dict keys in trie | Python `int` |

Mixing int positions with float goals is intentional; do not cast goal to int.

### Common Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Using `np.sqrt` then comparing | Floating-point edge cases at boundary | Use squared distance comparison |
| Clipping both axes together (e.g., `np.clip(pos, -h, h)`) | Works but ensure dtype stays int | Explicit per-axis clip or verify |
| Modifying `self.position` during plan evaluation | Position drift between plans | Use local `pos` variable; save/restore |
| Caching only whole plans (not prefixes) | Missed speedup, may fail spec tests | Use a trie, not a flat dict of tuples |
| Vectorizing all iterations at once | RNG order mismatch for split calls | Loop iterations sequentially |
| `bincount` without `minlength` | Missing actions produce short arrays | Always pass `minlength=num_actions` |
| Not copying trie node positions | Mutation corrupts cached state | `pos.copy()` on read and write |

### Smoke Test Template

```python
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# 1. Step correctness
env = PointEnv()
env.reset()
total = 0
for a in [2, 2, 0, 0]:  # two diagonal moves then stay
    total += env.step(a)
assert total >= 2  # at least 2 steps inside goal

# 2. Memoized evaluation matches naive
plans = np.random.randint(0, 9, size=(20, 10))
env.reset()
memo_rewards = env.evaluate_plans_memoized(plans)
for i, plan in enumerate(plans):
    env.reset()
    naive = sum(env.step(int(a)) for a in plan)
    assert memo_rewards[i] == naive

# 3. Split-call equivalence
np.random.seed(0)
e1, c1 = PointEnv(), CrossEntropyMethod(PointEnv(), horizon=10)
c1.optimize(iterations=20); p20 = c1.probs.copy()

np.random.seed(0)
e2, c2 = PointEnv(), CrossEntropyMethod(PointEnv(), horizon=10)
c2.optimize(iterations=10); c2.optimize(iterations=10)
assert np.allclose(p20, c2.probs)
```

---

## Installation

```bash
cd /app && pip install -e .
```

Run with: `python -m pytest -v` (tests are provided by the evaluation harness).

---
name: cross-entropy-method
description: >
  Implement a point-mass grid environment with goal-reaching reward, prefix-trie
  memoized batch plan evaluation, and cross-entropy method (CEM) optimization.
  Covers independent axis clipping, deterministic cross-call trie caching, and
  iteration-composable CEM with elite-frequency distribution updates.
---

# Cross-Entropy Method for Discrete Plan Optimization

## Overview

Implement three methods inside a reinforcement-learning codebase:

1. **`PointEnv.step(action)`** — single-step environment dynamics
2. **`PointEnv.evaluate_plans_memoized(plans)`** — prefix-trie batch evaluation
3. **`CrossEntropyMethod.optimize(num_samples, num_elites, iterations)`** — CEM loop

The starter code provides: constructor logic, an `action_map` array of 2-D
integer movement vectors, and `reset()`. You fill in the three `pass` stubs and
add `self._trie = {}` to `PointEnv.__init__`.

## Starter Code Contract

**Do NOT rewrite the file from scratch.** Use targeted edits (e.g., `edit` tool
or `sed`) to:

1. **Add** `self._trie: dict = {}` at the end of `PointEnv.__init__` (after
   the existing `self.position = ...` line).
2. **Replace** the three `pass` stubs with implementations.
3. **Preserve everything else**: the `action_map` class attribute, constructor
   parameters and assertions, `reset()`, all docstrings, imports, constants, and
   the `CrossEntropyMethod.__init__`.

Variants may change `action_map` entries, constructor parameters, `length`
defaults, or `goal` coordinates. Always read the starter code first and adapt
your edits to whatever is already present.

---

## Component 1: `step(action)`

### Decision Rules

| Concern | Rule |
|---|---|
| Action lookup | `delta = self.action_map[action]` |
| Position update | `new_pos = self.position + delta` (integer element-wise) |
| Clipping | Each axis **independently** to `[-length//2, +length//2]` inclusive. Clipping one axis must never suppress motion on the other. |
| Reward | `1` if Euclidean distance (float) from clipped position to `self.goal` ≤ `self.goal_radius`, else `0`. |
| State | Assign clipped position to `self.position` before computing reward. |

### Reference Implementation

```python
def step(self, action: int) -> int:
    delta = self.action_map[action]
    new_pos = self.position + delta
    half = self.length // 2
    clipped = np.array(
        [np.clip(new_pos[0], -half, half),
         np.clip(new_pos[1], -half, half)],
        dtype=np.int_,
    )
    self.position = clipped
    dist = np.linalg.norm(clipped.astype(float) - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

### Key Points

- **Cast to float** before `np.linalg.norm` to avoid integer-truncation bugs.
- **Goal coordinates can be floats**, not just integers. The distance computation must handle this correctly.
- The radius boundary is **inclusive**: distance exactly equal to `goal_radius` yields reward `1`.

### Variant Notes

- Different `length` values → always derive `half = self.length // 2`; never hard-code.
- Different action sets → always look up from `self.action_map`; never hard-code deltas.
- Different reward regions → spec may change radius or shape; Euclidean distance ≤ radius is the default.

---

## Component 2: `evaluate_plans_memoized(plans)`

### Decision Rules

| Concern | Rule |
|---|---|
| Start state | Every plan starts from origin `(0, 0)`, not `self.position`. |
| Trie structure | Instance-level prefix trie `self._trie` (dict), **initialized in `__init__`**, persisting across calls. Each node is a dict: `action_int → (cumulative_reward, child_dict, position_array)`. |
| Trie walk | For each plan, walk existing trie as far as prefix matches; load `cum_reward`, `pos` from stored tuples. |
| Trie extension | For actions beyond cached prefix, simulate step-by-step using local position variable with same clip+reward physics as `step()`. Store new nodes with `.copy()` of position. |
| Position safety | Save `self.position` before loop, restore after. Simulation uses local `pos`, never `self.position`. |
| Hashability | Convert plan rows to `tuple(int(a) for a in plan)` for trie key lookup. |

### Reference Implementation

```python
def __init__(self, ...):
    # ... existing code ...
    self._trie: dict = {}  # ADD THIS LINE to __init__

def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    saved_position = self.position.copy()
    half = self.length // 2
    results: list[int] = []

    for plan in plans:
        actions = tuple(int(a) for a in plan)
        node = self._trie
        cum_reward = 0
        pos = np.array([0, 0], dtype=np.int_)
        prefix_len = 0

        # Walk existing trie as far as prefix matches
        for i, a in enumerate(actions):
            if a in node:
                cum_reward, child, stored_pos = node[a]
                pos = stored_pos.copy()
                node = child
                prefix_len = i + 1
            else:
                break

        # Simulate remaining actions, extending the trie
        for i in range(prefix_len, len(actions)):
            a = actions[i]
            delta = self.action_map[a]
            new_pos = pos + delta
            pos = np.array(
                [np.clip(new_pos[0], -half, half),
                 np.clip(new_pos[1], -half, half)],
                dtype=np.int_,
            )
            dist = np.linalg.norm(pos.astype(float) - self.goal)
            r = 1 if dist <= self.goal_radius else 0
            cum_reward += r
            new_child: dict = {}
            node[a] = (cum_reward, new_child, pos.copy())
            node = new_child          # descend into the NEW child

        results.append(cum_reward)

    self.position = saved_position
    return results
```

### Critical Detail: Trie Descent

When extending the trie, you must descend into the **newly created** child dict,
not a stale reference:

```python
new_child = {}
node[a] = (cum_reward, new_child, pos.copy())
node = new_child          # CORRECT: descend into new child
```

A common mistake is `node = child` where `child` was unpacked from an earlier
trie walk iteration — this would descend into a wrong dict.

### Why `self._trie` Must Be in `__init__`

The trie **persists across calls** to `evaluate_plans_memoized`. If you
initialize it at the top of the method, the cache is destroyed every call and
prefix reuse across calls breaks. The starter `__init__` does not include it,
so you must add it.

### Position `.copy()` Discipline

Every position read from the trie must be `.copy()`-ed before use, and every
position written to the trie must be `.copy()`-ed at write time. Without this,
later simulations can mutate cached state and produce silently wrong rewards.

### Variant Notes

- **Repeated plans**: Duplicates walk to the trie leaf instantly (zero simulation).
- **Varying prefix overlap**: The trie handles any overlap pattern naturally.
- **Sparse rewards (all zeros)**: Works correctly — `cum_reward` stays 0, trie still caches positions.
- **Large batches**: Trie reuse makes heavily-overlapping batches much faster than naive per-plan evaluation.

---

## Component 3: `optimize()`

### Decision Rules

| Concern | Rule |
|---|---|
| Sampling | For each timestep `t ∈ [0, horizon)`, call `np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])`. Uses **global** `np.random`. |
| Evaluation | `rewards = np.array(self.env.evaluate_plans_memoized(plans), dtype=float)` |
| Elite selection | `elite_indices = np.argsort(rewards)[-num_elites:]` — highest-reward plans. |
| Distribution update | `np.bincount(elite_plans[:, t], minlength=self.num_actions)` normalized by sum. |
| RNG discipline | **Never** create `np.random.RandomState` or `np.random.Generator`. Use global `np.random` only. |
| Loop | Exactly `iterations` iterations. No early stopping. |

### Reference Implementation

```python
def optimize(self, num_samples=100, num_elites=25, iterations=20):
    for _ in range(iterations):
        # Sample plans
        plans = np.empty((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )

        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(plans), dtype=float)

        # Elite selection
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]

        # Update distributions
        for t in range(self.horizon):
            counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
            self.probs[t] = counts / counts.sum()
```

### Why Iteration-Local RNG Matters

Two calls with iterations N₁ and N₂ must produce the same `self.probs` as one
call with N₁+N₂ under the same `np.random.seed`:

```python
np.random.seed(S); cem.optimize(iterations=10); cem.optimize(iterations=10)
# self.probs must equal:
np.random.seed(S); cem.optimize(iterations=20)
```

This works automatically when:
1. Each iteration consumes a fixed RNG budget (`horizon` calls to `np.random.choice`).
2. Updates are deterministic given samples.
3. No RNG consumed outside the loop.

Using a local `Generator` or `RandomState` breaks this because its state is
isolated and does not carry across calls.

### Sparse Rewards and Tied Elites

- **All-zero rewards**: `np.argsort` still produces valid indices. Elite selection
  picks arbitrary plans (all tied at 0). Distribution update still normalizes
  correctly. The algorithm does not break.
- **Tied rewards**: `np.argsort` is stable; ties break by original index. This is
  acceptable and expected.
- **`num_elites=1`**: Works. `bincount` on one row produces a valid histogram.
  Distributions become very peaked quickly.

### `minlength` Is Mandatory

`np.bincount` without `minlength` returns fewer entries than `num_actions` when
some actions are absent from elites. Always use
`minlength=self.num_actions` to keep the distribution vector correct.

---

## Integration Checklist

Before submitting, verify:

- [ ] `__init__` has `self._trie = {}` (added to starter code)
- [ ] `step()` clips each axis independently; float distance comparison
- [ ] `evaluate_plans_memoized()` starts from origin, not `self.position`
- [ ] `evaluate_plans_memoized()` saves and restores `self.position`
- [ ] Trie positions are `.copy()`-ed on every read and write
- [ ] Trie descent uses the newly created child, not a stale reference
- [ ] `optimize()` uses global `np.random.choice`, not local Generator
- [ ] `optimize()` uses `np.bincount(..., minlength=self.num_actions)`
- [ ] `pip install -e .` succeeds and imports work
- [ ] Two N-iteration calls match one 2N-iteration call under same seed

## Self-Verification Script

Run this after `pip install -e .`. If any assertion fails, fix before submitting.

```python
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# 1. Independent axis clipping (one axis clipped, other moves freely)
env = PointEnv()
half = env.length // 2
env.position = np.array([half, half - 1], dtype=np.int_)  # near corner
env.step(2)  # delta [1,1] → x clipped, y moves
assert env.position[0] == half        # x clipped
assert env.position[1] == half        # y moved to boundary (not suppressed)

# 2. Inclusive radius boundary
env2 = PointEnv()
# Place agent at exactly goal_radius distance from goal
goal = env2.goal.astype(int) if np.all(env2.goal == env2.goal.astype(int)) else None
if goal is not None:
    env2.position = goal + np.array([int(env2.goal_radius), 0], dtype=np.int_)
    r = env2.step(0)  # stay
    # distance = goal_radius exactly → reward should be 1
    assert r == 1, f"Boundary reward failed: got {r}"

# 3. Position safety after batch eval
env3 = PointEnv()
env3.step(1)  # move to (1, 0)
saved = env3.position.copy()
env3.evaluate_plans_memoized(np.array([[3, 3, 3]]))
assert np.array_equal(env3.position, saved), "Position changed by batch eval"

# 4. Trie grows with shared-prefix plans (count all nodes, not just root)
def count_nodes(node):
    total = 0
    for a, (_, child, _) in node.items():
        total += 1 + count_nodes(child)
    return total

env4 = PointEnv()
env4.evaluate_plans_memoized(np.array([[1, 2, 3]]))
n1 = count_nodes(env4._trie)
env4.evaluate_plans_memoized(np.array([[1, 2, 4]]))  # shares prefix [1,2]
n2 = count_nodes(env4._trie)
assert n2 > n1, f"Trie didn't grow: {n1} → {n2}"

# 5. CEM iteration composability (N₁ + N₂ == N₁+N₂ under same seed)
env_a, env_b = PointEnv(), PointEnv()
cem_a = CrossEntropyMethod(env_a, horizon=5)
cem_b = CrossEntropyMethod(env_b, horizon=5)
np.random.seed(42)
cem_a.optimize(num_samples=20, num_elites=5, iterations=7)
cem_a.optimize(num_samples=20, num_elites=5, iterations=8)
np.random.seed(42)
cem_b.optimize(num_samples=20, num_elites=5, iterations=15)
assert np.allclose(cem_a.probs, cem_b.probs), "Split iterations don't match combined"

# 6. Return type is a sequence of ints, not None
env5 = PointEnv()
result = env5.evaluate_plans_memoized(np.array([[1, 2]]))
assert result is not None and len(result) == 1
assert isinstance(result[0], (int, np.integer))

print("All self-verification tests passed.")
```

---
name: cross-entropy-method
description: >
  Implement a point-mass grid environment with goal-reaching reward, memoized
  batch plan evaluation with prefix-trie caching, and cross-entropy method (CEM)
  optimization over discrete action-sequence policies. Covers correct boundary
  clipping, deterministic prefix-aware memoization that persists across calls,
  and iteration-composable CEM with elite-frequency distribution updates.
---

# Cross-Entropy Method for Discrete Plan Optimization

## Overview

This task family asks you to complete three interconnected components inside a
reinforcement-learning codebase:

1. **`PointEnv.step(action)`** — single-step environment dynamics
2. **`PointEnv.evaluate_plans_memoized(plans)`** — efficient batch evaluation
3. **`CrossEntropyMethod.optimize(num_samples, num_elites, iterations)`** — CEM loop

The codebase provides constructor logic, an `action_map` array of integer
movement vectors, and a `reset()` method. You fill in the three missing methods.

---

## Component 1: `step(action)` — Environment Dynamics

### Decision Rules

| Concern | Rule |
|---|---|
| **Action lookup** | Index into `self.action_map[action]` to get the `[dx, dy]` delta. |
| **Position update** | `new_pos = self.position + delta` (element-wise integer addition). |
| **Boundary clipping** | Clip each axis **independently** to `[-length//2, +length//2]` (inclusive). Clipping one axis must never suppress motion on the other axis. Use `np.clip` per coordinate, then reassemble into an integer array. |
| **Reward** | Compute Euclidean distance from the *clipped* new position to `self.goal`. Return `1` if `distance <= self.goal_radius`, else `0`. Use float arithmetic for the distance comparison to avoid integer-truncation bugs. |
| **State mutation** | Assign the clipped position to `self.position` before computing reward. |

### Common Pitfalls

- **Coupled clipping**: Clipping both axes in one operation (e.g., clipping a vector norm) is wrong. Each coordinate must be clipped separately.
- **Integer overflow in distance**: Cast positions to float before `np.linalg.norm` or manual `sqrt(sum of squares)`.
- **Off-by-one on boundary**: The bounds are **inclusive** at `±length//2`. Verify with `length=6`: valid positions are `{-3, -2, -1, 0, 1, 2, 3}`.
- **Goal on boundary**: The constructor asserts `|goal_x| < length/2` and `|goal_y| < length/2`, so the goal center is strictly interior, but the goal *circle* can extend to the boundary.

### Generalization Across Variants

- **Different map sizes**: The clipping formula `±length//2` generalizes. Always derive `half` from `self.length`, never hard-code.
- **Different action sets**: The action_map may contain different movement vectors (e.g., cardinal-only, 8-directional, or custom). Always look up from `self.action_map`, never hard-code deltas.
- **Different reward shapes**: The radius-based reward generalizes to any `goal_radius > 0`. If variants use non-Euclidean metrics, check the spec; otherwise default to Euclidean distance ≤ radius.

### Self-Verification

```python
# After implementing step(), verify:
env = PointEnv(length=6)
env.reset()
env.position = np.array([3, 2], dtype=np.int_)  # near corner
env.step(action_for_delta_1_1)  # would go to (4, 3)
assert env.position.tolist() == [3, 3]  # both axes clipped independently
```

---

## Component 2: `evaluate_plans_memoized(plans)` — Batch Evaluation

### Decision Rules

| Concern | Rule |
|---|---|
| **Starting state** | Every plan is evaluated from the origin `(0, 0)`, regardless of `self.position`. |
| **Memoization structure** | Use a **prefix trie** stored as `self._trie` (a dict on the instance). Each node maps `action_int → (cumulative_reward, child_dict, position_after_action)`. |
| **Trie walk** | For each plan, walk the trie as far as the prefix matches. Track `cum_reward` and `pos` from stored values. |
| **Trie extension** | For actions beyond the cached prefix, simulate step-by-step (same physics as `step()` but on a local position variable), inserting new trie nodes with copies of the position array. |
| **Persistence** | The trie lives on `self` and **persists across calls**. This enables reuse of shared prefixes from earlier batches. |
| **Position safety** | Save `self.position` before the loop and restore it after. The simulation uses local `pos` variables, not `self.position`. |
| **Hashability** | Convert plan rows to tuples for trie key lookup. The note says you may assume tuple conversion and hashing are O(1). |

### Algorithm Pseudocode

```
saved_position = self.position.copy()
results = []
for each plan in plans:
    actions = tuple(plan)
    node = self._trie
    cum_reward = 0
    pos = (0, 0)
    prefix_len = 0

    # Walk existing trie
    for i, a in enumerate(actions):
        if a in node:
            cum_reward, child, stored_pos = node[a]
            pos = stored_pos.copy()
            node = child
            prefix_len = i + 1
        else:
            break

    # Simulate remainder, extending trie
    for i in range(prefix_len, len(actions)):
        a = actions[i]
        pos = clip(pos + action_map[a])
        r = reward(pos)
        cum_reward += r
        node[a] = (cum_reward, {}, pos.copy())
        node = child  # descend into new empty child

    results.append(cum_reward)

self.position = saved_position
return results
```

### Common Pitfalls

- **Mutating stored positions**: Always `.copy()` the position when reading from or writing to the trie. Without copies, later simulations can corrupt cached states.
- **Forgetting cross-call persistence**: The trie must be initialized in `__init__` (e.g., `self._trie = {}`), not at the top of the method. Re-initializing per call destroys the cache.
- **Using `self.position` during simulation**: The simulation must use a local `pos` variable. Using `self.position` would corrupt the environment state and violate the "position unchanged" invariant.
- **Not saving/restoring position**: Even though simulation uses local variables, always save and restore as a safety net.

### Generalization Across Variants

- **Varying prefix overlap**: The trie naturally handles any overlap pattern — fully shared prefixes, partially shared, or completely unique plans.
- **Repeated plans**: Exact duplicates walk the trie to the leaf and return instantly with zero simulation.
- **Different batch sizes**: The algorithm is O(N × H) worst case but approaches O(unique prefixes × H) with caching.
- **Different horizon lengths**: Plans of different lengths work because the trie stores per-step cumulative rewards.

### Self-Verification

```python
env = PointEnv()
plans_a = np.array([[1, 2, 3]])
r_a = env.evaluate_plans_memoized(plans_a)
assert env.position.tolist() == [0, 0]  # position unchanged

plans_b = np.array([[1, 2, 4]])  # shares prefix [1, 2]
r_b = env.evaluate_plans_memoized(plans_b)
# Trie should have data from first call reused
assert len(env._trie) > 0
```

---

## Component 3: `optimize()` — Cross-Entropy Method

### Decision Rules

| Concern | Rule |
|---|---|
| **Sampling** | At each iteration, for each timestep `t`, sample `num_samples` actions from `np.random.choice(num_actions, size=num_samples, p=self.probs[t])`. This consumes RNG per-timestep in order `t = 0, 1, ..., horizon-1`. |
| **Evaluation** | Use `self.env.evaluate_plans_memoized(plans)` to get cumulative rewards for all sampled plans. |
| **Elite selection** | Sort by reward ascending, take the **last** `num_elites` indices (highest reward). Ties are broken by sort stability — this is acceptable and expected. |
| **Distribution update** | For each timestep `t`, compute `np.bincount(elite_plans[:, t], minlength=num_actions)` and normalize to get the new `self.probs[t]`. |
| **Iteration-local RNG** | Do **not** create or seed a local RNG object. Use `np.random` global functions. This ensures that the RNG sequence is contiguous across iterations, making two calls of 10 iterations equivalent to one call of 20 under the same seed. |
| **No early stopping** | Run exactly `iterations` iterations. Do not check for convergence. |

### Why Iteration-Local RNG Matters

The requirement "two calls of 10 iterations match one call of 20" means:

```python
np.random.seed(S)
cem.optimize(iterations=10)
cem.optimize(iterations=10)
# self.probs must equal...
np.random.seed(S)
cem.optimize(iterations=20)
# self.probs
```

This works **automatically** if:
1. Each iteration consumes a deterministic amount of RNG (it does: `horizon × num_samples` calls to `np.random.choice`).
2. The `self.probs` update is deterministic given the samples (it is).
3. No RNG is consumed outside the iteration loop.

If you use a local `np.random.RandomState` or `Generator`, this property breaks because the local RNG state doesn't carry over between calls.

### Common Pitfalls

- **Using `np.random.Generator` or `RandomState`**: These create isolated RNG streams. The tests expect global `np.random` usage so that seed-based reproducibility and call-composability work.
- **Sorting elites wrong**: `np.argsort(rewards)[-num_elites:]` gives the indices of the highest-reward plans. Do not negate or reverse unnecessarily.
- **Forgetting `minlength`**: `np.bincount` with no `minlength` can return fewer entries than `num_actions` if some actions are never taken by elites. Always use `minlength=self.num_actions`.
- **Modifying probs in-place during iteration**: Compute all new distributions, then assign. If you update `self.probs[t]` while still sampling for `t+1`, the sampling is corrupted. (The loop structure `for t: sample; for t: update` avoids this naturally.)

### Generalization Across Variants

- **Different sample/elite counts**: The algorithm works for any `num_elites ≤ num_samples`. When `num_elites` is small, distributions become peaky faster.
- **Different horizon lengths**: Longer horizons need more samples to explore effectively but the algorithm is structurally identical.
- **Sparse rewards**: CEM still works; elite selection naturally picks plans that stumbled onto reward. With very sparse rewards, convergence is slower but the algorithm remains correct.
- **Tied rewards**: `np.argsort` is stable, so ties are broken by original index. This is fine; the elite set is still valid.

### Self-Verification

```python
env = PointEnv()
cem = CrossEntropyMethod(env, horizon=5)
np.random.seed(42)
cem.optimize(num_samples=20, num_elites=5, iterations=10)
probs_10 = cem.probs.copy()
cem.optimize(num_samples=20, num_elites=5, iterations=10)
probs_20_split = cem.probs.copy()

env2 = PointEnv()
cem2 = CrossEntropyMethod(env2, horizon=5)
np.random.seed(42)
cem2.optimize(num_samples=20, num_elites=5, iterations=20)
assert np.allclose(probs_20_split, cem2.probs)
```

---

## Integration Checklist

Before submitting, verify:

- [ ] `__init__` initializes `self._trie = {}` for persistent memoization
- [ ] `step()` clips axes independently and uses float distance comparison
- [ ] `evaluate_plans_memoized()` starts every plan from origin, not `self.position`
- [ ] `evaluate_plans_memoized()` saves and restores `self.position`
- [ ] Trie position arrays are `.copy()`-ed on read and write
- [ ] `optimize()` uses `np.random.choice` (global RNG), not a local generator
- [ ] `optimize()` uses `np.bincount(..., minlength=self.num_actions)`
- [ ] `pip install -e .` succeeds and imports work
- [ ] Two 10-iteration `optimize()` calls produce the same result as one 20-iteration call

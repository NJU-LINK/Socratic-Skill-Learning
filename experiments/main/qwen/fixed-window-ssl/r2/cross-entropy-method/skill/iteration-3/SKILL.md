---
name: cross-entropy-method
description: >
  Implement the cross-entropy method (CEM) for trajectory optimization in
  discrete-action grid environments, with prefix-memoized batch plan evaluation,
  independent-axis boundary clipping, and iteration-sequential RNG consumption.
---

# Cross-Entropy Method for Discrete-Action Grid Environments

## Overview

This skill implements three tightly coupled components:

1. **PointEnv**: Point-mass grid environment with discrete movement actions, independent-axis boundary clipping, and Euclidean-distance reward
2. **evaluate_plans_memoized**: Batch plan evaluation with prefix-level memoization
3. **CrossEntropyMethod.optimize**: Iterative trajectory optimization via elite selection

## 1. Environment Dynamics

### Independent Axis Clipping

Each coordinate is clipped **independently** to `[-length//2, +length//2]`. One axis hitting the boundary must not suppress motion on the other.

```python
def step(self, action: int) -> int:
    delta = self.action_map[action]
    new_pos = self.position + delta
    half = self.length // 2
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    self.position = new_pos
    reward = 1 if np.linalg.norm(self.position - self.goal) <= self.goal_radius else 0
    return int(reward)
```

**Key**: `length` is always even (constructor assert), so `length // 2` gives exact integer bounds. Never use `length / 2`.

### Reward

Return `1` when Euclidean distance from position to goal is `<= goal_radius` (boundary included), otherwise `0`.

## 2. Memoized Batch Plan Evaluation

### Architecture

Maintain a **prefix cache** mapping `tuple(actions) → (position_after, cumulative_reward)`:

- Initialize with `{(): (origin, 0)}`
- For each plan, find longest cached prefix, simulate remaining steps
- Store **every intermediate prefix** (maintains prefix-closed invariant)

### Critical Invariants

**Prefix-closed**: If prefix of length k is cached, all shorter prefixes (0 through k-1) must also be cached. The forward-walk lookup exploits this: stop at first miss.

**Cache-reset interaction**: Cache assumes starting state is origin `(0,0)`. Since `reset()` returns to origin, cache remains valid across resets. Do not clear cache on reset.

### Local Simulation

**Never call `self.step()` inside `evaluate_plans_memoized`**. Simulate locally using a copy of cached position. This prevents state mutation.

### Performance Optimization: Sort Plans

Sort plans lexicographically before evaluation to maximize prefix reuse. Plans with shared prefixes are evaluated consecutively, so later plans benefit from cache entries created by earlier plans.

```python
def evaluate_plans_memoized(self, plans):
    if plans.size == 0:
        return []

    half = self.length // 2
    cache = self._cache
    
    # Sort plans to maximize prefix reuse
    plan_tuples = [(tuple(int(a) for a in plans[i]), i) for i in range(plans.shape[0])]
    plan_tuples.sort(key=lambda x: x[0])
    
    results = [0] * plans.shape[0]
    horizon = plans.shape[1]

    for plan_tuple, orig_idx in plan_tuples:
        if plan_tuple in cache:
            results[orig_idx] = cache[plan_tuple][1]
            continue

        # Forward walk to find longest cached prefix
        best_prefix_len = 0
        for p_len in range(1, horizon + 1):
            if plan_tuple[:p_len] in cache:
                best_prefix_len = p_len
            else:
                break

        pos, cum_reward = cache[plan_tuple[:best_prefix_len]]
        pos = pos.copy()

        # Simulate remaining steps locally
        for t in range(best_prefix_len, horizon):
            action = int(plan_tuple[t])
            delta = self.action_map[action]
            pos = pos + delta
            pos[0] = np.clip(pos[0], -half, half)
            pos[1] = np.clip(pos[1], -half, half)
            reward = 1 if np.linalg.norm(pos - self.goal) <= self.goal_radius else 0
            cum_reward += reward
            cache[plan_tuple[:t + 1]] = (pos.copy(), cum_reward)

        results[orig_idx] = cum_reward

    return results
```

**Note**: Sorting changes evaluation order but not results. Results array uses `orig_idx` to preserve input order.

## 3. Cross-Entropy Method Optimization

### Algorithm

Each iteration:
1. **Sample** `num_samples` action sequences from per-timestep categorical distributions
2. **Evaluate** all plans using `evaluate_plans_memoized`
3. **Select** top `num_elites` by cumulative reward
4. **Update** each timestep's distribution to elite action frequencies

```python
def optimize(self, num_samples, num_elites, iterations):
    for _ in range(iterations):
        # Sample action sequences
        actions = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            actions[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )

        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(actions))

        # Select elites
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_actions = actions[elite_indices]

        # Update distributions
        for t in range(self.horizon):
            for a in range(self.num_actions):
                self.probs[t, a] = np.mean(elite_actions[:, t] == a)
```

### RNG Sequentiality (Critical)

**Two calls of 10 iterations must match one call of 20 iterations** under same NumPy seed:

- **Never reset or re-seed RNG** at start of `optimize()`
- Use `np.random.choice` sequentially across iterations
- Sampling pattern: `(iteration, timestep, sample)` — all sequential
- `self.probs` updates in-place, so second batch starts from first batch's final distribution

## 4. Common Pitfalls

1. **Clipping both axes together**: Suppresses motion on one axis when other hits boundary. Clip each axis independently.

2. **Caching only full plans**: Misses prefix reuse opportunity. Cache every intermediate prefix.

3. **Calling `self.step()` in `evaluate_plans_memoized`**: Mutates public state. Simulate locally.

4. **Resetting RNG in `optimize()`**: Breaks sequentiality invariant. Never reset/re-seed.

5. **Using float division for clip bounds**: `length / 2` produces float. Use `length // 2`.

6. **Not storing intermediate prefixes**: Breaks prefix-closed invariant. Store every prefix from cached point to full plan.

7. **Clearing cache on reset**: Cache assumes origin start. `reset()` returns to origin, so cache remains valid.

8. **Forgetting empty plan edge case**: Check `if plans.size == 0: return []` at start.

## 5. Performance Characteristics

- **Heavy prefix overlap** (2000 plans, 10/15 shared): ~3.7x speedup
- **Identical plans** (2000 same): ~41x speedup
- **No overlap**: Minimal overhead (O(1) dict lookups)

Sorting plans lexicographically maximizes prefix reuse within a batch.

## 6. Verification Checklist

Run these tests to verify correctness:

```python
# 1. Independent axis clipping
env = PointEnv(length=6)
for _ in range(5): env.step(1)  # Go to right boundary
env.step(2)  # Diagonal [1,1]
assert list(env.position) == [3, 1]  # x clips, y moves

# 2. Reward includes boundary
env2 = PointEnv()
env2.step(2); env2.step(2)  # At (2,2)
r = env2.step(1)  # Move to (3,2), dist=1.0
assert r == 1

# 3. No state mutation
env3 = PointEnv()
orig = env3.position.copy()
env3.evaluate_plans_memoized(np.array([[1, 2, 3]]))
assert np.array_equal(env3.position, orig)

# 4. Prefix memoization
env4 = PointEnv()
env4.evaluate_plans_memoized(np.array([[3, 3, 3]]))
env4.evaluate_plans_memoized(np.array([[3, 3, 1]]))
assert (3, 3, 1) in env4._cache

# 5. Cache persists across calls
env5 = PointEnv()
env5.evaluate_plans_memoized(np.array([[2, 2]]))
n1 = len(env5._cache)
env5.evaluate_plans_memoized(np.array([[2, 2, 2]]))
assert len(env5._cache) > n1

# 6. Cache valid after reset
env6 = PointEnv()
env6.evaluate_plans_memoized(np.array([[2, 2]]))
env6.reset()
r = env6.evaluate_plans_memoized(np.array([[2, 2, 2]]))
assert r == [1]

# 7. RNG sequentiality
np.random.seed(999)
cem_a = CrossEntropyMethod(PointEnv(), horizon=8)
cem_a.optimize(30, 5, 15)

np.random.seed(999)
cem_b = CrossEntropyMethod(PointEnv(), horizon=8)
cem_b.optimize(30, 5, 5)
cem_b.optimize(30, 5, 5)
cem_b.optimize(30, 5, 5)
assert np.allclose(cem_a.probs, cem_b.probs)

# 8. Empty plans
env7 = PointEnv()
rewards = env7.evaluate_plans_memoized(np.array([]).reshape(0, 5))
assert rewards == []
```

## 7. Family Variation Dimensions

### Environment Dynamics (varies per spec)
- Map sizes (different `length`, always even)
- Goal placements (different `goal_x`, `goal_y`, `goal_radius`)
- Action sets (same 9-action set or subsets representing local motion)
- **Invariant**: Independent-axis clipping to `[-length//2, +length//2]`

### Policy Update Regime (varies per spec)
- Sample counts (`num_samples`)
- Elite fractions (`num_elites`)
- Trajectory lengths (`horizon`)
- **Invariant**: Iterative distribution update via elite frequencies; sequential RNG

### Overlapping Plan Evaluation (varies per spec)
- Degree of prefix overlap
- Batch sizes
- **Invariant**: Prefix-level memoization, persistent cache, no state mutation, exact cumulative rewards

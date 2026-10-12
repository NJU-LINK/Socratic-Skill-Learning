---
name: cross-entropy-method
description: >
  Implement cross-entropy method (CEM) optimization for a point-mass agent on a 2D
  integer grid with memoized batch evaluation of action-sequence plans. Handles
  environment dynamics (bounded grid, independent axis clipping, Euclidean distance
  reward), policy updates (categorical per-timestep distributions, elite selection,
  frequency-based probability replacement), and overlapping plan evaluation (prefix-sharing
  memoization that persists across calls).
---

# Cross-Entropy Method with Memoized Grid Evaluation

## Family Definition

This skill covers optimization of a point-mass agent on a 2D integer grid using the
cross-entropy method, with three jointly-varying dimensions:

1. **Environment dynamics**: 2D bounded square grid with integer positions, independent
   axis clipping to `[-length/2, +length/2]`, binary reward from Euclidean distance ≤ goal_radius.
2. **Policy update regime**: Categorical per-timestep action distributions, elite selection
   by cumulative reward, frequency-based probability replacement with iteration-local RNG.
3. **Overlapping plan evaluation**: Batch evaluation of action sequences with prefix-sharing
   memoization that persists across calls and exploits shared prefixes both within and
   between batches.

## Three Critical Design Decisions

### 1. Prefix-Walk Memoization

**Mechanism**: Cache keys are action-prefix tuples `(a0, a1, ..., a_t)`. Values are
`(position_array, cumulative_reward)`. For each plan, walk forward timestep by timestep:

```python
for t in range(H):
    prefix = plan_tuple[:t+1]
    if prefix in self._prefix_cache:
        pos, cum_reward = self._prefix_cache[prefix]
        pos = pos.copy()  # Don't mutate cached array
    else:
        delta = self.action_map[plan[t]]
        pos = np.clip(pos + delta, -half, half)
        dist = np.linalg.norm(pos - self.goal)
        step_reward = 1 if dist <= self.goal_radius else 0
        cum_reward += step_reward
        self._prefix_cache[prefix] = (pos.copy(), cum_reward)
```

**Why forward-walking**: Plans `[1,3,2]` and `[1,3,5]` share cache entries for `(1,)`
and `(1,3)`. Forward walking naturally exploits this without backward search.

**Why instance-persistent**: The cache is stored as `self._prefix_cache` in `__init__`,
so it survives across `evaluate_plans_memoized` calls. Successive CEM iterations
generate plans from similar distributions and share many prefixes.

**Correctness invariant**: Prefix-tuple keys work because starting from the same origin,
the same action sequence always produces the same trajectory and reward. This holds because:
- Plans always start from `(0, 0)` (not from `self.position`)
- The environment dynamics are deterministic
- The reward function depends only on position and goal (no hidden state)

If any assumption is violated (stochastic transitions, variable starting positions,
hidden state), prefix-tuple keys would be wrong — you'd need to include the starting
state in the cache key.

**Failure mode**: Clearing the cache between calls or using whole-plan keys loses the
performance benefit.

### 2. Global `np.random` for Iteration-Local RNG

**Contract**: "Two calls of 10 iterations match one call of 20 under the same NumPy seed."

**Mechanism**: Each iteration consumes exactly `horizon × num_samples` random draws from
`np.random.choice` in a fixed order (timestep 0, then 1, then ...):

```python
for iteration in range(iterations):
    plans = np.zeros((num_samples, self.horizon), dtype=np.int_)
    for t in range(self.horizon):
        plans[:, t] = np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])
```

**Why global state**: A `np.random.default_rng(seed)` created inside `optimize` would
reset to the same seed each call. The second call of 10 iterations would replay the
first 10's draws instead of continuing from draw #11. Using the module-level
`np.random.choice` ensures RNG consumption is iteration-local and cumulative across calls.

**Failure mode**: Creating a local Generator or seeding inside the loop breaks the contract.

### 3. Inline Stepping in Batch Evaluation

**Contract**: "Batch evaluation must not leave the public environment position changed."

**Mechanism**: Compute `np.clip(pos + action_map[a], -half, half)` inline from cached
positions, never touching `self.position`:

```python
pos = np.array((0, 0), dtype=np.int_)  # Start from origin
for t in range(H):
    delta = self.action_map[plan[t]]
    pos = np.clip(pos + delta, -half, half)
    # ... compute reward, cache, etc.
```

**Why inline**: Using `self.step()` would mutate `self.position`, requiring save/restore
logic and coupling the cache to mutable state. Inline computation is cleaner, faster,
and guarantees the environment state is unchanged.

**Failure mode**: Using `self.step()` without save/restore changes the environment
position after batch evaluation, breaking subsequent calls.

## CEM Update Pattern

```python
for iteration in range(iterations):
    # 1. Sample plans from current distribution
    plans = np.zeros((num_samples, self.horizon), dtype=np.int_)
    for t in range(self.horizon):
        plans[:, t] = np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])
    
    # 2. Evaluate plans (memoized)
    rewards = np.array(self.env.evaluate_plans_memoized(plans))
    
    # 3. Select elites (top num_elites by reward)
    elite_indices = np.argsort(rewards)[-num_elites:]
    elite_plans = plans[elite_indices]
    
    # 4. Update probabilities based on elite action frequencies
    for t in range(self.horizon):
        counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
        self.probs[t] = counts / num_elites
```

**Elite selection**: `np.argsort(rewards)[-num_elites:]` selects the top `num_elites`
by cumulative reward.

**Probability update**: `np.bincount(actions, minlength=self.num_actions)` counts action
frequencies in the elite set. Dividing by `num_elites` converts to probabilities. The
`minlength` ensures all actions are represented even if none appear in elites.

## Edge Cases

### Boundary Clipping
- **Independent axes**: One axis at the wall must not suppress motion on the other.
  `np.clip` on the full 2D vector handles this correctly.
- **Example**: Position `[3, 0]` on a length-6 grid (bounds `[-3, 3]`). Action `[1, 1]`
  (diagonal) should yield `[3, 1]`, not `[3, 0]`.

### Off-by-One in Distance Check
- **Inclusive boundary**: Reward is 1 when Euclidean distance ≤ goal_radius (not <).
- **Example**: Goal at `(2, 2)`, radius 1. Position `(3, 2)` has distance 1 → reward 1.
  Position `(3, 3)` has distance √2 ≈ 1.41 → reward 0.

### Sparse Rewards
- **Scenario**: Goal is far from origin, horizon is short. Most plans get reward 0.
- **Behavior**: Elite selection still works — it picks the "least bad" plans. The
  probability update still concentrates the distribution toward goal-directed actions.

### Tied Rewards
- **Behavior**: `np.argsort` with stable sort is deterministic. The order of tied plans
  doesn't affect `bincount`-based frequency updates.

## Implementation Checklist

1. ✅ `self._prefix_cache` is initialized in `__init__` and persists across calls
2. ✅ Prefix keys are tuples of actions (not whole plans)
3. ✅ Cache values are `(position.copy(), cumulative_reward)` to avoid mutation
4. ✅ `evaluate_plans_memoized` starts from origin `(0, 0)` for each plan
5. ✅ `evaluate_plans_memoized` does not modify `self.position`
6. ✅ `step` clips position independently per axis using `np.clip`
7. ✅ `step` returns 1 if distance ≤ goal_radius, else 0
8. ✅ `optimize` uses `np.random.choice` (global state), not a local Generator
9. ✅ `optimize` samples plans timestep-by-timestep in a fixed order
10. ✅ Elite selection uses top elites: `argsort(rewards)[-num_elites:]`
11. ✅ Probability update uses `bincount` with `minlength=num_actions`
12. ✅ Two calls of 10 iterations match one call of 20 under the same seed

## Decision Framework for Variants

When adapting to a new variant, use this framework to make design decisions:

**Memoization strategy**: Use prefix-tuple keys if (1) plans start from a fixed position,
(2) dynamics are deterministic, and (3) reward depends only on observable state. Otherwise,
include the starting state in the cache key.

**RNG strategy**: Use global `np.random` if the contract requires iteration-local RNG
consumption (e.g., "two calls of N match one call of 2N"). Use a local Generator if
reproducibility across different runs is required.

**Stepping strategy**: Use inline computation if batch evaluation must not modify
environment state. Use `self.step()` with save/restore if you need to reuse existing
step logic and can afford the overhead.

**Parameterization**: Always use `len(action_map)` for `num_actions`, not hardcoded values.
Always use `self.length // 2` for bounds, not hardcoded values.

## References

- Cross-entropy method: Rubinstein & Kroese (2016)
- Memoization: Action-prefix tuples as cache keys
- NumPy RNG: `np.random.choice` uses global state; `np.random.default_rng` uses local state

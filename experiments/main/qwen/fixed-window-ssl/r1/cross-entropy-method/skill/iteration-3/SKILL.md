---
name: cross-entropy-method
description: >
  Implement the cross-entropy method (CEM) for planning in discrete-action
  point-mass environments with bounded state spaces. Covers environment
  simulation with independent-axis boundary clipping, prefix-trie memoized
  batch plan evaluation, and iterative CEM optimization with RNG-continuous
  probability updates.
---

# Cross-Entropy Method for Bounded Point-Mass Planning

This skill addresses the implementation of a cross-entropy method (CEM) optimizer
for discrete-action environments where a point agent moves on a bounded integer grid
and receives reward for entering a goal region.

## Architectural Pattern: Separation of Physics from State

The most important structural decision is separating **pure physics computation** from
**state mutation**. Both `step()` and `evaluate_plans_memoized()` need the same physics
logic (move + clip + reward), but `step()` mutates `self.position` while
`evaluate_plans_memoized()` must NOT.

**Pattern**: Extract a private `_compute_step(pos, action) -> (new_pos, reward)` method
that performs pure computation without touching `self.position`. Then:
- `step()` calls `_compute_step(self.position, action)`, stores the result in
  `self.position`, and returns the reward.
- `evaluate_plans_memoized()` calls `_compute_step(cached_pos, action)` for cache
  misses, storing results in the cache dict.

This eliminates the risk of accidentally mutating `self.position` during batch
evaluation and ensures the physics logic is defined in exactly one place.

## Component 1: Environment Dynamics (`step`)

**Movement**: Add `action_map[action]` to current position.

**Clipping**: Each axis is clipped independently to `[-length//2, +length//2]`.
This is the most common source of bugs. If action `[1, -1]` is applied at position
`[length//2, 0]`, the result is `[length//2, -1]` — X clips but Y still moves.
Do NOT reject the entire move or couple the axes.

**Reward**: `1` if `euclidean_distance(new_pos, goal) <= goal_radius`, else `0`.
The boundary is inclusive (`<=`).

```python
def _compute_step(self, pos, action):
    delta = self.action_map[action]
    new_pos = pos + delta
    half = self.length // 2
    new_pos = np.array([
        np.clip(new_pos[0], -half, half),
        np.clip(new_pos[1], -half, half),
    ], dtype=np.int_)
    dist = np.linalg.norm(new_pos - self.goal)
    return new_pos, (1 if dist <= self.goal_radius else 0)

def step(self, action):
    new_pos, reward = self._compute_step(self.position, action)
    self.position = new_pos
    return reward
```

## Component 2: Prefix-Trie Memoized Batch Evaluation

**Data structure**: A dictionary `self._prefix_cache` mapping `tuple(action_sequence)`
to `(position_after_prefix, cumulative_reward)`. Initialized in `__init__` with:
```python
self._prefix_cache = {}
self._prefix_cache[()] = (np.array([0, 0], dtype=np.int_), 0)
```

**Algorithm**: For each plan, walk through actions building prefixes. On cache miss,
compute from parent prefix using `_compute_step`. On cache hit, reuse stored state.

```python
def evaluate_plans_memoized(self, plans):
    cache = self._prefix_cache
    rewards = []
    for plan in plans:
        plan_tuple = tuple(int(a) for a in plan)
        for t in range(len(plan_tuple)):
            prefix = plan_tuple[:t + 1]
            if prefix not in cache:
                parent_prefix = prefix[:-1]
                parent_pos, parent_cum = cache[parent_prefix]
                new_pos, step_r = self._compute_step(parent_pos, int(plan_tuple[t]))
                cache[prefix] = (new_pos.copy(), parent_cum + step_r)
        _, cum_reward = cache[plan_tuple]
        rewards.append(cum_reward)
    return rewards
```

**Critical invariants**:
1. **Cache persistence**: The cache lives on `self` and persists across calls. Plans
   from later calls can reuse prefixes computed in earlier calls.
2. **Position copies**: Always store `new_pos.copy()` in the cache. If you store a
   reference to a numpy array that later gets mutated, cached values will be corrupted.
3. **No side effects**: `self.position` must remain unchanged after the call.
4. **Prefix sharing**: Plans `[1,3,2]` and `[1,3,0]` share prefixes `(1,)` and
   `(1,3)`. The second plan only computes one new cache entry `(1,3,0)`.

### Performance Characteristics

Based on empirical testing, the memoization provides significant speedup in specific scenarios:

**High benefit scenarios** (2-30x speedup):
- **Very high prefix overlap**: When action distributions are concentrated (e.g., 90%+
  probability on one action), plans share many prefixes. Cache can be 50%+ smaller than
  naive evaluation.
- **Many repeated plans**: When the same plans appear multiple times in a batch, the cache
  provides massive speedup (30x observed with 1500 plans from 3 unique plans).
- **CEM iterations**: Later iterations benefit from cache entries computed in earlier
  iterations, especially as the distribution concentrates.

**Low benefit scenarios** (0.9-1.1x speedup):
- **Long horizons with moderate overlap**: When horizon is long (50+) and distributions
  are moderately concentrated (50%), the overhead of tuple creation and hashing can
  approach the simulation cost. Cache reduction may be only 3-5%.
- **Random plans with no overlap**: When plans are uniformly random, there's minimal
  prefix sharing. The memoization overhead slightly exceeds the benefit.

**Key insight**: The memoization is most valuable during CEM optimization as the
distribution concentrates over iterations. Early iterations with uniform distributions
see minimal benefit, but later iterations with concentrated distributions see 2-3x speedup.

### Cache Growth Management

The cache grows monotonically. For CEM with `num_samples` plans of horizon `H`:
- **Worst case** (no overlap): Cache grows by `num_samples * H` per iteration
- **Best case** (high overlap): Cache grows by much less due to prefix sharing
- **Typical CEM**: After 10-20 iterations with concentration, cache may have 50-70%
  fewer entries than the theoretical maximum

For typical parameters (100-500 samples, horizon 10-30), cache size is manageable
(thousands to tens of thousands of entries).

## Component 3: Cross-Entropy Method Optimization

**Algorithm per iteration**:
1. **Sample** `num_samples` plans: for each timestep `t`, draw actions from
   `self.probs[t]` using `np.random.choice(num_actions, size=num_samples, p=self.probs[t])`.
2. **Evaluate** all plans via `evaluate_plans_memoized`.
3. **Select elites**: `np.argsort(rewards)[-num_elites:]` gives indices of top plans.
4. **Update probs**: for each timestep `t`, compute action frequency among elites
   using `np.bincount(elite_plans[:, t], minlength=num_actions)` and set
   `self.probs[t] = counts / num_elites`.

**RNG continuity**: Use the **global** `np.random` functions (not `np.random.default_rng()`).
The global RNG state persists naturally across `optimize()` calls. Creating a local
RNG instance inside `optimize()` would reset the state each call, breaking the
equivalence: `optimize(10) + optimize(10) == optimize(20)`.

**Probability update is a hard replacement**: `self.probs[t]` is entirely replaced by
elite frequencies, not blended with the prior. This means after enough iterations,
probs can become deterministic (1.0 for one action, 0.0 for others).

## Edge Cases

### Boundary Behavior
- From `[half-1, half-1]` with action `[1,1]` → `[half, half]` (both valid)
- From `[half, half-1]` with action `[1,1]` → `[half, half]` (X clips, Y moves)
- From `[half, half]` with action `[1,1]` → `[half, half]` (both clip)
- From `[-half, -half]` with action `[-1,-1]` → `[-half, -half]` (both clip)

### Memoization Edge Cases
- **Identical plans in a batch**: The second occurrence hits the cache for every
  prefix, returning the same reward as the first.
- **Plans of different lengths**: The algorithm handles this naturally since it
  iterates to `len(plan_tuple)`.
- **Empty batch**: Returns empty list (no plans to evaluate).
- **Single-action plans**: Work correctly; prefix is `(action,)`.

### CEM Edge Cases
- **All elites tied**: `np.argsort` still returns valid indices; the frequency
  update works correctly.
- **`num_elites == num_samples`**: All plans are elites; probs become the empirical
  distribution of all sampled actions.
- **`num_elites == 1`**: Only the single best plan contributes; probs become one-hot.

## Variation Dimensions (from spec.yaml)

**Environment dynamics** — what changes across family members:
- Map size (`length`): affects clipping bounds and distance to goal
- Goal position and radius: affects which positions earn reward
- Action set: different movement vectors, but always local motion on the grid
- The physics pattern (add delta, clip independently, compute distance reward) is
  invariant; only the specific vectors and parameters change

**Policy update regime** — what changes across family members:
- `num_samples`, `num_elites`, `horizon`: affect convergence speed and quality
- Reward sparsity: some configurations may give reward 0 for most plans initially
- The CEM algorithm (sample → evaluate → select elites → update frequencies) is
  invariant; only the hyperparameters change

**Overlapping plan evaluation** — what changes across family members:
- Degree of prefix overlap: CEM iterations with concentrated probs generate many
  similar plans, increasing cache hit rate
- Batch size: larger batches benefit more from memoization
- The prefix-trie pattern is invariant; only the overlap statistics change

## Testing Strategy for Family Variants

When adapting to a new family member, test systematically:

### 1. Correctness Tests
```python
# Test step() with boundary cases
env = PointEnv(length=NEW_LENGTH, goal_x=NEW_GOAL_X, ...)
env.position = np.array([boundary_x, boundary_y])
env.step(action_that_clips_one_axis)
# Verify independent clipping

# Test memoization correctness
plans = generate_test_plans()
memo_rewards = env.evaluate_plans_memoized(plans)
naive_rewards = [naive_eval(plan) for plan in plans]
assert memo_rewards == naive_rewards

# Test position unchanged
assert list(env.position) == [0, 0]
```

### 2. RNG Continuity Test
```python
env1 = PointEnv(**new_config); cem1 = CrossEntropyMethod(env1, horizon=H)
np.random.seed(SEED)
cem1.optimize(S, E, 10)
cem1.optimize(S, E, 10)
p_split = cem1.probs.copy()

env2 = PointEnv(**new_config); cem2 = CrossEntropyMethod(env2, horizon=H)
np.random.seed(SEED)
cem2.optimize(S, E, 20)
assert np.allclose(p_split, cem2.probs)
```

### 3. Convergence Test
```python
env = PointEnv(**new_config)
cem = CrossEntropyMethod(env, horizon=H)
cem.optimize(S, E, iterations=30)
max_probs = cem.probs.max(axis=1)
assert max_probs.mean() > 0.5  # Should concentrate
```

### 4. Performance Validation (if required)
```python
# Generate plans with expected overlap pattern
plans = generate_plans_with_overlap(new_config)
env_memo = PointEnv(**new_config)
env_naive = PointEnv(**new_config)

time_memo = measure_time(env_memo.evaluate_plans_memoized, plans)
time_naive = measure_time(naive_evaluate, plans)

# Verify correctness
assert env_memo.evaluate_plans_memoized(plans) == naive_evaluate(plans)

# Check speedup is reasonable (may vary by scenario)
print(f"Speedup: {time_naive/time_memo:.2f}x")
```

## Debugging Strategy

When tests fail, check in this order:
1. **Is `self.position` unchanged after `evaluate_plans_memoized`?** If not, you're
   mutating it somewhere in the evaluation loop.
2. **Does memoized evaluation match naive evaluation?** Run both on the same plans
   and compare. Mismatches indicate cache corruption (usually from not copying positions).
3. **Does `optimize(10) + optimize(10)` match `optimize(20)`?** If not, you're
   creating a new RNG or re-seeding inside `optimize()`.
4. **Are probabilities summing to 1.0 at each timestep?** If not, `bincount` may be
   missing the `minlength` parameter.
5. **Is axis clipping independent?** Test with position at `[half, 0]` and action
   `[1, -1]`. Expected result: `[half, -1]`.
6. **Does CEM converge for the new configuration?** If not, check that the goal is
   reachable and the horizon is sufficient.

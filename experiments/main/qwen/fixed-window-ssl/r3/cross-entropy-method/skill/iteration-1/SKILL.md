---
name: cross-entropy-method
description: >
  Implement cross-entropy method (CEM) optimization for discrete action planning
  in point-mass grid environments. Covers environment dynamics with independent
  axis clipping, prefix-memoized batch plan evaluation, and iterative policy
  updates with RNG consistency guarantees.
---

# Cross-Entropy Method for Discrete Action Planning

## Overview

This skill implements three core components for CEM-based planning in discrete
grid environments:

1. **Environment dynamics** (`PointEnv.step`): Translate discrete actions into
   state updates with boundary clipping and goal-proximity rewards.
2. **Memoized batch evaluation** (`PointEnv.evaluate_plans_memoized`): Efficiently
   evaluate multiple action sequences by caching shared prefixes.
3. **Policy optimization** (`CrossEntropyMethod.optimize`): Iteratively refine
   action distributions using elite selection and empirical frequency updates.

## Key Implementation Patterns

### 1. Independent Axis Clipping

**Mechanism**: When an action would move the agent outside bounds, clip each
coordinate independently. Do NOT skip the entire move if one axis is out of bounds.

**Implementation**:
```python
delta = self.action_map[action]
new_pos = np.array([
    np.clip(self.position[0] + delta[0], -self._half, self._half),
    np.clip(self.position[1] + delta[1], -self._half, self._half),
], dtype=np.int_)
```

**Why it matters**: Independent clipping allows partial progress. For example,
if at position (2, 3) with bounds [-3, 3] and action [1, 1], the x-coordinate
moves to 3 (valid) while y tries 4 but clips to 3. Both axes are updated.

**Common mistake**: Using a single `np.clip(new_pos, -half, half)` on the entire
array is correct, but checking bounds before applying the move is wrong. Always
apply the move, then clip.

### 2. Goal Reward with Euclidean Distance

**Mechanism**: Return reward 1 if the resulting position is within `goal_radius`
(inclusive) of the goal, otherwise 0.

**Implementation**:
```python
dist = np.linalg.norm(new_pos - self.goal)
step_reward = 1 if dist <= self.goal_radius else 0
```

**Key detail**: The boundary is inclusive (`<=`), not exclusive (`<`). This
matters when the agent lands exactly on the goal circle boundary.

### 3. Prefix Memoization for Batch Evaluation

**Mechanism**: Cache the state (position, cumulative reward) for every action
prefix encountered during batch evaluation. Reuse cached states when multiple
plans share prefixes.

**Data structure**:
```python
# Maps tuple_of_actions -> (position_after, cumulative_reward)
self._prefix_cache = {(): (np.array([0, 0], dtype=np.int_), 0)}
```

**Algorithm**:
```python
for plan in plans:
    plan_tuple = tuple(int(a) for a in plan)
    for i in range(len(plan_tuple)):
        prefix = plan_tuple[:i + 1]
        if prefix not in cache:
            prev_prefix = plan_tuple[:i]
            prev_pos, prev_reward = cache[prev_prefix]
            # Simulate one step from prev_pos
            action = prefix[i]
            delta = action_map[action]
            new_pos = np.array([
                np.clip(prev_pos[0] + delta[0], -half, half),
                np.clip(prev_pos[1] + delta[1], -half, half),
            ], dtype=np.int_)
            dist = np.linalg.norm(new_pos - goal)
            step_reward = 1 if dist <= goal_radius else 0
            cache[prefix] = (new_pos, prev_reward + step_reward)
    
    _, total_reward = cache[plan_tuple]
    rewards.append(total_reward)
```

**Critical requirements**:
- **Persistence**: Cache must persist across calls to `evaluate_plans_memoized`.
  Initialize once in `__init__`, not in the method.
- **Prefix sharing**: Cache every prefix, not just complete plans. This enables
  reuse when plans share initial actions.
- **No side effects**: Do NOT call `self.step()` during evaluation, as it mutates
  `self.position`. Inline the step logic or save/restore position.
- **Start from origin**: Every plan is evaluated from (0, 0), regardless of the
  current environment position.

**Performance**: With N plans of horizon H, worst-case time is O(N*H) when no
prefixes are shared. With heavy overlap, time approaches O(unique_prefixes),
which can be much smaller.

### 4. Cross-Entropy Method Optimization

**Mechanism**: Iteratively sample action sequences, evaluate them, select elites,
and update action probabilities based on elite frequencies.

**Algorithm**:
```python
for _ in range(iterations):
    # Sample plans
    plans = np.empty((num_samples, horizon), dtype=np.int_)
    for t in range(horizon):
        plans[:, t] = np.random.choice(
            num_actions, size=num_samples, p=self.probs[t]
        )
    
    # Evaluate
    rewards = np.array(env.evaluate_plans_memoized(plans))
    
    # Select elites
    elite_indices = np.argsort(rewards)[-num_elites:]
    elite_plans = plans[elite_indices]
    
    # Update probabilities
    for t in range(horizon):
        for a in range(num_actions):
            self.probs[t, a] = np.mean(elite_plans[:, t] == a)
```

**RNG consistency**: Use `np.random.choice()` with the global numpy RNG. Do NOT
create a new `np.random.Generator` or reset the seed inside `optimize()`. This
ensures that calling `optimize(iterations=10)` twice produces the same result as
calling `optimize(iterations=20)` once under the same seed.

**Why it works**: The global RNG state advances naturally across iterations. Each
call to `np.random.choice()` consumes random numbers in a deterministic order,
so splitting iterations across multiple calls preserves the RNG sequence.

**Edge case handling**: Guard against zero-probability rows (can occur if no
elite uses a particular action at a timestep):
```python
row_sums = self.probs.sum(axis=1, keepdims=True)
zero_rows = (row_sums.flatten() == 0)
if np.any(zero_rows):
    self.probs[zero_rows] = 1.0 / num_actions
```

## Testing Strategy

### Correctness Tests

1. **Step behavior**: Verify position updates and rewards for known action sequences.
2. **Independent clipping**: Test scenarios where one axis clips but the other doesn't.
3. **Memoization correctness**: Compare memoized results against brute-force evaluation.
4. **Position invariance**: Ensure `evaluate_plans_memoized` doesn't change `self.position`.
5. **Prefix sharing**: Verify cache grows correctly and reuses shared prefixes.
6. **RNG consistency**: Confirm `optimize(10); optimize(10)` matches `optimize(20)`.

### Performance Tests

1. **Cache hit rate**: With overlapping plans, measure speedup vs. non-memoized evaluation.
2. **Convergence**: Verify CEM learns to reach the goal (early timesteps favor actions
   that move toward the goal).

### Edge Cases

1. **Empty plans**: Handle `plans.shape == (N, 0)` gracefully (return all zeros).
2. **Zero elites**: Guard against `num_elites == 0` (shouldn't happen, but defensive).
3. **Deterministic convergence**: When `probs` becomes all 0/1, sampling is deterministic.
4. **Boundary goals**: Test goals near edges where clipping affects reachability.

## Variation Dimensions

According to the spec, the following aspects may vary across family members:

### Environment Dynamics
- **Map size** (`length`): Affects clipping bounds and reachable states.
- **Goal placement** (`goal_x`, `goal_y`): Changes optimal path and reward structure.
- **Goal radius**: Larger radius makes goal easier to reach.
- **Action set**: Different movement vectors (still local motion in same state space).
- **Boundary behavior**: Clipping rules (always independent per axis).

### Policy Update Regime
- **Sample count** (`num_samples`): More samples = better exploration but slower.
- **Elite fraction** (`num_elites`): Smaller fraction = more aggressive updates.
- **Horizon** (`horizon`): Longer horizons require more iterations to converge.
- **Reward sparsity**: Sparse rewards (small goal radius) make optimization harder.
- **Convergence patterns**: Different configs may converge to different policies.

### Overlapping Plan Evaluation
- **Prefix overlap**: Plans may share many or few prefixes.
- **Batch size** (N): Larger batches benefit more from memoization.
- **Horizon** (H): Longer plans have more prefixes to cache.
- **Redundancy**: Some plans may be identical; memoization handles this naturally.

## Invariants (Must Hold Across All Variants)

1. **Independent clipping**: Each axis clipped separately, never suppress entire move.
2. **Inclusive distance check**: Reward 1 when `dist <= goal_radius`, not `<`.
3. **Origin-based evaluation**: All plans evaluated from (0, 0), not current position.
4. **No side effects**: `evaluate_plans_memoized` must not change `self.position`.
5. **Persistent cache**: Cache survives across calls, not reset per call.
6. **Prefix-level caching**: Cache every prefix, not just complete plans.
7. **RNG consistency**: Use global numpy RNG; no seed resets inside `optimize()`.
8. **Iteration-local updates**: Each iteration samples, evaluates, selects elites, updates.
9. **Probability normalization**: `self.probs[t]` sums to 1 for all t.
10. **Exact rewards**: Memoized evaluation must return exact cumulative rewards.

## Common Pitfalls

1. **Mutating position during evaluation**: Calling `self.step()` changes `self.position`.
   Solution: Inline step logic or save/restore position.
2. **Skipping moves on boundary violation**: Checking bounds before applying move is wrong.
   Solution: Always apply move, then clip each axis independently.
3. **Exclusive distance check**: Using `<` instead of `<=` for goal radius.
   Solution: Use `<=` to include boundary.
4. **Resetting cache per call**: Cache must persist across calls for efficiency.
   Solution: Initialize in `__init__`, not in `evaluate_plans_memoized`.
5. **Caching only complete plans**: Misses prefix sharing opportunities.
   Solution: Cache every prefix `plan_tuple[:i+1]`.
6. **Creating new RNG in optimize**: Breaks consistency guarantee.
   Solution: Use `np.random.choice()` with global RNG.
7. **Not handling zero-probability rows**: Can cause `np.random.choice` to fail.
   Solution: Reset to uniform distribution if row sum is 0.

## Performance Optimization

1. **Local variable caching**: In `evaluate_plans_memoized`, cache frequently accessed
   attributes (`self._half`, `self.action_map`, etc.) as local variables.
2. **Tuple conversion**: Convert numpy arrays to tuples for hashing. Assume O(1) cost.
3. **Incremental prefix building**: Walk through plan action-by-action, checking cache
   at each step. This naturally handles prefix sharing.
4. **Avoid redundant computation**: Once a prefix is cached, never recompute it.

## Debugging Tips

1. **Print cache size**: After evaluation, check `len(self._prefix_cache)` to verify
   prefix sharing is working.
2. **Compare with brute force**: For small plan sets, verify memoized results match
   brute-force evaluation.
3. **Check position invariance**: Assert `self.position == [0, 0]` after evaluation.
4. **Verify RNG sequence**: Print first few sampled plans to confirm deterministic behavior.
5. **Test boundary cases**: Manually trace actions near boundaries to verify clipping.

---
name: cross-entropy-method
description: >
  Implement cross-entropy method (CEM) optimization for discrete action planning
  in point-mass grid environments. Covers environment dynamics with independent
  axis clipping, prefix-memoized batch plan evaluation, and iterative policy
  updates with RNG consistency guarantees.
---

# Cross-Entropy Method for Discrete Action Planning

## Core Principles

This skill addresses three interconnected challenges in CEM-based planning:

1. **Environment dynamics**: How discrete actions translate to state updates and rewards
2. **Efficient batch evaluation**: How to evaluate many plans without redundant computation
3. **Policy optimization**: How to iteratively refine action distributions

The key insight is that these three components must work together seamlessly: the environment must be deterministic and side-effect-free for batch evaluation, the memoization must exploit plan structure, and the optimization must respect RNG semantics.

## Principle 1: Deterministic, Side-Effect-Free Environment Dynamics

### Independent Axis Clipping

**Core mechanism**: When an action would move the agent outside bounds, clip each coordinate independently. This preserves partial progress.

**Why independent clipping matters**: If at position (2, 3) with bounds [-3, 3] and action [1, 1]:
- x: 2 + 1 = 3 (within bounds)
- y: 3 + 1 = 4 → clipped to 3
- Result: (3, 3) - both axes updated, not blocked entirely

**Common mistake**: Checking bounds before applying the move. Always apply the move, then clip each axis independently.

**Generalization**: This principle applies to any bounded state space. The key is that each dimension is constrained independently, allowing partial progress when one dimension hits a boundary.

### Inclusive Boundary Rewards

**Core mechanism**: Return reward 1 if the resulting position is within `goal_radius` (inclusive) of the goal, otherwise 0.

**Formula**: `reward = 1 if distance(position, goal) <= goal_radius else 0`

**Why inclusive matters**: When the agent lands exactly on the goal circle boundary, it should receive reward. Using `<` instead of `<=` creates an off-by-one error that's hard to detect.

**Generalization**: This applies to any geometric reward region. The boundary condition (inclusive vs exclusive) must match the problem specification exactly.

### Side-Effect-Free Evaluation

**Core mechanism**: Batch evaluation must not mutate the environment's public state. All plans are evaluated from the origin (or specified start state), regardless of the current environment position.

**Implementation pattern**: Inline the step logic in the batch evaluator rather than calling `self.step()`, which would mutate `self.position`.

**Why this matters**: CEM evaluates many plans per iteration. If evaluation mutates state, subsequent evaluations start from the wrong position, producing incorrect results.

**Generalization**: Any batch evaluation method must be pure (no side effects). This is a fundamental requirement for correct Monte Carlo sampling.

## Principle 2: Prefix Memoization for Efficient Batch Evaluation

### Core Mechanism

Cache the state (position, cumulative reward) for every action prefix encountered during batch evaluation. Reuse cached states when multiple plans share prefixes.

**Data structure**: Dictionary mapping action tuples to (position, cumulative_reward).

**Base case**: Empty tuple `()` maps to (origin_position, 0).

### Algorithm

For each plan:
1. Convert to tuple for hashing
2. Walk through actions one-by-one
3. At each step, check if the current prefix is cached
4. If not, compute it from the previous (cached) prefix
5. Store the new prefix in the cache
6. After processing all actions, the final cache entry contains the total reward

### Why Prefix-Level Caching Matters

**Performance**: With N plans of horizon H, worst-case is O(N*H) when no prefixes are shared. With heavy overlap, time approaches O(unique_prefixes), which can be much smaller.

**Example**: If 100 plans all start with action 2, the prefix (2,) is computed once and reused 100 times.

**Generalization**: This principle applies to any sequential decision problem where plans share structure. The key insight is that the state after a prefix depends only on the prefix, not on what comes after.

### Persistence Across Calls

**Core requirement**: The cache must persist across calls to `evaluate_plans_memoized`. Initialize once in `__init__`, not reset per call.

**Why persistence matters**: CEM calls the evaluator multiple times per iteration, and multiple iterations. If the cache is reset, you lose all the benefit of memoization.

**Generalization**: Any memoization strategy must persist across the optimization loop to be effective.

## Principle 3: Cross-Entropy Method with RNG Consistency

### Core Algorithm

**Iteration loop**:
1. **Sample**: Generate `num_samples` plans by sampling each timestep independently from its categorical distribution
2. **Evaluate**: Use memoized batch evaluation to get cumulative rewards
3. **Select elites**: Keep top `num_elites` plans by reward
4. **Update**: Set `probs[t, a]` = fraction of elites that use action `a` at timestep `t`

### RNG Consistency Guarantee

**Core requirement**: Calling `optimize(iterations=10)` twice must produce the same result as calling `optimize(iterations=20)` once under the same seed.

**Why this matters**: The global numpy RNG state advances naturally across iterations. Each call to `np.random.choice()` consumes random numbers in a deterministic order. Splitting iterations across multiple calls preserves the RNG sequence.

**Implementation**: Use `np.random.choice()` with the global RNG. Do NOT create a new `np.random.Generator` or reset the seed inside `optimize()`.

**Generalization**: This principle applies to any iterative stochastic optimization. The key is that RNG consumption must be iteration-local, not call-local.

### Edge Case: Zero-Probability Rows

**Problem**: If no elite uses a particular action at a timestep, `probs[t, a]` becomes 0. This can cause `np.random.choice()` to fail in subsequent iterations.

**Solution**: After updating probabilities, check for zero-sum rows and reset them to uniform distribution.

**Generalization**: Any categorical distribution update must handle the case where some actions receive zero probability.

## Structural Template

### PointEnv Initialization

Add these fields in `__init__`:

```python
# Precompute half-length for clipping (used in step and evaluate)
self._half = length // 2

# Persistent prefix cache: maps action tuple -> (position, cumulative_reward)
# Base case: empty tuple means origin with zero reward
self._prefix_cache: dict[tuple, tuple[np.ndarray, int]] = {
    (): (np.array([0, 0], dtype=np.int_), 0)
}
```

### PointEnv.step(action)

```python
def step(self, action: int) -> int:
    # Apply action delta with independent axis clipping
    delta = self.action_map[action]
    new_pos = np.array([
        np.clip(self.position[0] + delta[0], -self._half, self._half),
        np.clip(self.position[1] + delta[1], -self._half, self._half),
    ], dtype=np.int_)
    
    # Update position
    self.position = new_pos
    
    # Compute reward: 1 if within goal radius (inclusive), else 0
    dist = np.linalg.norm(new_pos - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

### PointEnv.evaluate_plans_memoized(plans)

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    # Cache references for performance
    cache = self._prefix_cache
    half = self._half
    action_map = self.action_map
    goal = self.goal
    goal_radius = self.goal_radius
    
    rewards = []
    
    for plan in plans:
        # Convert plan to tuple for hashing
        plan_tuple = tuple(int(a) for a in plan)
        
        # Build up prefixes incrementally, caching each one
        for i in range(len(plan_tuple)):
            prefix = plan_tuple[:i + 1]
            
            # If this prefix is not cached, compute it from the previous prefix
            if prefix not in cache:
                prev_prefix = plan_tuple[:i]
                prev_pos, prev_reward = cache[prev_prefix]
                
                # Apply action (inline step logic to avoid mutating self.position)
                action = prefix[i]
                delta = action_map[action]
                new_pos = np.array([
                    np.clip(prev_pos[0] + delta[0], -half, half),
                    np.clip(prev_pos[1] + delta[1], -half, half),
                ], dtype=np.int_)
                
                # Compute step reward
                dist = np.linalg.norm(new_pos - goal)
                step_reward = 1 if dist <= goal_radius else 0
                
                # Cache this prefix
                cache[prefix] = (new_pos, prev_reward + step_reward)
        
        # Get final cumulative reward for this plan
        _, total_reward = cache[plan_tuple]
        rewards.append(total_reward)
    
    return rewards
```

### CrossEntropyMethod.optimize(num_samples, num_elites, iterations)

```python
def optimize(self, num_samples, num_elites, iterations):
    env = self.env
    horizon = self.horizon
    num_actions = self.num_actions
    
    for _ in range(iterations):
        # Sample plans: each timestep sampled independently from its distribution
        plans = np.empty((num_samples, horizon), dtype=np.int_)
        for t in range(horizon):
            plans[:, t] = np.random.choice(
                num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate all plans using memoized batch evaluation
        rewards = np.array(env.evaluate_plans_memoized(plans))
        
        # Select elites: top num_elites by cumulative reward
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Update probabilities: empirical frequency of each action among elites
        for t in range(horizon):
            for a in range(num_actions):
                self.probs[t, a] = np.mean(elite_plans[:, t] == a)
        
        # Guard against zero-probability rows (defensive)
        row_sums = self.probs.sum(axis=1, keepdims=True)
        zero_rows = (row_sums.flatten() == 0)
        if np.any(zero_rows):
            self.probs[zero_rows] = 1.0 / num_actions
```

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

## Adaptation to Variants

### Different Action Sets

If the action set changes (e.g., 4 cardinal directions instead of 9), the core mechanisms remain the same:
- `action_map` defines the movement vectors
- `num_actions` is derived from `len(action_map)`
- The memoization and optimization logic is unchanged

The key is that the action set must still represent local motion in the same state space.

### Different Map Sizes

If `length` changes:
- `self._half` is recomputed as `length // 2`
- Clipping bounds adjust automatically
- The reachable state space changes, but the algorithms are unchanged

### Different Goal Placements

If `goal_x`, `goal_y`, or `goal_radius` changes:
- The reward structure changes
- The optimal policy changes
- But the evaluation and optimization mechanisms are unchanged

### Different Sample/Elite Counts

If `num_samples` or `num_elites` changes:
- More samples = better exploration but slower
- Smaller elite fraction = more aggressive updates
- The core algorithm is unchanged; only the hyperparameters differ

### Different Horizons

If `horizon` changes:
- Longer horizons require more iterations to converge
- The memoization cache grows larger (more prefixes)
- The core algorithm is unchanged; only the planning depth differs

## Common Pitfalls

1. **Mutating position during evaluation**: Calling `self.step()` changes `self.position`.
   **Solution**: Inline step logic in `evaluate_plans_memoized`.

2. **Skipping moves on boundary violation**: Checking bounds before applying move.
   **Solution**: Always apply move, then clip each axis independently.

3. **Exclusive distance check**: Using `<` instead of `<=` for goal radius.
   **Solution**: Use `<=` to include boundary.

4. **Resetting cache per call**: Cache must persist across calls for efficiency.
   **Solution**: Initialize in `__init__`, not in `evaluate_plans_memoized`.

5. **Caching only complete plans**: Misses prefix sharing opportunities.
   **Solution**: Cache every prefix `plan_tuple[:i+1]`.

6. **Creating new RNG in optimize**: Breaks consistency guarantee.
   **Solution**: Use `np.random.choice()` with global RNG.

7. **Not handling zero-probability rows**: Can cause `np.random.choice` to fail.
   **Solution**: Reset to uniform distribution if row sum is 0.

8. **Forgetting to initialize `self._half`**: Needed for clipping in both methods.
   **Solution**: Compute `self._half = length // 2` in `__init__`.

## Testing Checklist

Before submitting, verify:

- [ ] `step()` updates position correctly with independent clipping
- [ ] `step()` returns 1 when `dist <= goal_radius`, 0 otherwise
- [ ] `evaluate_plans_memoized()` returns correct cumulative rewards
- [ ] `evaluate_plans_memoized()` does not change `self.position`
- [ ] Cache persists across calls and reuses shared prefixes
- [ ] `optimize(10); optimize(10)` matches `optimize(20)` under same seed
- [ ] CEM learns to reach the goal (early timesteps favor goal-directed actions)
- [ ] Probabilities sum to 1 at all timesteps

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

## Complete Structural Template

### PointEnv Initialization

Add these fields in `__init__`:

```python
def __init__(self, length, goal_x, goal_y, goal_radius):
    # ... existing code ...
    
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

**Key details**:
- Clip each axis **independently** after applying the delta
- Use `<=` for goal radius check (boundary is inclusive)
- Update `self.position` before computing reward

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

**Critical requirements**:
- **Do NOT call `self.step()`** - it mutates `self.position`. Inline the step logic instead.
- **Cache persists across calls** - initialized once in `__init__`, not reset here.
- **Cache every prefix** - enables sharing when plans have common initial actions.
- **All plans evaluated from origin** - the cache base case `()` starts at (0, 0).

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

**RNG consistency**: Use `np.random.choice()` with the global numpy RNG. Do NOT
create a new `np.random.Generator` or reset the seed inside `optimize()`. This
ensures that calling `optimize(iterations=10)` twice produces the same result as
calling `optimize(iterations=20)` once under the same seed.

## Key Implementation Patterns

### 1. Independent Axis Clipping

**Mechanism**: When an action would move the agent outside bounds, clip each
coordinate independently. Do NOT skip the entire move if one axis is out of bounds.

**Example**: At position (2, 3) with bounds [-3, 3] and action [1, 1]:
- x: 2 + 1 = 3 (within bounds, no clipping)
- y: 3 + 1 = 4 → clipped to 3
- Result: (3, 3) - both axes updated, partial progress preserved

**Common mistake**: Checking bounds before applying the move. Always apply the
move, then clip each axis independently.

### 2. Goal Reward with Euclidean Distance

**Mechanism**: Return reward 1 if the resulting position is within `goal_radius`
(inclusive) of the goal, otherwise 0.

**Formula**: `reward = 1 if np.linalg.norm(position - goal) <= goal_radius else 0`

**Key detail**: The boundary is inclusive (`<=`), not exclusive (`<`). This
matters when the agent lands exactly on the goal circle boundary.

### 3. Prefix Memoization

**Data structure**: Dictionary mapping action tuples to (position, cumulative_reward).

**Algorithm**: For each plan, walk through actions one-by-one. At each step:
1. Check if the current prefix is cached
2. If not, compute it from the previous (cached) prefix
3. Store the new prefix in the cache
4. After processing all actions, the final cache entry contains the total reward

**Performance**: With N plans of horizon H, worst-case is O(N*H) when no prefixes
are shared. With heavy overlap, time approaches O(unique_prefixes).

### 4. Cross-Entropy Method

**Iteration loop**:
1. **Sample**: Generate `num_samples` plans by sampling each timestep independently
2. **Evaluate**: Use memoized batch evaluation to get cumulative rewards
3. **Select elites**: Keep top `num_elites` plans by reward
4. **Update**: Set `probs[t, a]` = fraction of elites that use action `a` at timestep `t`

**Why RNG consistency works**: The global numpy RNG state advances naturally across
iterations. Each call to `np.random.choice()` consumes random numbers in a
deterministic order, so splitting iterations across multiple calls preserves the
RNG sequence.

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

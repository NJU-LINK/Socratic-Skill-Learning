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

## Core Components

### 1. Environment Dynamics (PointEnv)

**State**: Integer position `(x, y)` on a square grid of side `length`, bounded to
`[-length/2, +length/2]` on each axis independently.

**Actions**: Discrete action indices mapping to 2D movement vectors (e.g., 9-directional
motion including stay). The action set represents local motion in the state space.

**Step mechanics**:
```
new_pos = position + action_map[action]
new_pos[0] = clip(new_pos[0], -length//2, +length//2)
new_pos[1] = clip(new_pos[1], -length//2, +length//2)
```

**Critical invariant**: Each axis is clipped independently. If one axis would exceed
the boundary, it clips to the boundary while the other axis still updates normally.
Do NOT reject the entire move or couple the axes.

**Reward**: `1` if `euclidean_distance(new_pos, goal) <= goal_radius`, else `0`.
The boundary is inclusive (`<=`).

### 2. Prefix-Trie Memoized Batch Evaluation

**Purpose**: Evaluate N plans of horizon H efficiently by caching intermediate states
for shared action prefixes.

**Data structure**: A dictionary mapping `tuple(action_sequence)` to
`(position_after_prefix, cumulative_reward)`.

**Algorithm**:
```python
cache = {}
cache[()] = (origin_position, 0)  # empty prefix

for each plan:
    for t in range(len(plan)):
        prefix = tuple(plan[:t+1])
        if prefix not in cache:
            parent_prefix = prefix[:-1]
            parent_pos, parent_cum_reward = cache[parent_prefix]
            new_pos, step_reward = simulate_step(parent_pos, plan[t])
            cache[prefix] = (new_pos.copy(), parent_cum_reward + step_reward)
    
    total_reward = cache[tuple(plan)][1]
```

**Key invariants**:
- Cache persists across calls (stored on `self`), enabling reuse between batches
- Positions stored in cache must be copies, not references to mutable arrays
- The environment's public `position` attribute must NOT be modified by batch evaluation
- Plans sharing prefixes (even partial) benefit from cache hits
- Every plan starts from the origin (empty prefix state)

**Performance**: For plans with high prefix overlap, this reduces O(N*H) simulations
to O(unique_prefixes) simulations. The cache grows monotonically.

### 3. Cross-Entropy Method Optimization

**Purpose**: Iteratively improve a factored action distribution `probs[t, a]` to
maximize expected cumulative reward.

**Algorithm per iteration**:
```python
# 1. Sample plans from current distribution
plans = zeros((num_samples, horizon))
for t in range(horizon):
    plans[:, t] = random.choice(num_actions, size=num_samples, p=probs[t])

# 2. Evaluate all plans
rewards = env.evaluate_plans_memoized(plans)

# 3. Select elites (top num_elites by reward)
elite_indices = argsort(rewards)[-num_elites:]
elite_plans = plans[elite_indices]

# 4. Update distributions from elite action frequencies
for t in range(horizon):
    action_counts = bincount(elite_plans[:, t], minlength=num_actions)
    probs[t] = action_counts / num_elites
```

**RNG continuity invariant**: The random number generator state must persist across
`optimize()` calls. Two calls of `iterations=10` must produce identical results to
one call of `iterations=20` under the same initial seed. This means:
- Do NOT create a new RNG instance inside `optimize()`
- Do NOT re-seed at the start of `optimize()`
- Use the global numpy RNG or a persistent instance stored on `self`

**Probability update**: Each timestep's distribution is replaced entirely by the
empirical frequency of actions among elites at that timestep. This is a hard
replacement, not a blend with the prior.

## Edge Cases and Pitfalls

### Boundary Behavior
- Action `[1, 1]` from position `[length//2 - 1, length//2 - 1]` moves to
  `[length//2, length//2]` (both axes valid)
- Action `[1, 1]` from position `[length//2, length//2 - 1]` moves to
  `[length//2, length//2]` (X clips, Y still moves)
- Action `[1, 1]` from position `[length//2, length//2]` stays at
  `[length//2, length//2]` (both axes clip)

### Memoization Correctness
- Identical plans in a batch should return identical rewards
- Cache must be initialized with the empty prefix mapping to origin state
- When retrieving from cache, unpack both position and cumulative reward
- The final cumulative reward for a plan is the reward stored at its full prefix

### CEM Convergence
- With sufficient iterations, `probs` should concentrate on high-reward actions
- If all elites have the same reward (tie), the update still works correctly
- The distribution can become deterministic (probability 1.0 for one action)

## Variation Dimensions

This skill handles the following spec-declared variations:

**Environment dynamics**:
- Different map sizes (`length`)
- Different start and goal placements
- Different action sets (still representing local motion)
- Different boundary behaviors (always independent-axis clipping)
- Different reward regions (always Euclidean distance based)

**Policy update regime**:
- Different sample counts (`num_samples`)
- Different elite fractions (`num_elites`)
- Different trajectory lengths (`horizon`)
- Different reward sparsity levels
- Different convergence patterns

**Overlapping plan evaluation**:
- Varying degrees of prefix overlap
- Repeated and unique plans in batches
- Different batch sizes
- Cache persistence across multiple optimization iterations

## Implementation Checklist

- [ ] `step(action)`: Add delta, clip each axis independently, compute Euclidean
      distance reward with inclusive boundary
- [ ] `evaluate_plans_memoized(plans)`: Prefix-trie cache with persistent storage,
      copy positions into cache, do not modify `self.position`
- [ ] `optimize()`: Sample from `probs`, evaluate, select elites, update `probs`
      with elite frequencies, maintain RNG continuity across calls
- [ ] Initialize cache with empty prefix `() -> (origin, 0)`
- [ ] Store cache on `self` for persistence across calls
- [ ] Use global numpy RNG or persistent instance (not created per-call)

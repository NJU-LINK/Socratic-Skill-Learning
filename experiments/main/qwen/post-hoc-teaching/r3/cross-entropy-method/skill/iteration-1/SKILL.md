---
name: cross-entropy-method
description: Implementation of the Cross-Entropy Method (CEM) for trajectory optimization in point-mass environments with memoized batch evaluation
---

# Cross-Entropy Method for Point-Mass Trajectory Optimization

## Overview

The Cross-Entropy Method (CEM) is a sampling-based optimization algorithm for finding high-reward action sequences in environments with discrete action spaces. This skill covers the implementation of CEM for point-mass environments with memoized batch evaluation.

## Core Components

### 1. Point Environment (PointEnv)

A 2D grid environment where an agent receives rewards for reaching a goal region.

**Key Properties:**
- State: Integer position (x, y) on a bounded square grid
- Actions: 9 discrete movement vectors (including stay, 4 cardinal, 4 diagonal)
- Reward: Binary (1 if within goal radius, 0 otherwise)
- Boundary handling: Independent clipping per axis

**Step Implementation:**
```python
def step(self, action: int) -> int:
    # Apply movement
    movement = self.action_map[action]
    self.position = self.position + movement
    
    # Clip each coordinate independently
    half_length = self.length // 2
    self.position[0] = np.clip(self.position[0], -half_length, half_length)
    self.position[1] = np.clip(self.position[1], -half_length, half_length)
    
    # Calculate reward
    distance = np.linalg.norm(self.position - self.goal)
    return 1 if distance <= self.goal_radius else 0
```

**Critical Details:**
- Clipping is **independent per axis**: x-clipping doesn't affect y-movement
- Boundary is inclusive: `[-length/2, +length/2]`
- Reward boundary is inclusive: distance ≤ goal_radius
- Position is integer-valued throughout

### 2. Memoized Batch Evaluation

Efficiently evaluate multiple action sequences by caching prefix results.

**Requirements:**
- All plans evaluated from origin (0, 0)
- Environment position unchanged after evaluation
- Cache persists across calls
- Prefix sharing (not just whole-plan caching)

**Implementation Strategy:**
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    # Initialize cache if needed
    if not hasattr(self, '_memo_cache'):
        self._memo_cache = {}
    
    # Save and restore position
    original_position = self.position.copy()
    rewards = []
    
    for plan in plans:
        plan_tuple = tuple(plan)
        
        # Find longest cached prefix
        cached_prefix_length = 0
        for prefix_length in range(1, len(plan) + 1):
            prefix = plan_tuple[:prefix_length]
            if prefix in self._memo_cache:
                cached_prefix_length = prefix_length
            else:
                break
        
        # Jump directly to cached state — NO step() replay for cached prefix
        if cached_prefix_length > 0:
            cached_pos, cached_reward = self._memo_cache[
                plan_tuple[:cached_prefix_length]
            ]
            self.position = cached_pos.copy()
            total_reward = cached_reward
        else:
            # No cached prefix, start from origin
            self.position = np.array((0, 0), dtype=np.int_)
            total_reward = 0
        
        # Execute ONLY the remaining (uncached) steps
        for i in range(cached_prefix_length, len(plan)):
            action = plan[i]
            reward = self.step(action)
            total_reward += reward
            
            # Cache this prefix: store (position, cumulative_reward)
            prefix = plan_tuple[:i + 1]
            self._memo_cache[prefix] = (self.position.copy(), total_reward)
        
        rewards.append(total_reward)
    
    self.position = original_position
    return rewards
```

**Key Insights:**
- Cache stores `(action_prefix_tuple) -> (position, cumulative_reward)` tuples
- Jump directly to cached state instead of replaying steps — this is what enables real speedup
- Always evaluate from origin when no prefix is cached
- Prefix sharing: if plans share `[a, b, c]`, only execute the non-shared suffix
- Cache grows monotonically across calls
- Performance scales with prefix overlap: 10-step shared prefix in 20-step plans yields ~2x speedup

### 3. Cross-Entropy Method Optimization

Iteratively improve action distributions by selecting elite samples.

**Algorithm:**
```python
def optimize(self, num_samples, num_elites, iterations):
    for iteration in range(iterations):
        # 1. Sample action sequences
        samples = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            samples[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # 2. Evaluate samples
        rewards = self.env.evaluate_plans_memoized(samples)
        
        # 3. Select elites
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_samples = samples[elite_indices]
        
        # 4. Update distributions
        for t in range(self.horizon):
            action_counts = np.bincount(
                elite_samples[:, t], minlength=self.num_actions
            )
            self.probs[t] = action_counts / num_elites
```

**Critical Properties:**
- **Iteration-local RNG**: Each iteration consumes RNG independently
- Calling `optimize(10)` twice equals calling `optimize(20)` once (with same seed)
- Each timestep has independent categorical distribution
- Elite selection: top `num_elites` by cumulative reward
- Distribution update: empirical frequencies from elite samples

## Variation Dimensions

### Environment Dynamics

**What varies:**
- Map size (length parameter)
- Goal position (goal_x, goal_y)
- Goal radius
- Action set (still 9 local movements)
- Boundary behavior (always independent clipping)

**Invariants:**
- Integer positions
- Independent axis clipping
- Euclidean distance for reward
- Inclusive boundaries

### Policy Update Regime

**What varies:**
- Sample count (num_samples)
- Elite fraction (num_elites / num_samples)
- Trajectory length (horizon)
- Reward sparsity
- Convergence patterns

**Invariants:**
- Per-timestep independent sampling
- Elite selection by cumulative reward
- Frequency-based distribution updates
- Iteration-local RNG consumption

### Overlapping Plan Evaluation

**What varies:**
- Degree of prefix overlap
- Batch size
- Repeated vs unique plans
- Cache hit patterns

**Invariants:**
- Prefix-based memoization
- Evaluation from origin
- Position restoration
- Exact reward computation

## Common Pitfalls

1. **Position not restored**: Always save and restore environment position
2. **Evaluating from wrong position**: Always start from (0, 0) for batch evaluation
3. **Coupled clipping**: X and Y must be clipped independently
4. **Cache invalidation**: Cache is valid because evaluation always starts from origin
5. **RNG state**: Must be iteration-local for reproducibility
6. **Tied rewards**: np.argsort uses quicksort by default (NOT stable); for stable tie-breaking use `kind='stable'`
7. **Deterministic priors**: When probs are 0/1, all samples are identical
8. **Cache must store state**: Storing only rewards defeats memoization; must cache `(position, reward)` pairs to skip steps

## Testing Strategy

**Unit Tests:**
- Step function: movement, clipping, reward calculation
- Boundary cases: corners, edges, goal boundary
- Memoization: prefix sharing, cache persistence, position restoration
- CEM: distribution updates, RNG consumption, elite selection

**Integration Tests:**
- End-to-end optimization
- Convergence to goal
- Performance with overlapping plans

**Edge Cases:**
- Deterministic distributions
- Tied rewards
- Sparse rewards (large maps, small goals)
- Repeated optimize calls

## Performance Considerations

- Memoization with state caching provides measurable speedup on overlapping plan sets
- Prefix sharing is more effective than whole-plan caching
- Cache lookup is O(1) with tuple hashing
- Evaluation is O(H - cached_prefix_length) per plan (only uncached steps executed)
- CEM iteration is O(N*H) worst case, but much faster with prefix overlap
- With 50% prefix overlap, expect ~2x speedup; with 90% overlap, expect ~10x speedup

## Generalization

This implementation pattern applies to:
- Any discrete-action trajectory optimization problem
- Environments with deterministic dynamics
- Problems with overlapping candidate solutions
- Scenarios requiring reproducible optimization

The key principles are:
1. Memoize prefix computations
2. Maintain clean state boundaries
3. Use iteration-local randomness
4. Select elites by cumulative performance
5. Update distributions from elite frequencies

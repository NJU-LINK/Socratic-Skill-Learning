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

## Variant Adaptation Guide

When implementing a new variant, systematically check each dimension:

### Environment Dynamics Adaptation

**Check these parameters:**
- `length`: Affects clipping bounds
- `goal_x`, `goal_y`: Affects reward calculation
- `goal_radius`: Affects reward boundary
- `action_map`: May have different number of actions or movement vectors

**Adaptation pattern:**
```python
# Always read these from self, don't hardcode
half_length = self.length // 2  # or self.length / 2 if float positions
self.position[i] = np.clip(self.position[i], -half_length, half_length)
distance = np.linalg.norm(self.position - self.goal)
```

**Critical checks:**
- Are positions integer or float? (affects dtype)
- Is clipping independent per axis? (usually yes, but verify)
- Is reward boundary inclusive or exclusive? (check ≤ vs <)

### Policy Update Regime Adaptation

**Check these parameters:**
- `num_actions`: May differ from 9
- `horizon`: Affects probs shape
- Elite selection: May use different criteria
- Distribution update: May use different rules

**Adaptation pattern:**
```python
# Always use self.num_actions, don't hardcode 9
self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

# For elite selection, verify the criterion
elite_indices = np.argsort(rewards)[-num_elites:]  # top-k by reward

# For distribution update, verify the rule
self.probs[t] = action_counts / num_elites  # empirical frequencies
```

**Critical checks:**
- Is elite selection by cumulative reward or per-step reward?
- Are distributions updated independently per timestep?
- Is RNG consumption iteration-local? (must be for reproducibility)

### Overlapping Plan Evaluation Adaptation

**Check these requirements:**
- Evaluation start state: Usually origin, but verify
- Position restoration: Must preserve caller's state
- Cache persistence: Must work across calls
- Prefix sharing: Must cache subplans, not just whole plans

**Adaptation pattern:**
```python
# Cache must store (state, cumulative_value) to enable state jumps
cache[prefix] = (state_copy, cumulative_reward)

# Jump to cached state, don't replay
if prefix in cache:
    state, reward = cache[prefix]
    self.position = state.copy()
    total_reward = reward
```

**Critical checks:**
- What state must be cached? (position, plus any other env state)
- Is evaluation always from the same start state? (usually yes)
- Must the public position be unchanged after evaluation? (usually yes)

## Validation Checklist

When implementing a new variant, verify:

**Environment:**
- [ ] Step function applies movement correctly
- [ ] Boundary handling matches spec (clipping, wraparound, etc.)
- [ ] Reward calculation matches spec (distance metric, boundary inclusion)
- [ ] Position dtype matches spec (int vs float)

**Memoization:**
- [ ] Cache stores (state, value) pairs, not just values
- [ ] Evaluation starts from correct initial state
- [ ] Public state is restored after evaluation
- [ ] Cache persists across calls
- [ ] Prefix sharing works (not just whole-plan caching)
- [ ] Measurable speedup on overlapping plans

**Optimization:**
- [ ] Sampling uses correct distributions
- [ ] Elite selection matches spec
- [ ] Distribution update matches spec
- [ ] RNG consumption is iteration-local
- [ ] Split calls match combined calls (e.g., 10+10 == 20)

**Edge cases:**
- [ ] Deterministic distributions (all probability on one action)
- [ ] Tied rewards (multiple plans with same reward)
- [ ] Empty plans array
- [ ] Single-action plans
- [ ] Boundary conditions (positions at limits)

## Common Pitfalls

1. **Position not restored**: Always save and restore environment state
2. **Evaluating from wrong state**: Verify the required start state (usually origin)
3. **Coupled operations**: If spec says "independent", ensure operations don't interfere
4. **Cache stores only values**: Must cache (state, value) to skip replay
5. **RNG state not iteration-local**: Each iteration must consume RNG independently
6. **Hardcoded constants**: Use `self.num_actions`, `self.length`, etc., not literals
7. **Assuming stability**: `np.argsort` is NOT stable by default; use `kind='stable'` if needed
8. **Floating point precision**: Distance comparisons may need tolerance for float positions

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

**Memoization efficiency:**
- Cache stores (state, value) pairs to enable O(1) state jumps
- Prefix sharing reduces redundant computation proportionally to overlap
- With P% prefix overlap in H-step plans, expect ~1/(1-P) speedup
- Cache lookup is O(1) with tuple hashing
- Evaluation is O(H - cached_prefix_length) per plan

**CEM iteration complexity:**
- Sampling: O(N × H) where N is num_samples, H is horizon
- Evaluation: O(N × H) worst case, better with prefix overlap
- Elite selection: O(N log N) for sorting
- Distribution update: O(H × num_actions)

**Optimization tips:**
- Use vectorized operations where possible (e.g., np.random.choice for all samples at timestep t)
- Cache grows monotonically; consider memory limits for very long horizons
- For deterministic distributions, all samples are identical (no benefit from large N)

## Debugging Strategies

When tests fail, use this systematic approach:

**Environment bugs:**
- Test step() manually with known actions and verify position/reward
- Check boundary behavior at edges (does it clip correctly?)
- Verify reward calculation with manual distance computation
- Test independent axis behavior (move one axis while other is at limit)

**Memoization bugs:**
- Verify cache stores (state, value) tuples, not just values
- Check that evaluation starts from correct initial state
- Verify position is restored after evaluation
- Test with overlapping plans and verify speedup
- Manually trace through a small example to verify cache hits

**Optimization bugs:**
- Verify RNG consumption is iteration-local (test 10+10 == 20)
- Check that elite selection uses correct criterion
- Verify distribution update rule matches spec
- Test with deterministic distributions (all samples should be identical)
- Check that probs sum to 1.0 after each update

**Common debugging techniques:**
- Print intermediate values to trace execution
- Compare with manual calculation for small examples
- Test edge cases explicitly (boundaries, empty inputs, etc.)
- Verify invariants (position restored, probs sum to 1, etc.)

## Generalization

This implementation pattern applies to:
- Any discrete-action trajectory optimization problem
- Environments with deterministic dynamics
- Problems with overlapping candidate solutions
- Scenarios requiring reproducible optimization
- Variants with different action spaces, reward structures, or boundary behaviors

**Key principles:**
1. **Memoize prefix computations**: Cache (state, value) pairs to enable state jumps
2. **Maintain clean state boundaries**: Save/restore state, evaluate from correct initial state
3. **Use iteration-local randomness**: Each iteration consumes RNG independently
4. **Select elites by cumulative performance**: Top-k by total reward (or per spec)
5. **Update distributions from elite frequencies**: Empirical frequencies from elite samples
6. **Parameterize everything**: Use `self.num_actions`, `self.length`, etc., not hardcoded values
7. **Verify invariants**: Position restored, probs sum to 1, cache persists, etc.

**When adapting to new variants:**
- Read the spec carefully for each variation dimension
- Use the Variant Adaptation Guide to check each dimension
- Follow the Validation Checklist to verify correctness
- Test edge cases specific to the variant
- Compare with manual calculations for small examples

---
name: cross-entropy-method
description: Implementation of the Cross-Entropy Method (CEM) for trajectory optimization in discrete-action environments with memoized plan evaluation
---

# Cross-Entropy Method for Discrete-Action Trajectory Optimization

## Quick Reference: Critical Requirements

**Before implementing, verify these 7 requirements:**

1. **Independent axis clipping**: Each dimension clips separately; clipping x must not suppress y
2. **Inclusive goal boundary**: Use `<=` not `<` for distance checks
3. **Empty prefix seeding**: Cache must be seeded with `()` -> (start_position, 0) before first evaluation
4. **Conditional caching**: Only write to cache if prefix not already present
5. **Cache persistence**: Cache persists across multiple `evaluate_plans_memoized` calls
6. **Side-effect freedom**: Environment position unchanged after batch evaluation
7. **Iteration-local RNG**: No RNG state saved/restored between iterations

**When to use this skill**: Sequential decision optimization where you can sample solutions, evaluate quality, and learn from top performers.

---

## Overview

The Cross-Entropy Method (CEM) iteratively refines a probability distribution over action sequences by:
1. Sampling candidate action sequences from current distribution
2. Evaluating each sequence's cumulative reward
3. Selecting top-performing "elite" sequences
4. Updating distribution to match elite action frequencies

This skill applies to point-mass environments in bounded 2D grids, but the principles generalize to any sequential decision problem.

## Component Integration

**Data flow**: CEM → evaluate_plans_memoized → step → environment

- **CEM** generates batches of action plans and updates probability distributions
- **evaluate_plans_memoized** evaluates plans efficiently using prefix caching
- **step** simulates individual actions with clipping and reward calculation
- **Environment** maintains state (position) and provides reset/step interface

**Key interaction**: CEM calls `evaluate_plans_memoized` multiple times per optimization. The cache accumulates across calls, making subsequent iterations faster as plans share prefixes with previously evaluated plans.

## Core Components

### 1. Environment Dynamics (PointEnv)

**State Space**: Integer coordinates in `[-length/2, +length/2]` per axis.

**Action Space**: Discrete actions mapped to 2D movement vectors (9 directions: stay, 4 cardinal, 4 diagonal).

**Step Function**:
```python
def step(self, action: int) -> int:
    delta = action_map[action]
    position = position + delta
    # CRITICAL: Clip each axis INDEPENDENTLY
    half = length // 2
    position[0] = clip(position[0], -half, half)
    position[1] = clip(position[1], -half, half)
    # CRITICAL: Use <= for inclusive boundary
    distance = euclidean_distance(position, goal)
    return 1 if distance <= goal_radius else 0
```

### 2. Memoized Plan Evaluation

**Purpose**: Evaluate batches of action sequences efficiently using prefix caching.

**Algorithm**:
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    saved_position = position.copy()
    # CRITICAL: Seed cache with empty prefix
    if () not in _state_cache:
        _state_cache[()] = (saved_position.copy(), 0)
    
    for each plan:
        # Find longest cached prefix (search from horizon down to 0)
        for t from horizon down to 0:
            prefix = plan[:t]
            if prefix in _state_cache:
                restore position and reward from cache
                break
        # Continue simulation from cached state
        for t from cached_length to horizon:
            reward = step(plan[t])
            cumulative_reward += reward
            # CRITICAL: Only cache if not already present
            if plan[:t+1] not in _state_cache:
                _state_cache[plan[:t+1]] = (position.copy(), cumulative_reward)
    
    position = saved_position  # CRITICAL: Restore position
    return rewards
```

**Key insight**: Plans sharing prefixes (e.g., `[2,2,1]` and `[2,2,0]`) reuse cached states, transforming O(N×H) work into O(unique prefixes) work.

### 3. Cross-Entropy Optimization

**Algorithm**:
```python
def optimize(self, num_samples, num_elites, iterations):
    for iteration in range(iterations):
        # Sample plans from current distribution
        plans = zeros((num_samples, horizon))
        for t in range(horizon):
            plans[:, t] = random.choice(num_actions, size=num_samples, p=probs[t])
        
        # Evaluate all plans
        rewards = env.evaluate_plans_memoized(plans)
        
        # Select elites (top num_elites by reward)
        elite_indices = argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Update probabilities from elite frequencies
        for t in range(horizon):
            for action in range(num_actions):
                count = sum(elite_plans[:, t] == action)
                probs[t, action] = count / num_elites
```

**Critical requirement**: RNG consumption must be iteration-local. Two calls of 10 iterations must match one call of 20 iterations under the same seed. Never save/restore RNG state between iterations.

## Variation Dimensions & Adaptation

### Environment Dynamics
**What varies**: Map size, goal placement, goal radius, action sets, boundary behavior, reward metric

**Adaptation**: Identify state space, action space, transition function, and reward function. The CEM algorithm doesn't change—only environment-specific components do. Key invariants: independent axis clipping, inclusive boundaries, Euclidean distance metric.

### Policy Update Regime
**What varies**: Sample counts, elite fractions, trajectory lengths, reward sparsity, convergence patterns

**Adaptation**: Adjust hyperparameters based on problem difficulty. Sparse rewards need more samples. Long horizons need more iterations. High-dimensional action spaces need more elites. Key invariant: iteration-local RNG consumption.

### Overlapping Plan Evaluation
**What varies**: Prefix overlap, repeated plans, batch sizes, cache persistence

**Adaptation**: Memoization works whenever plans share prefixes. More overlap = greater speedup. For independent plans, memoization adds overhead. Key invariants: cache persistence across calls, conditional writes, side-effect freedom.

## Common Pitfalls

### Environment Implementation
1. **Axis coupling in clipping**: Each dimension must clip independently. Clipping x must not suppress y.
2. **Goal boundary inclusivity**: Use `<=` not `<` for distance checks. Boundary positions are typically valid.

### Memoization Implementation
3. **Cache persistence**: Cache must persist across calls, not just within one call. Memoization is only valuable if it accumulates knowledge.
4. **Side-effect freedom**: Environment position must be unchanged after batch evaluation. Evaluation functions should be pure.
5. **Cache completeness**: Store both state AND cumulative reward. Cache everything needed to resume computation.
6. **Empty prefix seeding**: Cache must be seeded with empty prefix `()` before evaluating plans. Without seeding, the first plan has no cached prefix to find.
7. **Conditional caching**: Only write to cache if prefix not already present. Unconditional writes defeat memoization.

### CEM Implementation
8. **RNG iteration locality**: Must be iteration-local for reproducibility. Never save/restore RNG state within an iteration loop.
9. **Elite selection stability**: Use stable sorting for deterministic tie-breaking. Always use deterministic selection when possible.

## Testing Checklist

### Environment
- [ ] Independent axis clipping: Verify clipping one axis doesn't suppress others
- [ ] Boundary inclusivity: Test positions at exact boundary values
- [ ] Goal detection: Verify reward at exactly `goal_radius` distance
- [ ] Negative coordinates: Test movement in negative directions
- [ ] Stay action: Verify action [0,0] doesn't change position

### Memoization
- [ ] Cache persistence: Verify cache grows across multiple evaluation calls
- [ ] Prefix sharing: Verify plans with shared prefixes reuse cached states
- [ ] Side-effect freedom: Verify position unchanged after evaluation
- [ ] Exact duplicates: Verify identical plans return identical rewards
- [ ] Cache correctness: Verify cached results match fresh computation

### CEM
- [ ] Iteration locality: Verify 10+10 iterations equals 20 iterations
- [ ] Probability normalization: Verify probabilities sum to 1 at each timestep
- [ ] Elite selection: Verify highest-reward plans are selected
- [ ] Distribution update: Verify probabilities match elite frequencies
- [ ] Convergence: Verify policy improves over iterations

### Edge Cases
- [ ] Empty plans: Handle zero-length plan arrays
- [ ] Single step: Handle horizon=1
- [ ] Large goal radius: Handle goals that cover entire environment
- [ ] Goal at origin: Handle goal at starting position
- [ ] All plans identical: Handle batch of duplicate plans

## Example Usage

```python
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# Create environment
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)

# Create optimizer
cem = CrossEntropyMethod(env, horizon=15)

# Optimize
np.random.seed(42)
cem.optimize(num_samples=100, num_elites=25, iterations=20)

# Check learned policy
print("Action probabilities at timestep 0:")
print(cem.probs[0])
```

## Performance Analysis

### Memoization Performance
- **Speedup**: O(N×H) → O(unique prefixes) when plans share structure
- **Memory**: One cache entry per unique prefix (position + reward)
- **When it helps**: High prefix overlap (CEM's typical case)
- **When it hurts**: No overlap (adds overhead without benefit)

### CEM Performance
- **Sample count**: More samples = more stable estimates, but O(samples × horizon) evaluation cost
- **Elite count**: More elites = more exploration, fewer = more exploitation
- **Iteration count**: More iterations = better convergence, but each iteration is expensive
- **Trade-off**: Balance exploration (many samples/elites) vs exploitation (focused search)

### Scaling
- **Horizon length**: Longer horizons exponentially increase plan space, but memoization keeps it tractable
- **Action space size**: More actions = more samples needed for good coverage
- **Environment complexity**: Complex dynamics = more iterations needed for convergence

## Debugging Tips

1. **Check memoization**: Print cache size after evaluation to verify it's growing
2. **Verify position restoration**: Check `env.position` before and after evaluation
3. **Test RNG locality**: Compare probs after 10+10 iterations vs 20 iterations
4. **Visualize convergence**: Plot reward distribution over iterations
5. **Check elite selection**: Print elite rewards to verify they're the highest

## Adapting to New Variants

When encountering a new variant:

1. **Identify what changed**: Map changes to the three variation dimensions (environment_dynamics, policy_update_regime, overlapping_plan_evaluation)
2. **Verify invariants still hold**: Check the 7 critical requirements from the Quick Reference
3. **Adapt implementation**: Reuse patterns if invariants hold; adjust if invariants change
4. **Test thoroughly**: Run the testing checklist and add variant-specific tests

### Common Variant Patterns
- **Larger maps**: Increase `length`, adjust goal placement to stay within bounds
- **Different goals**: Change `goal_x`, `goal_y`, `goal_radius` while maintaining `|goal| < length/2`
- **Different action sets**: Modify `action_map` but keep the same step/clip/reward logic
- **Different horizons**: Adjust `horizon` parameter, ensure cache handles longer prefixes
- **Different sample sizes**: Adjust `num_samples` and `num_elites`, verify probability normalization

## Reference Implementation

The complete reference implementation is in `/app/cross_entropy_method/cross_entropy.py`. Key implementation details:

### Environment (PointEnv)
```python
def __init__(self, length, goal_x, goal_y, goal_radius):
    # ... existing init code ...
    self.position = np.array((0, 0), dtype=np.int_)
    # CRITICAL: Initialize the memoization cache
    self._state_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {}

def step(self, action: int) -> int:
    delta = PointEnv.action_map[action]
    self.position = self.position + delta
    half = self.length // 2
    self.position[0] = np.clip(self.position[0], -half, half)
    self.position[1] = np.clip(self.position[1], -half, half)
    dist = np.linalg.norm(self.position - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

### Memoized Evaluation
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    saved_position = self.position.copy()
    
    # CRITICAL: Seed the cache with the empty prefix (starting state)
    # Without this, the first plan ever evaluated has no cached prefix to find
    empty_key = ()
    if empty_key not in self._state_cache:
        self._state_cache[empty_key] = (saved_position.copy(), 0)
    
    N, H = plans.shape
    rewards = []
    for i in range(N):
        plan = tuple(plans[i].tolist())
        best_prefix_len = 0
        best_pos = np.array((0, 0), dtype=np.int_)
        best_reward = 0
        
        # Search for longest cached prefix (from H down to 0)
        for t in range(H, -1, -1):
            prefix = plan[:t]
            if prefix in self._state_cache:
                best_prefix_len = t
                best_pos, best_reward = self._state_cache[prefix]
                break
        
        self.position = best_pos.copy()
        total_reward = best_reward
        for t in range(best_prefix_len, H):
            action = plan[t]
            reward = self.step(action)
            total_reward += reward
            prefix = plan[:t + 1]
            
            # CRITICAL: Only cache if not already present
            # Without this check, we overwrite cached entries and lose memoization benefits
            if prefix not in self._state_cache:
                self._state_cache[prefix] = (self.position.copy(), total_reward)
        
        rewards.append(total_reward)
    self.position = saved_position
    return rewards
```

### CEM Optimization
```python
def optimize(self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20) -> None:
    for _ in range(iterations):
        plans = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        for t in range(self.horizon):
            for a in range(self.num_actions):
                count = np.sum(elite_plans[:, t] == a)
                self.probs[t, a] = count / num_elites
```

## Summary

This skill provides a complete implementation of the Cross-Entropy Method for discrete-action trajectory optimization in bounded 2D environments. The key innovations are:

1. **Independent axis clipping**: Physical constraints are per-dimension
2. **Prefix-based memoization**: Caches intermediate states to avoid redundant computation
3. **Iteration-local RNG**: Ensures reproducibility and enables split optimization
4. **Side-effect free evaluation**: Enables multiple evaluations without interference

The skill is designed to generalize across the three variation dimensions: environment dynamics, policy update regime, and overlapping plan evaluation. By understanding the underlying principles rather than memorizing implementation details, you can adapt this skill to new variants within the family.

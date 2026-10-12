---
name: cross-entropy-method
description: Implementation of the Cross-Entropy Method (CEM) for trajectory optimization in discrete-action environments with memoized plan evaluation
---

# Cross-Entropy Method for Discrete-Action Trajectory Optimization

## Overview

The Cross-Entropy Method (CEM) is a sampling-based optimization algorithm that iteratively improves a policy by:
1. Sampling candidate action sequences from a probability distribution
2. Evaluating each sequence's cumulative reward
3. Selecting the top-performing "elite" sequences
4. Updating the probability distribution to match elite action frequencies

This skill applies to point-mass environments in bounded 2D grids where agents receive rewards for reaching goal regions.

## Core Components

### 1. Environment Dynamics (PointEnv)

**State Space**: Integer coordinates in a bounded square `[-length/2, +length/2]` for each axis independently.

**Action Space**: Discrete actions mapped to 2D movement vectors (typically 9 directions including stay, 4 cardinal, 4 diagonal).

**Step Function**:
```python
def step(self, action: int) -> int:
    # Apply movement
    delta = action_map[action]
    position = position + delta
    
    # Clip each axis INDEPENDENTLY to bounds
    # Critical: clipping one axis must NOT suppress motion on the other
    half = length // 2
    position[0] = clip(position[0], -half, half)
    position[1] = clip(position[1], -half, half)
    
    # Check goal proximity
    distance = euclidean_distance(position, goal)
    return 1 if distance <= goal_radius else 0
```

**Key Invariants**:
- Independent axis clipping: if x would exceed bounds but y wouldn't, x clips and y still moves
- Inclusive boundary: positions at exactly `±length/2` are valid
- Goal check: Euclidean distance `<=` goal_radius (not `<`)

### 2. Memoized Plan Evaluation

**Purpose**: Efficiently evaluate batches of action sequences by caching intermediate states.

**Algorithm**:
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    # Save current position
    saved_position = position.copy()
    
    # Initialize persistent cache if needed
    if not hasattr(self, '_state_cache'):
        _state_cache = {}  # maps prefix_tuple -> (position, cumulative_reward)
    
    rewards = []
    for each plan:
        # Find longest cached prefix
        for t from horizon down to 0:
            prefix = plan[:t]
            if prefix in _state_cache:
                restore position and reward from cache
                break
        
        # Continue simulation from cached state
        for t from cached_length to horizon:
            reward = step(plan[t])
            cumulative_reward += reward
            cache[plan[:t+1]] = (position.copy(), cumulative_reward)
        
        rewards.append(cumulative_reward)
    
    # Restore original position
    position = saved_position
    return rewards
```

**Critical Properties**:
- Cache persists across multiple calls to `evaluate_plans_memoized`
- Prefix sharing: plans `[2,2,1]` and `[2,2,0]` share the cached prefix `(2,2)`
- Environment position is restored after evaluation (side-effect free)
- Cache stores both position AND cumulative reward for each prefix

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

**Critical Properties**:
- **Iteration-local RNG**: Each iteration consumes RNG state independently
  - Two calls of 10 iterations must match one call of 20 iterations under same seed
  - This means no RNG state is saved/restored between iterations
- **Elite selection**: Use `argsort` to get indices, then slice top `num_elites`
- **Probability update**: Count action frequencies in elites, normalize by `num_elites`
- **Distribution shape**: `probs[t, a]` = probability of action `a` at timestep `t`

## Variation Dimensions

### Environment Dynamics
The skill handles variations in:
- **Map size**: Different `length` values (must be even, positive)
- **Goal placement**: Different `goal_x`, `goal_y` (must satisfy `|goal| < length/2`)
- **Goal radius**: Different `goal_radius` values (must be positive)
- **Action sets**: Different action maps (still representing local motion)
- **Boundary behavior**: Clipping rules remain the same (independent per-axis)
- **Reward metric**: Euclidean distance with inclusive boundary

### Policy Update Regime
The skill handles variations in:
- **Sample counts**: Different `num_samples` values
- **Elite fractions**: Different `num_elites` values
- **Trajectory lengths**: Different `horizon` values
- **Reward sparsity**: Works with both dense and sparse rewards
- **Convergence patterns**: Handles deterministic priors, tied rewards, repeated optimization calls

### Overlapping Plan Evaluation
The skill handles variations in:
- **Prefix overlap**: Plans sharing common prefixes benefit from caching
- **Repeated plans**: Exact duplicate plans reuse cached results
- **Batch sizes**: Different numbers of plans per evaluation
- **Cache persistence**: Memoization accumulates across multiple evaluation calls

## Common Pitfalls

1. **Axis coupling in clipping**: Clipping x must not prevent y from moving
   - Wrong: `if x > bound: x = bound; else: x += delta_x; y += delta_y`
   - Right: `x = clip(x + delta_x, -bound, bound); y = clip(y + delta_y, -bound, bound)`

2. **Goal boundary**: Use `<=` not `<` for distance check
   - Position exactly at `goal_radius` distance should receive reward

3. **Memoization scope**: Cache must persist across calls, not just within one call
   - Initialize cache in `__init__` or lazily on first use
   - Don't clear cache between `evaluate_plans_memoized` calls

4. **Position restoration**: Environment position must be unchanged after batch evaluation
   - Save position at start, restore at end
   - This allows evaluation to be called multiple times without side effects

5. **RNG consumption**: Must be iteration-local for reproducibility
   - Don't save/restore RNG state between iterations
   - Two calls of N iterations must equal one call of 2N iterations

6. **Elite selection with ties**: `argsort` handles ties deterministically
   - When rewards are tied, lower indices come first in sorted order
   - Taking the last `num_elites` indices gives highest rewards

## Testing Checklist

- [ ] Step function clips each axis independently
- [ ] Step function returns 1 when distance `<=` goal_radius
- [ ] Memoization cache persists across calls
- [ ] Prefix sharing works (not just whole-plan caching)
- [ ] Environment position unchanged after evaluation
- [ ] Two calls of 10 iterations match one call of 20 iterations
- [ ] Handles boundary cases (position at exact bounds)
- [ ] Handles edge cases (goal at origin, large goal radius)

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

## Performance Considerations

- **Memoization speedup**: Most significant when plans share long prefixes
- **Cache memory**: Stores (position, reward) for each unique prefix
- **Batch evaluation**: Evaluates N plans in one call for efficiency
- **Iteration count**: More iterations = better convergence but more computation

## Debugging Tips

1. **Check memoization**: Print cache size after evaluation to verify it's growing
2. **Verify position restoration**: Check `env.position` before and after evaluation
3. **Test RNG locality**: Compare probs after 10+10 iterations vs 20 iterations
4. **Visualize convergence**: Plot reward distribution over iterations
5. **Check elite selection**: Print elite rewards to verify they're the highest

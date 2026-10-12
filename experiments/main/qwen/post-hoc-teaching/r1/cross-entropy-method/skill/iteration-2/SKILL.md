---
name: cross-entropy-method
description: Implementation of the Cross-Entropy Method (CEM) for trajectory optimization in discrete-action environments with memoized plan evaluation
---

# Cross-Entropy Method for Discrete-Action Trajectory Optimization

## Overview

The Cross-Entropy Method (CEM) is a sampling-based optimization algorithm for trajectory optimization. The core principle: iteratively refine a probability distribution over action sequences by keeping the best-performing samples and learning from their structure.

**When to use this skill**: Any problem requiring optimization of sequential decisions under uncertainty, where:
- You can sample candidate solutions from a parameterized distribution
- You can evaluate solution quality (reward/fitness)
- The solution space has structure that elites can reveal

**Core algorithm**:
1. Sample candidate action sequences from current distribution
2. Evaluate each sequence's cumulative reward
3. Select top-performing "elite" sequences
4. Update distribution to match elite action frequencies

This skill applies to point-mass environments in bounded 2D grids where agents receive rewards for reaching goal regions, but the principles generalize to any sequential decision problem.

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
    
    # CRITICAL: Seed cache with empty prefix (starting state)
    # This ensures the first plan always has a cached prefix to find
    if () not in _state_cache:
        _state_cache[()] = (saved_position.copy(), 0)
    
    rewards = []
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
- **Empty prefix seeding**: Cache must be seeded with `()` -> (starting_position, 0) before evaluating any plans, otherwise the first plan has no cached prefix to find
- **Conditional caching**: Only write to cache if prefix not already present; unconditional writes defeat memoization by overwriting cached entries

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

## Variation Dimensions & Adaptation Strategies

### Environment Dynamics
**What varies**: Map size, goal placement, goal radius, action sets, boundary behavior, reward metric

**Adaptation principles**:
- **Boundary handling**: Always clip each dimension independently. The key insight: clipping one dimension must not suppress motion in others. This is a physical constraint, not an implementation detail.
- **Goal checking**: Use the distance metric specified (typically Euclidean). Always use inclusive boundary (`<=` not `<`) unless explicitly stated otherwise.
- **Action spaces**: The action map defines the mapping from discrete actions to state changes. The skill works with any action set that represents local motion in the state space.
- **State representation**: Integer coordinates are typical, but the principle applies to any discrete state space with well-defined transitions.

**When adapting**: Identify the state space, action space, transition function, and reward function. The CEM algorithm itself doesn't change—only these environment-specific components do.

### Policy Update Regime
**What varies**: Sample counts, elite fractions, trajectory lengths, reward sparsity, convergence patterns

**Adaptation principles**:
- **Iteration locality**: RNG consumption must be iteration-local. This is critical for reproducibility and allows splitting optimization across multiple calls. Never save/restore RNG state between iterations.
- **Elite selection**: Use stable sorting (argsort) to handle ties deterministically. The top-K by reward are elites, regardless of absolute reward values.
- **Distribution updates**: Count action frequencies in elites, normalize by elite count. This works for any categorical distribution, not just uniform priors.
- **Convergence**: More samples = more stable estimates but slower iterations. More elites = more exploration but less exploitation. The optimal balance depends on problem complexity.

**When adapting**: Adjust these hyperparameters based on problem difficulty. Sparse rewards need more samples. Long horizons need more iterations. High-dimensional action spaces need more elites.

### Overlapping Plan Evaluation
**What varies**: Prefix overlap, repeated plans, batch sizes, cache persistence

**Adaptation principles**:
- **Memoization scope**: Cache must persist across calls, not just within one call. This is essential for CEM, which makes many evaluation calls with overlapping plans.
- **Prefix sharing**: The key optimization: plans sharing common prefixes should reuse cached intermediate states. This transforms O(N×H) work into O(unique prefixes) work.
- **Cache contents**: Store both position (state) AND cumulative reward for each prefix. Storing only reward forces replay; storing only position forces recomputation.
- **Side-effect freedom**: Batch evaluation must not change the environment's public state. Save and restore position to enable multiple evaluations without interference.

**When adapting**: The memoization strategy works whenever plans have overlapping prefixes. The more overlap, the greater the speedup. For completely independent plans, memoization adds overhead without benefit.

## Common Pitfalls & How to Avoid Them

### Environment Implementation
1. **Axis coupling in clipping**: Each dimension must be clipped independently
   - **Why it matters**: Physical constraints are per-dimension, not coupled
   - **How to verify**: Test that clipping x doesn't prevent y from moving
   - **General principle**: Constraints apply to each dimension separately unless explicitly coupled

2. **Goal boundary inclusivity**: Use `<=` not `<` for distance checks
   - **Why it matters**: Boundary positions are typically valid
   - **How to verify**: Test position exactly at `goal_radius` distance
   - **General principle**: Unless stated otherwise, boundaries are inclusive

### Memoization Implementation
3. **Cache persistence**: Must persist across calls, not just within one call
   - **Why it matters**: CEM makes many evaluation calls with overlapping plans
   - **How to verify**: Check cache size grows across multiple `evaluate_plans_memoized` calls
   - **General principle**: Memoization is only valuable if it accumulates knowledge

4. **Side-effect freedom**: Environment position must be unchanged after batch evaluation
   - **Why it matters**: Enables multiple evaluations without interference
   - **How to verify**: Check position before and after evaluation
   - **General principle**: Evaluation functions should be pure (no side effects)

5. **Cache completeness**: Store both state AND cumulative reward
   - **Why it matters**: Storing only one forces recomputation of the other
   - **How to verify**: Ensure cache enables skipping from any cached prefix
   - **General principle**: Cache everything needed to resume computation

6. **Empty prefix seeding**: Cache must be seeded with empty prefix `()` before evaluating plans
   - **Why it matters**: Without seeding, the first plan has no cached prefix to find, causing crashes or fragile reliance on default values
   - **How to verify**: Evaluate a single plan on a fresh cache; verify it doesn't crash and correctly starts from origin
   - **General principle**: Always initialize cache with the starting state before any lookups

7. **Conditional caching**: Only write to cache if prefix not already present
   - **Why it matters**: Unconditional writes overwrite cached entries, defeating memoization and forcing redundant simulation
   - **How to verify**: Evaluate plans with shared prefixes; verify cache size doesn't grow unnecessarily and performance improves
   - **General principle**: Cache writes should be conditional to preserve existing cached data

### CEM Implementation
8. **RNG iteration locality**: Must be iteration-local for reproducibility
   - **Why it matters**: Enables splitting optimization across multiple calls
   - **How to verify**: Two calls of N iterations must equal one call of 2N iterations
   - **General principle**: Never save/restore RNG state within an iteration loop

9. **Elite selection stability**: Use stable sorting for deterministic tie-breaking
   - **Why it matters**: Ensures reproducibility and consistent behavior
   - **How to verify**: Test with tied rewards
   - **General principle**: Always use deterministic selection when possible

## Testing & Verification Strategy

### Environment Tests
- [ ] **Independent axis clipping**: Verify clipping one axis doesn't suppress others
- [ ] **Boundary inclusivity**: Test positions at exact boundary values
- [ ] **Goal detection**: Verify reward at exactly `goal_radius` distance
- [ ] **Negative coordinates**: Test movement in negative directions
- [ ] **Stay action**: Verify action [0,0] doesn't change position

### Memoization Tests
- [ ] **Cache persistence**: Verify cache grows across multiple evaluation calls
- [ ] **Prefix sharing**: Verify plans with shared prefixes reuse cached states
- [ ] **Side-effect freedom**: Verify position unchanged after evaluation
- [ ] **Exact duplicates**: Verify identical plans return identical rewards
- [ ] **Cache correctness**: Verify cached results match fresh computation

### CEM Tests
- [ ] **Iteration locality**: Verify 10+10 iterations equals 20 iterations
- [ ] **Probability normalization**: Verify probabilities sum to 1 at each timestep
- [ ] **Elite selection**: Verify highest-reward plans are selected
- [ ] **Distribution update**: Verify probabilities match elite frequencies
- [ ] **Convergence**: Verify policy improves over iterations

### Edge Cases
- [ ] **Empty plans**: Handle zero-length plan arrays
- [ ] **Single step**: Handle horizon=1
- [ ] **Large goal radius**: Handle goals that cover entire environment
- [ ] **Goal at origin**: Handle goal at starting position
- [ ] **All plans identical**: Handle batch of duplicate plans

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

## Performance Analysis & Optimization

### Memoization Performance
- **Speedup potential**: O(N×H) → O(unique prefixes) when plans share structure
- **Memory cost**: One cache entry per unique prefix (position + reward)
- **When it helps**: High prefix overlap (CEM's typical case)
- **When it hurts**: No overlap (adds overhead without benefit)
- **Optimization**: Search for longest cached prefix first (O(H) per plan)

### CEM Performance
- **Sample count**: More samples = more stable estimates, but O(samples × horizon) evaluation cost
- **Elite count**: More elites = more exploration, fewer = more exploitation
- **Iteration count**: More iterations = better convergence, but each iteration is expensive
- **Trade-off**: Balance exploration (many samples/elites) vs exploitation (focused search)

### Batch Evaluation
- **Vectorization**: Evaluate all plans in one call for efficiency
- **Cache reuse**: Plans evaluated in the same batch share cache lookups
- **Memory locality**: Process plans sequentially to maximize cache hits

### Scaling Considerations
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

When encountering a new variant within this family, follow this reasoning process:

### Step 1: Identify What Changed
- Read the variant specification carefully
- Map changes to the three variation dimensions (environment_dynamics, policy_update_regime, overlapping_plan_evaluation)
- Determine which changes affect invariants vs which are just parameter variations

### Step 2: Verify Invariants Still Hold
- Independent axis clipping: Does the new variant still require this?
- Inclusive boundaries: Are boundaries still inclusive?
- Cache persistence: Does memoization still need to persist across calls?
- Iteration locality: Is RNG consumption still iteration-local?
- Side-effect freedom: Must evaluation still be side-effect free?

### Step 3: Adapt Implementation
- If invariants hold: Reuse the same implementation patterns
- If invariants change: Identify the new invariant and adjust accordingly
- If new constraints appear: Add handling for the new constraints while preserving existing invariants

### Step 4: Test Thoroughly
- Run the testing checklist from this skill
- Add variant-specific tests for the new constraints
- Verify that existing invariants still hold under the new variant

### Common Variant Patterns

**Larger maps**: Increase `length`, adjust goal placement to stay within bounds
**Different goals**: Change `goal_x`, `goal_y`, `goal_radius` while maintaining `|goal| < length/2`
**Different action sets**: Modify `action_map` but keep the same step/clip/reward logic
**Different horizons**: Adjust `horizon` parameter, ensure cache handles longer prefixes
**Different sample sizes**: Adjust `num_samples` and `num_elites`, verify probability normalization

## Reference Implementation

The complete reference implementation is in `/app/cross_entropy_method/cross_entropy.py`. Key implementation details:

### Environment (PointEnv)
```python
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

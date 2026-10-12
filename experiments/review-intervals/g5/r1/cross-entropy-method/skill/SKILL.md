---
name: cross-entropy-method
description: Implementation patterns for cross-entropy method optimization in bounded discrete-action environments with prefix-trie memoization for efficient batch plan evaluation
---

# Cross-Entropy Method Skill

This skill captures the core mechanisms for implementing cross-entropy method (CEM) optimization in environments with discrete actions, bounded state spaces, and the need for efficient batch evaluation of action sequences.

## Core Mechanisms

### 1. Independent Axis Clipping in Bounded Environments

**Pattern**: When an agent moves in a bounded space, clip each coordinate independently after applying the motion delta.

**Implementation**:
```python
def step(self, action: int) -> int:
    delta = self.action_map[action]
    self.position = self.position + delta
    
    # Clip each coordinate independently
    half = self.length // 2
    self.position[0] = np.clip(self.position[0], -half, half)
    self.position[1] = np.clip(self.position[1], -half, half)
    
    # Compute reward based on final position
    dist = np.linalg.norm(self.position - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

**Critical insight**: Do NOT reject the entire move if either axis would exceed bounds. Add the delta first, then clip each axis independently. This allows motion on one axis even when the other is at its boundary.

**Verification**: Test with position at boundary (e.g., `[3, 2]` in a `[-3, 3]` space) and action `[1, 1]`. Expected result: `[3, 3]` (x clipped, y moved).

### 2. Prefix-Trie Memoization for Batch Plan Evaluation

**Pattern**: Use a trie (prefix tree) to cache intermediate states during plan evaluation, enabling reuse of shared prefixes across plans.

**Data structure**:
```python
# Trie node structure
{
    '_pos': np.array([...]),      # Position at this prefix
    '_reward': int,                # Cumulative reward up to this prefix
    '_children': {action: node}    # Child nodes indexed by action
}
```

**Algorithm**:
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    # Save public state
    saved_position = self.position.copy()
    
    results = []
    for plan in plans:
        plan_tuple = tuple(int(a) for a in plan)
        
        # Walk trie as far as cached
        node = self._cache
        cached_depth = 0
        
        for i, action in enumerate(plan_tuple):
            if action in node['_children']:
                node = node['_children'][action]
                cached_depth = i + 1
            else:
                break
        
        # Simulate remaining steps from cached state
        pos = node['_pos'].copy()
        cum_reward = node['_reward']
        
        for i in range(cached_depth, len(plan_tuple)):
            action = plan_tuple[i]
            
            # Create new trie node
            new_node = {'_children': {}}
            pos, cum_reward = self._simulate_from(pos, cum_reward, action)
            new_node['_pos'] = pos.copy()
            new_node['_reward'] = cum_reward
            
            node['_children'][action] = new_node
            node = new_node
        
        results.append(cum_reward)
    
    # Restore public state
    self.position = saved_position
    return results
```

**Key properties**:
- Trie persists across calls (stored as `self._cache`)
- Reuses shared prefixes, not just exact duplicates
- Does NOT mutate `self.position` during evaluation
- Provides significant speedup (20x+) when plans share prefixes

**Critical insight**: The trie root represents the initial state (position, cumulative reward). Each edge is an action. Walk the trie to find the deepest cached prefix, then simulate only the uncached suffix.

### 3. Cross-Entropy Method Optimization Loop

**Pattern**: Iteratively refine action distributions by sampling plans, evaluating them, selecting elites, and updating distributions based on elite action frequencies.

**Algorithm**:
```python
def optimize(self, num_samples, num_elites, iterations):
    for _ in range(iterations):
        # Sample plans: each timestep from its categorical distribution
        plans = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate all plans
        rewards = self.env.evaluate_plans_memoized(plans)
        rewards = np.array(rewards)
        
        # Select elites (top num_elites by reward)
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Update probabilities based on elite action frequencies
        for t in range(self.horizon):
            for a in range(self.num_actions):
                self.probs[t, a] = np.mean(elite_plans[:, t] == a)
```

**Critical insights**:
- Use global numpy RNG sequentially (don't reset seeds per iteration)
- This ensures iteration-local RNG consumption: two calls of 10 iterations match one call of 20 under the same seed
- Elite selection uses `np.argsort` descending, taking the last `num_elites` indices
- Probability update: for each timestep, compute frequency of each action among elites

## Family Invariants

These properties hold across all variants in the task family:

1. **Independent axis clipping**: Motion on one axis is never suppressed by boundary violations on another axis
2. **Prefix-trie memoization**: Batch evaluation must reuse shared prefixes, not just cache whole plans
3. **State preservation**: Batch evaluation must not mutate the public environment position
4. **Iteration-local RNG**: CEM optimization must consume RNG sequentially so that splitting iterations preserves behavior
5. **Cumulative rewards**: Plans earn per-step rewards summed over the trajectory
6. **Exact results**: Memoization must produce results identical to brute-force simulation

### Mapping Spec Axes to Invariants

For transfer to unseen variants, understand how the three spec axes relate to these invariants:

**environment_dynamics axis** → Invariants #1, #5, #6
- The clipping bounds are always `[-length//2, length//2]` regardless of map size
- The reward condition is always `Euclidean distance ≤ goal_radius` regardless of goal placement
- Independent axis clipping applies to any bounded square environment
- Cumulative per-step rewards apply regardless of goal geometry

**policy_update_regime axis** → Invariant #4
- The probability update formula `np.mean(elite_plans[:, t] == a)` works for any elite fraction
- Iteration-local RNG consumption holds regardless of sample count, elite count, or horizon
- Sequential global RNG usage ensures split-iteration equivalence for any iteration count

**overlapping_plan_evaluation axis** → Invariants #2, #3
- The prefix-trie structure works for any degree of prefix overlap (from 0% to 100%)
- State preservation (save/restore position) applies regardless of batch size or plan uniqueness
- Trie persistence across calls enables cumulative speedup for any evaluation pattern

## Spec-Declared Variations

These dimensions vary across family members:

### Environment Dynamics
- **Map size**: `length` parameter (must be even for integer bounds)
- **Goal placement**: `goal_x`, `goal_y` coordinates
- **Goal radius**: `goal_radius` for circular reward region
- **Action set**: `action_map` defining discrete motion vectors
- **Boundary behavior**: Clipping bounds `[-length/2, length/2]`

### Policy Update Regime
- **Sample count**: `num_samples` per iteration
- **Elite fraction**: `num_elites` selection
- **Trajectory length**: `horizon` parameter
- **Reward sparsity**: Goal radius and placement affect reward frequency
- **Convergence patterns**: Different environments require different iteration counts

### Overlapping Plan Evaluation
- **Prefix overlap**: Degree of shared prefixes in plan batches
- **Batch size**: Number of plans evaluated simultaneously
- **Plan uniqueness**: Mix of repeated and unique plans
- **Horizon variation**: Different plan lengths across calls

## Verification Procedures

### Boundary Clipping
```python
# Test independent axis clipping at actual boundaries
env.position = np.array([3, 2])  # Near boundary in [-3, 3] space
env.step(2)  # Action [1, 1]
assert np.array_equal(env.position, [3, 3])  # x clipped, y moved
```

### Memoization Correctness
```python
# Compare memoized results to brute-force simulation
def brute_force_eval(env, plan):
    pos = np.array([0, 0], dtype=np.int_)
    half = env.length // 2
    total = 0
    for a in plan:
        delta = PointEnv.action_map[a]
        pos = np.clip(pos + delta, -half, half)
        dist = np.linalg.norm(pos - env.goal)
        if dist <= env.goal_radius:
            total += 1
    return total

# Verify for many plans with shared prefixes
assert list(memoized_rewards) == [brute_force_eval(env, p) for p in plans]
```

### RNG Iteration-Locality
```python
# Two calls of 10 iterations should match one call of 20
np.random.seed(100)
cem1.optimize(iterations=10)
cem1.optimize(iterations=10)

np.random.seed(100)
cem2.optimize(iterations=20)

assert np.allclose(cem1.probs, cem2.probs)
```

### Memoization Speedup
```python
# Second call with same plans should be much faster
t0 = time.time()
r1 = env.evaluate_plans_memoized(plans)
t1 = time.time()
r2 = env.evaluate_plans_memoized(plans)  # All cached
t2 = time.time()

speedup = (t1 - t0) / (t2 - t1)
assert speedup > 10  # Expect significant speedup
assert list(r1) == list(r2)  # Results must match
```

## Common Pitfalls

1. **Rejecting entire moves at boundaries**: Don't check bounds before applying delta. Add first, then clip per-axis.

2. **Caching whole plans only**: A simple `dict[tuple(plan) → reward]` doesn't reuse shared prefixes. Use a trie.

3. **Mutating public state during batch evaluation**: Always save/restore `self.position` or use local variables for simulation.

4. **Resetting RNG seeds**: Don't create per-iteration generators. Use global RNG sequentially.

5. **Incorrect elite selection**: Use `np.argsort(rewards)[-num_elites:]` for descending order, not ascending.

6. **Forgetting to copy arrays**: When storing positions in trie nodes, use `.copy()` to avoid aliasing issues.

## Performance Considerations

- **Trie depth**: Deeper plans create deeper tries, but shared prefixes reduce redundant computation
- **Memory usage**: Trie nodes store position arrays and cumulative rewards; memory grows with unique prefixes
- **Speedup magnitude**: Expect 10-50x speedup when plans share significant prefixes
- **Batch size**: Larger batches benefit more from memoization due to increased prefix sharing probability

## Applicability

This skill applies to:
- Discrete-action reinforcement learning with bounded state spaces
- Cross-entropy method and similar sampling-based optimization
- Any scenario requiring efficient batch evaluation of action sequences with shared prefixes
- Environments where state transitions are deterministic and memoizable

The patterns generalize to:
- Higher-dimensional state spaces (extend clipping to all dimensions)
- Different action representations (continuous actions require different sampling)
- Stochastic environments (memoization becomes approximate or requires state discretization)
- Different optimization objectives (modify reward computation and elite selection)

## Handling Freeform Variations

The spec declares all three axes as "freeform", meaning variants can differ substantially. Here's how to adapt:

### When action_map changes
The implementation already uses `self.action_map[action]` and `len(PointEnv.action_map)`, so it works with any action set. No code changes needed.

### When goal parameters change
The clipping logic (`[-length//2, length//2]`) is independent of goal placement. The reward condition (`distance ≤ goal_radius`) works for any goal coordinates and radius. No code changes needed.

### When length changes
The clipping bounds scale automatically via `self.length // 2`. The constraint `length % 2 == 0` is enforced by the constructor assertion. If a variant uses odd length, the assertion must be relaxed and bounds adjusted to `[-(length-1)/2, (length-1)/2]` or similar.

### When environment becomes stochastic
Memoization breaks down because the same action sequence can yield different outcomes. Options:
- Disable memoization and simulate each plan independently
- Use expected rewards with state discretization
- Accept approximate memoization (cache only deterministic portions)

### When plans don't start from origin
The current trie root assumes origin `(0,0)` with reward `0`. If a variant requires evaluating plans from different starting positions:
- Reset the trie when starting position changes
- Parameterize the trie root by starting position
- Use separate tries per starting position

### When batch evaluation must preserve additional state
The current implementation saves/restores `self.position`. If a variant has additional state (velocity, orientation, etc.), extend the save/restore pattern to all mutable state fields.

## v01-Specific Assumptions vs Family Invariants

**v01-specific** (may change in other variants):
- Plans always evaluated from origin `(0,0)`
- Environment is deterministic
- `length` is even (integer bounds)
- Goal coordinates are floats, but position is integer
- Nine-action movement set (including stay)

**Family invariants** (hold across all variants):
- Independent axis clipping
- Prefix-trie memoization for shared prefixes
- State preservation during batch evaluation
- Iteration-local RNG consumption
- Cumulative per-step rewards
- Exact memoization results

---
name: cross-entropy-method
description: Implementation of the Cross-Entropy Method (CEM) for trajectory optimization in point-mass environments with memoized batch evaluation
---

# Cross-Entropy Method for Point-Mass Trajectory Optimization

## Overview

The Cross-Entropy Method (CEM) is a sampling-based optimization algorithm for finding high-reward action sequences in environments with discrete action spaces. This skill covers three tightly coupled components: a point-mass environment with configurable dynamics, memoized batch evaluation of action plans, and iterative CEM optimization of action distributions.

## Core Components

### 1. Point Environment (PointEnv)

A 2D grid environment where an agent receives rewards for reaching a goal region.

**Key Properties:**
- State: Position (x, y) on a bounded square grid
- Actions: Discrete movement vectors indexed into an action map
- Reward: Binary (1 if within goal radius, 0 otherwise)
- Boundary handling: Independent clipping per axis

**Step Implementation Pattern:**
```python
def step(self, action: int) -> int:
    movement = self.action_map[action]
    self.position = self.position + movement
    
    # Clip each coordinate independently
    half_length = self.length // 2  # or / 2 for float positions
    for i in range(len(self.position)):
        self.position[i] = np.clip(self.position[i], -half_length, half_length)
    
    distance = np.linalg.norm(self.position - self.goal)
    return 1 if distance <= self.goal_radius else 0
```

**Critical Details:**
- Clipping is **independent per axis**: x-clipping doesn't affect y-movement
- Boundary is inclusive: `[-length/2, +length/2]`
- Reward boundary is inclusive: distance ≤ goal_radius
- Position dtype depends on variant (integer or float)

### 2. Memoized Batch Evaluation

Efficiently evaluate multiple action sequences by caching prefix results with state.

**Requirements:**
- All plans evaluated from the designated start state (usually origin)
- Environment position unchanged after evaluation
- Cache persists across calls
- Prefix sharing (not just whole-plan caching)

**Implementation Pattern:**
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    if not hasattr(self, '_memo_cache'):
        self._memo_cache = {}
    
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
        
        # Jump to cached state — NO step() replay for cached prefix
        if cached_prefix_length > 0:
            cached_pos, cached_reward = self._memo_cache[
                plan_tuple[:cached_prefix_length]
            ]
            self.position = cached_pos.copy()
            total_reward = cached_reward
        else:
            self.position = np.array((0, 0), dtype=np.int_)  # or start state
            total_reward = 0
        
        # Execute ONLY the remaining (uncached) steps
        for i in range(cached_prefix_length, len(plan)):
            reward = self.step(plan[i])
            total_reward += reward
            prefix = plan_tuple[:i + 1]
            self._memo_cache[prefix] = (self.position.copy(), total_reward)
        
        rewards.append(total_reward)
    
    self.position = original_position
    return rewards
```

**Critical Insight:**
The cache must store `(state, cumulative_value)` pairs — not just values. This enables jumping directly to cached states instead of replaying steps. Storing only rewards means every step is re-executed, defeating the purpose of memoization.

### 3. Cross-Entropy Method Optimization

Iteratively improve action distributions by selecting elite samples.

**Algorithm:**
```python
def optimize(self, num_samples, num_elites, iterations):
    for iteration in range(iterations):
        # 1. Sample action sequences from per-timestep distributions
        samples = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            samples[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # 2. Evaluate all samples
        rewards = self.env.evaluate_plans_memoized(samples)
        
        # 3. Select elites (top num_elites by cumulative reward)
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_samples = samples[elite_indices]
        
        # 4. Update distributions from elite action frequencies
        for t in range(self.horizon):
            action_counts = np.bincount(
                elite_samples[:, t], minlength=self.num_actions
            )
            self.probs[t] = action_counts / num_elites
```

**Critical Properties:**
- **Iteration-local RNG**: Each iteration consumes RNG independently
- Calling `optimize(10)` twice equals calling `optimize(20)` once (same seed)
- Each timestep has independent categorical distribution
- Elite selection: top `num_elites` by cumulative reward
- Distribution update: empirical frequencies from elite samples

## Adaptation Guide

When implementing a variant, check each dimension systematically:

### Environment Dynamics

| Parameter | What to check |
|-----------|--------------|
| `length` | Clipping bounds; integer division vs float |
| `goal_x`, `goal_y` | Reward calculation center |
| `goal_radius` | Inclusive (≤) vs exclusive (<) boundary |
| `action_map` | Number of actions; movement vectors |
| Position dtype | Integer (`np.int_`) vs float |
| Boundary behavior | Independent clipping vs coupled vs wraparound |

### Policy Update Regime

| Parameter | What to check |
|-----------|--------------|
| `num_actions` | May differ from 9; use `self.num_actions` |
| `horizon` | Affects probs shape |
| Elite selection | Cumulative reward vs per-step vs other criterion |
| Distribution update | Empirical frequencies vs weighted vs other rule |
| RNG consumption | Must be iteration-local for reproducibility |

### Overlapping Plan Evaluation

| Requirement | What to check |
|-------------|--------------|
| Start state | Usually origin, but verify |
| State restoration | Must preserve caller's state |
| Cache persistence | Must work across calls |
| Cache content | Must store (state, value) pairs for true speedup |
| Prefix sharing | Must cache subplans, not just whole plans |

## Validation Checklist

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
4. **Cache stores only values**: Must cache (state, value) to skip replay — this is the #1 memoization mistake
5. **RNG state not iteration-local**: Each iteration must consume RNG independently
6. **Hardcoded constants**: Use `self.num_actions`, `self.length`, etc., not literals
7. **Assuming sort stability**: `np.argsort` uses quicksort by default (NOT stable); use `kind='stable'` if needed
8. **Floating point precision**: Distance comparisons may need tolerance for float positions

## Performance Considerations

**Memoization efficiency:**
- Cache stores (state, value) pairs to enable O(1) state jumps
- Prefix sharing reduces redundant computation proportionally to overlap
- Speedup scales with overlap ratio: ~1/(1-P) where P is prefix overlap fraction
- Cache lookup is O(1) with tuple hashing
- Evaluation is O(H - cached_prefix_length) per plan

**CEM iteration complexity:**
- Sampling: O(N × H) where N is num_samples, H is horizon
- Evaluation: O(N × H) worst case, better with prefix overlap
- Elite selection: O(N log N) for sorting
- Distribution update: O(H × num_actions)

**Optimization tips:**
- Use vectorized operations where possible (e.g., `np.random.choice` for all samples at timestep t)
- Cache grows monotonically; consider memory limits for very long horizons
- For deterministic distributions, all samples are identical (no benefit from large N)

## Debugging Strategies

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

## Generalization Principles

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

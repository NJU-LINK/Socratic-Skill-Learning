---
name: cross-entropy-method
description: >
  Implement a cross-entropy method (CEM) optimization loop for a discrete-action
  point-mass grid environment. Covers three coupled components: (1) a step function
  with independent per-axis clipping and Euclidean-distance reward, (2) memoized
  batch plan evaluation exploiting shared prefixes with position-caching to avoid
  duplicated dynamics logic, and (3) an iterative CEM optimizer with iteration-local
  RNG consumption and vectorized probability updates. The skill generalizes across
  map sizes, goal placements, start positions, action sets, sample sizes, elite
  fractions, horizon lengths, and reward sparsity patterns.
---

# Cross-Entropy Method for Discrete Grid Navigation

## Overview

This skill implements three methods for CEM-based grid navigation optimization:

1. **`PointEnv.step(action)`** — environment dynamics (single source of truth)
2. **`PointEnv.evaluate_plans_memoized(plans)`** — efficient batch evaluation with position-caching
3. **`CrossEntropyMethod.optimize(...)`** — CEM policy update with vectorized frequency computation

## Family Invariants vs. Variation Points

### Invariants (must hold for all variants)

- **Environment structure**: 2D grid with bounded coordinates, discrete actions, cumulative reward
- **Memoization pattern**: Cache state alongside computed values to avoid duplicated logic
- **CEM algorithm**: Sample → Evaluate → Select elites → Update distribution
- **RNG iteration-locality**: Each iteration must advance RNG state by a fixed, deterministic amount
- **Position neutrality**: Batch evaluation must not leave environment state changed (save-and-restore)

### Variation Points (can differ across family members)

- **Map size**: `length` parameter (even, positive integer)
- **Start position**: Where plans begin evaluation (v01 uses origin `(0, 0)`, but variants may differ)
- **Goal placement**: `goal_x`, `goal_y` coordinates (can be float)
- **Goal radius**: `goal_radius` for reward region
- **Action set**: Number and definition of discrete actions (v01 uses 9 movements)
- **Clipping bounds**: May vary with map size or other parameters
- **Reward structure**: Binary (0/1) in v01, but variants may use different reward functions
- **CEM hyperparameters**: Sample sizes, elite fractions, horizon lengths

## Component 1: Environment Step Function

### Implementation Pattern

```python
def step(self, action: int) -> int:
    movement = self.action_map[action]
    new_pos = self.position.copy()
    new_pos[0] += movement[0]
    new_pos[1] += movement[1]
    
    # Independent per-axis clipping
    half = self.length // 2
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    
    self.position = new_pos
    
    # Squared distance comparison (avoids sqrt, more efficient)
    dist_sq = (self.position[0] - self.goal[0])**2 + (self.position[1] - self.goal[1])**2
    radius_sq = self.goal_radius**2
    return 1 if dist_sq <= radius_sq else 0
```

### Critical Details

- **Independent axis clipping**: clipping one axis must NOT suppress motion on the other. If at `[3, 0]` with `length=6` and action `[1, 1]`, result is `[3, 1]` (x clipped, y moves freely).
- **Integer positions**: positions are integer-valued; movement vectors are integers; goal coordinates can be float.
- **Inclusive boundary**: reward is given when distance ≤ `goal_radius`. Squared distance comparison (`dist_sq <= radius_sq`) is equivalent and more efficient than sqrt.
- **Single source of truth**: `step()` is the ONLY code that implements environment dynamics. All other components must delegate to `step()` or cache its results — never reimplement the add-then-clip logic.

## Component 2: Memoized Batch Plan Evaluation

### Key Design Principles

1. **Cache state alongside computed values**: Store `(cumulative_reward, position)` tuples in the cache. This eliminates duplicated step logic and provides O(1) state restoration.

2. **Parameterized start position**: Call `self.reset()` at the beginning to determine the start position dynamically. This works for any variant, whether start is `(0, 0)` or elsewhere.

3. **Save-and-restore pattern**: Save the caller's position at the beginning and restore it at the end. This satisfies the position neutrality invariant for ALL pre-call states, not just the common case.

### Implementation Pattern

```python
def __init__(self, ...):
    # ... other init ...
    self._memo: dict[tuple[int, ...], tuple[int, np.ndarray]] = {}

def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    n_plans, horizon = plans.shape
    
    # Save caller's original position (save-and-restore pattern)
    original_pos = self.position.copy()
    
    # Determine start position for plan evaluation
    self.reset()
    start_pos = self.position.copy()
    
    results = []
    
    for i in range(n_plans):
        plan_tuple = tuple(int(a) for a in plans[i])
        
        # Check if full plan is cached
        if plan_tuple in self._memo:
            cumulative_reward, _ = self._memo[plan_tuple]
            results.append(cumulative_reward)
            continue
        
        # Find longest cached prefix
        best_prefix_len = 0
        best_prefix_key = ()
        for prefix_len in range(len(plan_tuple) - 1, 0, -1):
            prefix_key = plan_tuple[:prefix_len]
            if prefix_key in self._memo:
                best_prefix_len = prefix_len
                best_prefix_key = prefix_key
                break
        
        # Restore state from cached prefix or start position
        if best_prefix_len > 0:
            cumulative_reward, saved_pos = self._memo[best_prefix_key]
            self.position = saved_pos.copy()  # .copy() is essential!
            start_idx = best_prefix_len
        else:
            self.position = start_pos.copy()
            cumulative_reward = 0
            start_idx = 0
        
        # Simulate remaining steps using step() — the single source of truth
        for t in range(start_idx, horizon):
            reward = self.step(plan_tuple[t])
            cumulative_reward += reward
            
            # Cache this prefix with both reward AND position
            prefix_key = plan_tuple[:t + 1]
            if prefix_key not in self._memo:
                self._memo[prefix_key] = (cumulative_reward, self.position.copy())
        
        # Store full plan result
        self._memo[plan_tuple] = (cumulative_reward, self.position.copy())
        results.append(cumulative_reward)
    
    # Restore caller's original position (not just start position!)
    self.position = original_pos
    return results
```

### Critical Details

- **`.copy()` is essential**: Without copying the position array when storing/restoring, later steps would mutate the cached array, corrupting the cache.
- **Prefix-level caching**: Cache every prefix `(a_0,)`, `(a_0, a_1)`, ..., not just full plans. This enables sharing across plans with common beginnings.
- **Persistence across calls**: `self._memo` accumulates across multiple calls to `evaluate_plans_memoized`.
- **Position neutrality (save-and-restore)**: Restore the caller's original position at the end, not just the start position. This satisfies the invariant for ALL pre-call states.
- **Tuple keys**: Convert numpy arrays to tuples for dict keys (numpy arrays are not hashable).
- **Delegation to step()**: The memoization component calls `step()` for each action — it never reimplements add-then-clip logic.

### Cache Validity

The memoization cache is tied to the environment configuration. If parameters change after the cache is populated, cached rewards become invalid. In v01, parameters are set in `__init__` and not modified, so cache invalidation is not a concern.

## Component 3: Cross-Entropy Method Optimizer

### Implementation Pattern

```python
def optimize(self, num_samples=100, num_elites=25, iterations=20):
    for _ in range(iterations):
        # Sample plans from current distribution
        plans = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        
        # Select elites
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Vectorized probability update using bincount
        new_probs = np.zeros_like(self.probs)
        for t in range(self.horizon):
            counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
            new_probs[t] = counts / num_elites
        self.probs = new_probs
```

### Critical Details

- **Iteration-local RNG**: Use the global `np.random` state (not creating a fresh `np.random.default_rng()` inside `optimize()`). This ensures that calling `optimize(iterations=10)` twice produces the same result as calling `optimize(iterations=20)` once under the same seed. Each iteration consumes exactly `horizon` calls to `np.random.choice`, so the global state advances deterministically per iteration.
  
  **The mechanism**: The requirement is that each iteration advances the RNG state by a fixed, deterministic amount. What **breaks** this is creating a *fresh* RNG inside `optimize()` — that resets the RNG to a default state on every call.

- **Vectorized probability update**: Use `np.bincount` to compute action frequencies in one call per timestep, eliminating the inner loop over actions. `np.bincount(array, minlength=N)` returns an array of length N with the count of each integer value 0..N-1. Divide by `num_elites` to get frequencies.

- **Elite selection**: Use `np.argsort(rewards)[-num_elites:]` to get the indices of the top `num_elites` plans. Ties are broken by argsort's stable ordering.

- **Probability update**: Replace (not blend) the distribution with elite action frequencies. If no elite uses action `a` at timestep `t`, `probs[t, a]` becomes 0. Distribution can collapse to deterministic — this is expected behavior.

## Integration and Testing Checklist

When implementing or verifying this skill:

1. **Step function**: Verify independent axis clipping, boundary behavior, and correct reward computation for positions inside/outside the goal circle. Test squared distance comparison with float goal coordinates.
2. **Memoization**: Verify that shared prefixes are cached with positions, that the memo persists across calls, that position is restored to caller's original value (not hardcoded origin) after batch evaluation, that results are exact (not approximate), and that the cache stores `(reward, position)` tuples.
3. **Start position parameterization**: Verify that the implementation works correctly when the start position is not `(0, 0)`. Call `reset()` to determine the start position dynamically.
4. **CEM optimizer**: Verify that the distribution updates correctly using vectorized bincount, that RNG consumption is iteration-local (split calls match single long call), and that the optimizer converges toward the goal.
5. **Edge cases**: Single-step plans, empty plans array, all-zero rewards, deterministic distributions (prob = 1.0 for one action), plans that hit the boundary repeatedly, unreachable goals, float goal coordinates, sparse rewards (small goal radius).
6. **No duplicated logic**: Verify that `step()` is the only code implementing environment dynamics. The memoization component should call `step()`, not reimplement add-then-clip.

## Generalization Notes

- **Different action sets**: The action_map can have any number of 2D movement vectors. The `num_actions` is derived from `len(action_map)`. The CEM automatically adapts.
- **Different start positions**: The implementation uses `reset()` to determine the start position dynamically. This works for any variant.
- **Different reward structures**: If the reward function changes, only `step()` needs modification. The memoization and CEM components remain valid as long as rewards are cumulative and deterministic.
- **Different dynamics**: If a family variant adds friction, momentum, or other state-dependent effects, the position-caching pattern ensures these changes only need to be implemented in `step()`. The memoization component automatically benefits from the updated dynamics.
- **Parameter changes**: If a variant allows changing environment parameters after construction, the memoization cache should be cleared when parameters change.

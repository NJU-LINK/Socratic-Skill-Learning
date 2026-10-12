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

This skill addresses the problem of optimizing action sequences in a bounded 2D
grid environment using the cross-entropy method (CEM). The task decomposes into
three methods that must work together correctly:

1. **`PointEnv.step(action)`** — environment dynamics (the single source of truth)
2. **`PointEnv.evaluate_plans_memoized(plans)`** — efficient batch evaluation with position-caching
3. **`CrossEntropyMethod.optimize(...)`** — CEM policy update with vectorized frequency computation

## Family Invariants vs. Variation Points

Before diving into implementation, it's critical to distinguish what is invariant across the family from what can vary:

### Family Invariants (must hold for all variants)

- **Environment structure**: 2D grid with bounded coordinates, discrete actions, cumulative reward
- **Memoization pattern**: Cache state alongside computed values to avoid duplicated logic
- **CEM algorithm**: Sample → Evaluate → Select elites → Update distribution
- **RNG iteration-locality**: Each iteration must advance RNG state by a fixed, deterministic amount
- **Position neutrality**: Batch evaluation must not leave environment state changed

### Variation Points (can differ across family members)

- **Map size**: `length` parameter (even, positive integer)
- **Start position**: Where plans begin evaluation (v01 uses origin `(0, 0)`, but variants may differ)
- **Goal placement**: `goal_x`, `goal_y` coordinates
- **Goal radius**: `goal_radius` for reward region
- **Action set**: Number and definition of discrete actions (v01 uses 9 movements)
- **Clipping bounds**: May vary with map size or other parameters
- **Reward structure**: Binary (0/1) in v01, but variants may use different reward functions
- **Sample sizes, elite fractions, horizon lengths**: CEM hyperparameters

**Critical insight**: The start position is a variation point, not an invariant. The skill must parameterize the start position rather than hardcoding `(0, 0)`.

## Component 1: Environment Step Function

### Core Mechanics

- **State**: integer 2D position on a square grid of side `length`, centered at origin
- **Bounds**: each coordinate independently clipped to `[-length/2, +length/2]`
- **Actions**: discrete indices into an action map of 2D movement vectors
- **Reward**: `1` if Euclidean distance from position to goal center ≤ `goal_radius`, else `0`

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
    
    # Euclidean distance check using squared distance (avoids sqrt, more efficient)
    dist_sq = (self.position[0] - self.goal[0])**2 + (self.position[1] - self.goal[1])**2
    radius_sq = self.goal_radius**2
    return 1 if dist_sq <= radius_sq else 0
```

### Critical Details

- **Independent axis clipping**: clipping one axis must NOT suppress motion on the other. If at `[3, 0]` with `length=6` and action `[1, 1]`, result is `[3, 1]` (x clipped, y moves freely).
- **Integer positions**: positions are integer-valued; movement vectors are integers.
- **Inclusive boundary**: reward is given when distance is exactly equal to `goal_radius`. Using squared distance comparison (`dist_sq <= radius_sq`) is equivalent and more efficient than computing sqrt.
- **Cumulative reward**: each step independently returns 0 or 1; total plan reward is the sum.
- **Single source of truth**: `step()` is the ONLY code that implements environment dynamics. All other components (memoization, prefix replay) must delegate to `step()` or cache its results — never reimplement the add-then-clip logic.

### Variation: Different Map Sizes and Goal Placements

The same logic applies for any `length` (even, positive), any goal position strictly inside bounds, and any positive `goal_radius`. The clipping bounds change with `length/2`; the reward region changes with goal position and radius.

## Component 2: Memoized Batch Plan Evaluation

### Purpose

Evaluate N plans of horizon H efficiently by caching cumulative rewards for action prefixes. Plans sharing initial action sequences reuse cached intermediate results.

### Key Design Principle: Cache State Alongside Computed Values

**The problem**: When you hit a cached prefix, you need to restore the environment state (position) to continue simulation from that point. You could replay the prefix actions from the start position, but that duplicates the step mechanics logic — a second implementation that must stay in sync with `step()`. If a family variant changes clipping rules, adds friction, or modifies dynamics, you must update both places, and a mismatch produces silently wrong cumulative rewards.

**The solution**: Store `(cumulative_reward, position)` tuples in the cache. On a cache hit, restore position directly — O(1) instead of O(prefix_length), and no duplicated logic.

### Critical Variation: Parameterized Start Position

**The start position is NOT necessarily `(0, 0)`**. While v01 uses the origin, family variants may have different start positions. The implementation must:

1. **Determine the start position dynamically**: Call `self.reset()` at the beginning of `evaluate_plans_memoized` to get the start position. This works for any variant because `reset()` returns the start position.
2. **Use the start position for all plans**: Each plan is evaluated from the start position, not hardcoded to `(0, 0)`.
3. **Restore the caller's original position after evaluation**: The batch evaluation must not leave the environment state changed. Save the caller's position before the call and restore it after, regardless of what it was.

This ensures the implementation adapts automatically to any start position without code changes, and satisfies the position neutrality invariant for all pre-call states.

### Implementation Pattern

```python
def __init__(self, ...):
    # ... other init ...
    # Cache: action prefix tuple -> (cumulative_reward, position_after_prefix)
    self._memo: dict[tuple[int, ...], tuple[int, np.ndarray]] = {}

def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    n_plans, horizon = plans.shape
    
    # Save caller's original position (save-and-restore pattern)
    # This satisfies the invariant: batch evaluation must not leave state changed
    original_pos = self.position.copy()
    
    # Determine start position for plan evaluation
    self.reset()
    start_pos = self.position.copy()
    
    results = []
    
    for i in range(n_plans):
        plan_tuple = tuple(int(a) for a in plans[i])
        
        # Check if we already have the full plan cached
        if plan_tuple in self._memo:
            cumulative_reward, _ = self._memo[plan_tuple]
            results.append(cumulative_reward)
            continue
        
        # Find the longest cached prefix
        best_prefix_len = 0
        best_prefix_key = ()
        for prefix_len in range(len(plan_tuple) - 1, 0, -1):
            prefix_key = plan_tuple[:prefix_len]
            if prefix_key in self._memo:
                best_prefix_len = prefix_len
                best_prefix_key = prefix_key
                break
        
        # Restore state from cached prefix (no replay needed!)
        if best_prefix_len > 0:
            cumulative_reward, saved_pos = self._memo[best_prefix_key]
            self.position = saved_pos.copy()  # .copy() is essential!
            start_idx = best_prefix_len
        else:
            # Use the start position (from reset()), not hardcoded (0, 0)
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
    # This satisfies the invariant for ALL pre-call states
    self.position = original_pos
    return results
```

### Critical Details

- **Position caching**: Store `(reward, position)` tuples, not just rewards. This eliminates duplicated step logic and provides O(1) state restoration.
- **`.copy()` is essential**: Without copying the position array when storing/restoring, later steps would mutate the cached array, corrupting the cache.
- **Prefix-level caching**: Cache every prefix `(a_0,)`, `(a_0, a_1)`, ..., not just full plans. This enables sharing across plans with common beginnings.
- **Persistence across calls**: `self._memo` is an instance attribute initialized in `__init__`. It accumulates across multiple calls to `evaluate_plans_memoized`.
- **Position neutrality (save-and-restore)**: The environment's `self.position` must be restored to whatever value it had before the call, not just reset to the start position. Save the caller's position at the beginning (`original_pos = self.position.copy()`), then restore it at the end (`self.position = original_pos`). This satisfies the invariant for ALL pre-call states, not just the common case where position is at start.
- **Tuple keys**: Convert numpy arrays to tuples for dict keys (numpy arrays are not hashable).
- **All plans start from the environment's start position**: Each plan is evaluated independently from the start position (determined by `reset()`), not from the environment's current position or a hardcoded value.
- **Delegation to step()**: The only code that implements environment dynamics is `step()`. The memoization component calls `step()` for each action — it never reimplements the add-then-clip logic.

### Cache Validity

The memoization cache is tied to the environment configuration (start position, goal position, goal radius, map size, action map). If any of these parameters change after the cache is populated, the cached rewards become invalid. In v01, these parameters are set in `__init__` and not modified, so cache invalidation is not a concern. However, if a variant allows parameter changes, the cache should be cleared when parameters change.

### Efficiency Considerations

- With heavy prefix overlap (e.g., CEM samples sharing early actions), most plans reuse cached prefixes, reducing simulation to only the divergent suffixes.
- Position restoration from cache is O(1) — just a copy of the stored position array.
- The prefix search is O(H) hash lookups per plan. For very large batches with long horizons, a trie structure could improve this, but dict-based prefix search is sufficient for typical CEM workloads.

### Generalization: This Pattern Applies Everywhere

The "cache state alongside computed value" pattern is a general technique for any memoized simulation:
- **Dynamic programming**: Cache `(value, state)` in DP tables when the state is needed to continue
- **Reinforcement learning**: Cache `(return, state)` in trajectory buffers
- **Tree search**: Cache `(evaluation, board_state)` in game tree nodes
- **Any memoized simulation**: If you need to resume from a cached point, cache the full state, not just the scalar result

## Component 3: Cross-Entropy Method Optimizer

### Algorithm

1. **Sample** `num_samples` action sequences of length `horizon` from the current categorical distribution `self.probs[t]` at each timestep `t`
2. **Evaluate** all sampled plans using `env.evaluate_plans_memoized`
3. **Select** the top `num_elites` plans by cumulative reward
4. **Update** `self.probs[t, a]` to the frequency of action `a` among elites at timestep `t`

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
  
  **The mechanism**: The requirement is that each iteration advances the RNG state by a fixed, deterministic amount. Under this invariant, iteration N always sees the same RNG state regardless of whether iterations 1..N-1 happened in the same `optimize()` call or a previous one. Both global `np.random` and a stored instance `self.rng = np.random.default_rng()` satisfy this. What **breaks** is creating a *fresh* RNG inside `optimize()` — that resets the RNG to a default state on every call.

- **Vectorized probability update**: Use `np.bincount` to compute action frequencies in one call per timestep, eliminating the inner loop over actions. `np.bincount(array, minlength=N)` returns an array of length N with the count of each integer value 0..N-1. Divide by `num_elites` to get frequencies. For 9 actions it's a modest speedup; for larger action sets it matters more. The key pattern: when you need "frequency of each value in an integer array," reach for `np.bincount` rather than iterating over possible values.

- **Elite selection**: Use `np.argsort(rewards)[-num_elites:]` to get the indices of the top `num_elites` plans. Ties are broken by argsort's stable ordering.

- **Probability update**: Replace (not blend) the distribution with elite action frequencies. This is the standard CEM update. If no elite uses action `a` at timestep `t`, `probs[t, a]` becomes 0.

- **Distribution can collapse**: After enough iterations, some actions may have probability 0. This is expected behavior — the CEM converges toward a deterministic policy.

### Variation: Different Sample Sizes, Elite Fractions, Horizons

The algorithm is parameterized and works for any valid combination:
- `num_samples > num_elites > 0`
- Any horizon length
- The only requirement is that the probability vectors remain valid (non-negative, sum to 1) after each update — guaranteed by the frequency-based update.

## Integration and Testing Checklist

When implementing or verifying this skill:

1. **Step function**: Verify independent axis clipping, boundary behavior, and correct reward computation for positions inside/outside the goal circle. Test squared distance comparison.
2. **Memoization**: Verify that shared prefixes are cached with positions, that the memo persists across calls, that position is reset to the start position (not hardcoded origin) after batch evaluation, that results are exact (not approximate), and that the cache stores `(reward, position)` tuples.
3. **Start position parameterization**: Verify that the implementation works correctly when the start position is not `(0, 0)`. Call `reset()` to determine the start position dynamically.
4. **CEM optimizer**: Verify that the distribution updates correctly using vectorized bincount, that RNG consumption is iteration-local (split calls match single long call), and that the optimizer converges toward the goal.
5. **Edge cases**: Single-step plans, all-zero rewards, deterministic distributions (prob = 1.0 for one action), plans that hit the boundary repeatedly, unreachable goals.
6. **No duplicated logic**: Verify that `step()` is the only code implementing environment dynamics. The memoization component should call `step()`, not reimplement add-then-clip.

## Generalization Notes

- **Different action sets**: The action_map can have any number of 2D movement vectors. The `num_actions` is derived from `len(action_map)`. The CEM automatically adapts.
- **Different start positions**: The implementation uses `reset()` to determine the start position dynamically. This works for any variant, whether the start is at the origin or elsewhere.
- **Different reward structures**: If the reward function changes (e.g., negative rewards for steps, different distance metrics), only `step()` needs modification. The memoization and CEM components remain valid as long as rewards are cumulative and deterministic. Because the memo caches positions alongside rewards, any change to `step()` automatically propagates — no second implementation to update.
- **Different state spaces**: The skill assumes a 2D integer grid with clipping. For continuous or higher-dimensional spaces, the clipping and distance computations would need adjustment, but the CEM structure (sample → evaluate → select elites → update) remains the same.
- **Non-deterministic environments**: The current implementation assumes deterministic transitions. For stochastic environments, multiple rollouts per plan would be needed, but the CEM framework still applies.
- **Different dynamics**: If a family variant adds friction, momentum, or other state-dependent effects, the position-caching pattern ensures these changes only need to be implemented in `step()`. The memoization component automatically benefits from the updated dynamics.
- **Parameter changes**: If a variant allows changing environment parameters (goal, radius, map size) after construction, the memoization cache should be cleared when parameters change, as cached rewards become invalid.

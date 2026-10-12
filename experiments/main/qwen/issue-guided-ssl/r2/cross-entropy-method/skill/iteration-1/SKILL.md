---
name: cross-entropy-method
description: >
  Reusable implementation pattern for the Cross-Entropy Method (CEM) applied to
  point-mass navigation in bounded grid worlds with discrete actions. Covers three
  coupled components: (1) environment dynamics with independent-axis boundary clipping
  and Euclidean-distance reward, (2) prefix-tree memoized batch plan evaluation with
  position save/restore, and (3) iterative CEM policy optimization with persistent
  instance-level RNG ensuring split-call equivalence.
---

# Cross-Entropy Method for Point-Mass Navigation

## Overview

This skill implements a complete CEM optimization loop for a point-mass agent navigating
a bounded 2D grid toward a circular goal. The three components — environment dynamics,
memoized evaluation, and policy optimization — are tightly coupled and must each satisfy
specific invariants to produce correct results.

## Component 1: Environment Dynamics (`step`)

### Mechanism

```
position ← position + action_map[action]
position.x ← clip(position.x, -half, +half)   # independent
position.y ← clip(position.y, -half, +half)   # independent
reward ← 1 if ||position - goal||₂ ≤ goal_radius else 0
```

### Critical Invariants

1. **Independent axis clipping**: Each coordinate is clipped separately. An action that
   would push one axis out of bounds must NOT suppress motion on the other axis.
   - Example: At position `[half, 0]`, action `[1, 1]` → position becomes `[half, 1]`
     (x clipped, y still moves).
   - Anti-pattern: Reverting the entire move if any axis exceeds bounds.

2. **Inclusive boundary**: The bounds are `[-length/2, +length/2]` inclusive on both ends.
   With `length=6`, valid positions are `{-3, -2, -1, 0, 1, 2, 3}` per axis.

3. **Inclusive reward threshold**: Reward is 1 when Euclidean distance is **≤**
   `goal_radius` (boundary included), not strictly less than.

4. **Integer positions**: Position remains integer-typed throughout. `np.clip` on integer
   arrays preserves dtype.

### Variation Dimensions

- Map size (`length`): Changes clipping bounds.
- Goal placement (`goal_x`, `goal_y`): Changes reward geometry.
- Goal radius: Changes the size of the reward region.
- Action set: The 9 standard movement vectors (including stay), but the skill must
  accommodate any discrete action set mapped to 2D integer deltas.

## Component 2: Memoized Plan Evaluation (`evaluate_plans_memoized`)

### Mechanism

Prefix-tree cache mapping `tuple(action_sequence[:k])` → cumulative reward after k steps
from origin. For each plan:

1. Find longest cached prefix by iterating `plan[:1], plan[:2], ...` and breaking at
   first miss (cache is prefix-closed by construction).
2. Reset environment to origin.
3. Replay cached prefix actions to restore position state.
4. Simulate remaining actions, caching each new prefix's cumulative reward.
5. After all plans processed, restore the environment's public position.

### Critical Invariants

1. **Position save/restore**: Save `self.position.copy()` at entry, restore at exit.
   The public environment state must be unchanged after batch evaluation.

2. **Origin reset per plan**: Each plan starts evaluation from `(0, 0)`, not from the
   saved position or from the previous plan's endpoint.

3. **Prefix-closed cache**: Every prefix of every evaluated plan is cached. This
   guarantees that if `plan[:k]` is cached, then `plan[:j]` for all `j < k` is also
   cached, enabling the break-at-first-miss optimization.

4. **Persistent cache**: The cache (`self._cache`) is initialized in `__init__`, not
   in `evaluate_plans_memoized`. It persists across calls, enabling cross-call reuse.

5. **Hashable keys**: Convert numpy arrays to `tuple(int(a) for a in plan)` for dict keys.

### Performance Characteristics

- First call with N plans of horizon H: O(N × H) step evaluations in worst case.
- Subsequent calls with shared prefixes: Significant reduction in step evaluations.
- Identical plans: Second evaluation is O(H) replays + O(1) cache lookups (no new steps).

### Variation Dimensions

- Degree of prefix overlap: From no overlap (all unique) to full overlap (all identical).
- Batch size: Number of plans evaluated simultaneously.
- Horizon length: Affects cache depth and replay cost.

## Component 3: CEM Policy Optimization (`optimize`)

### Mechanism

```
for iteration in range(iterations):
    # Sample: draw num_samples plans of length horizon from current distributions
    plans[t, :] ~ categorical(probs[t]) for each timestep t
    
    # Evaluate: get cumulative rewards for all plans
    rewards = env.evaluate_plans_memoized(plans)
    
    # Select elites: keep num_elites highest-reward plans
    elite_indices = argsort(rewards)[-num_elites:][::-1]
    
    # Update: replace each timestep's distribution with elite action frequencies
    for t in range(horizon):
        probs[t] = bincount(elite_plans[:, t], minlength=n_actions) / num_elites
```

### Critical Invariants

1. **Persistent instance RNG**: Use `self.np_random` (a `np.random.Generator` created
   in `__init__`), never global `np.random` or re-seeding inside `optimize`. This
   ensures reproducibility and split-call equivalence.

2. **Split-call equivalence**: `optimize(iters=10)` followed by `optimize(iters=10)`
   must produce identical `self.probs` as a single `optimize(iters=20)` under the same
   RNG seed. This requires:
   - No RNG state reset between calls.
   - Identical RNG consumption pattern per iteration (loop timesteps 0..T-1, draw
     num_samples actions at each).
   - `self.probs` carries over between calls (not re-initialized).

3. **Distribution validity**: After each update, `probs[t]` must be a valid probability
   distribution (non-negative, sums to 1). Using `bincount / num_elites` guarantees this.

4. **Elite selection**: `np.argsort(rewards)[-num_elites:][::-1]` selects the top
   `num_elites` by cumulative reward. Ties are broken by argsort's default behavior.

### Variation Dimensions

- Sample count (`num_samples`): More samples → better exploration but slower.
- Elite fraction (`num_elites / num_samples`): Smaller fraction → more selective.
- Horizon length: Longer horizons → harder optimization, more parameters.
- Convergence patterns: Some problems converge quickly, others need many iterations.
- Reward sparsity: Sparse rewards require more samples/iterations.

## Integration Notes

### How the Components Interact

1. `optimize` calls `evaluate_plans_memoized` which calls `step`.
2. The env's `_cache` accumulates across all CEM iterations, providing increasing
   speedup as the policy concentrates and plans share more prefixes.
3. The env's `position` is saved/restored within `evaluate_plans_memoized`, so the
   CEM loop never corrupts external environment state.
4. The CEM's `probs` carry over between `optimize` calls, enabling warm-starting.

### Common Failure Modes

| Failure | Root Cause | Fix |
|---|---|---|
| Coupled axis clipping | Reverting entire move on OOB | Clip each axis independently |
| Corrupted env state | No save/restore in evaluate | Save position at entry, restore at exit |
| No memoization speedup | Whole-plan caching only | Cache every prefix |
| Non-reproducible CEM | Global np.random or re-seeding | Persistent `self.np_random` |
| Split-call mismatch | Re-initializing probs or RNG | Carry state across calls |
| Cache key errors | Using unhashable numpy arrays | Convert to `tuple(int(a) ...)` |
| Wrong position after cache hit | Not replaying prefix | Reset + replay cached prefix actions |

## Reference Implementation

See `scripts/cross_entropy.py` for a complete, tested implementation.

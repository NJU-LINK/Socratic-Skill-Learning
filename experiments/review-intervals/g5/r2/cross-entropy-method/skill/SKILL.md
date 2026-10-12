---
name: cross-entropy-method
description: >
  Implement a cross-entropy method (CEM) optimizer for a discrete-action
  point-mass grid environment. Covers three coupled components: (1) a
  point-environment step function with independent per-axis clipping and
  Euclidean-distance reward, (2) prefix-trie memoized batch plan evaluation
  that preserves environment state, and (3) a CEM optimize loop with
  per-timestep categorical sampling, elite selection, and frequency-based
  probability updates under iteration-local RNG semantics.
---

# Cross-Entropy Method for Discrete-Action Point Environments

## Overview

This skill solves a three-part implementation task: a small gridworld
environment (`PointEnv`), a memoized batch evaluator for action-sequence
plans, and a cross-entropy method optimizer (`CrossEntropyMethod`). The
three components are tightly coupled — the optimizer calls the evaluator,
which calls the step dynamics — so correctness requires all three to agree
on state representation, reward semantics, and side-effect discipline.

## Component 1: Environment Step Dynamics (`step`)

### Mechanism

Given an integer action index, look up the 2D displacement vector from
`action_map`, add it to the current position, then **clip each axis
independently** to the inclusive bounds `[-length/2, +length/2]`. After
updating position, return reward `1` if `euclidean_distance(position, goal)
<= goal_radius`, else `0`.

### Critical Design Decision: Independent Axis Clipping

**Pitfall**: A common mistake is to reject the entire move if *either* axis
would exceed bounds. This is wrong. Each axis is clipped independently:

```
new_x = clip(pos_x + delta_x, -half, +half)
new_y = clip(pos_y + delta_y, -half, +half)
```

If the agent is at the right edge (x = +half) and takes action [1, 1]:
- x clips to +half (no movement on x)
- y still advances by +1 (movement on y is NOT suppressed)

This means the agent can still make progress along one axis even when
blocked on the other. The reward is then computed on the post-clip position.

### Reward Semantics

- **Inclusive boundary**: `distance <= goal_radius` (not `<`). An agent
  exactly on the circle boundary receives reward 1.
- Euclidean distance via `np.linalg.norm(position - goal)`.
- Reward is per-step: each step independently checks the resulting position.

### Position Management

- `step()` mutates `self.position` in place.
- The initial position is `(0, 0)` (center of the grid).
- `reset()` returns position to `(0, 0)`.

## Component 2: Memoized Batch Plan Evaluation (`evaluate_plans_memoized`)

### Mechanism

Evaluate N plans (each a sequence of H actions) from the origin, returning
the cumulative per-step reward for each plan. Use a **prefix trie cache**
to avoid re-simulating shared action prefixes.

### Critical Design Decision: Prefix Trie, Not Whole-Plan Cache

**Pitfall**: Caching only complete plan → reward mappings misses the
opportunity to share work when plans share prefixes. The spec explicitly
requires prefix reuse.

**Correct approach**: The cache maps `tuple(action_0, ..., action_t)` →
`(position_tuple, cumulative_reward)`. For each plan, walk through actions
one at a time, building the prefix key incrementally. At each step:
1. Check if the current prefix key is in the cache.
2. If yes: jump to the cached position and cumulative reward; continue from
   there for remaining actions.
3. If no: simulate the step from current position, compute reward, store in
   cache, continue.

### State Preservation

- Each plan is evaluated **from the origin (0, 0)**, not from
  `self.position`.
- After the entire batch, `self.position` must be **unchanged**.
- Implementation: use local variables for simulation position; do NOT mutate
  `self.position` during evaluation. Alternatively, save and restore
  `self.position`.

### Cache Persistence

- The cache is stored as an instance attribute (e.g., `self._cache`).
- It **persists across calls** to `evaluate_plans_memoized`.
- This means a second call with plans that share prefixes with previously
  evaluated plans gets a speedup from the existing cache entries.

### Key Type Consideration

`np.ndarray` is not hashable. Convert action sequences to `tuple` for use
as dictionary keys. The task states we may assume tuple conversion and
hashing are constant-time for simplicity.

## Component 3: Cross-Entropy Optimization (`optimize`)

### Mechanism

Iteratively improve a policy (represented as per-timestep categorical
distributions over actions) by:
1. **Sampling**: Draw `num_samples` plans, each of length `horizon`. At each
   timestep t, sample the action from `self.probs[t]` (a categorical
   distribution over `num_actions`).
2. **Evaluating**: Score each plan using `env.evaluate_plans_memoized`.
3. **Selecting elites**: Keep the top `num_elites` plans by cumulative
   reward (descending sort).
4. **Updating**: For each timestep t, compute the frequency of each action
   among the elite plans. Set `self.probs[t]` to this frequency
   distribution.

### Critical Design Decision: Iteration-Local RNG

**Pitfall 1**: If extra RNG consumption happens between iterations (e.g.,
creating a new RNG per iteration, or consuming RNG for non-sampling
operations), then calling `optimize(iterations=10)` twice will NOT produce
the same result as calling `optimize(iterations=20)` once under the same
seed.

**Pitfall 2**: Do NOT use `self.rng = np.random.default_rng()`. The test
harness seeds the global NumPy random state via `np.random.seed(...)`, but
`default_rng()` creates an independent RNG stream that ignores
`np.random.seed()`. This causes the split-vs-combined iteration test to
fail because the two CEM instances will consume different random sequences.

**Correct approach**: Use the global `np.random.choice(...)` API directly.
This ensures compatibility with `np.random.seed()` and preserves
iteration-locality because each iteration consumes global RNG state only
during the sampling step. No instance-level RNG attribute is needed.

```python
# In optimize, per iteration:
for t in range(self.horizon):
    plans[:, t] = np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])
```

### Probability Update Correctness

- After elite selection, for each timestep t:
  - Count occurrences of each action (0 through num_actions-1) among elites.
  - Use `np.bincount(elite_plans[:, t], minlength=self.num_actions)`.
  - Divide by `num_elites` to get frequencies.
  - This always produces a valid probability distribution (sums to 1.0).
- The update can produce **deterministic** distributions (probability 1.0
  for one action) if all elites chose the same action at a timestep. This
  is expected behavior.

### Idempotency of Multiple Calls

- `optimize` uses the current `self.probs` as the starting distribution.
- Calling `optimize(10)` then `optimize(10)` continues from where the first
  call left off, using the updated `self.probs` and the continued RNG state.
- This is equivalent to a single `optimize(20)` call.

## Adaptation Guide

### Varying Environment Parameters

| Parameter | Effect | Adaptation |
|-----------|--------|------------|
| `length` | Changes clipping bounds `[-L/2, L/2]` | Clipping formula `half = length // 2` is general |
| `goal_x, goal_y` | Changes reward region center | Reward check `norm(pos - goal) <= radius` is general |
| `goal_radius` | Changes reward region size | Same formula; larger radius = easier task |
| Action set | Different movement vectors | `action_map` is a class attribute; step logic uses it generically |

### Varying CEM Parameters

| Parameter | Effect | Adaptation |
|-----------|--------|------------|
| `num_samples` | More samples = better estimation | No code change needed |
| `num_elites` | Fewer elites = more aggressive updates | No code change; ensure `num_elites <= num_samples` |
| `horizon` | Longer plans = longer optimization | `self.probs` shape adapts via constructor |
| `iterations` | More iterations = more refinement | RNG locality ensures composability |

### Edge Cases to Handle

1. **Deterministic distributions**: After enough iterations, `self.probs[t]`
   may become one-hot. `np.random.choice` with a one-hot `p` works correctly.
2. **Tied rewards**: `np.argsort` with ties is stable; any consistent
   tie-breaking is acceptable for elite selection.
3. **Sparse rewards**: If no plan reaches the goal, all rewards are 0. Elite
   selection still works (picks arbitrary plans), and the update may not
   change probabilities meaningfully. This is correct behavior.
4. **Empty plans (H=0)**: Edge case; should return 0 reward for all plans.
5. **Single sample / single elite**: Works but produces deterministic
   updates; not useful in practice but not a bug.

## Quick Start Implementation Recipe

Follow this checklist to implement all three methods correctly:

### 1. Add cache to `__init__`

```python
# In PointEnv.__init__, add:
self._cache: dict[tuple[int, ...], tuple[tuple[int, int], int]] = {}
```

### 2. Implement `step(action)`

```python
def step(self, action: int) -> int:
    delta = PointEnv.action_map[action]
    new_pos = self.position + delta
    
    # Clip each axis INDEPENDENTLY
    half = self.length // 2
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    
    self.position = new_pos
    
    # Inclusive boundary check
    dist = np.linalg.norm(self.position - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

### 3. Implement `evaluate_plans_memoized(plans)`

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    saved_position = self.position.copy()
    n_plans, horizon = plans.shape
    rewards = []
    
    for i in range(n_plans):
        pos = np.array((0, 0), dtype=np.int_)  # Always start from origin
        cum_reward = 0
        prefix_key: tuple[int, ...] = ()
        
        for t in range(horizon):
            a = int(plans[i, t])
            prefix_key = prefix_key + (a,)
            
            if prefix_key in self._cache:
                pos_tuple, cum_reward = self._cache[prefix_key]
                pos = np.array(pos_tuple, dtype=np.int_)
                continue
            
            # Simulate step
            delta = PointEnv.action_map[a]
            new_pos = pos + delta
            half = self.length // 2
            new_pos[0] = np.clip(new_pos[0], -half, half)
            new_pos[1] = np.clip(new_pos[1], -half, half)
            pos = new_pos
            
            dist = np.linalg.norm(pos - self.goal)
            step_reward = 1 if dist <= self.goal_radius else 0
            cum_reward += step_reward
            
            self._cache[prefix_key] = (tuple(pos.tolist()), cum_reward)
        
        rewards.append(cum_reward)
    
    self.position = saved_position  # Restore position
    return rewards
```

### 4. Implement `optimize(num_samples, num_elites, iterations)`

```python
def optimize(self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20) -> None:
    for _ in range(iterations):
        # Use global np.random (NOT self.rng = np.random.default_rng())
        plans = np.empty((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        
        elite_indices = np.argsort(rewards)[::-1][:num_elites]
        elite_plans = plans[elite_indices]
        
        for t in range(self.horizon):
            action_counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
            self.probs[t] = action_counts / num_elites
```

### Critical Checklist

- [ ] `step()`: Clip each axis independently (not whole-move rejection)
- [ ] `step()`: Use `<=` for goal_radius check (inclusive boundary)
- [ ] `evaluate_plans_memoized()`: Initialize `self._cache = {}` in `__init__`
- [ ] `evaluate_plans_memoized()`: Always start from origin `(0, 0)`, not `self.position`
- [ ] `evaluate_plans_memoized()`: Save and restore `self.position`
- [ ] `evaluate_plans_memoized()`: Use prefix tuples as cache keys
- [ ] `optimize()`: Use `np.random.choice()` (global API), NOT `self.rng.choice()`
- [ ] `optimize()`: Do NOT create `self.rng = np.random.default_rng()`

## Implementation Reference

See `references/reference_impl.py` for a complete working implementation of
all three components.

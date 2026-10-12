---
name: cross-entropy-method
description: >
  Implement cross-entropy method (CEM) optimization for discrete action planning
  in point-mass environments with prefix-trie memoization, independent axis clipping,
  and iteration-local RNG consumption.
---

# Cross-Entropy Method Skill

This skill covers three tightly coupled implementation methods for CEM-based planning
in discrete grid environments. Each method has specific failure modes that must be
avoided.

## 1. Environment Dynamics: `PointEnv.step(action)`

### Core Mechanism
- Apply action delta to current position
- Clip each axis **independently** to `[-length/2, +length/2]`
- Return reward 1 if Euclidean distance to goal `<= goal_radius`, else 0

### Critical Failure Modes

**WRONG: Joint clipping (rejects entire move if out of bounds)**
```python
# WRONG - if new position is out of bounds, reject the whole move
if np.all((new_pos >= -half) & (new_pos <= half)):
    self.position = new_pos
```

**CORRECT: Independent axis clipping**
```python
# CORRECT - clip each axis separately
new_pos[0] = np.clip(new_pos[0], -half, half)
new_pos[1] = np.clip(new_pos[1], -half, half)
self.position = new_pos
```

**Why it matters**: At position `(3, 0)` with action `[1, 1]`, the x-axis clips to 3
but y-axis should still move to 1. Joint clipping would reject the entire move, leaving
the agent at `(3, 0)` instead of `(3, 1)`.

### Goal Boundary Check

**WRONG: Strict inequality**
```python
# WRONG - excludes boundary
return 1 if dist < self.goal_radius else 0
```

**CORRECT: Inclusive boundary**
```python
# CORRECT - includes boundary
return 1 if dist <= self.goal_radius else 0
```

**Why it matters**: At position `(3, 2)` with goal at `(2, 2)` and radius 1, the
distance is exactly 1.0. Inclusive check returns reward 1; exclusive returns 0.

### Distance Computation

Cast position to float before computing distance to avoid integer overflow:
```python
dist = np.linalg.norm(self.position.astype(float) - self.goal)
```

## 2. Prefix-Trie Memoization: `PointEnv.evaluate_plans_memoized(plans)`

### Core Mechanism
- Evaluate N plans of length H, returning cumulative rewards
- Memoize prefixes (not just whole plans) for reuse across calls
- Restore environment position after evaluation

### Critical Initialization Requirement

**The `_memo` dict MUST be initialized in `__init__` as an instance variable:**

```python
def __init__(self, ...):
    # ... other initialization ...
    self._memo: dict[tuple[int, ...], tuple[int, np.ndarray]] = {}
```

**Why this is critical:**
- If `_memo` is not initialized, `evaluate_plans_memoized` will raise `AttributeError`
- Each environment instance has its own memo (it's an instance variable, not a class variable)
- The memo persists across calls to `evaluate_plans_memoized` for that specific environment
- Different environment instances (with different parameters) have separate memos

### Data Structure: Prefix Trie with Position Caching

```python
# self._memo maps action-tuple -> (cumulative_reward, position_at_end_of_prefix)
# Example: {(2,): (0, array([1, 1])), (2, 2): (1, array([2, 2]))}
```

### Algorithm

For each plan:
1. Find longest prefix already in memo (iterate from length 1 to H, break on miss)
2. Restore position to cached position at end of that prefix
3. Simulate remaining suffix, memoizing each new prefix
4. Store cumulative reward

```python
def evaluate_plans_memoized(self, plans):
    results = np.zeros(len(plans), dtype=int)
    saved_pos = self.position.copy()
    
    for i in range(len(plans)):
        plan_tuple = tuple(int(a) for a in plans[i])
        
        # Find longest cached prefix
        best_prefix_len = 0
        best_cum_reward = 0
        best_pos = np.array((0, 0), dtype=np.int_)
        
        for length in range(1, len(plan_tuple) + 1):
            prefix = plan_tuple[:length]
            if prefix in self._memo:
                best_prefix_len = length
                best_cum_reward, best_pos = self._memo[prefix]
            else:
                break  # No longer prefixes can be cached
        
        # Restore state and simulate suffix
        self.position = best_pos.copy()
        cum_reward = best_cum_reward
        
        for t in range(best_prefix_len, len(plan_tuple)):
            cum_reward += self.step(plan_tuple[t])
            prefix = plan_tuple[:t + 1]
            self._memo[prefix] = (cum_reward, self.position.copy())
        
        results[i] = cum_reward
    
    self.position = saved_pos
    return results
```

### Critical Failure Modes

**WRONG: Only caching whole plans**
```python
# WRONG - no prefix reuse
if plan_tuple in self._memo:
    return self._memo[plan_tuple]
```

**Why it matters**: If plans `[[2, 2, 0], [2, 2, 1]]` are evaluated, the prefix
`(2, 2)` is simulated twice. With prefix caching, it's simulated once.

**WRONG: Not restoring position**
```python
# WRONG - position leaks
def evaluate_plans_memoized(self, plans):
    for plan in plans:
        self.reset()  # or not even this
        # ... simulate ...
    # self.position is now at the end of the last plan
```

**Why it matters**: The environment's public state must not change. If position is
`(1, 1)` before the call, it must be `(1, 1)` after.

**WRONG: Not replaying prefix to set state**
```python
# WRONG - skips prefix simulation but doesn't restore position
if prefix in self._memo:
    cum_reward = self._memo[prefix]
    # But self.position is still at origin!
```

**Why it matters**: You must either (a) re-step through the prefix to set position,
or (b) cache the position at each prefix node. Option (b) is faster and shown above.

### Memoization Persistence

The memo persists across calls. If `evaluate_plans_memoized` is called twice, the
second call can reuse prefixes from the first. This is essential for CEM, which
evaluates many batches of plans.

### Performance Characteristics

**When memoization helps:**
- Plans share long prefixes (e.g., CEM samples many similar plans)
- Multiple calls to `evaluate_plans_memoized` with overlapping plans
- Large batch sizes with redundant prefixes

**When memoization may not help:**
- All plans are completely unique with no shared prefixes
- Very short horizons (prefix overhead dominates)
- First call with empty memo (no reuse yet)

**Memory considerations:**
- Each memo entry stores `(cumulative_reward, position_copy)`
- For horizon H and N plans, worst case is O(N*H) entries
- In practice, CEM generates many plans with shared prefixes, so actual memory is much less
- The memo grows monotonically (entries are never deleted)

### Edge Cases

**Empty plans array:**
```python
plans = np.array([]).reshape(0, horizon)
rewards = env.evaluate_plans_memoized(plans)
# Returns empty array, no memo entries added
```

**Single plan:**
```python
plans = np.array([[2, 2, 0]])
rewards = env.evaluate_plans_memoized(plans)
# Evaluates the plan, memoizes all prefixes: (2,), (2,2), (2,2,0)
```

**Repeated identical plans:**
```python
plans = np.array([[2, 2, 0], [2, 2, 0]])
rewards = env.evaluate_plans_memoized(plans)
# First plan: simulates and memoizes all prefixes
# Second plan: hits cache immediately, no simulation needed
```

## 3. Iteration-Local RNG: `CrossEntropyMethod.optimize(...)`

### Core Mechanism
- Sample `num_samples` plans of length `horizon`
- Evaluate plans, select top `num_elites` by cumulative reward
- Update action distributions from elite frequencies
- Repeat for `iterations`

### Critical Constraint: Iteration-Local RNG

**WRONG: Sampling all iterations at once**
```python
# WRONG - consumes all RNG at once
all_plans = np.random.choice(n_actions, size=(iterations, num_samples, horizon))
for it in range(iterations):
    plans = all_plans[it]
    # ...
```

**CORRECT: Sample one iteration at a time**
```python
# CORRECT - each iteration consumes RNG independently
for it in range(iterations):
    plans = np.zeros((num_samples, horizon), dtype=int)
    for t in range(horizon):
        plans[:, t] = np.random.choice(n_actions, size=num_samples, p=self.probs[t])
    # ... evaluate and update ...
```

**Why it matters**: The task requires that `optimize(10)` called twice produces the
same result as `optimize(20)` called once under the same seed. This is only possible
if each iteration consumes a deterministic amount of RNG in the same order.

### Elite Selection

Use `np.argsort` for stable sorting:
```python
elite_indices = np.argsort(rewards)[-num_elites:]
```

This handles tied rewards correctly (stable sort preserves order of equal elements).

### Distribution Update

For each timestep, count elite action frequencies:
```python
for t in range(horizon):
    elite_actions = plans[elite_indices, t]
    counts = np.bincount(elite_actions, minlength=n_actions)
    self.probs[t] = counts / num_elites
```

Use `minlength=n_actions` to ensure the bincount has the right shape even if some
actions are not present in the elite set.

## Spec Variation Dimensions

### Environment Dynamics
- **Map size**: `length` parameter changes clipping bounds
- **Goal placement**: `goal_x`, `goal_y` change reward region
- **Goal radius**: `goal_radius` changes inclusive boundary
- **Action set**: `action_map` defines movement vectors (9 actions in seed)

The implementation handles all these via parameters. The clipping logic is
`np.clip(pos, -length//2, length//2)` which works for any even `length`.

### Policy Update Regime
- **Sample count**: `num_samples` changes Monte Carlo accuracy
- **Elite fraction**: `num_elites` changes selection pressure
- **Horizon**: `horizon` changes plan length
- **Reward sparsity**: Environment dynamics determine reward density

The CEM loop is agnostic to these parameters. It just samples, evaluates, selects,
and updates.

### Overlapping Plan Evaluation
- **Prefix overlap**: Plans may share long or short prefixes
- **Repeated plans**: Same plan may appear multiple times
- **Batch size**: N plans evaluated together

The prefix-trie memoization handles all these. Shared prefixes are cached and reused.
Repeated plans hit the cache immediately. Larger batches benefit more from memoization.

## Testing Checklist

- [ ] Independent axis clipping (x clips, y still moves)
- [ ] Inclusive goal boundary (distance == radius returns 1)
- [ ] Prefix memoization (shared prefixes evaluated once)
- [ ] Cross-call memoization (memo persists between calls)
- [ ] Position restoration (env position unchanged after evaluation)
- [ ] RNG iteration-locality (two calls of N match one call of 2N)
- [ ] Elite selection with ties (argsort is stable)
- [ ] Distribution update (probs sum to 1, correct frequencies)

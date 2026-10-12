---
name: cross-entropy-method
description: >
  Implement cross-entropy method (CEM) optimization for discrete-action point-mass
  environments with prefix-based memoization. Handles independent axis clipping,
  Euclidean distance rewards, and efficient batch evaluation of overlapping action plans.
---

# Cross-Entropy Method for Discrete-Action Point-Mass Environments

This skill implements three core components for CEM-based planning in grid-like environments:
1. `PointEnv.step(action)` - environment dynamics with independent clipping
2. `PointEnv.evaluate_plans_memoized(plans)` - batch evaluation with prefix memoization
3. `CrossEntropyMethod.optimize(...)` - iterative policy optimization

## Family Invariants (Always True)

### Environment Dynamics
- **Action map is a class attribute**: `PointEnv.action_map` defines the discrete action set. Subclasses may override this with different numbers of actions.
- **Always use `self.action_map`**: Never hardcode `PointEnv.action_map` in methods that may be called on subclasses. Use `self.action_map[action]` to respect polymorphism.
- **Independent axis clipping**: Each coordinate is clipped independently to `[-length/2, +length/2]`. Clipping one axis must NOT suppress motion on the other axis.
  ```python
  new_pos = pos + delta
  new_pos[0] = np.clip(new_pos[0], -half, half)
  new_pos[1] = np.clip(new_pos[1], -half, half)
  ```
- **Euclidean distance reward**: Return 1 if `np.linalg.norm(position - goal) <= goal_radius`, else 0. The boundary is inclusive.

### Memoized Plan Evaluation
- **Always evaluate from origin**: `evaluate_plans_memoized` ALWAYS starts each plan from position `(0, 0)`, regardless of `env.position`. The cache is keyed by absolute action prefixes from origin, not relative to current position.
- **Position invariance**: `evaluate_plans_memoized` must NOT modify `env.position`. All evaluation happens on temporary state.
- **CRITICAL: Do NOT call `self.step()` inside `evaluate_plans_memoized`**: Calling `step()` would mutate `env.position`. Instead, re-implement the dynamics inline with identical logic to `step()`.
- **Prefix-based memoization**: Cache intermediate states keyed by action prefix tuples `(a_0, a_1, ..., a_t)`. This reuses computation for plans sharing prefixes, not just identical plans.
- **Cache initialization**: The `_plan_cache` dict must be initialized in `PointEnv.__init__` (it's not in the starter code). Initialize as `self._plan_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {}`.
- **Cache persistence**: The cache persists across multiple calls to `evaluate_plans_memoized`. Store as instance variable `self._plan_cache`.
- **Cache structure**: Map `tuple(actions) -> (position_array, cumulative_reward)`. Store a **copy** of position (via `.copy()`) to avoid mutation issues.

### Cross-Entropy Optimization
- **Timestep-by-timestep sampling**: For each timestep `t`, sample all plans' action at `t` together:
  ```python
  for t in range(horizon):
      samples[:, t] = np.random.choice(num_actions, size=num_samples, p=self.probs[t])
  ```
  Do NOT sample plan-by-plan (this breaks RNG consumption patterns).
- **Deterministic elite selection**: Use `np.argsort(rewards)[-num_elites:]` for deterministic tie-breaking. Do NOT use `np.argpartition` (non-deterministic for ties).
- **Elite frequency update**: For each timestep, count action frequencies among elites and normalize:
  ```python
  for t in range(horizon):
      action_counts = np.bincount(elites[:, t], minlength=self.num_actions)
      self.probs[t] = action_counts / num_elites
  ```
- **Iteration-local RNG consumption**: Calling `optimize(iterations=10)` twice must produce the same result as calling `optimize(iterations=20)` once under the same seed. This is achieved by consuming RNG in a loop: `for _ in range(iterations): ...`.
- **Polymorphism in `__init__`**: `CrossEntropyMethod.__init__` must use `len(env.action_map)`, NOT `len(PointEnv.action_map)`. This is a critical fix from the starter code.

## Spec-Declared Variations (May Change)

### Environment Configuration
- `length`: Side length of square environment (must be even, `length/2` is integer)
- `goal_x`, `goal_y`: Goal position coordinates (must satisfy `|goal| < length/2`)
- `goal_radius`: Radius of goal circle (positive)
- Bounds: `[-length/2, +length/2]` for each axis

### Action Space
- `action_map`: May have different numbers of actions (e.g., 5-action vs 9-action sets)
- Actions still represent local motion in the same 2D state space
- Always use `len(env.action_map)` for `num_actions`, never hardcode

### Optimization Parameters
- `num_samples`: Number of Monte Carlo trajectory samples per iteration
- `num_elites`: Number of top-reward samples to keep
- `iterations`: Number of CEM iterations
- `horizon`: Length of action sequences

### Plan Batch Characteristics
- Degree of prefix overlap (plans may share many prefixes or be mostly unique)
- Batch size `N` and horizon `H` vary
- Memoization must handle both heavily overlapping and mostly unique plan sets efficiently

## Implementation Patterns

### Step Function Pattern
```python
def step(self, action: int) -> int:
    # Apply action
    delta = self.action_map[action]
    self.position = self.position + delta
    
    # Independent clipping
    half = self.length // 2
    self.position[0] = np.clip(self.position[0], -half, half)
    self.position[1] = np.clip(self.position[1], -half, half)
    
    # Euclidean distance reward
    dist = np.linalg.norm(self.position - self.goal)
    return 1 if dist <= self.goal_radius else 0
```

### Memoized Evaluation Pattern
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    results = []
    half = self.length // 2
    
    for plan in plans:
        prefix = ()
        pos = np.array((0, 0), dtype=np.int_)
        cum_reward = 0
        
        for action in plan:
            prefix = prefix + (int(action),)
            if prefix in self._plan_cache:
                pos, cum_reward = self._plan_cache[prefix]
            else:
                # CRITICAL: Do NOT call self.step() here!
                # Re-implement dynamics inline to avoid mutating env.position
                delta = self.action_map[int(action)]
                new_pos = pos + delta
                new_pos = np.array([
                    int(np.clip(new_pos[0], -half, half)),
                    int(np.clip(new_pos[1], -half, half)),
                ], dtype=np.int_)
                
                dist = np.linalg.norm(new_pos - self.goal)
                reward = 1 if dist <= self.goal_radius else 0
                cum_reward += reward
                
                # Cache with position COPY
                self._plan_cache[prefix] = (new_pos.copy(), cum_reward)
                pos = new_pos
        
        results.append(cum_reward)
    
    return results
```

### Optimize Pattern
```python
def optimize(self, num_samples=100, num_elites=25, iterations=20):
    for _ in range(iterations):
        # Sample timestep-by-timestep
        samples = np.zeros((num_samples, self.horizon), dtype=int)
        for t in range(self.horizon):
            samples[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(samples))
        
        # Select elites (deterministic)
        elite_indices = np.argsort(rewards)[-num_elites:]
        elites = samples[elite_indices]
        
        # Update probabilities
        for t in range(self.horizon):
            action_counts = np.bincount(elites[:, t], minlength=self.num_actions)
            self.probs[t] = action_counts / num_elites
```

## Critical Checks

1. **Polymorphism**: `CrossEntropyMethod.__init__` must use `len(env.action_map)`, not `len(PointEnv.action_map)`.
2. **Position invariance**: After `evaluate_plans_memoized`, `env.position` must be unchanged.
3. **Cache initialization**: `_plan_cache` must be initialized in `PointEnv.__init__` (not in starter code).
4. **Cache correctness**: Cached positions must be copies (`.copy()`), not references to mutable arrays.
5. **No step() in evaluate_plans_memoized**: Do NOT call `self.step()` inside `evaluate_plans_memoized` as it would mutate `env.position`.
6. **RNG determinism**: Test that `optimize(10) + optimize(10)` equals `optimize(20)` under the same seed.
7. **Independent clipping**: Test that clipping one axis doesn't suppress the other (e.g., from `(2,3)` with action `[1,1]`, result is `(3,3)` not `(2,3)`).
8. **Prefix sharing**: Verify that plans with shared prefixes result in fewer cache entries than the sum of individual plan lengths.
9. **Dynamics consistency**: The inline dynamics in `evaluate_plans_memoized` must be identical to `step()` (same clipping, same reward calculation).

## Common Pitfalls

1. **Calling `self.step()` in `evaluate_plans_memoized`**: This mutates `env.position` and violates the position invariance requirement. Always re-implement dynamics inline.

2. **Forgetting to initialize `_plan_cache`**: The starter code doesn't include `_plan_cache` in `__init__`. You must add it: `self._plan_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {}`.

3. **Not using `.copy()` for cached positions**: If you cache `new_pos` directly without `.copy()`, subsequent operations might mutate the cached array, corrupting future lookups.

4. **Using `len(PointEnv.action_map)` in `CrossEntropyMethod.__init__`**: This breaks polymorphism. Use `len(env.action_map)` instead.

5. **Sampling plan-by-plan instead of timestep-by-timestep**: This breaks the RNG consumption pattern and causes `optimize(10) + optimize(10)` to differ from `optimize(20)`.

6. **Using `np.argpartition` for elite selection**: This is non-deterministic for ties. Use `np.argsort` for deterministic behavior.

7. **Mutating cached positions**: When retrieving from cache, `pos` is a reference to the cached array. If you later do `pos[0] = ...`, you corrupt the cache. Always create new arrays via operations like `pos + delta`.

## Performance Considerations

- Prefix-based memoization provides significant speedup (40x+ on repeated plans) when plans share prefixes.
- Cache grows with the number of unique prefixes encountered. For heavily overlapping plan sets, cache size is manageable.
- Tuple conversion for cache keys is acceptable per the spec; assume constant-time hashing.
- For very large batches with minimal overlap, memoization overhead may be non-trivial but still correct.
- Building prefix tuples incrementally is O(H²) for a plan of length H due to tuple concatenation. This is acceptable for typical horizon sizes.

## Edge Cases and Robustness

- **Float goal coordinates**: `goal_x` and `goal_y` can be floats. Position is always integer, so `np.linalg.norm(int_pos - float_goal)` works correctly.
- **Very small/large goal_radius**: The implementation handles any positive radius. Very small radius (e.g., 0.001) means only exact matches get reward. Very large radius means most positions get reward.
- **Negative goal coordinates**: Works correctly. The environment is symmetric around origin.
- **Empty plans (horizon=0)**: Returns reward 0. The loop over actions doesn't execute.
- **Sparse rewards**: When most plans get reward 0, elite selection still works. The elites will be those rare plans that got reward > 0, or if all are 0, the selection is arbitrary but deterministic.
- **Zero probabilities**: After elite selection, some actions may have 0 probability at certain timesteps. This is correct CEM behavior — those actions are never sampled again. If all elites choose the same action, that timestep becomes deterministic.
- **Tied rewards**: `np.argsort` handles ties deterministically (stable sort). Plans with equal rewards are ordered by their index in the array.
- **Interleaving step() and evaluate_plans_memoized()**: If you call `step()` to move the environment, then call `evaluate_plans_memoized()`, the evaluation still starts from origin (0,0). The `env.position` is not used in evaluation.

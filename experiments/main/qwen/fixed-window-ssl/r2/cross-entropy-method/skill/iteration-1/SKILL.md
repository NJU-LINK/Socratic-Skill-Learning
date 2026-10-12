---
name: cross-entropy-method
description: >
  Implement the cross-entropy method (CEM) for trajectory optimization in
  discrete-action grid environments, with prefix-memoized batch plan evaluation,
  independent-axis boundary clipping, and iteration-sequential RNG consumption.
---

# Cross-Entropy Method for Discrete-Action Grid Environments

## Overview

This skill covers the implementation of three tightly coupled components:

1. **A point-mass grid environment** (`PointEnv`) with discrete movement actions,
   independent-axis boundary clipping, and Euclidean-distance reward.
2. **Memoized batch plan evaluation** that reuses shared prefixes across plans
   and persists the cache across calls.
3. **Cross-entropy optimization** that iteratively samples action sequences,
   selects elites, and updates per-timestep categorical distributions.

## 1. Environment Dynamics

### Independent Axis Clipping

When the agent moves, each coordinate is clipped **independently** to the
inclusive bounds `[-length/2, +length/2]`. This means if one axis hits the
boundary, the other axis can still move freely.

```python
def step(self, action: int) -> int:
    delta = self.action_map[action]
    new_pos = self.position + delta
    half = self.length // 2
    # Clip each axis independently
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    self.position = new_pos
    reward = 1 if np.linalg.norm(self.position - self.goal) <= self.goal_radius else 0
    return int(reward)
```

**Key invariant**: `length` is always even (enforced by constructor assert),
so `length // 2` gives the exact integer bound. Never use float division
(`length / 2`) for clip bounds.

### Reward

Reward is `1` when the **resulting** position is within Euclidean distance
`<= goal_radius` of the goal center, otherwise `0`. The boundary of the goal
circle is included.

## 2. Memoized Batch Plan Evaluation

### Architecture

The core design is a **prefix cache** mapping `tuple_of_actions → (position_after, cumulative_reward)`:

- Seed with `{(): (origin_position, 0)}` — the empty prefix at the start state.
- For each plan, find the **longest cached prefix**, then simulate only the
  remaining steps from the cached position and cumulative reward.
- After simulating, store **every new prefix** computed so future plans benefit.

### Local Simulation (No State Mutation)

Inside `evaluate_plans_memoized`, **never call `self.step()`**. Instead,
simulate locally using a copy of the cached position. This makes it
structurally impossible to leak state changes to the public environment.

```python
def evaluate_plans_memoized(self, plans):
    half = self.length // 2
    cache = self._cache
    results = []
    horizon = plans.shape[1]

    for i in range(plans.shape[0]):
        plan_tuple = tuple(int(a) for a in plans[i])

        if plan_tuple in cache:
            results.append(cache[plan_tuple][1])
            continue

        # Find longest cached prefix by forward walk (stops early)
        best_prefix_len = 0
        for p_len in range(1, horizon + 1):
            if plan_tuple[:p_len] in cache:
                best_prefix_len = p_len
            else:
                break

        # Start from cached state
        pos, cum_reward = cache[plan_tuple[:best_prefix_len]]
        pos = pos.copy()

        # Simulate remaining steps locally
        for t in range(best_prefix_len, horizon):
            action = int(plans[i, t])
            delta = self.action_map[action]
            pos = pos + delta
            pos[0] = np.clip(pos[0], -half, half)
            pos[1] = np.clip(pos[1], -half, half)
            reward = 1 if np.linalg.norm(pos - self.goal) <= self.goal_radius else 0
            cum_reward += reward
            cache[plan_tuple[:t + 1]] = (pos.copy(), cum_reward)

        results.append(cum_reward)

    return results
```

**Performance note**: The forward walk stops at the first missing prefix, making
it O(k) where k is the length of the longest cached prefix. This is more
efficient than a backward scan for plans with long shared prefixes. The cache
is always prefix-closed (if a prefix of length k exists, all shorter prefixes
also exist), so the forward walk is correct.

### Key Properties

- **Cache persists across calls**: The `_cache` dict is an instance attribute,
  so subsequent calls to `evaluate_plans_memoized` reuse all previously
  computed prefixes.
- **Shared prefix reuse**: If plan A = `[3, 3, 3]` and plan B = `[3, 3, 1]`,
  after evaluating A the cache has entries for `()`, `(3,)`, `(3,3)`, `(3,3,3)`.
  Evaluating B finds `(3,3)` as the longest prefix and only simulates one step.
- **Exact duplicate plans**: If the same plan appears multiple times, the second
  occurrence hits the full-plan cache entry immediately.
- **Public state unchanged**: Because simulation is local, `self.position` is
  never modified.

## 3. Cross-Entropy Method Optimization

### Algorithm

Each iteration:
1. **Sample** `num_samples` action sequences of length `horizon` from the
   current per-timestep categorical distributions.
2. **Evaluate** all plans using `evaluate_plans_memoized`.
3. **Select** the top `num_elites` plans by cumulative reward.
4. **Update** each timestep's distribution to the empirical action frequencies
   among the elites.

```python
def optimize(self, num_samples, num_elites, iterations):
    for _ in range(iterations):
        # Sample action sequences
        actions = np.zeros((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            actions[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )

        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(actions))

        # Select elites
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_actions = actions[elite_indices]

        # Update distributions
        for t in range(self.horizon):
            for a in range(self.num_actions):
                self.probs[t, a] = np.mean(elite_actions[:, t] == a)
```

### RNG Sequentiality (Critical Invariant)

**Two calls of 10 iterations must match one call of 20 iterations** under the
same NumPy seed. This means:

- **Never reset or re-seed the RNG** at the start of `optimize()`.
- Use `np.random.choice` (or a stored `self.rng`) sequentially across
  iterations.
- The sampling pattern is `(iteration, timestep, sample)` — all sequential.
- `self.probs` is updated in-place, so the second batch of 10 iterations
  starts from the distribution left by the first batch.

### Sampling Pattern

For each timestep `t`, sample `num_samples` actions independently from
`self.probs[t]`. This gives an `(iterations × horizon)` sequence of
`np.random.choice` calls that must be deterministic given the same starting
RNG state.

## 4. Family Variation Dimensions

### Environment Dynamics (varies)
- Map sizes (different `length` values, always even)
- Start and goal placements (different `goal_x`, `goal_y`, `goal_radius`)
- Action sets representing local motion (same 9-action set or subsets)
- Boundary behavior (always independent-axis clipping to `[-length/2, +length/2]`)
- Reward geometry (always Euclidean distance to goal center, threshold at `goal_radius`)

### Policy Update Regime (varies)
- Sample counts (`num_samples`)
- Elite fractions (`num_elites`)
- Trajectory lengths (`horizon`)
- Reward sparsity levels (determined by goal placement and radius)
- Convergence patterns (determined by above parameters)
- **Invariant**: iterative distribution update via elite frequencies; sequential RNG

### Overlapping Plan Evaluation (varies)
- Degree of prefix overlap (from none to complete)
- Repeated vs. unique plans
- Batch sizes (`N` in `(N, H)` plans array)
- **Invariant**: prefix-level memoization, persistent cache, no state mutation,
  exact cumulative rewards

## 5. Common Pitfalls

1. **Clipping both axes together**: Using `min/max` on the vector magnitude or
   clipping both axes to the same value suppresses motion on one axis when the
   other hits the boundary. Always clip each axis independently.

2. **Caching only full plans**: This misses the opportunity to reuse shared
   prefixes, which is the primary performance benefit of memoization.

3. **Calling `self.step()` inside `evaluate_plans_memoized`**: This mutates the
   public environment state. Always simulate locally.

4. **Resetting RNG in `optimize()`**: This breaks the sequentiality invariant
   and causes two calls of 10 iterations to differ from one call of 20.

5. **Using float division for clip bounds**: `length / 2` produces a float;
   always use `length // 2` for integer bounds.

6. **Not storing intermediate prefixes**: Only storing the final plan result
   means future plans with shared prefixes get no benefit. Store every prefix
   computed during simulation.

## 6. Performance Characteristics

### Memoization Speedup

The prefix cache provides significant speedup for batches with shared prefixes:
- **Heavy prefix overlap** (e.g., 1000 plans sharing first 10 of 15 actions): ~5x speedup vs. naive evaluation
- **Identical plans** (all N plans the same): ~70x speedup (first plan simulates fully, rest hit full-plan cache)
- **No overlap**: minimal overhead (each plan simulates fully, but cache lookups are O(1) dict lookups)

### Forward Walk vs. Backward Scan

The prefix lookup uses a **forward walk** (check prefixes from shortest to longest, stop at first miss) rather than a backward scan (check from longest to shortest). Both are O(H) worst case, but the forward walk stops early when the cache has a long shared prefix, making it faster in practice.

### Cache Properties

- The cache is **prefix-closed**: if a prefix of length k is cached, all shorter prefixes are also cached. This is guaranteed because we store every intermediate prefix during simulation.
- The forward walk exploits this property: it can safely break at the first missing prefix because no longer prefix can be cached.

## 7. Verification Checklist

- [ ] `step()` clips each axis independently to `[-length//2, +length//2]`
- [ ] `step()` returns 1 when `np.linalg.norm(position - goal) <= goal_radius`
- [ ] `evaluate_plans_memoized()` uses local simulation, not `self.step()`
- [ ] Cache is seeded with empty prefix at origin with zero reward
- [ ] Cache persists across calls (instance attribute)
- [ ] Every intermediate prefix is stored during simulation
- [ ] `self.position` is unchanged after `evaluate_plans_memoized()` returns
- [ ] `optimize()` does not reset or re-seed RNG
- [ ] Two calls of N iterations match one call of 2N iterations under same seed
- [ ] Elite selection uses `np.argsort(rewards)[-num_elites:]`
- [ ] Distribution update uses empirical frequencies among elites
- [ ] Probs sum to 1.0 at each timestep after update

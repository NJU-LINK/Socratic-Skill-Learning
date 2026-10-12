---
name: cross-entropy-method
description: >
  Reusable implementation pattern for cross-entropy method (CEM) optimization
  in bounded grid environments with discrete actions, featuring independent axis
  clipping, prefix-aware memoized plan evaluation, and iteration-local RNG
  handling for deterministic policy updates.
---

# Cross-Entropy Method Skill

This skill covers the implementation of CEM-based planning in bounded 2D grid
environments with discrete action spaces. The skill addresses three orthogonal
family axes: environment dynamics, overlapping plan evaluation, and policy
update regime.

## 1. Environment Dynamics: Independent Axis Clipping

### Core Mechanism

In a bounded 2D grid with integer coordinates, actions translate to state
updates via an action map. The critical invariant is **independent axis
clipping**: when the agent attempts to move beyond a boundary, only the
offending axis is clipped; the other axis must still update.

### Implementation Pattern

```python
def step(self, action: int) -> int:
    dx, dy = self.action_map[action]
    half = self.length // 2
    
    # Independent clipping: each axis clipped separately
    new_x = int(np.clip(self.position[0] + dx, -half, half))
    new_y = int(np.clip(self.position[1] + dy, -half, half))
    self.position = np.array([new_x, new_y], dtype=np.int_)
    
    # Inclusive boundary check for reward
    dist = np.sqrt((new_x - self.goal[0])**2 + (new_y - self.goal[1])**2)
    return 1 if dist <= self.goal_radius else 0
```

### Common Pitfalls

- **Coupled clipping bug**: Skipping the entire step when any axis is at
  boundary. Each axis must be clipped independently.
- **Exclusive vs inclusive boundary**: The reward condition is
  `dist <= goal_radius`, not `dist < goal_radius`. Landing exactly on the
  goal boundary counts.
- **Integer vs float positions**: Positions are integer, but goal coordinates
  and distances are float. Use `np.sqrt` for Euclidean distance.

### Variation Dimensions

- **Map size**: Different `length` values change the bounds `[-length/2, length/2]`.
- **Goal placement**: Different `(goal_x, goal_y)` and `goal_radius` values.
- **Action sets**: Different action maps (e.g., 4-connected vs 8-connected grids).

## 2. Overlapping Plan Evaluation: Prefix-Aware Memoization

### Core Mechanism

When evaluating batches of action sequences, many plans share common prefixes.
A **prefix trie** (or equivalently, a memoization cache keyed by prefix tuples)
allows simulating each unique prefix exactly once and reusing the result.

### Implementation Pattern

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    # Save state: all plans start from origin, not current state
    saved_position = self.position.copy()
    
    if not hasattr(self, '_memo'):
        self._memo = {}  # prefix_tuple -> (x, y, cumulative_reward)
    
    results = []
    for plan in plans:
        plan_tuple = tuple(int(a) for a in plan)
        current_prefix = ()
        
        for i, action in enumerate(plan_tuple):
            current_prefix = current_prefix + (action,)
            if current_prefix not in self._memo:
                # Get parent state
                if i == 0:
                    px, py = 0, 0
                    parent_cum_reward = 0
                else:
                    parent_prefix = current_prefix[:-1]
                    px, py, parent_cum_reward = self._memo[parent_prefix]
                
                # Simulate one step from parent state
                self.position = np.array([px, py], dtype=np.int_)
                reward = self.step(action)
                new_x, new_y = int(self.position[0]), int(self.position[1])
                cum_reward = parent_cum_reward + reward
                
                self._memo[current_prefix] = (new_x, new_y, cum_reward)
        
        _, _, total_reward = self._memo[plan_tuple]
        results.append(total_reward)
    
    # Restore state so public position is unchanged
    self.position = saved_position
    return results
```

### Key Invariants

- **Cross-call persistence**: The memo cache persists across calls. If call 1
  evaluates `[2, 5, 1]` and call 2 evaluates `[2, 5, 7]`, call 2 reuses the
  `[2, 5]` prefix from call 1.
- **State restoration**: After evaluating the batch, `self.position` must be
  restored to its original value. The environment's public state is unchanged.
- **Origin-based evaluation**: Every plan starts from the origin `(0, 0)`, not
  from the environment's current position.

### Performance Characteristics

- **Time complexity**: O(N × H) in the worst case (no sharing), but with
  significant speedup when plans share prefixes.
- **Space complexity**: O(U) where U is the number of unique prefixes across
  all evaluated plans.
- **Sharing degree**: With random plans of length H over A actions, the number
  of unique prefixes grows as O(min(N × H, A^H)).

### Variation Dimensions

- **Prefix overlap**: Different degrees of sharing (e.g., CEM samples vs random plans).
- **Batch size**: Different numbers of plans per evaluation call.
- **Horizon length**: Different plan lengths H.

## 3. Policy Update Regime: CEM with Iteration-Local RNG

### Core Mechanism

The cross-entropy method maintains a per-timestep categorical distribution over
actions. Each iteration samples plans, evaluates them, selects elites, and
updates distributions to elite action frequencies.

### Implementation Pattern

```python
def optimize(self, num_samples=100, num_elites=25, iterations=20):
    for _ in range(iterations):
        # Sample plans: column-by-column for deterministic RNG consumption
        plans = np.empty((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate all plans
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        
        # Select elites: top num_elites by cumulative reward
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Update distributions to elite action frequencies
        for t in range(self.horizon):
            for a in range(self.num_actions):
                self.probs[t, a] = np.sum(elite_plans[:, t] == a) / num_elites
```

### Critical RNG Discipline

The spec requires: "two calls of 10 iterations match one call of 20 under the
same NumPy seed." This implies:

- **Persistent RNG state**: Use the global `np.random` state (or a persistent
  `RandomState` object) that survives across `optimize()` calls.
- **Deterministic consumption order**: Sample timestep-by-timestep in a fixed
  order (0, 1, ..., H-1) every iteration. This ensures the RNG is consumed in
  the same sequence regardless of how `optimize()` is called.
- **No reseeding**: Do not call `np.random.seed()` inside the loop. The caller
  controls the seed.

### Common Pitfalls

- **Row-wise sampling**: Sampling `plans[i, :]` for each plan `i` consumes RNG
  in a different order than column-wise sampling, breaking determinism.
- **Creating new RNG per iteration**: This resets the RNG state and breaks the
  "two calls of 10 == one call of 20" invariant.
- **Non-stable argsort**: When rewards are tied, `np.argsort` is stable by
  default, but be aware that different tie-breaking can affect elite selection.

### Variation Dimensions

- **Sample count**: Different `num_samples` values.
- **Elite fraction**: Different `num_elites / num_samples` ratios.
- **Trajectory length**: Different `horizon` values.
- **Reward sparsity**: Different environment configurations leading to sparse
  vs dense rewards.
- **Convergence patterns**: Different numbers of iterations needed for
  convergence.

## Integration: How the Three Axes Interact

The three axes are orthogonal but interact in the full CEM loop:

1. **Environment dynamics** determine how actions translate to state updates and
   rewards. The independent axis clipping and inclusive boundary check are
   family invariants.

2. **Memoized evaluation** accelerates the CEM's plan evaluation step. The
   prefix trie exploits the fact that CEM samples often share prefixes,
   especially in later iterations when the distribution becomes peaked.

3. **CEM optimization** drives the policy update. The iteration-local RNG
   discipline ensures reproducibility and composability (split calls match
   single calls).

### Typical Usage Pattern

```python
# Setup
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)
cem = CrossEntropyMethod(env, horizon=15)

# Optimize (RNG state is controlled by caller)
np.random.seed(42)
cem.optimize(num_samples=100, num_elites=25, iterations=20)

# The optimized policy is in cem.probs
# Each row sums to 1, and high-probability actions indicate the learned policy
```

## Testing Checklist

When implementing or adapting this skill, verify:

- [ ] **Independent axis clipping**: At boundary, one axis clips while the other moves.
- [ ] **Inclusive boundary**: Reward is 1 when `dist == goal_radius`.
- [ ] **Memoization persistence**: Cache survives across `evaluate_plans_memoized` calls.
- [ ] **State restoration**: Environment position unchanged after batch evaluation.
- [ ] **Prefix sharing**: Plans with common prefixes reuse cached states.
- [ ] **RNG determinism**: Two calls of N iterations == one call of 2N iterations.
- [ ] **Probability normalization**: `probs[t].sum() == 1.0` for all t after optimization.
- [ ] **Empty plans**: `evaluate_plans_memoized` handles empty input correctly.
- [ ] **Identical plans**: Repeated plans reuse cache, no redundant computation.

## Family Generalization

This skill generalizes to:

- **Different grid sizes**: The clipping logic works for any `length` (must be even).
- **Different action sets**: The action map can be changed (e.g., 4-connected grid).
- **Different reward structures**: The reward function can be adapted (e.g., distance-based rewards).
- **Different CEM variants**: The core CEM loop can be modified (e.g., soft updates, eligibility traces).

The key is to preserve the **mechanisms** (independent clipping, prefix trie,
column-wise RNG consumption) rather than memorizing specific parameter values.

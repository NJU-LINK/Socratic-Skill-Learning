---
name: cross-entropy-method
description: Implement cross-entropy method optimization for point-mass environments with trie-based memoization, independent axis clipping, and distance-based rewards
---

# Cross-Entropy Method for Point-Mass Environments

## Overview

This skill implements the cross-entropy method (CEM) for optimizing policies in discrete-action point-mass environments. The implementation handles three key components: environment dynamics with boundary clipping, efficient batch evaluation with prefix-sharing memoization, and iterative distribution updates.

## Core Components

### 1. Environment Dynamics (PointEnv.step)

**Mechanism**: Discrete actions map to 2D movement vectors. Position updates with independent axis clipping to bounded grid.

**Implementation**:
```python
def step(self, action: int) -> int:
    # Get movement vector
    delta = self.action_map[action]
    
    # Update position
    self.position = self.position + delta
    
    # Clip each coordinate independently to [-length/2, length/2]
    half = self.length // 2
    self.position[0] = np.clip(self.position[0], -half, half)
    self.position[1] = np.clip(self.position[1], -half, half)
    
    # Check if in goal region (distance <= goal_radius)
    dist = np.linalg.norm(self.position - self.goal)
    reward = 1 if dist <= self.goal_radius else 0
    return reward
```

**Critical Details**:
- **Independent clipping**: Each axis clips separately. Clipping x must NOT suppress motion on y.
- **Inclusive boundary**: Use `<=` for goal_radius check (boundary is included).
- **Position update**: Add delta first, then clip.
- **Action map**: The starter code defines 9 actions (8 directions + stay). If the action set varies, ensure `action_map` is correctly defined.

**Family Variation**: Map size, goal placement, action sets, and boundary behavior may vary. The invariant is independent per-axis clipping and inclusive distance-based reward.

### 2. Memoized Batch Evaluation (PointEnv.evaluate_plans_memoized)

**Mechanism**: Trie-based cache shares computation across plans with common prefixes.

**Trie Data Structure**:
```python
# In __init__:
self._trie_root: dict = {}  # Root is just a dict

# Each node is a dict: {action_key: (position, cumulative_reward, children_dict)}
# - position: np.ndarray of shape (2,) - MUST BE A COPY, not a reference
# - cumulative_reward: int
# - children_dict: dict (same structure as parent)
```

**Implementation**:
```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    half = self.length // 2
    goal = self.goal
    goal_radius = self.goal_radius
    action_map = self.action_map
    trie_root = self._trie_root
    
    rewards = []
    
    for plan in plans:
        # Start at root with initial state (always from origin)
        node = trie_root  # current node's children dict
        pos = np.array((0, 0), dtype=np.int_)
        cum_reward = 0
        
        # Traverse trie for each action in plan
        for action in plan:
            # CRITICAL: Convert numpy scalar to Python int for dict key
            action_key = int(action)
            
            if action_key not in node:
                # Compute new state
                delta = action_map[action_key]
                new_pos = pos + delta
                new_pos = new_pos.copy()  # CRITICAL: avoid aliasing
                
                # Clip independently
                new_pos[0] = np.clip(new_pos[0], -half, half)
                new_pos[1] = np.clip(new_pos[1], -half, half)
                
                # Compute step reward
                dist = np.linalg.norm(new_pos - goal)
                step_reward = 1 if dist <= goal_radius else 0
                new_cum_reward = cum_reward + step_reward
                
                # Create new trie node
                new_node = {}
                node[action_key] = (new_pos, new_cum_reward, new_node)
            
            # Move to next node
            pos, cum_reward, node = node[action_key]
        
        rewards.append(cum_reward)
    
    return rewards
```

**Critical Details**:
- **Always start from origin**: Plans are evaluated from (0,0) regardless of `env.position`.
- **int(action) conversion**: When iterating over numpy arrays, convert to Python int before using as dict key. Without this, numpy int64 keys won't match Python int keys.
- **Prefix sharing**: Plans with common prefixes reuse cached states. E.g., `[2,2,1]` and `[2,2,3]` share the `[2,2]` computation.
- **Persistence**: Trie persists across multiple calls to `evaluate_plans_memoized`.
- **No side effects**: Must not modify `env.position`.
- **new_pos.copy()**: CRITICAL to copy the position array to avoid aliasing issues. If you store a reference to `pos + delta`, subsequent modifications will corrupt the cache.

**Family Variation**: Plan batch size, horizon length, and degree of prefix overlap vary. The invariant is exact cumulative reward computation with prefix-level memoization.

### 3. Cross-Entropy Optimization (CrossEntropyMethod.optimize)

**Mechanism**: Iteratively refine action distribution by sampling plans, selecting elites, and updating probabilities.

**Implementation**:
```python
def optimize(self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20) -> None:
    for _ in range(iterations):
        # Sample plans from current distribution
        plans = np.empty((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )
        
        # Evaluate all plans using memoized evaluation
        rewards = self.env.evaluate_plans_memoized(plans)
        rewards = np.array(rewards)
        
        # Select elites (top num_elites by reward)
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        # Update probabilities based on elite action frequencies
        for t in range(self.horizon):
            actions = elite_plans[:, t]
            counts = np.bincount(actions, minlength=self.num_actions)
            self.probs[t] = counts / num_elites
```

**Critical Details**:
- **Iteration-locality**: RNG consumption must be iteration-local. Two calls of `optimize(iterations=10)` must match one call of `optimize(iterations=20)` under the same seed.
- **Natural RNG flow**: Do not reset or manipulate RNG state; let it flow naturally through iterations.
- **Elite selection**: Use `np.argsort(rewards)[-num_elites:]` to get top-k indices.
- **Probability normalization**: `counts / num_elites` automatically normalizes to sum to 1.
- **minlength in bincount**: Ensure `minlength=self.num_actions` to handle cases where not all actions appear in elites.

**Family Variation**: Sample counts, elite fractions, trajectory lengths, reward sparsity, and convergence patterns vary. The invariant is correct probabilistic updates under deterministic priors, tied rewards, and sparse rewards.

## Common Pitfalls

1. **Axis coupling in clipping**: Clipping x must not affect y and vice versa. Use separate `np.clip` calls per axis.
2. **Reward boundary**: Use `<=` for goal_radius check (inclusive boundary).
3. **Memoization side effects**: `evaluate_plans_memoized` must not modify `env.position`.
4. **Trie node structure**: Store position and cumulative reward at each node to avoid recomputation.
5. **RNG determinism**: Do not reset or manipulate RNG state; let it flow naturally through iterations.
6. **Elite selection**: Use `np.argsort` to get indices, then select top-k. Handle ties consistently.
7. **Probability normalization**: After computing frequencies, ensure probabilities sum to 1.
8. **Numpy scalar conversion**: When iterating over numpy arrays, convert to Python int before using as dict key: `action_key = int(action)`.
9. **Position copying**: When storing positions in trie nodes, use `.copy()` to avoid aliasing.
10. **Origin-based evaluation**: Plans must be evaluated from origin (0,0), not from current `env.position`.
11. **bincount minlength**: Use `minlength=self.num_actions` to ensure all actions are counted even if not present in elites.

## Implementation Checklist

Before submitting, verify:

- [ ] Step function clips each axis independently
- [ ] Step function returns correct reward (distance <= goal_radius)
- [ ] Memoization shares prefixes across plans
- [ ] Memoization persists across multiple calls
- [ ] `evaluate_plans_memoized` does not modify env.position
- [ ] `evaluate_plans_memoized` evaluates from origin regardless of env.position
- [ ] CEM updates probabilities correctly
- [ ] Two calls of N iterations match one call of 2N iterations
- [ ] Handles different environment configurations (size, goal, radius)
- [ ] Handles edge cases (boundary positions, identical plans, single-step plans)
- [ ] Action keys are converted to Python int before dict lookup
- [ ] Position arrays are copied when stored in trie nodes
- [ ] bincount uses minlength parameter

## Testing Strategy

1. **Basic mechanics**: Test step function with simple actions, verify position updates and rewards.
2. **Clipping**: Test independent axis clipping at boundaries (both positive and negative).
3. **Reward boundary**: Test positions at exactly goal_radius distance.
4. **Memoization**: Test prefix sharing, persistence, and no side effects.
5. **CEM**: Test optimization converges, iteration locality holds.
6. **Edge cases**: Test action 0 (stay), boundary hitting, large batches, identical plans, negative coordinates.

## Generalization

This skill applies to any discrete-action point-mass environment with:
- Bounded 2D grid with independent axis clipping
- Distance-based reward (Euclidean or other metrics)
- Need for efficient batch plan evaluation with prefix sharing
- Iterative distribution-based optimization

The specific action set, grid size, goal configuration, and reward function may vary, but the core mechanisms (independent clipping, trie memoization, iteration-local CEM) remain invariant.

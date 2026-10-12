# CEM Gridworld Implementation Patterns

## Table of Contents
- [Prefix Memoization](#prefix-memoization)
- [Independent Axis Clipping](#independent-axis-clipping)
- [Sequential RNG Consumption](#sequential-rng-consumption)

## Prefix Memoization
Use a persistent trie (or dictionary keyed by action tuples) rooted at the origin to memoize plan evaluation. Each node stores position, cumulative reward, and children keyed by action. This naturally reuses shared prefixes across plans, achieving O(unique_prefixes) complexity instead of O(N*H), and avoids mutating the environment's public position.

Initialize the root with the origin and 0 reward. For each plan, walk the structure action-by-action; on cache miss, compute the new position and step reward, and create the child node. Append the leaf node's cumulative reward as the plan's total reward.

## Independent Axis Clipping
When clipping positions to grid bounds (e.g., `[-length/2, +length/2]`), apply `np.clip` with scalar bounds so each coordinate is clipped independently. Hitting a boundary on one axis must not zero out or suppress the other axis's update (e.g., diagonal motion at a boundary).

```python
self.position = np.clip(self.position + movement, -half, half).astype(np.int_)
```

## Sequential RNG Consumption
In cross-entropy optimization, sample plans column-by-column (for each timestep `t`, draw `num_samples` actions from `probs[t]`) rather than row-by-row. Use the global `np.random` state and do **not** reset seeds, save/restore RNG state, or create per-iteration `RandomState` objects inside the loop.

```python
for t in range(horizon):
    plans[:, t] = np.random.choice(num_actions, size=num_samples, p=self.probs[t])
```

This ensures RNG consumption is strictly sequential and deterministic (e.g., two calls of 10 iterations match one call of 20 under the same NumPy seed).
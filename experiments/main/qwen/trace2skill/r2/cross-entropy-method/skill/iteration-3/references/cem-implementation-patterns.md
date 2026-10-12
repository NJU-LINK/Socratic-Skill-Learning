# CEM Implementation Patterns

## Prefix-Trie Memoization for Plan Evaluation
When evaluating sequences of actions (plans) in a stateful environment, overlapping prefixes can be memoized to achieve O(suffix_length) work.
- **Cache state and reward**: Maintain a trie or dictionary cache mapping action-prefix tuples to `(environment_state, cumulative_reward)`.
- **Avoid re-simulation**: Find the longest cached prefix, restore the cached state, and resume execution from the suffix. Do not re-simulate the prefix steps by calling the environment's step function, as this recomputes expensive transitions and defeats memoization.
- Always save and restore the environment's initial state before and after batch evaluation to avoid mutating the global state.

## Iteration-Local RNG Consumption
Ensure RNG consumption is strictly iteration-local so that multiple calls with fewer iterations match a single call with the sum of iterations under the same seed.
- In the CEM optimize loop, iterate through timesteps and sample actions using the global numpy random state sequentially (e.g., `np.random.choice(..., p=self.probs[t])`).
- Avoid global or persistent RNG state outside the iteration loop.

## Grid Environment Mechanics
- **Independent Axis Clipping**: Apply boundary clipping to each coordinate independently (e.g., `np.clip(new_pos, -half, half)`) after adding the movement vector. Avoid conditional logic that rejects the whole movement if any axis exceeds bounds, ensuring sliding along a wall correctly updates the unblocked axis.
- **Goal Rewards**: Use inclusive Euclidean distance (`np.linalg.norm(pos - goal) <= goal_radius`) for goal rewards.
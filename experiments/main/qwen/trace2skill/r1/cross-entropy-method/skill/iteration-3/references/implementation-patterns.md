# CEM Implementation Patterns

This reference details proven patterns for implementing the Cross-Entropy Method (CEM) in trajectory optimization and grid environments.

## Prefix-based Trajectory Memoization
Initialize the cache with the empty prefix `()` mapping to the start state `(origin, 0)`. For each plan, convert to a hashable tuple and search backwards from the full length to find the longest cached prefix. Simulate only the remaining steps and cache every intermediate prefix. This maximizes reuse of shared sub-trajectories across both intra-batch and inter-batch calls.

```python
cache = {(): (initial_state, 0)}
for plan in plans:
    start_idx = 0
    state, cum_reward = initial_state, 0
    # Search backwards for longest cached prefix
    for j in range(horizon, 0, -1):
        prefix = tuple(plan[:j])
        if prefix in cache:
            state, cum_reward = cache[prefix]
            start_idx = j
            break
    
    for j in range(start_idx, horizon):
        state = transition(state, plan[j])
        cum_reward += reward(state)
        cache[tuple(plan[:j+1])] = (state.copy(), cum_reward)
```

## Independent Axis Clipping and State Encapsulation
In bounded grid environments, apply coordinate clipping independently to each axis so that hitting a boundary on one axis does not suppress valid motion on the other. Always save and restore the environment's internal position state before and after batch plan evaluation to prevent side effects from leaking into subsequent environment interactions.

```python
new_pos = position + action_delta
new_pos[0] = np.clip(new_pos[0], -half_length, half_length)
new_pos[1] = np.clip(new_pos[1], -half_length, half_length)
```

## Deterministic Column-wise RNG Sampling
To guarantee that multiple sequential optimization calls (e.g., 10 + 10 iterations) perfectly match a single combined call (20 iterations) under the same global seed, sample action plans column-by-column (timestep-by-timestep across all samples) using the global RNG. Avoid creating local RNG instances or resetting seeds inside the optimization loop.

```python
for iteration in range(iterations):
    for t in range(horizon):
        samples[:, t] = np.random.choice(num_actions, size=num_samples, p=probs[t])
```
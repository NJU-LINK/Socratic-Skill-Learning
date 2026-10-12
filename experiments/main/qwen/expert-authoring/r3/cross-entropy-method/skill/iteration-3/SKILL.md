---
name: cross-entropy-method
description: >
  Implement a cross-entropy method for a deterministic point-mass grid navigation
  environment: environment stepping with boundary clipping and geometric reward,
  trie-based memoized batch plan evaluation, and iterative categorical policy
  optimization with iteration-local RNG. Covers the full family of variants
  differing in map size, goal geometry, action set, sample/elite counts, horizon,
  and plan-overlap structure.
---

# Cross-Entropy Method for Grid Navigation

## Execution Checklist

Follow these steps in order. Do not deviate.

1. `cat /app/cross_entropy_method/cross_entropy.py` — read the skeleton
2. Write the complete implementation (see code blocks below) via `cat > ... << 'EOF'`
3. `cd /app && pip install -e . 2>&1 | tail -2`
4. Run the smoke test (single command below)
5. Stop. Do not search for test files, read other package files, or re-read the written file.

## 1. `PointEnv.step(action)` → `int`

```python
def step(self, action: int) -> int:
    half = self.length // 2
    delta = self.action_map[action]
    # Add delta then clip each axis INDEPENDENTLY
    new_x = max(-half, min(half, self.position[0] + delta[0]))
    new_y = max(-half, min(half, self.position[1] + delta[1]))
    self.position = np.array([new_x, new_y], dtype=np.int_)
    # Reward: 1 if Euclidean distance to goal <= goal_radius (inclusive), else 0
    dx = self.position[0] - self.goal[0]
    dy = self.position[1] - self.goal[1]
    return 1 if dx * dx + dy * dy <= self.goal_radius * self.goal_radius else 0
```

**Decision rules:**
- Bounds are `[-length//2, +length//2]` inclusive; `length` is always even.
- Clip each axis independently — clipping one axis must NOT suppress motion on the other.
- Use squared-distance comparison (never `np.sqrt`) to avoid floating-point boundary issues.
- Keep `self.position` as integer dtype (`np.int_`).
- `self.goal` retains whatever dtype the constructor received (int or float); do not cast it.

## 2. `__init__` — Add trie root

Add this line at the end of the existing `__init__`:
```python
self._trie_root = {'pos': np.array((0, 0), dtype=np.int_), 'reward': 0, 'children': {}}
```

Each trie node stores: position (np.ndarray int), cumulative reward (int), children (dict mapping `int` action → child node).

## 3. `PointEnv.evaluate_plans_memoized(plans)` → `Sequence[int]`

**Interface:** `plans` is `np.ndarray` shape `(N, H)`. Returns sequence of N cumulative rewards.
**Side-effect contract:** `self.position` must be unchanged on return.

**Algorithm per plan:**
1. Walk trie from root following plan actions; stop at first missing child.
2. From the deepest matched node, simulate remaining steps (same clip+reward logic as `step`).
3. Create new trie nodes for each simulated step.
4. Return final cumulative reward.

**Critical details:**
- Save `self.position` at entry, restore at exit.
- Use `pos.copy()` when reading from / writing to trie nodes (prevent shared-reference bugs).
- Convert numpy action to Python `int` before using as dict key: `a = int(plan[t])`.
- Plans are always evaluated from origin `(0,0)`, NOT from `self.position`.
- Trie persists across calls — do NOT reset it between invocations.

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    saved_position = self.position.copy()
    half = self.length // 2
    action_map = self.action_map
    goal = self.goal
    gr_sq = self.goal_radius * self.goal_radius
    root = self._trie_root
    N, H = plans.shape
    results = []
    for i in range(N):
        plan = plans[i]
        node = root
        start = 0
        pos = node['pos'].copy()
        cum = node['reward']
        for t in range(H):
            a = int(plan[t])
            child = node['children'].get(a)
            if child is not None:
                node = child
                pos = node['pos'].copy()
                cum = node['reward']
                start = t + 1
            else:
                break
        for t in range(start, H):
            a = int(plan[t])
            delta = action_map[a]
            nx = max(-half, min(half, pos[0] + delta[0]))
            ny = max(-half, min(half, pos[1] + delta[1]))
            pos = np.array([nx, ny], dtype=np.int_)
            dx = pos[0] - goal[0]
            dy = pos[1] - goal[1]
            if dx * dx + dy * dy <= gr_sq:
                cum += 1
            new_node = {'pos': pos.copy(), 'reward': cum, 'children': {}}
            node['children'][a] = new_node
            node = new_node
        results.append(cum)
    self.position = saved_position
    return results
```

## 4. `CrossEntropyMethod.optimize(num_samples, num_elites, iterations)`

```python
def optimize(self, num_samples=100, num_elites=25, iterations=20):
    for _ in range(iterations):
        # Sample: timestep-by-timestep from Categorical(self.probs[t])
        plans = np.empty((num_samples, self.horizon), dtype=np.int_)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t])
        # Evaluate
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        # Elite selection: top num_elites by reward
        elite_idx = np.argsort(rewards)[-num_elites:]
        # Replace distribution with elite action frequencies
        for t in range(self.horizon):
            self.probs[t] = (
                np.bincount(plans[elite_idx, t], minlength=self.num_actions)
                / num_elites)
```

**Critical properties:**

| Property | How to achieve |
|---|---|
| Iteration-local RNG | Loop iterations sequentially; sample timestep-by-timestep `t=0,1,...,H-1` within each. Never vectorize across iterations. |
| Split-call equivalence | `optimize(10) + optimize(10)` ≡ `optimize(20)` under same `np.random.seed` — guaranteed by sequential iteration + fixed per-iteration RNG order. |
| Distribution update | Replace (not blend) with `bincount(elite_actions, minlength=num_actions) / num_elites`. |
| Continuity | Method reads/writes `self.probs`; subsequent calls continue from the updated distribution. |

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Using `np.sqrt` for distance | Use `dx*dx + dy*dy <= r*r` |
| Clipping suppresses other axis | Clip x and y independently via scalar `max/min` |
| Modifying `self.position` during eval | Use local `pos`; save/restore `self.position` |
| Whole-plan caching (not prefix) | Use a trie, not a flat dict of tuples |
| Vectorizing all iterations | Breaks split-call RNG equivalence; loop sequentially |
| `bincount` without `minlength` | Always `minlength=self.num_actions` |
| Not copying trie positions | Use `pos.copy()` on read/write |
| Casting goal to int | Never cast `self.goal`; it may be float |

## Smoke Test (run as one command)

```python
cd /app && python3 -c "
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# Step: (0,0)->(1,1)->(2,2)=goal->stay->stay = reward 3
env = PointEnv(); env.reset()
assert sum(env.step(a) for a in [2, 2, 0, 0]) == 3

# Independent axis clipping at boundary
env.reset()
for _ in range(3): env.step(1)  # x=3
env.step(2)  # [1,1] -> x clips to 3, y moves to 1
assert np.array_equal(env.position, [3, 1])

# Inclusive goal boundary
env2 = PointEnv(length=10, goal_x=0.0, goal_y=0.0, goal_radius=1.0)
env2.reset()
assert env2.step(1) == 1  # (1,0) dist=1.0 <= 1.0

# Memoized matches naive
np.random.seed(42)
plans = np.random.randint(0, 9, size=(20, 10))
memo = env.evaluate_plans_memoized(plans)
for i, p in enumerate(plans):
    env.reset(); assert memo[i] == sum(env.step(int(a)) for a in p)

# Trie persistence across calls
env3 = PointEnv()
r1 = env3.evaluate_plans_memoized(np.array([[1,2,3],[1,2,4]]))
r2 = env3.evaluate_plans_memoized(np.array([[1,2,5]]))
env3.reset()
assert r2[0] == sum(env3.step(int(a)) for a in [1,2,5])

# Position unchanged
env.reset(); env.step(1); pos = env.position.copy()
env.evaluate_plans_memoized(np.random.randint(0, 9, size=(5, 8)))
assert np.array_equal(pos, env.position)

# Split-call equivalence
np.random.seed(0)
c1 = CrossEntropyMethod(PointEnv(), horizon=10); c1.optimize(iterations=20)
p20 = c1.probs.copy()
np.random.seed(0)
c2 = CrossEntropyMethod(PointEnv(), horizon=10)
c2.optimize(iterations=10); c2.optimize(iterations=10)
assert np.allclose(p20, c2.probs)

# CEM convergence
np.random.seed(0)
env4 = PointEnv()
cem = CrossEntropyMethod(env4, horizon=15)
cem.optimize(num_samples=200, num_elites=30, iterations=50)
env4.reset()
total = sum(env4.step(int(a)) for a in np.argmax(cem.probs, axis=1))
assert total >= 10

print('All smoke tests passed!')
"
```

## Variant Dimensions

These axes vary across the family — your implementation must handle all:

- **environment_dynamics**: map size, start/goal placement, action set (local motion in 2D), boundary behavior, geometric reward regions
- **policy_update_regime**: sample counts, elite fractions, trajectory lengths, reward sparsity, convergence patterns
- **overlapping_plan_evaluation**: prefix overlap degree, batch sizes, exact results under performance pressure

---
name: cross-entropy-method
description: Implementation of cross-entropy method (CEM) for trajectory optimization in discrete-action point-mass environments with trie-based memoized plan evaluation
---

# Cross-Entropy Method for Point-Mass Trajectory Optimization

## Quick-Start Recipe

Implement three methods in `cross_entropy.py`:

### Step 1: `PointEnv.step(action)` → int
```python
movement = self.action_map[action]
new_pos = self.position + movement
half = self.length // 2
new_pos[0] = np.clip(new_pos[0], -half, half)   # independent per axis
new_pos[1] = np.clip(new_pos[1], -half, half)
self.position = new_pos
dist = np.linalg.norm(self.position - self.goal)
return 1 if dist <= self.goal_radius else 0      # inclusive boundary
```

### Step 2: `PointEnv.__init__` — add trie root
```python
self._trie_root = {"pos": np.array([0, 0], dtype=np.int_), "reward": 0, "children": {}}
```

### Step 3: `PointEnv.evaluate_plans_memoized(plans)` → Sequence[int]
Walk the trie per plan: follow child pointers for cache hits (O(1) each), simulate and create nodes for misses. Never touch `self.position`. Return `node["reward"]` at end of each plan.

### Step 4: `CrossEntropyMethod.optimize(num_samples, num_elites, iterations)`
Each iteration: sample plans (per-timestep `np.random.choice`), evaluate with memoized method, `np.argsort` for elite selection, `np.bincount(minlength=num_actions)` for frequency update. Sequential RNG consumption ensures split equivalence.

## Family Invariants

### Environment Dynamics
- **Independent axis clipping**: Each coordinate clipped separately to `[-length/2, +length/2]`. Clipping one axis must NOT suppress motion on the other.
- **Inclusive Euclidean reward**: Return 1 when `dist(position, goal) ≤ goal_radius`, else 0.
- **Integer positions**: State is `np.int_` array; actions index into `action_map`.
- **Origin start**: All plans evaluate from `(0, 0)`.
- **Use `self.action_map`**: Never hardcode movement vectors — variants may have different action sets.

### Memoized Plan Evaluation
- **Prefix sharing**: Cache reuses shared prefixes, not just whole repeated plans.
- **Persistence**: Cache survives across multiple `evaluate_plans_memoized` calls.
- **Position invariance**: Batch evaluation must NOT modify `self.position`.
- **Cumulative reward**: Each plan earns sum of per-step rewards from origin.

### CEM Policy Update
- **Independent timestep sampling**: Each timestep samples from its own categorical distribution.
- **Elite selection**: Top `num_elites` by cumulative reward via `np.argsort`.
- **Frequency update**: Replace each timestep's distribution with elite action frequencies.
- **Iteration-local RNG**: `optimize(N) + optimize(N)` under same seed = `optimize(2N)`. Requires sequential RNG consumption — no resetting or per-iteration isolation.

## Trie-Based Memoization (Recommended)

**Why trie over flat dict:** Flat dict uses `tuple(plan[:t+1])` as key → O(t) to create + O(t) to hash per step → O(H²) total. Trie uses integer key lookup → O(1) per step → O(H) total. Measured 1.7x faster at H=10, 2.7x at H=100.

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    results = []
    for plan in plans:
        node = self._trie_root
        for t in range(len(plan)):
            a = int(plan[t])
            if a in node["children"]:
                node = node["children"][a]          # O(1) cache hit
            else:
                movement = self.action_map[a]
                new_pos = node["pos"] + movement
                half = self.length // 2
                new_pos = np.array([
                    np.clip(new_pos[0], -half, half),
                    np.clip(new_pos[1], -half, half)
                ], dtype=np.int_)
                dist = np.linalg.norm(new_pos - self.goal)
                step_reward = 1 if dist <= self.goal_radius else 0
                child = {
                    "pos": new_pos,
                    "reward": node["reward"] + step_reward,
                    "children": {}
                }
                node["children"][a] = child
                node = child                        # advance pointer
        results.append(node["reward"])
    return results
```

**Key properties:**
- `new_pos` is a fresh array from `np.array([...])` — no copy needed
- Prefix monotonicity: once a prefix hits, all longer prefixes hit too
- Shared prefixes stored once as trie nodes, not duplicated

## CEM Optimization

```python
def optimize(self, num_samples, num_elites, iterations):
    for _ in range(iterations):
        plans = np.zeros((num_samples, self.horizon), dtype=int)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(self.num_actions, size=num_samples, p=self.probs[t])
        
        rewards = np.array(self.env.evaluate_plans_memoized(plans))
        elite_indices = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_indices]
        
        for t in range(self.horizon):
            action_counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
            self.probs[t] = action_counts / num_elites
```

**Why this works for split equivalence:**
- `np.random.choice` consumes RNG sequentially per timestep
- Iteration 1 consumes RNG for all timesteps, then iteration 2, etc.
- Two calls of 10 iterations consume the same RNG sequence as one call of 20

## Local Verification

**Run these tests locally before submitting:**

```python
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# Test 1: Independent axis clipping
env = PointEnv(length=6)
env.position = np.array([3, 0], dtype=np.int_)
env.step(2)  # [1,1] -> x clipped to 3, y should move to 1
assert np.array_equal(env.position, [3, 1]), "Axis clipping failed"

# Test 2: Inclusive boundary
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)
env.position = np.array([2, 2], dtype=np.int_)
assert env.step(1) == 1, "Perimeter reward failed"  # dist=1, should get reward

# Test 3: Memoization correctness
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)
plans = np.array([[2, 2, 0, 0, 0], [2, 2, 2, 0, 0], [0, 0, 0, 0, 0]])
rewards = env.evaluate_plans_memoized(plans)
assert list(rewards) == [4, 1, 0], f"Expected [4,1,0], got {list(rewards)}"

# Test 4: Position invariance
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)
env.reset()
pos_before = env.position.copy()
_ = env.evaluate_plans_memoized(np.array([[2, 2, 2]]))
assert np.array_equal(env.position, pos_before), "Position changed"

# Test 5: RNG split equivalence
for seed in [0, 42, 123]:
    np.random.seed(seed)
    env_a = PointEnv()
    cem_a = CrossEntropyMethod(env_a, horizon=5)
    cem_a.optimize(50, 10, 20)
    
    np.random.seed(seed)
    env_b = PointEnv()
    cem_b = CrossEntropyMethod(env_b, horizon=5)
    cem_b.optimize(50, 10, 10)
    cem_b.optimize(50, 10, 10)
    
    assert np.allclose(cem_a.probs, cem_b.probs), f"RNG split failed for seed {seed}"

# Test 6: CEM convergence
np.random.seed(42)
env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=1)
cem = CrossEntropyMethod(env, horizon=3)
cem.optimize(200, 20, 10)
assert np.argmax(cem.probs[0]) == 2, "CEM didn't learn diagonal action"
assert np.argmax(cem.probs[1]) == 2, "CEM didn't learn diagonal action"

print("✓ All local verification tests passed")
```

## Common Pitfalls

| Pitfall | Wrong | Correct |
|---------|-------|---------|
| Joint clipping | `if x>h or y>h: clip both` | Clip each axis independently |
| Cache mutation | `cache[key] = (pos, reward)` where pos is reused | Fresh array per node (trie) or `.copy()` (flat dict) |
| Position side effects | Using `self.step()` in evaluation | Simulate internally from trie node positions |
| Missing actions | `np.unique` without `minlength` | `np.bincount(minlength=self.num_actions)` |
| Non-inclusive boundary | `dist < radius` | `dist <= radius` |

## Debugging Guide

**If tests fail, check these in order:**

1. **Boundary clipping fails**: Verify you're clipping each axis independently, not jointly
2. **Perimeter reward fails**: Check you're using `<=` not `<` for distance comparison
3. **Memoization incorrect**: Verify you're not modifying `self.position` during evaluation
4. **RNG split fails**: Ensure you're not resetting RNG state between iterations
5. **CEM doesn't converge**: Check you're using `np.argsort` (not `argpartition`) for elite selection

## Variation Dimensions

### Environment Dynamics (varies)
- Map size (`length`), goal placement, goal radius
- Action set (different movement vectors, still 9 discrete actions)
- Boundary behavior (always independent clipping, bounds change with `length`)

### Policy Update Regime (varies)
- Sample count, elite fraction, horizon length
- Reward sparsity, convergence patterns
- Repeated calls to `optimize` (must maintain RNG continuity)

### Overlapping Plan Evaluation (varies)
- Prefix overlap degree, duplicate plans, batch size
- Cache hit rate depends on plan diversity and horizon

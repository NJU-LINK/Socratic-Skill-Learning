---
name: cross-entropy-method
description: >
  Implements a point-mass grid environment with goal-circle reward, a trie-memoized
  batch plan evaluator with prefix sharing, and the cross-entropy method (CEM) for
  iterative policy optimization over discrete action sequences.
---

# Cross-Entropy Method on a Point-Mass Grid

## Quick Orientation

You must implement three methods in a starter file (`cross_entropy.py`):

| Method | Purpose | Core trick |
|---|---|---|
| `PointEnv.step(action)` | One env step: move, clip, reward | Independent per-axis clipping |
| `PointEnv.evaluate_plans_memoized(plans)` | Batch plan eval with caching | Trie prefix cache, inline sim |
| `CrossEntropyMethod.optimize(...)` | Iterative CEM policy search | Iteration-local RNG discipline |

**Workflow:** Read the starter code → implement all three methods → `pip install -e .` → run the diagnostic command in §Self-Verification → `pytest`.

The starter code provides: a 9-action integer movement table (`action_map`), constructor
fields (`length`, `goal`, `goal_radius`, `position`), a `reset()` method, and a
`CrossEntropyMethod` class with a uniform `self.probs` matrix of shape `(horizon, num_actions)`.

**Note:** `variant.py` contains only default config constants. You do not need to read it; all needed values are on `self`.

---

## Axis 1 — Environment Dynamics (`step`)

### Decision Rules

| Concern | Rule |
|---|---|
| **Position update** | `new_pos = self.position + self.action_map[action]` — this creates a **new** array (critical: never use `+=` which mutates in place and corrupts trie state) |
| **Clipping** | Clip each axis **independently** to `[-length//2, +length//2]` inclusive. Clipping one axis must **not** suppress motion on the other axis. |
| **Reward** | `1` if Euclidean distance from clipped position to `self.goal` is `<= goal_radius`, else `0`. Use squared comparison `(dx² + dy²) <= r²` to avoid sqrt. |
| **State mutation** | `self.position = new_pos` (assignment, not in-place mutation). Return the integer reward. |

### Implementation Pattern

```python
def step(self, action: int) -> int:
    delta = self.action_map[action]
    new_pos = self.position + delta       # new array — does NOT mutate self.position
    half = self.length // 2
    # Independent per-axis clipping — critical: do NOT early-return or skip axes
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    self.position = new_pos               # assign new array to self.position
    dx = self.position[0] - self.goal[0]
    dy = self.position[1] - self.goal[1]
    return 1 if (dx * dx + dy * dy) <= self.goal_radius ** 2 else 0
```

### Verification Checklist

- [ ] At boundary `(half, 0)`, action `[1, 1]` → position becomes `(half, 1)`, not `(half, 0)`. The y-axis still moves.
- [ ] Action `0` (zero vector `[0, 0]`) from any position leaves position unchanged.
- [ ] `goal_radius` may be float; position is integer. Squared comparison handles mixed types.
- [ ] `length` is always even (asserted in constructor), so `length // 2` is exact.
- [ ] `self.position + delta` creates a new array; `self.position += delta` would mutate in place — **never use `+=`**.

---

## Axis 2 — Overlapping Plan Evaluation (`evaluate_plans_memoized`)

### Decision Rules

| Concern | Rule |
|---|---|
| **Starting state** | Every plan starts from origin `(0, 0)`, **not** from `self.position`. |
| **Side effects** | Must **not** leave `self.position` changed after the call. |
| **Memoization scope** | Persists **across calls** (stored on `self`). Must cache **prefixes** (sub-plans), not just whole plans. |
| **Return** | Sequence of N cumulative integer rewards (one per plan). Empty input → empty list. |

### Trie-Based Prefix Caching

Use a nested-dict trie rooted at `self._trie_root`. Each node stores:
- `_reward`: cumulative reward from origin through this prefix
- `_pos`: `(x, y)` tuple — the position after executing this prefix

For each plan, walk the trie action by action. When a child is missing, simulate one step
from the parent's cached position (inline, **not** via `self.step` to avoid mutating
`self.position`). Create the child node with updated cumulative reward and position.

```python
def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
    if not hasattr(self, '_trie_root'):
        self._trie_root = {'_reward': 0, '_pos': (0, 0)}

    results = []
    half = self.length // 2
    gx, gy = float(self.goal[0]), float(self.goal[1])
    r_sq = self.goal_radius ** 2

    for plan in plans:
        node = self._trie_root
        for action_val in plan:
            a = int(action_val)
            if a not in node:
                px, py = node['_pos']
                dx, dy = self.action_map[a]
                nx = max(-half, min(half, px + dx))
                ny = max(-half, min(half, py + dy))
                step_r = 1 if ((nx - gx) ** 2 + (ny - gy) ** 2) <= r_sq else 0
                node[a] = {'_reward': node['_reward'] + step_r, '_pos': (nx, ny)}
            node = node[a]
        results.append(node['_reward'])
    return results
```

### Why Inline Instead of Calling `step()`

Calling `self.step()` would mutate `self.position`. Saving and restoring around each call
works but is fragile and slower. Inlining the one-step logic keeps the trie self-contained
and guarantees no side effects on the environment's public state.

### Why Convert Goal to Float Up Front

Extracting `gx, gy = float(self.goal[0]), float(self.goal[1])` before the loop avoids
repeated numpy scalar extraction. Combined with integer positions, the squared arithmetic
stays exact (small integer × small integer fits in float64 without rounding).

### Verification Checklist

- [ ] Two calls with identical plans return identical results (memo is deterministic).
- [ ] After evaluation, `self.position` equals its value before the call.
- [ ] Plans sharing a long common prefix only simulate the diverging suffix.
- [ ] Plans from different calls that share prefixes reuse cached nodes.
- [ ] Empty plans array `np.empty((0, H), dtype=int)` → returns `[]`.
- [ ] Return type is a sequence (list) of Python ints, length = `plans.shape[0]`.

---

## Axis 3 — Policy Update Regime (`optimize`)

### Decision Rules

| Concern | Rule |
|---|---|
| **Sampling** | At each timestep `t`, draw `num_samples` actions from `Categorical(self.probs[t])`. Use `np.random.choice`. |
| **Evaluation** | Pass all sampled plans to `self.env.evaluate_plans_memoized(plans)`. |
| **Elite selection** | Sort by reward descending; take top `num_elites` indices. On ties, any deterministic tie-breaking (e.g., `argsort` stable order) is fine. |
| **Distribution update** | `self.probs[t, a] = count(action a among elites at timestep t) / num_elites`. |
| **RNG discipline** | Each iteration consumes exactly `horizon` calls to `np.random.choice`, each drawing `num_samples` values. No extra RNG. This guarantees that two calls of `k` iterations equal one call of `2k` iterations under the same seed. |
| **State** | `self.probs` is updated in place. No return value. |

### Implementation Pattern

```python
def optimize(self, num_samples: int, num_elites: int, iterations: int) -> None:
    for _ in range(iterations):
        # 1. Sample plans — one np.random.choice per timestep, deterministic RNG consumption
        plans = np.empty((num_samples, self.horizon), dtype=int)
        for t in range(self.horizon):
            plans[:, t] = np.random.choice(
                self.num_actions, size=num_samples, p=self.probs[t]
            )

        # 2. Evaluate all plans
        rewards = np.array(self.env.evaluate_plans_memoized(plans))

        # 3. Select elites (top num_elites by reward)
        elite_indices = np.argsort(rewards)[-num_elites:]  # ascending sort, take last
        elite_plans = plans[elite_indices]

        # 4. Update distributions from elite frequencies
        for t in range(self.horizon):
            counts = np.bincount(elite_plans[:, t], minlength=self.num_actions)
            self.probs[t] = counts / num_elites
```

### Verification Checklist

- [ ] `optimize(100, 25, 10)` then `optimize(100, 25, 10)` equals single `optimize(100, 25, 20)` under same seed.
- [ ] `self.probs[t].sum() == 1.0` for all `t` after each iteration.
- [ ] `self.probs` shape remains `(horizon, self.num_actions)`.
- [ ] No extra `np.random` calls (no shuffling, no tie-breaking randomness, no `np.random.seed()` inside the method).
- [ ] With default parameters, greedy argmax plan achieves near-optimal reward.

---

## Self-Verification (Diagnostic Command)

After implementing all three methods, run this comprehensive check before `pytest`:

```bash
cd /app && pip install -e . && python3 -c "
import numpy as np
from cross_entropy_method.cross_entropy import PointEnv, CrossEntropyMethod

# 1. step: boundary clipping preserves other axis
env = PointEnv()
env.position = np.array([3, 0], dtype=np.int_)
env.step(2)  # [1,1] at x-boundary
assert list(env.position) == [3, 1], f'Clip failed: {env.position}'

# 2. step: goal perimeter included
env.reset()
env.step(2); r = env.step(2)  # (2,2), dist=0
assert r == 1

# 3. memoized: prefix sharing and position safety
env2 = PointEnv()
r1 = env2.evaluate_plans_memoized(np.array([[2, 2, 3], [2, 2, 4]]))
r2 = env2.evaluate_plans_memoized(np.array([[2, 2, 5]]))
assert env2.position[0] == 0 and env2.position[1] == 0, 'Position leaked'

# 4. memoized: empty plans
assert env2.evaluate_plans_memoized(np.empty((0, 3), dtype=int)) == []

# 5. optimize: RNG iteration-locality
np.random.seed(42)
e3 = PointEnv(); c3 = CrossEntropyMethod(e3, horizon=5)
c3.optimize(50, 10, 20); p20 = c3.probs.copy()
np.random.seed(42)
e4 = PointEnv(); c4 = CrossEntropyMethod(e4, horizon=5)
c4.optimize(50, 10, 10); c4.optimize(50, 10, 10)
assert np.allclose(p20, c4.probs), 'RNG locality broken'

# 6. optimize: convergence (greedy plan should achieve high reward)
np.random.seed(42)
e5 = PointEnv(); c5 = CrossEntropyMethod(e5, horizon=15)
c5.optimize(100, 25, 20)
best = np.array([[np.argmax(c5.probs[t]) for t in range(15)]])
assert e5.evaluate_plans_memoized(best)[0] >= 10, 'CEM did not converge'

print('All diagnostics passed')
"
```

If any assertion fails, the corresponding section (§Axis 1–3) has the fix.

---

## Generalization Across Variation Axes

### Environment Variations (map size, goal placement, action set)

- **Always read `self.length`, `self.goal`, `self.goal_radius` from the instance** — never hardcode the v01 defaults (6, 2, 2, 1).
- The action map may differ in other variants; always use `self.action_map[action]`.
- `self.num_actions = len(PointEnv.action_map)` automatically adapts to different action sets.
- Clipping bound is always `±(self.length // 2)`. The constructor asserts `length` is even.
- Different goal positions (including negative coordinates, near corners) work naturally — the squared-distance check is position-agnostic.

### Policy Update Variations (sample count, elite fraction, horizon)

- All parameters (`num_samples`, `num_elites`, `iterations`) are method arguments, not constants.
- `num_elites` could be 1 (single elite) or equal to `num_samples` (no selection pressure). The code handles both.
- `horizon` is set in `CrossEntropyMethod.__init__` and stored as `self.horizon`.
- With small `num_samples`, CEM may not converge. The implementation is still correct; convergence quality depends on parameter sufficiency.

### Plan Evaluation Variations (overlap degree, batch size)

- The trie naturally handles any overlap pattern — fully unique, fully identical, or partially shared prefixes.
- For fully unique plans, the trie degrades to plain simulation (no speedup, still correct).
- For fully identical plans, only the first plan simulates; the rest are O(H) dict lookups.
- Large batch sizes with high overlap yield the greatest speedup; the trie scales linearly with unique prefixes.

---

## Common Pitfalls

1. **Axis-coupled clipping**: Writing `if abs(new_x) <= half: ... else: clip x AND skip y`. Each axis clips independently; the other axis always updates.
2. **Mutating `self.position` in `evaluate_plans_memoized`**: Even temporarily. Use the trie's stored positions or save/restore.
3. **In-place array mutation**: Using `self.position += delta` instead of `new_pos = self.position + delta`. The `+=` operator mutates the underlying array, which corrupts trie positions that reference the same memory.
4. **Re-seeding RNG inside `optimize`**: Never call `np.random.seed()` inside the method. The caller controls the seed.
5. **Using `self.step()` inside `evaluate_plans_memoized`**: Works only if you save/restore `self.position` for every single step — error-prone. Prefer inlining.
6. **Whole-plan memoization only**: The spec requires prefix sharing. A dict keyed by full plan tuple misses all prefix overlap.
7. **Forgetting `int()` conversion**: `np.ndarray` elements may be `np.int64`; convert with `int()` before using as dict keys.
8. **Returning `None` from `evaluate_plans_memoized`**: The method must always return a list. An empty `plans` array should produce `[]`, not `None`.

---

## Installation & Testing

```bash
cd /app && pip install -e .
pytest
```

No additional packages beyond `numpy` are required.

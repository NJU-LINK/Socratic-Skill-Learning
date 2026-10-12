#!/usr/bin/env python3
"""
Self-contained reference for the three core algorithms.
Run with: python references/verify_reference.py

This script does NOT import from cross_entropy_method — it reimplements the key
logic in isolation so you can verify correctness against the task spec before
touching the starter code.
"""
import numpy as np
from collections.abc import Sequence


# ── Reference action map (9 integer movement vectors) ──────────────────────
ACTION_MAP = np.array(
    [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
    dtype=np.int_,
)


# ── 1. Reference step() ────────────────────────────────────────────────────
def ref_step(
    position: np.ndarray,
    action: int,
    length: int,
    goal: np.ndarray,
    goal_radius: float,
) -> tuple[np.ndarray, int]:
    """Return (new_position, reward) without mutating inputs."""
    delta = ACTION_MAP[action]
    new_pos = position + delta
    half = length // 2
    new_pos = new_pos.copy()
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    dx = new_pos[0] - goal[0]
    dy = new_pos[1] - goal[1]
    reward = 1 if (dx * dx + dy * dy) <= goal_radius ** 2 else 0
    return new_pos, reward


# ── 2. Reference trie-based evaluate_plans_memoized ────────────────────────
class RefMemoizedEvaluator:
    """Standalone trie evaluator for testing."""

    def __init__(self, length: int, goal: np.ndarray, goal_radius: float):
        self.length = length
        self.goal = goal
        self.goal_radius = goal_radius
        self._root = {"_reward": 0, "_pos": (0, 0)}

    def evaluate(self, plans: np.ndarray) -> list[int]:
        half = self.length // 2
        results = []
        for plan in plans:
            node = self._root
            for action_val in plan:
                a = int(action_val)
                if a not in node:
                    px, py = node["_pos"]
                    dx, dy = ACTION_MAP[a]
                    nx = max(-half, min(half, px + dx))
                    ny = max(-half, min(half, py + dy))
                    gx, gy = self.goal[0], self.goal[1]
                    step_r = (
                        1 if ((nx - gx) ** 2 + (ny - gy) ** 2) <= self.goal_radius ** 2 else 0
                    )
                    node[a] = {"_reward": node["_reward"] + step_r, "_pos": (nx, ny)}
                node = node[a]
            results.append(node["_reward"])
        return results


# ── 3. Reference CEM optimize loop ─────────────────────────────────────────
def ref_optimize(
    probs: np.ndarray,
    evaluator: RefMemoizedEvaluator,
    num_samples: int,
    num_elites: int,
    iterations: int,
    num_actions: int,
    horizon: int,
) -> np.ndarray:
    """Return updated probs (does not mutate input)."""
    probs = probs.copy()
    for _ in range(iterations):
        plans = np.empty((num_samples, horizon), dtype=int)
        for t in range(horizon):
            plans[:, t] = np.random.choice(num_actions, size=num_samples, p=probs[t])
        rewards = np.array(evaluator.evaluate(plans))
        elite_idx = np.argsort(rewards)[-num_elites:]
        elite_plans = plans[elite_idx]
        for t in range(horizon):
            counts = np.bincount(elite_plans[:, t], minlength=num_actions)
            probs[t] = counts / num_elites
    return probs


# ── Self-tests ─────────────────────────────────────────────────────────────
def run_tests():
    length = 6
    goal = np.array([2.0, 2.0])
    goal_radius = 1.0
    half = length // 2

    # --- step tests ---
    # From origin, action 2 [1,1] → (1,1), dist²=2 > 1 → reward 0
    pos = np.array([0, 0], dtype=np.int_)
    new_pos, r = ref_step(pos, 2, length, goal, goal_radius)
    assert list(new_pos) == [1, 1] and r == 0, f"step test 1 failed: {new_pos}, {r}"

    # From (1,1), action 2 → (2,2), dist²=0 ≤ 1 → reward 1
    new_pos2, r2 = ref_step(new_pos, 2, length, goal, goal_radius)
    assert list(new_pos2) == [2, 2] and r2 == 1, f"step test 2 failed: {new_pos2}, {r2}"

    # Boundary: at (3,0), action 2 [1,1] → x clips to 3, y becomes 1
    pos_b = np.array([3, 0], dtype=np.int_)
    new_b, rb = ref_step(pos_b, 2, length, goal, goal_radius)
    assert list(new_b) == [3, 1], f"boundary clip failed: {new_b}"

    # Boundary: at (3,3), action 2 [1,1] → both clip to (3,3)
    pos_c = np.array([3, 3], dtype=np.int_)
    new_c, rc = ref_step(pos_c, 2, length, goal, goal_radius)
    assert list(new_c) == [3, 3], f"double clip failed: {new_c}"

    # Action 0 [0,0] → no movement
    pos_d = np.array([1, 2], dtype=np.int_)
    new_d, rd = ref_step(pos_d, 0, length, goal, goal_radius)
    assert list(new_d) == [1, 2], f"stay action failed: {new_d}"

    print("✓ step tests passed")

    # --- memoized evaluation tests ---
    ev = RefMemoizedEvaluator(length, goal, goal_radius)

    # Plan: [2, 2] → (0,0)→(1,1)→(2,2), rewards: 0+1=1
    plans = np.array([[2, 2]], dtype=int)
    res = ev.evaluate(plans)
    assert res == [1], f"memo test 1 failed: {res}"

    # Same plan again → same result from cache
    res2 = ev.evaluate(plans)
    assert res2 == [1], f"memo test 2 failed: {res2}"

    # Plan with stay action: [0, 2, 2] → (0,0)→(0,0)→(1,1)→(2,2), rewards: 0+0+1=1
    plans3 = np.array([[0, 2, 2]], dtype=int)
    res3 = ev.evaluate(plans3)
    assert res3 == [1], f"memo test 3 failed: {res3}"

    # Verify prefix sharing: the prefix (2,) should already be cached
    # from the first evaluation of [2,2]. Plan [2, 1] should reuse node for (2,)
    plans4 = np.array([[2, 1]], dtype=int)
    res4 = ev.evaluate(plans4)
    # (0,0)→(1,1)[r=0]→(2,1)[dist²=1 ≤ 1 → r=1], total=1
    assert res4 == [1], f"memo test 4 failed: {res4}"

    print("✓ memoized evaluation tests passed")

    # --- CEM iteration-local RNG test ---
    np.random.seed(42)
    ev_a = RefMemoizedEvaluator(length, goal, goal_radius)
    probs_init = np.ones((5, 9)) / 9
    probs_10a = ref_optimize(probs_init, ev_a, 50, 10, 10, 9, 5)

    np.random.seed(42)
    ev_b = RefMemoizedEvaluator(length, goal, goal_radius)
    probs_10b = ref_optimize(probs_init, ev_b, 50, 10, 10, 9, 5)

    # Continue for 10 more
    probs_20 = ref_optimize(probs_10b, ev_b, 50, 10, 10, 9, 5)

    # Single 20-iteration call
    np.random.seed(42)
    ev_c = RefMemoizedEvaluator(length, goal, goal_radius)
    probs_20_single = ref_optimize(probs_init, ev_c, 50, 10, 20, 9, 5)

    assert np.allclose(probs_20, probs_20_single), "RNG iteration-locality failed"
    assert np.allclose(probs_10a, probs_10b), "Determinism failed"
    print("✓ CEM RNG iteration-locality test passed")

    print("\nAll reference tests passed ✓")


if __name__ == "__main__":
    run_tests()

#!/usr/bin/env python3
"""
Standalone gold-standard for the three core algorithms.
Run with: python skill/cross-entropy-method/references/verify_reference.py

This script does NOT import from cross_entropy_method — it reimplements the key
logic in isolation. Use it to verify your understanding of the spec BEFORE
writing code in the starter file, or to cross-check your implementation's output.
"""
import numpy as np

ACTION_MAP = np.array(
    [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
    dtype=np.int_,
)


def ref_step(position, action, length, goal, goal_radius):
    """Return (new_position, reward). Pure function — no mutation."""
    delta = ACTION_MAP[action]
    new_pos = position + delta  # new array, not in-place
    half = length // 2
    new_pos = new_pos.copy()
    new_pos[0] = np.clip(new_pos[0], -half, half)
    new_pos[1] = np.clip(new_pos[1], -half, half)
    dx = new_pos[0] - goal[0]
    dy = new_pos[1] - goal[1]
    reward = 1 if (dx * dx + dy * dy) <= goal_radius ** 2 else 0
    return new_pos, reward


class RefTrieEvaluator:
    """Standalone trie evaluator — mirrors evaluate_plans_memoized."""

    def __init__(self, length, goal, goal_radius):
        self.length = length
        self.goal = goal
        self.goal_radius = goal_radius
        self._root = {"_reward": 0, "_pos": (0, 0)}

    def evaluate(self, plans):
        half = self.length // 2
        gx, gy = float(self.goal[0]), float(self.goal[1])
        r_sq = self.goal_radius ** 2
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
                    step_r = 1 if ((nx - gx) ** 2 + (ny - gy) ** 2) <= r_sq else 0
                    node[a] = {"_reward": node["_reward"] + step_r, "_pos": (nx, ny)}
                node = node[a]
            results.append(node["_reward"])
        return results


def run_tests():
    length, goal, goal_radius = 6, np.array([2.0, 2.0]), 1.0
    half = length // 2

    # --- step ---
    pos = np.array([0, 0], dtype=np.int_)
    new_pos, r = ref_step(pos, 2, length, goal, goal_radius)
    assert list(new_pos) == [1, 1] and r == 0

    new_pos2, r2 = ref_step(new_pos, 2, length, goal, goal_radius)
    assert list(new_pos2) == [2, 2] and r2 == 1

    # Boundary: x clips but y still moves
    pos_b = np.array([half, 0], dtype=np.int_)
    new_b, _ = ref_step(pos_b, 2, length, goal, goal_radius)
    assert list(new_b) == [half, 1], f"Boundary clip failed: {new_b}"

    # Goal perimeter: exactly at distance = radius
    pos_p = np.array([3, 2], dtype=np.int_)
    _, rp = ref_step(pos_p, 0, length, goal, goal_radius)
    assert rp == 1, "Perimeter should be included (<=)"

    # Negative boundary
    pos_n = np.array([-half, -half], dtype=np.int_)
    new_n, _ = ref_step(pos_n, 6, length, goal, goal_radius)
    assert list(new_n) == [-half, -half], f"Neg clip: {new_n}"

    print("✓ step tests passed")

    # --- trie evaluation ---
    ev = RefTrieEvaluator(length, goal, goal_radius)

    # Prefix sharing within a batch
    plans = np.array([[2, 2, 3], [2, 2, 4]])
    res = ev.evaluate(plans)
    assert res == [2, 1], f"Prefix test: {res}"

    # Cross-call prefix reuse
    res2 = ev.evaluate(np.array([[2, 2, 5]]))
    assert res2 == [2], f"Cross-call: {res2}"

    # Empty plans
    assert ev.evaluate(np.empty((0, 3), dtype=int)) == []

    print("✓ trie evaluation tests passed")

    # --- CEM RNG locality ---
    probs_init = np.ones((5, 9)) / 9

    np.random.seed(42)
    ev_a = RefTrieEvaluator(length, goal, goal_radius)
    probs_20 = _run_cem(probs_init, ev_a, 50, 10, 20)

    np.random.seed(42)
    ev_b = RefTrieEvaluator(length, goal, goal_radius)
    probs_10 = _run_cem(probs_init, ev_b, 50, 10, 10)
    probs_10_10 = _run_cem(probs_10, ev_b, 50, 10, 10)

    assert np.allclose(probs_20, probs_10_10), "RNG iteration-locality failed"

    # Probs validity
    assert np.allclose(probs_20.sum(axis=1), 1.0), "Probs don't sum to 1"

    print("✓ CEM RNG iteration-locality test passed")
    print("\nAll reference tests passed ✓")


def _run_cem(probs, evaluator, num_samples, num_elites, iterations):
    probs = probs.copy()
    num_actions, horizon = probs.shape[1], probs.shape[0]
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


if __name__ == "__main__":
    run_tests()

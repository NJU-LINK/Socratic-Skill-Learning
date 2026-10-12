"""
Reference implementation for Cross-Entropy Method with prefix-trie memoization.

This file demonstrates the three core methods:
1. PointEnv.step() - independent axis clipping + inclusive goal check
2. PointEnv.evaluate_plans_memoized() - prefix-trie caching with position restore
3. CrossEntropyMethod.optimize() - iteration-local RNG sampling
"""
from __future__ import annotations
from collections.abc import Sequence
import numpy as np


class PointEnv:
    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(self, length=6, goal_x=2, goal_y=2, goal_radius=1):
        self.length = length
        self.goal = np.array((goal_x, goal_y))
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)
        
        # CRITICAL: Initialize memo dict as instance variable
        # Each environment instance has its own memo
        # Maps tuple-of-actions -> (cumulative_reward, position_copy)
        self._memo: dict[tuple[int, ...], tuple[int, np.ndarray]] = {}

    def reset(self):
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        """
        Apply action, clip each axis independently, return reward.
        
        KEY: np.clip on each axis SEPARATELY. Do NOT reject the whole move
        if the new position is out of bounds.
        """
        delta = self.action_map[action]
        new_pos = self.position + delta
        half = self.length // 2
        new_pos[0] = np.clip(new_pos[0], -half, half)
        new_pos[1] = np.clip(new_pos[1], -half, half)
        self.position = new_pos
        dist = np.linalg.norm(self.position.astype(float) - self.goal)
        return 1 if dist <= self.goal_radius else 0

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate plans from origin with prefix-trie memoization.
        
        CRITICAL INVARIANTS:
        1. All plans are evaluated from origin (0,0), regardless of self.position
        2. self.position is restored after all plans are evaluated
        3. Memo persists across calls AND across reset() calls
        4. Prefix caching: if (a,b) is cached, we don't re-simulate it for (a,b,c)
        
        The memo is keyed by action tuples and stores (cumulative_reward, position).
        When no prefix is cached, best_pos defaults to (0,0) — the origin.
        """
        results = np.zeros(len(plans), dtype=int)
        saved_pos = self.position.copy()

        for i in range(len(plans)):
            plan_tuple = tuple(int(a) for a in plans[i])

            # Find longest cached prefix
            best_prefix_len = 0
            best_cum_reward = 0
            best_pos = np.array((0, 0), dtype=np.int_)

            for length in range(1, len(plan_tuple) + 1):
                prefix = plan_tuple[:length]
                if prefix in self._memo:
                    best_prefix_len = length
                    best_cum_reward, best_pos = self._memo[prefix]
                else:
                    break

            # Restore to cached position and simulate suffix
            self.position = best_pos.copy()
            cum_reward = best_cum_reward

            for t in range(best_prefix_len, len(plan_tuple)):
                cum_reward += self.step(plan_tuple[t])
                prefix = plan_tuple[:t + 1]
                self._memo[prefix] = (cum_reward, self.position.copy())

            results[i] = cum_reward

        self.position = saved_pos
        return results


class CrossEntropyMethod:
    def __init__(self, env: PointEnv, horizon: int = 15):
        self.env = env
        # Use env's action_map length — adapts to different action sets
        self.num_actions = len(env.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

    def optimize(self, num_samples=100, num_elites=25, iterations=20):
        """
        CEM optimization loop.
        
        KEY: Sample one iteration at a time using np.random.choice.
        This ensures RNG consumption is iteration-local, so
        optimize(10) + optimize(10) == optimize(20) under same seed.
        """
        T = self.horizon
        n_actions = self.num_actions

        for it in range(iterations):
            # Sample plans: one timestep at a time
            plans = np.zeros((num_samples, T), dtype=int)
            for t in range(T):
                plans[:, t] = np.random.choice(
                    n_actions, size=num_samples, p=self.probs[t]
                )

            # Evaluate all plans
            rewards = self.env.evaluate_plans_memoized(plans)

            # Select elites
            elite_indices = np.argsort(rewards)[-num_elites:]

            # Update distributions from elite frequencies
            for t in range(T):
                elite_actions = plans[elite_indices, t]
                counts = np.bincount(elite_actions, minlength=n_actions)
                self.probs[t] = counts / num_elites

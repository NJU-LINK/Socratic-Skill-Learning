#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

target = Path("cross_entropy_method/cross_entropy.py")
target.write_text(
    '''from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """A point-mass environment with integer state updates and goal rewards."""

    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = 20,
        goal_x: float = 3,
        goal_y: float = 8,
        goal_radius: float = 1,
    ):
        assert length > 0
        assert length % 2 == 0
        assert np.abs(goal_x) < length / 2
        assert np.abs(goal_y) < length / 2
        assert goal_radius > 0

        self.length = length
        self.action_map = np.array(self.action_map, dtype=np.int_)
        self.goal = np.array((goal_x, goal_y))
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)

    def reset(self) -> np.ndarray:
        """Return the agent to the center of the square."""
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        """Advance the environment by one action and return the resulting reward."""
        boundary = self.length // 2
        self.position = np.clip(self.position + self.action_map[action], -boundary, boundary)
        delta = self.position - self.goal
        return int(np.dot(delta, delta) <= self.goal_radius * self.goal_radius)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate many plans exactly while reusing repeated computation."""
        plans = np.asarray(plans, dtype=np.int_)
        if plans.ndim == 1:
            plans = plans.reshape(1, -1)

        boundary = self.length // 2
        radius_sq = self.goal_radius * self.goal_radius
        cache: dict[tuple[int, ...], tuple[tuple[int, int], int]] = {(): ((0, 0), 0)}
        rewards: list[int] = []

        for plan in plans:
            prefix: tuple[int, ...] = ()
            position = (0, 0)
            total_reward = 0

            for raw_action in plan:
                action = int(raw_action)
                prefix = (*prefix, action)
                cached = cache.get(prefix)
                if cached is not None:
                    position, total_reward = cached
                    continue

                next_position = np.clip(
                    np.array(position, dtype=np.int_) + self.action_map[action],
                    -boundary,
                    boundary,
                )
                position = (int(next_position[0]), int(next_position[1]))
                dx = position[0] - self.goal[0]
                dy = position[1] - self.goal[1]
                total_reward += int(dx * dx + dy * dy <= radius_sq)
                cache[prefix] = (position, total_reward)

            rewards.append(total_reward)

        return rewards


class CrossEntropyMethod:
    """Optimize action distributions for a fixed-horizon PointEnv plan."""

    def __init__(
        self,
        env: PointEnv,
        horizon: int = 15,
    ):
        self.env = env
        self.num_actions = len(env.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """Update `self.probs` with the cross-entropy method."""
        for _ in range(iterations):
            plans = np.empty((num_samples, self.horizon), dtype=np.int_)
            for step_idx in range(self.horizon):
                plans[:, step_idx] = np.random.choice(
                    self.num_actions,
                    size=num_samples,
                    p=self.probs[step_idx],
                )

            rewards = np.asarray(self.env.evaluate_plans_memoized(plans), dtype=np.float64)
            elite_indices = np.argsort(rewards, kind="stable")[-num_elites:]
            elites = plans[elite_indices]

            updated = np.zeros_like(self.probs)
            for step_idx in range(self.horizon):
                counts = np.bincount(elites[:, step_idx], minlength=self.num_actions)
                updated[step_idx] = counts / num_elites

            self.probs = updated
'''
)
PY

#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

Path("/app/cross_entropy_method/cross_entropy.py").write_text(
    '''from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """A point-mass environment with reward along an L-shaped corridor."""

    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = 24,
        goal_x: float = 6,
        goal_y: float = 6,
        goal_radius: float = 0.5,
    ):
        assert length > 0 and length % 2 == 0
        assert np.abs(goal_x) < length / 2
        assert np.abs(goal_y) < length / 2
        assert goal_radius > 0

        self.length = length
        self.goal = np.array((goal_x, goal_y), dtype=float)
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)
        self._corridor_x = np.arange(1, int(np.floor(goal_x)) + 1, dtype=np.int_)
        self._corridor_y = np.arange(1, int(np.floor(goal_y)) + 1, dtype=np.int_)
        self._plan_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {
            (): (np.array((0, 0), dtype=np.int_), 0)
        }

    def reset(self) -> np.ndarray:
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def _reward_for_position(self, position: np.ndarray) -> int:
        x, y = int(position[0]), int(position[1])
        in_horizontal = y == 0 and x in self._corridor_x
        in_vertical = x == int(self.goal[0]) and y in self._corridor_y
        in_goal = np.linalg.norm(position - self.goal) <= self.goal_radius
        return int(in_horizontal or in_vertical or in_goal)

    def step(self, action: int) -> int:
        action_index = int(action)
        if not 0 <= action_index < len(self.action_map):
            raise IndexError(f"invalid action index: {action}")
        half = self.length // 2
        self.position = np.clip(
            self.position + self.action_map[action_index], -half, half
        ).astype(np.int_)
        return self._reward_for_position(self.position)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        plan_array = np.asarray(plans, dtype=np.int_)
        if plan_array.ndim != 2:
            raise ValueError("plans must have shape (N, H)")

        half = self.length // 2
        rewards: list[int] = []
        for plan in plan_array:
            actions = tuple(int(action) for action in plan)
            cached = self._plan_cache.get(actions)
            if cached is not None:
                rewards.append(cached[1])
                continue

            prefix = actions
            while prefix not in self._plan_cache:
                prefix = prefix[:-1]

            position, total = self._plan_cache[prefix]
            position = position.copy()
            built = list(prefix)
            for action in actions[len(prefix):]:
                position = np.clip(
                    position + self.action_map[action], -half, half
                ).astype(np.int_)
                total += self._reward_for_position(position)
                built.append(action)
                self._plan_cache[tuple(built)] = (position.copy(), total)
            rewards.append(total)
        return rewards


class CrossEntropyMethod:
    def __init__(self, env: PointEnv, horizon: int = 15):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones((horizon, self.num_actions), dtype=float) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        if num_samples <= 0:
            raise ValueError("num_samples must be positive")
        if not 0 < num_elites <= num_samples:
            raise ValueError("num_elites must be in [1, num_samples]")
        if iterations < 0:
            raise ValueError("iterations must be non-negative")

        for _ in range(iterations):
            plans = np.empty((num_samples, self.horizon), dtype=np.int_)
            for timestep in range(self.horizon):
                plans[:, timestep] = np.random.choice(
                    self.num_actions,
                    size=num_samples,
                    p=self.probs[timestep],
                )

            rewards = np.asarray(self.env.evaluate_plans_memoized(plans), dtype=float)
            elite_indices = np.argsort(rewards, kind="stable")[-num_elites:]
            elites = plans[elite_indices]
            updated = np.zeros_like(self.probs)
            for timestep in range(self.horizon):
                updated[timestep] = (
                    np.bincount(elites[:, timestep], minlength=self.num_actions)
                    / num_elites
                )
            self.probs = updated
''',
    encoding="utf-8",
)
PY

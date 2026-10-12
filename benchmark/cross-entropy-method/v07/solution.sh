#!/bin/bash
set -euo pipefail

PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

relative_path = Path('cross_entropy_method/cross_entropy.py')
candidates = [Path('/app') / relative_path, Path.cwd() / relative_path]
for path in candidates:
    if path.exists():
        break
else:
    raise FileNotFoundError('Could not locate cross_entropy_method/cross_entropy.py')

path.write_text(
    '''from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """A bounded point-mass environment with sparse rewards near a corner."""

    action_map = np.array(
        [
            [1, 0],
            [1, 1],
            [0, 1],
            [-1, 1],
            [-1, 0],
            [-1, -1],
            [0, -1],
            [1, -1],
        ],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = 24,
        goal_x: float = 10,
        goal_y: float = 9,
        goal_radius: float = 1.0,
    ):
        assert length > 0
        assert length % 2 == 0
        assert np.abs(goal_x) <= length / 2
        assert np.abs(goal_y) <= length / 2
        assert goal_radius > 0

        self.length = length
        self.goal = np.array((goal_x, goal_y), dtype=float)
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)

    def reset(self) -> np.ndarray:
        """Return the agent to the origin."""
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        """Advance one action and return the integer reward for the new position."""
        half_length = self.length // 2
        self.position = np.clip(
            self.position + self.action_map[int(action)],
            -half_length,
            half_length,
        )
        return int(np.sum((self.position - self.goal) ** 2) <= self.goal_radius**2)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate plans exactly while reusing overlapping prefixes."""
        plans = np.asarray(plans, dtype=np.int_)
        if plans.ndim != 2:
            raise ValueError('plans must be a 2D array')

        half_length = self.length // 2
        goal_radius_sq = self.goal_radius**2
        origin = np.array((0, 0), dtype=np.int_)
        original_position = self.position.copy()
        rewards: list[int] = []

        root = {
            'children': {},
            'position': origin.copy(),
            'reward': 0,
        }

        try:
            for plan in plans:
                node = root
                index = 0
                horizon = len(plan)

                while index < horizon:
                    child = node['children'].get(int(plan[index]))
                    if child is None:
                        break
                    node = child
                    index += 1

                position = node['position'].copy()
                total_reward = node['reward']

                while index < horizon:
                    action = int(plan[index])
                    position = np.clip(
                        position + self.action_map[action],
                        -half_length,
                        half_length,
                    )
                    total_reward += int(
                        np.sum((position - self.goal) ** 2) <= goal_radius_sq
                    )
                    child = {
                        'children': {},
                        'position': position.copy(),
                        'reward': total_reward,
                    }
                    node['children'][action] = child
                    node = child
                    index += 1

                rewards.append(total_reward)
        finally:
            self.position = original_position

        return rewards


class CrossEntropyMethod:
    """Cross-entropy optimizer over discrete action sequences."""

    def __init__(self, env: PointEnv, horizon: int = 20):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones((horizon, self.num_actions), dtype=float) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """Update `self.probs` by repeatedly fitting to elite sampled plans."""
        if num_samples <= 0:
            raise ValueError('num_samples must be positive')
        if num_elites <= 0:
            raise ValueError('num_elites must be positive')
        if num_elites > num_samples:
            raise ValueError('num_elites cannot exceed num_samples')
        if iterations < 0:
            raise ValueError('iterations cannot be negative')

        for _ in range(iterations):
            plans = np.stack(
                [
                    np.random.choice(self.num_actions, size=num_samples, p=row)
                    for row in self.probs
                ],
                axis=1,
            )
            rewards = np.asarray(self.env.evaluate_plans_memoized(plans), dtype=float)
            elite_start = num_samples - num_elites
            elite_indices = np.argpartition(rewards, elite_start)[elite_start:]
            elites = plans[elite_indices]

            for timestep in range(self.horizon):
                counts = np.bincount(elites[:, timestep], minlength=self.num_actions)
                self.probs[timestep] = counts / num_elites
'''
)
PY

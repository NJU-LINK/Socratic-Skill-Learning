#!/bin/bash
set -euo pipefail

cd /app

cat > cross_entropy_method/cross_entropy.py <<'PY'
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


DEFAULT_ENV_LENGTH = 6
DEFAULT_GOAL_X = 2
DEFAULT_GOAL_Y = 2
DEFAULT_GOAL_RADIUS = 1


class PointEnv:
    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = DEFAULT_ENV_LENGTH,
        goal_x: float = DEFAULT_GOAL_X,
        goal_y: float = DEFAULT_GOAL_Y,
        goal_radius: float = DEFAULT_GOAL_RADIUS,
    ):
        assert length > 0 and length % 2 == 0
        assert abs(goal_x) < length / 2 and abs(goal_y) < length / 2
        assert goal_radius > 0
        self.length = length
        self.goal = np.array((goal_x, goal_y))
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)
        self._plan_cache = {(): (self.position.copy(), 0)}

    def reset(self) -> np.ndarray:
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        half = self.length // 2
        self.position = np.clip(
            self.position + self.action_map[action],
            -half,
            half,
        ).astype(np.int_, copy=False)
        return int(np.linalg.norm(self.position - self.goal) <= self.goal_radius)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        rewards = []
        half = self.length // 2
        for raw_plan in plans:
            plan = tuple(int(action) for action in raw_plan)
            if plan in self._plan_cache:
                rewards.append(self._plan_cache[plan][1])
                continue

            prefix = plan
            while prefix not in self._plan_cache:
                prefix = prefix[:-1]
            position, reward = self._plan_cache[prefix]
            position = position.copy()
            built = list(prefix)
            for action in plan[len(prefix):]:
                position = np.clip(
                    position + self.action_map[action],
                    -half,
                    half,
                ).astype(np.int_, copy=False)
                reward += int(np.linalg.norm(position - self.goal) <= self.goal_radius)
                built.append(action)
                self._plan_cache[tuple(built)] = (position.copy(), reward)
            rewards.append(reward)

        self.reset()
        return rewards


class CrossEntropyMethod:
    def __init__(self, env: PointEnv, horizon: int = 15):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones((horizon, self.num_actions)) / self.num_actions

    def optimize(
        self,
        num_samples: int = 100,
        num_elites: int = 25,
        iterations: int = 20,
    ) -> None:
        for _ in range(iterations):
            samples = np.empty((num_samples, self.horizon), dtype=np.int_)
            for timestep in range(self.horizon):
                samples[:, timestep] = np.random.choice(
                    self.num_actions,
                    size=num_samples,
                    p=self.probs[timestep],
                )
            rewards = np.asarray(self.env.evaluate_plans_memoized(samples))
            elites = samples[np.argsort(rewards)[-num_elites:]]
            updated = np.zeros_like(self.probs)
            for timestep in range(self.horizon):
                updated[timestep] = (
                    np.bincount(elites[:, timestep], minlength=self.num_actions)
                    / num_elites
                )
            self.probs = updated
PY

python3 -m pip install --break-system-packages -e .

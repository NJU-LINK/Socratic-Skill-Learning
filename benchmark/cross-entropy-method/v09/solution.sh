#!/bin/bash
set -euo pipefail

cat <<'PY' > cross_entropy_method/cross_entropy.py
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """
    A point-mass environment in which an agent gets reward for reaching a goal circle.

    :param length: Side length of the square env
    :param goal_x: X-coordinate of the goal circle
    :param goal_y: Y-coordinate of the goal circle
    :param goal_radius: Radius of the goal circle
    :param start_x: X-coordinate of the starting position
    :param start_y: Y-coordinate of the starting position
    """

    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = 30,
        goal_x: float = 13,
        goal_y: float = -14,
        goal_radius: float = 2,
        start_x: int = -6,
        start_y: int = 4,
    ):
        assert length > 0
        assert length % 2 == 0
        half_length = length / 2
        assert np.abs(goal_x) < half_length
        assert np.abs(goal_y) < half_length
        assert np.abs(start_x) <= half_length
        assert np.abs(start_y) <= half_length
        assert goal_radius > 0

        self.length = length
        self.goal = np.array((goal_x, goal_y), dtype=np.float64)
        self.goal_radius = goal_radius
        self.start = np.array((start_x, start_y), dtype=np.int_)
        self._min_coord = int(-half_length)
        self._max_coord = int(half_length)

        self.position = self.start.copy()

    def reset(self) -> np.ndarray:
        """Reset the environment by returning the agent to the configured start."""
        self.position = self.start.copy()
        return self.position.copy()

    def step(self, action: int) -> int:
        """Simulate one environment step and return the immediate reward."""
        move = PointEnv.action_map[int(action)]
        self.position = np.clip(self.position + move, self._min_coord, self._max_coord)
        delta = self.position.astype(np.float64) - self.goal
        return int(delta.dot(delta) <= self.goal_radius * self.goal_radius)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate plans exactly using memoization to improve repeated-plan workloads."""
        plans = np.asarray(plans, dtype=np.int_)
        if plans.ndim != 2:
            raise ValueError("plans must be a 2D array")

        root = [int(self.start[0]), int(self.start[1]), 0, {}]
        goal_x = float(self.goal[0])
        goal_y = float(self.goal[1])
        goal_radius_sq = self.goal_radius * self.goal_radius
        min_coord = self._min_coord
        max_coord = self._max_coord
        rewards = np.empty(plans.shape[0], dtype=np.int_)

        for idx, plan in enumerate(plans):
            node = root
            for raw_action in plan:
                action = int(raw_action)
                children = node[3]
                child = children.get(action)
                if child is None:
                    move = PointEnv.action_map[action]
                    x = node[0] + int(move[0])
                    y = node[1] + int(move[1])
                    if x < min_coord:
                        x = min_coord
                    elif x > max_coord:
                        x = max_coord
                    if y < min_coord:
                        y = min_coord
                    elif y > max_coord:
                        y = max_coord

                    dx = x - goal_x
                    dy = y - goal_y
                    reward = int(dx * dx + dy * dy <= goal_radius_sq)
                    child = [x, y, node[2] + reward, {}]
                    children[action] = child
                node = child
            rewards[idx] = node[2]

        return rewards


class CrossEntropyMethod:
    """Cross-entropy optimizer for finite-horizon plans in PointEnv."""

    def __init__(
        self,
        env: PointEnv,
        horizon: int = 25,
    ):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions), dtype=np.float64) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """Update the action distributions from elite sampled plans."""
        if num_samples <= 0:
            raise ValueError("num_samples must be positive")
        if num_elites <= 0 or num_elites > num_samples:
            raise ValueError("num_elites must be between 1 and num_samples")
        if iterations < 0:
            raise ValueError("iterations must be non-negative")

        actions = np.arange(self.num_actions, dtype=np.int_)

        for _ in range(iterations):
            plans = np.empty((num_samples, self.horizon), dtype=np.int_)
            for timestep in range(self.horizon):
                plans[:, timestep] = np.random.choice(actions, size=num_samples, p=self.probs[timestep])

            rewards = np.asarray(self.env.evaluate_plans_memoized(plans), dtype=np.float64)
            elite_indices = np.argsort(rewards, kind="stable")[-num_elites:]
            elites = plans[elite_indices]

            counts = np.zeros_like(self.probs)
            for timestep in range(self.horizon):
                counts[timestep] = np.bincount(elites[:, timestep], minlength=self.num_actions)

            self.probs = counts / num_elites
PY

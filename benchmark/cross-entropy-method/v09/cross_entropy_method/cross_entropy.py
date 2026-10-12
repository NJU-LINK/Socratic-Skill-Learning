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
        # TODO: Implement this function to pass tests.
        pass

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate plans exactly using memoization to improve repeated-plan workloads."""
        # TODO: Implement this function to pass tests.
        pass


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
        # TODO: Implement this function to pass tests.
        pass

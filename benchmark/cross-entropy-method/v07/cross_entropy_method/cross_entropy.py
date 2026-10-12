from __future__ import annotations

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
        # TODO: Implement this function to pass tests.
        raise NotImplementedError

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate plans exactly while reusing overlapping prefixes."""
        # TODO: Implement this function to pass tests.
        raise NotImplementedError


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
        # TODO: Implement this function to pass tests.
        raise NotImplementedError

from __future__ import annotations

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
        self.goal = np.array((goal_x, goal_y))
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)

    def reset(self) -> np.ndarray:
        """Return the agent to the center of the square."""
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        """Advance the environment by one action and return the resulting reward."""
        # TODO: Implement this function.
        raise NotImplementedError

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """Evaluate many plans exactly while reusing repeated computation."""
        # TODO: Implement this function.
        raise NotImplementedError


class CrossEntropyMethod:
    """Optimize action distributions for a fixed-horizon PointEnv plan."""

    def __init__(
        self,
        env: PointEnv,
        horizon: int = 15,
    ):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """Update `self.probs` with the cross-entropy method."""
        # TODO: Implement this function.
        raise NotImplementedError

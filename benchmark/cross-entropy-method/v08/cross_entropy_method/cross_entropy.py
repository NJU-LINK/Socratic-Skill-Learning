from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """
    A point-mass environment with reward along a narrow corridor and a small goal pocket.

    :param length: Side length of the square env
    :param goal_x: X-coordinate of the terminal pocket center
    :param goal_y: Y-coordinate of the terminal pocket center
    :param goal_radius: Radius of the terminal pocket
    """

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
        assert length > 0
        assert length % 2 == 0
        assert np.abs(goal_x) < length / 2
        assert np.abs(goal_y) < length / 2
        assert goal_radius > 0

        self.length = length
        self.goal = np.array((goal_x, goal_y), dtype=float)
        self.goal_radius = goal_radius
        self.position = np.array((0, 0), dtype=np.int_)

        self._corridor_x = np.arange(1, int(np.floor(goal_x)) + 1, dtype=np.int_)
        self._corridor_y = np.arange(1, int(np.floor(goal_y)) + 1, dtype=np.int_)
        self._plan_cache: dict[tuple[int, ...], tuple[np.ndarray, int]] = {(): (self.position.copy(), 0)}

    def reset(self) -> np.ndarray:
        """Reset the environment by returning the agent to the center of the square."""
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def _reward_for_position(self, position: np.ndarray) -> int:
        x, y = int(position[0]), int(position[1])
        in_horizontal = y == 0 and x in self._corridor_x
        in_vertical = x == int(self.goal[0]) and y in self._corridor_y
        in_goal = np.linalg.norm(position - self.goal) <= self.goal_radius
        return int(in_horizontal or in_vertical or in_goal)

    def step(self, action: int) -> int:
        """
        Simulate a step in the environment.

        The agent moves on the bounded square using the displacement in
        ``PointEnv.action_map[action]``. Reward is binary and depends on whether the new
        position lies on the narrow rewarded corridor or in the terminal goal pocket.

        :param action: The agent's discrete action (an index into PointEnv.action_map)
        :return: Reward for this environment step (+1 when the resulting position is in
            the rewarded corridor or goal pocket, otherwise 0)
        """
        # TODO: Implement this function to pass tests
        pass

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate multiple plans in the PointEnv environment using memoization.

        Plans may share long prefixes, and hidden tests will reuse the same environment
        instance across multiple batches. Cache design therefore needs to preserve exact
        cumulative rewards while staying correct when later calls introduce new plan sets.

        :param plans: Array of actions shaped (N, H) where N is the number of plans and
            H is the planning horizon.
        :return: A sequence of N rewards giving the total reward of each plan.
        """
        # TODO: Implement this function to pass tests
        pass


class CrossEntropyMethod:
    """Cross-entropy optimizer for discrete action plans in PointEnv."""

    def __init__(
        self,
        env: PointEnv,
        horizon: int = 15,
    ):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions), dtype=float) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """
        Perform cross-entropy optimization to update ``self.probs``.

        Hidden tests call this method multiple times on the same optimizer, so each call
        must continue from the current probability table rather than reinitializing it.

        :param num_samples: The number of Monte Carlo trajectory samples to generate at
            each iteration.
        :param num_elites: The number of elite samples to keep at each iteration.
        :param iterations: The number of iterations of the cross-entropy method to run.
        """
        # TODO: Implement this function to pass tests
        pass

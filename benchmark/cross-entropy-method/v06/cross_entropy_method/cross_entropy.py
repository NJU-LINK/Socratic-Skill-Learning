from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """
    A point-mass environment in which an agent gets reward for reaching a goal disk.

    :param x_bounds: Inclusive min/max x-coordinates for the rectangular environment.
    :param y_bounds: Inclusive min/max y-coordinates for the rectangular environment.
    :param goal_x: X-coordinate of the goal center.
    :param goal_y: Y-coordinate of the goal center.
    :param goal_radius: Radius of the goal disk.
    """

    action_map = np.array(
        [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        x_bounds: tuple[int, int] = (-4, 3),
        y_bounds: tuple[int, int] = (-2, 5),
        goal_x: float = 2,
        goal_y: float = 2,
        goal_radius: float = 1,
    ):
        assert x_bounds[0] <= 0 <= x_bounds[1]
        assert y_bounds[0] <= 0 <= y_bounds[1]
        assert x_bounds[0] < x_bounds[1]
        assert y_bounds[0] < y_bounds[1]
        assert x_bounds[0] <= goal_x <= x_bounds[1]
        assert y_bounds[0] <= goal_y <= y_bounds[1]
        assert goal_radius > 0

        self.x_bounds = x_bounds
        self.y_bounds = y_bounds
        self.goal = np.array((goal_x, goal_y), dtype=float)
        self.goal_radius = goal_radius

        self.position = np.array((0, 0), dtype=np.int_)

    def reset(self) -> np.ndarray:
        """Reset the environment by returning the agent to the origin."""
        self.position = np.array((0, 0), dtype=np.int_)
        return self.position

    def step(self, action: int) -> int:
        """
        Simulate a step in the environment.

        :param action: The agent's discrete action (an index into PointEnv.action_map).
        :return: Reward for this environment step (+1 if the agent lands in the goal
            disk, including the boundary, and 0 otherwise).
        """
        # TODO: Implement this function to pass tests.
        pass

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate multiple plans in the PointEnv environment, using memoization for
        increased efficiency.

        Each plan is an action sequence of shape (H,), and `plans` has shape (N, H).
        The return value should contain the cumulative reward for every plan.

        :param plans: Array of actions shaped (N, H) where N is the number of plans and
            H is the planning horizon.
        :return: A sequence of N rewards giving the total reward of each plan.
        """
        # TODO: Implement this function to pass tests.
        pass


class CrossEntropyMethod:
    """
    Uses the cross-entropy method to try to create a policy that maximizes reward in a
    PointEnv.

    :param env: The PointEnv in which to create a plan.
    :param horizon: The total number of actions that the agent will take.
    """

    def __init__(
        self,
        env: PointEnv,
        horizon: int = 15,
    ):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon

        # self.probs[i, j] is the probability of taking action j at timestep i.
        self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """
        Perform cross-entropy optimization to try to create a reward-maximizing policy.

        The primary effect of this method is updating self.probs in place.

        Calling this method multiple times should continue optimization from the current
        probability table rather than resetting it.

        :param num_samples: The number of Monte Carlo trajectory samples to generate at
            each iteration.
        :param num_elites: The number of elite samples to keep at each iteration.
        :param iterations: The number of cross-entropy updates to run.
        """
        # TODO: Implement this function to pass tests.
        pass

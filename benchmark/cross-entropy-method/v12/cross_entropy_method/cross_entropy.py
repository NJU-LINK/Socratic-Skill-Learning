from __future__ import annotations

from collections.abc import Sequence

import numpy as np


class PointEnv:
    """A clipped square gridworld with a sparse reward basin near the boundary."""

    action_map = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]],
        dtype=np.int_,
    )

    def __init__(
        self,
        length: int = 24,
        goal_x: float = 11,
        goal_y: float = 10,
        goal_radius: float = 1.0,
        reward_start_timestep: int = 12,
    ):
        assert length > 0
        assert length % 2 == 0
        assert np.abs(goal_x) < length / 2
        assert np.abs(goal_y) < length / 2
        assert goal_radius > 0
        assert reward_start_timestep >= 0

        self.length = length
        self.goal = np.array((goal_x, goal_y), dtype=float)
        self.goal_radius = goal_radius
        self.reward_start_timestep = reward_start_timestep

        self.position = np.array((0, 0), dtype=np.int_)
        self.timestep = 0

    def reset(self) -> np.ndarray:
        """Reset the environment to the origin and clear step count."""
        self.position = np.array((0, 0), dtype=np.int_)
        self.timestep = 0
        return self.position

    def step(self, action: int) -> int:
        """
        Simulate one step of local motion with clipping at the square boundary.

        :param action: Index into ``PointEnv.action_map``.
        :return: Integer reward for this step.
        """
        # TODO: Implement this function.
        pass

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate a batch of plans exactly while reusing repeated prefix work.

        :param plans: Array of shape ``(N, H)`` containing discrete action plans.
        :return: Length-N sequence of cumulative rewards.
        """
        # TODO: Implement this function.
        pass


class CrossEntropyMethod:
    """Plan action sequences for ``PointEnv`` with the cross-entropy method."""

    def __init__(self, env: PointEnv, horizon: int = 24):
        self.env = env
        self.num_actions = len(PointEnv.action_map)
        self.horizon = horizon
        self.probs = np.ones(shape=(horizon, self.num_actions)) / self.num_actions

    def optimize(
        self, num_samples: int = 200, num_elites: int = 40, iterations: int = 25
    ) -> None:
        """
        Update ``self.probs`` by repeatedly sampling plans and keeping the elites.

        Repeated calls should continue from the current ``self.probs`` instead of
        reinitializing the policy.
        """
        # TODO: Implement this function.
        pass

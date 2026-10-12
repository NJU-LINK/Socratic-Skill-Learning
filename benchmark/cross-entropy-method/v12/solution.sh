#!/bin/bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

normalize_path() {
  "$PYTHON_BIN" -c 'import os, sys; path = os.path.realpath(sys.argv[1]); print("/" + path.lstrip("/"))' "$1"
}

SCRIPT_DIR="$(normalize_path "$(dirname -- "${BASH_SOURCE[0]}")")"

discover_task_root() {
  local candidate
  for candidate in \
    "$SCRIPT_DIR/.." \
    "$SCRIPT_DIR/../input" \
    "$SCRIPT_DIR/../"* \
    "$SCRIPT_DIR/../../"*; do
    if [ -d "$candidate" ] \
      && [ -f "$candidate/pyproject.toml" ] \
      && [ -f "$candidate/cross_entropy_method/cross_entropy.py" ]; then
      normalize_path "$candidate"
      return 0
    fi
  done

  printf 'Could not locate task root from %s\n' "$SCRIPT_DIR" >&2
  return 1
}

TASK_ROOT="$(discover_task_root)"
export TASK_ROOT

"$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["TASK_ROOT"]) / "cross_entropy_method" / "cross_entropy.py"
path.write_text(
    '''from __future__ import annotations

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
        move = self.action_map[int(action)]
        lower = -(self.length // 2)
        upper = self.length // 2 - 1

        self.position = np.clip(self.position + move, lower, upper).astype(np.int_)
        self.timestep += 1

        reward_active = self.timestep >= self.reward_start_timestep
        in_goal = np.linalg.norm(self.position - self.goal) <= self.goal_radius
        return int(reward_active and in_goal)

    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate a batch of plans exactly while reusing repeated prefix work.

        :param plans: Array of shape ``(N, H)`` containing discrete action plans.
        :return: Length-N sequence of cumulative rewards.
        """
        plans = np.asarray(plans, dtype=np.int_)
        if plans.ndim != 2:
            raise ValueError("plans must have shape (N, H)")

        lower = -(self.length // 2)
        upper = self.length // 2 - 1
        cache: dict[tuple[int, ...], tuple[int, int, int, int]] = {(): (0, 0, 0, 0)}
        rewards: list[int] = []

        for plan in plans:
            prefix: tuple[int, ...] = ()
            for action in plan.tolist():
                next_prefix = prefix + (int(action),)
                if next_prefix not in cache:
                    x, y, timestep, total_reward = cache[prefix]
                    dx, dy = self.action_map[action]
                    next_x = int(np.clip(x + int(dx), lower, upper))
                    next_y = int(np.clip(y + int(dy), lower, upper))
                    next_timestep = timestep + 1
                    reward_active = next_timestep >= self.reward_start_timestep
                    in_goal = (
                        np.hypot(next_x - self.goal[0], next_y - self.goal[1])
                        <= self.goal_radius
                    )
                    cache[next_prefix] = (
                        next_x,
                        next_y,
                        next_timestep,
                        total_reward + int(reward_active and in_goal),
                    )
                prefix = next_prefix
            rewards.append(cache[prefix][3])

        return rewards


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
        if num_samples <= 0:
            raise ValueError("num_samples must be positive")
        if num_elites <= 0 or num_elites > num_samples:
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

            updated_probs = np.zeros_like(self.probs)
            for timestep in range(self.horizon):
                counts = np.bincount(elites[:, timestep], minlength=self.num_actions)
                updated_probs[timestep] = counts / num_elites
            self.probs = updated_probs
''',
    encoding="utf-8",
)
PY

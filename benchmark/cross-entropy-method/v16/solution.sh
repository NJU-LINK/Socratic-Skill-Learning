#!/bin/bash
set -euo pipefail

if command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
elif command -v python >/dev/null 2>&1; then
  python_bin="python"
else
  echo "Could not locate python or python3" >&2
  exit 1
fi

if [ -f "cross_entropy_method/cross_entropy.py" ]; then
  target="$PWD/cross_entropy_method/cross_entropy.py"
elif [ -f "/app/cross_entropy_method/cross_entropy.py" ]; then
  target="/app/cross_entropy_method/cross_entropy.py"
else
  echo "Could not locate cross_entropy_method/cross_entropy.py" >&2
  exit 1
fi

"$python_bin" - <<'PY' "$target"
from pathlib import Path
import sys


def replace_method(source: str, method_name: str, replacement: str) -> str:
    lines = source.splitlines()
    start = None
    indent = ""

    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {method_name}("):
            start = index
            indent = line[: len(line) - len(stripped)]
            break

    if start is None:
        raise RuntimeError(f"Failed to find method: {method_name}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if not stripped:
            continue
        current_indent = lines[index][: len(lines[index]) - len(stripped)]
        if len(current_indent) <= len(indent) and not stripped.startswith((")", "]", "}")):
            end = index
            break

    replacement_lines = replacement.strip("\n").splitlines()
    updated_lines = lines[:start] + replacement_lines + lines[end:]
    return "\n".join(updated_lines) + "\n"


path = Path(sys.argv[1])
source = path.read_text()

source = replace_method(
    source,
    "step",
    '''    def step(self, action: int) -> int:
        """
        Simulate a step in the environment.

        :param action: The agent's discrete action (an index into PointEnv.action_map)
        :return: Reward for this environment step (+1 if the agent lands in the goal
            circle, including the circle boundary, and 0 otherwise)
        """
        half_length = self.length // 2
        next_position = self.position + self.action_map[action]
        self.position = np.clip(next_position, -half_length, half_length).astype(np.int_, copy=False)
        distance_sq = np.sum((self.position - self.goal) ** 2)
        return int(distance_sq <= self.goal_radius**2)
''',
)

source = replace_method(
    source,
    "evaluate_plans_memoized",
    '''    def evaluate_plans_memoized(self, plans: np.ndarray) -> Sequence[int]:
        """
        Evaluate multiple plans in the PointEnv environment, using memoization for
        increased efficiency.

        Hidden evaluation includes workloads with large, redundant plan batches. Exact
        cumulative rewards must still be preserved.

        :param plans: Array of actions shaped (N, H) where N is the number of plans and
            H is the planning horizon.
        :return: A sequence of N rewards giving the total reward of each plan.
        """
        plans = np.asarray(plans, dtype=np.int_)
        if plans.ndim != 2:
            raise ValueError("plans must be a 2D array of shape (N, H)")

        num_plans, horizon = plans.shape
        if num_plans == 0:
            return np.zeros(0, dtype=np.int_)

        half_length = self.length // 2
        positions = np.zeros((num_plans, 2), dtype=np.int_)
        rewards = np.zeros(num_plans, dtype=np.int_)
        goal = self.goal.astype(float, copy=False)
        goal_radius_sq = float(self.goal_radius) ** 2

        for timestep in range(horizon):
            state_actions = np.empty((num_plans, 3), dtype=np.int_)
            state_actions[:, :2] = positions
            state_actions[:, 2] = plans[:, timestep]

            unique_state_actions, inverse = np.unique(state_actions, axis=0, return_inverse=True)
            unique_next_positions = unique_state_actions[:, :2] + self.action_map[unique_state_actions[:, 2]]
            unique_next_positions = np.clip(unique_next_positions, -half_length, half_length).astype(
                np.int_, copy=False
            )

            distance_sq = np.sum((unique_next_positions - goal) ** 2, axis=1)
            unique_step_rewards = (distance_sq <= goal_radius_sq).astype(np.int_)

            positions = unique_next_positions[inverse]
            rewards += unique_step_rewards[inverse]

        return rewards
''',
)

source = replace_method(
    source,
    "optimize",
    '''    def optimize(
        self, num_samples: int = 100, num_elites: int = 25, iterations: int = 20
    ) -> None:
        """
        Perform cross-entropy optimization to try to create a reward-maximizing policy.

        Uses the initial value of self.probs in the first iteration and then iteratively
        updates self.probs. Calling this method multiple times should continue improving
        from the current policy instead of resetting optimization state.

        :param num_samples: The number of Monte Carlo trajectory samples to generate at
            each iteration.
        :param num_elites: The number of elite samples to keep at each iteration.
        :param iterations: The number of optimization iterations to run.
        """
        if num_samples <= 0:
            raise ValueError("num_samples must be positive")
        if num_elites <= 0 or num_elites > num_samples:
            raise ValueError("num_elites must be in the range [1, num_samples]")
        if iterations < 0:
            raise ValueError("iterations must be non-negative")

        for _ in range(iterations):
            sampled_actions = [
                np.random.choice(self.num_actions, size=num_samples, p=self.probs[timestep])
                for timestep in range(self.horizon)
            ]
            plans = np.stack(sampled_actions, axis=1)
            rewards = np.asarray(self.env.evaluate_plans_memoized(plans), dtype=np.int_)

            elite_indices = np.argsort(rewards, kind="stable")[-num_elites:]
            elites = plans[elite_indices]

            counts = np.zeros_like(self.probs)
            for action in range(self.num_actions):
                counts[:, action] = np.count_nonzero(elites == action, axis=0)
            self.probs = counts / num_elites
''',
)

path.write_text(source)
PY

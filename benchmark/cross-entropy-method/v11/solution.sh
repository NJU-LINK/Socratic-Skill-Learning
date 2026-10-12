#!/bin/bash
set -euo pipefail

PYTHON_BIN="$(command -v python3 || command -v python)"

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

path = Path("/app/cross_entropy_method/cross_entropy.py")
text = path.read_text()

cache_old = """        self.position = self.start.copy()\n"""
cache_new = """        self.position = self.start.copy()\n        self._plan_cache = {(): ((int(self.start[0]), int(self.start[1])), 0)}\n"""
if cache_old in text and "self._plan_cache" not in text:
    text = text.replace(cache_old, cache_new, 1)

step_old = """        # TODO: Implement this function to pass tests\n        pass\n"""
step_new = """        delta = PointEnv.action_map[action]\n        half_length = self.length // 2\n        self.position = np.clip(self.position + delta, -half_length, half_length)\n        return int(np.sum((self.position - self.goal) ** 2) <= self.goal_radius**2)\n"""
if step_old in text:
    text = text.replace(step_old, step_new, 1)
elif step_new not in text:
    raise RuntimeError("Could not locate PointEnv.step placeholder")

eval_old = """        # TODO: Implement this function to pass tests\n        pass\n\n\nclass CrossEntropyMethod:\n"""
eval_new = """        rewards = []\n        half_length = self.length // 2\n        goal_radius_squared = self.goal_radius**2\n\n        for plan in plans:\n            plan_tuple = tuple(int(action) for action in plan)\n\n            prefix_length = len(plan_tuple)\n            while plan_tuple[:prefix_length] not in self._plan_cache:\n                prefix_length -= 1\n\n            prefix = plan_tuple[:prefix_length]\n            position, reward = self._plan_cache[prefix]\n            current_position = np.array(position, dtype=np.int_)\n            current_reward = reward\n\n            for action in plan_tuple[prefix_length:]:\n                current_position = np.clip(\n                    current_position + PointEnv.action_map[action], -half_length, half_length
                )\n                current_reward += int(\n                    np.sum((current_position - self.goal) ** 2) <= goal_radius_squared\n                )\n                prefix = prefix + (action,)\n                self._plan_cache[prefix] = (\n                    (int(current_position[0]), int(current_position[1])),\n                    current_reward,\n                )\n\n            rewards.append(current_reward)\n\n        return rewards\n\n\nclass CrossEntropyMethod:\n"""
if eval_old in text:
    text = text.replace(eval_old, eval_new, 1)
elif eval_new not in text:
    raise RuntimeError("Could not locate PointEnv.evaluate_plans_memoized placeholder")

opt_old = """        # TODO: Implement this function to pass tests\n        pass\n"""
opt_new = """        if num_samples <= 0:\n            raise ValueError(\"num_samples must be positive\")\n        if num_elites <= 0:\n            raise ValueError(\"num_elites must be positive\")\n        if num_elites > num_samples:\n            raise ValueError(\"num_elites cannot exceed num_samples\")\n\n        for _ in range(iterations):\n            plans = np.empty((num_samples, self.horizon), dtype=np.int_)\n            for timestep in range(self.horizon):\n                plans[:, timestep] = np.random.choice(\n                    self.num_actions, size=num_samples, p=self.probs[timestep]\n                )\n\n            rewards = np.asarray(self.env.evaluate_plans_memoized(plans))\n            elite_indices = np.argsort(rewards)[-num_elites:]\n            elite_plans = plans[elite_indices]\n\n            for timestep in range(self.horizon):\n                self.probs[timestep] = np.bincount(\n                    elite_plans[:, timestep], minlength=self.num_actions\n                ) / num_elites\n"""
if opt_old in text:
    text = text.replace(opt_old, opt_new, 1)
elif opt_new not in text:
    raise RuntimeError("Could not locate CrossEntropyMethod.optimize placeholder")

path.write_text(text)
PY

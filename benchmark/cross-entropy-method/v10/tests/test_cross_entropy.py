import numpy as np

import cross_entropy_method.cross_entropy as cem_module
from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def manual_plan_reward(env: PointEnv, plan: np.ndarray) -> int:
    lower = -(env.length // 2)
    upper = env.length // 2
    position = env.position.astype(np.int_, copy=True)
    reward = 0
    for action in plan:
        position = np.clip(
            position + PointEnv.action_map[action],
            lower,
            upper,
        ).astype(np.int_)
        reward += int(np.linalg.norm(position - env.goal) <= env.goal_radius)
    return reward


def simulate_optimize(
    initial_probs: np.ndarray,
    rewards_fn,
    num_samples: int,
    num_elites: int,
    iterations: int,
    seed: int,
) -> np.ndarray:
    np.random.seed(seed)
    probs = initial_probs.copy()
    num_actions = probs.shape[1]
    horizon = probs.shape[0]
    for _ in range(iterations):
        plans = np.empty((num_samples, horizon), dtype=np.int_)
        for timestep in range(horizon):
            plans[:, timestep] = np.random.choice(
                num_actions,
                size=num_samples,
                p=probs[timestep],
            )
        rewards = np.asarray(rewards_fn(plans), dtype=np.int_)
        elite_indices = np.argsort(rewards, kind="stable")[-num_elites:]
        elite_plans = plans[elite_indices]
        updated = np.zeros_like(probs)
        for timestep in range(horizon):
            updated[timestep] = (
                np.bincount(elite_plans[:, timestep], minlength=num_actions)
                / num_elites
            )
        probs = updated
    return probs


def test_step_clips_at_bounds_and_counts_boundary_goal_reward():
    env = PointEnv(length=4, goal_x=1, goal_y=1, goal_radius=np.sqrt(2))
    assert env.step(1) == 1
    assert np.array_equal(env.position, np.array((1, 0)))

    env.reset()
    env.step(1)
    assert env.step(3) == 1
    assert np.array_equal(env.position, np.array((1, 1)))

    edge_env = PointEnv(length=4, goal_x=-1.5, goal_y=-1.5, goal_radius=0.5)
    edge_env.position = np.array((2, 2), dtype=np.int_)
    assert edge_env.step(2) == 0
    assert np.array_equal(edge_env.position, np.array((2, 2)))


def test_evaluate_plans_memoized_is_exact_for_overlapping_plans_and_preserves_state():
    env = PointEnv(length=6, goal_x=1, goal_y=1, goal_radius=1.5)
    env.position = np.array((2, -1), dtype=np.int_)
    plans = np.array(
        [
            [1, 3, 5, 7],
            [1, 3, 5, 7],
            [1, 3, 5, 1],
            [1, 3, 1, 1],
        ],
        dtype=np.int_,
    )

    rewards = env.evaluate_plans_memoized(plans)
    expected = [manual_plan_reward(env, plan) for plan in plans]

    assert list(rewards) == expected
    assert np.array_equal(env.position, np.array((2, -1)))


def test_evaluate_plans_memoized_reuses_overlapping_prefixes(monkeypatch):
    env = PointEnv(length=8, goal_x=1, goal_y=2, goal_radius=1.5)
    env.position = np.array((1, -1), dtype=np.int_)
    plans = np.array(
        [[1, 1, 1, 1, 3, 3, 3, 3]] * 30
        + [[1, 1, 1, 1, 3, 3, 3, 1]] * 30
        + [[1, 1, 1, 1, 3, 3, 1, 1]] * 30
        + [[1, 1, 1, 1, 3, 1, 1, 1]] * 30,
        dtype=np.int_,
    )
    expected = [manual_plan_reward(env, plan) for plan in plans]
    unique_prefixes = {
        tuple(plan[:prefix_length])
        for plan in plans
        for prefix_length in range(1, plans.shape[1] + 1)
    }

    norm_calls = 0
    original_norm = cem_module.np.linalg.norm

    def counting_norm(*args, **kwargs):
        nonlocal norm_calls
        norm_calls += 1
        return original_norm(*args, **kwargs)

    monkeypatch.setattr(cem_module.np.linalg, "norm", counting_norm)

    rewards = env.evaluate_plans_memoized(plans)

    assert list(rewards) == expected
    assert norm_calls == len(unique_prefixes)


class RewardByPlanEnv(PointEnv):
    def evaluate_plans_memoized(self, plans: np.ndarray):
        return [
            int(plan[0] == 0) + int(plan[1] in (1, 2))
            for plan in plans
        ]


def test_optimize_respects_nonuniform_and_deterministic_priors():
    env = RewardByPlanEnv(length=6, goal_x=0, goal_y=0, goal_radius=1)
    cem = CrossEntropyMethod(env, horizon=3)
    cem.probs = np.array(
        [
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.55, 0.25, 0.20, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.10, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.90],
        ],
        dtype=float,
    )

    seed = 7
    expected = simulate_optimize(
        cem.probs,
        env.evaluate_plans_memoized,
        num_samples=12,
        num_elites=4,
        iterations=1,
        seed=seed,
    )

    np.random.seed(seed)
    cem.optimize(num_samples=12, num_elites=4, iterations=1)

    assert np.allclose(cem.probs, expected)
    assert np.array_equal(
        cem.probs[0],
        np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    )
    assert np.allclose(cem.probs.sum(axis=1), 1.0)


class TiedRewardEnv(PointEnv):
    def evaluate_plans_memoized(self, plans: np.ndarray):
        return [int(plan[-1] == 0) for plan in plans]


def test_repeated_optimize_calls_match_one_long_call_with_ties():
    initial_probs = np.array(
        [
            [0.7, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.4, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0],
        ],
        dtype=float,
    )
    seed = 123

    env_one = TiedRewardEnv(length=6, goal_x=0, goal_y=0, goal_radius=1)
    one_call = CrossEntropyMethod(env_one, horizon=2)
    one_call.probs = initial_probs.copy()
    np.random.seed(seed)
    one_call.optimize(num_samples=10, num_elites=5, iterations=2)

    env_split = TiedRewardEnv(length=6, goal_x=0, goal_y=0, goal_radius=1)
    split_call = CrossEntropyMethod(env_split, horizon=2)
    split_call.probs = initial_probs.copy()
    np.random.seed(seed)
    split_call.optimize(num_samples=10, num_elites=5, iterations=1)
    split_call.optimize(num_samples=10, num_elites=5, iterations=1)

    expected = simulate_optimize(
        initial_probs,
        env_one.evaluate_plans_memoized,
        num_samples=10,
        num_elites=5,
        iterations=2,
        seed=seed,
    )

    assert np.allclose(one_call.probs, split_call.probs)
    assert np.allclose(one_call.probs, expected)
    assert np.allclose(one_call.probs.sum(axis=1), 1.0)

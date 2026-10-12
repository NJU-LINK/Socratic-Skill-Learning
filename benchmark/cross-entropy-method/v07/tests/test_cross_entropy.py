import time

import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod
from cross_entropy_method.cross_entropy import PointEnv


def assert_rewards_equal(actual, expected) -> None:
    np.testing.assert_array_equal(np.asarray(actual, dtype=np.int_), np.asarray(expected, dtype=np.int_))


def reference_plan_rewards(env: PointEnv, plans: np.ndarray) -> list[int]:
    half_length = env.length // 2
    goal_radius_sq = env.goal_radius**2
    results = []
    for plan in np.asarray(plans, dtype=np.int_):
        position = np.array((0, 0), dtype=np.int_)
        total_reward = 0
        for action in plan:
            position = np.clip(position + env.action_map[int(action)], -half_length, half_length)
            total_reward += int(np.sum((position - env.goal) ** 2) <= goal_radius_sq)
        results.append(total_reward)
    return results


def test_step_slides_along_wall_and_rewards_goal_boundary() -> None:
    env = PointEnv(length=4, goal_x=2, goal_y=2, goal_radius=1.0)

    env.position = np.array((2, 0), dtype=np.int_)
    reward = env.step(1)

    assert tuple(env.position) == (2, 1)
    assert reward == 1

    env.position = np.array((2, 2), dtype=np.int_)
    reward = env.step(1)

    assert tuple(env.position) == (2, 2)
    assert reward == 1


def test_evaluate_plans_memoized_matches_reference_and_preserves_state() -> None:
    env = PointEnv(length=8, goal_x=3, goal_y=2, goal_radius=1.5)
    env.position = np.array((-2, 1), dtype=np.int_)
    plans = np.array(
        [
            [1, 1, 1, 2, 2, 7],
            [1, 1, 1, 2, 0, 0],
            [1, 1, 1, 2, 0, 0],
            [4, 4, 6, 6, 0, 0],
        ],
        dtype=np.int_,
    )

    actual = env.evaluate_plans_memoized(plans)

    assert_rewards_equal(actual, reference_plan_rewards(env, plans))
    assert tuple(env.position) == (-2, 1)


def test_evaluate_plans_memoized_is_measurably_faster_on_shared_prefixes() -> None:
    env = PointEnv(length=40, goal_x=19, goal_y=18, goal_radius=1.0)
    prefix = np.full(180, 1, dtype=np.int_)
    num_plans = 4096
    suffix_length = 4
    suffixes = np.empty((num_plans, suffix_length), dtype=np.int_)
    for index in range(num_plans):
        value = index
        for offset in range(suffix_length - 1, -1, -1):
            suffixes[index, offset] = value % len(env.action_map)
            value //= len(env.action_map)

    plans = np.concatenate(
        (np.repeat(prefix[None, :], num_plans, axis=0), suffixes),
        axis=1,
    )

    assert len(np.unique(plans, axis=0)) == num_plans

    expected = reference_plan_rewards(env, plans)

    start = time.perf_counter()
    actual = env.evaluate_plans_memoized(plans)
    memoized_time = time.perf_counter() - start

    start = time.perf_counter()
    slow_reference = reference_plan_rewards(env, plans)
    reference_time = time.perf_counter() - start

    assert_rewards_equal(actual, expected)
    assert_rewards_equal(actual, slow_reference)
    assert memoized_time < reference_time * 0.5


class WeightedRewardEnv:
    def evaluate_plans_memoized(self, plans: np.ndarray) -> np.ndarray:
        target = np.array((1, 2, 3), dtype=np.int_)
        weights = np.array((4, 2, 1), dtype=np.int_)
        return ((plans == target) * weights).sum(axis=1)


def test_optimize_updates_probabilities_and_reuses_current_distribution(monkeypatch) -> None:
    cem = CrossEntropyMethod(WeightedRewardEnv(), horizon=3)

    expected_prob_rows = [
        [np.ones(8) / 8, np.ones(8) / 8, np.ones(8) / 8],
        [
            np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0]),
        ],
    ]
    sampled_columns = [
        np.array([0, 1, 1, 7], dtype=np.int_),
        np.array([0, 1, 2, 7], dtype=np.int_),
        np.array([0, 1, 3, 7], dtype=np.int_),
        np.array([1, 1, 1, 1], dtype=np.int_),
        np.array([1, 2, 2, 1], dtype=np.int_),
        np.array([3, 3, 1, 1], dtype=np.int_),
    ]
    state = {"call": 0}

    def fake_choice(num_actions: int, size: int, p: np.ndarray) -> np.ndarray:
        assert num_actions == 8
        assert size == 4
        phase = state["call"] // 3
        row = state["call"] % 3
        np.testing.assert_allclose(p, expected_prob_rows[phase][row])
        result = sampled_columns[state["call"]]
        state["call"] += 1
        return result.copy()

    monkeypatch.setattr(np.random, "choice", fake_choice)

    cem.optimize(num_samples=4, num_elites=2, iterations=1)
    np.testing.assert_allclose(
        cem.probs,
        np.array(
            [
                [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0],
            ]
        ),
    )

    cem.optimize(num_samples=4, num_elites=2, iterations=1)
    np.testing.assert_allclose(
        cem.probs,
        np.array(
            [
                [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0],
            ]
        ),
    )

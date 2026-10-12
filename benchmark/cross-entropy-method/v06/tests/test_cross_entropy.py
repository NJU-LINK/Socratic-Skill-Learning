from __future__ import annotations

import time

import numpy as np
import pytest

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def action_index(delta: tuple[int, int]) -> int:
    return int(np.where((PointEnv.action_map == np.array(delta, dtype=np.int_)).all(axis=1))[0][0])


def naive_plan_reward(env: PointEnv, plan: np.ndarray) -> int:
    position = np.array((0, 0), dtype=np.int_)
    total = 0
    half_length = env.length // 2
    for action in plan:
        position = position + PointEnv.action_map[action]
        position = np.clip(position, -half_length, half_length)
        delta = position.astype(float) - env.goal
        total += int(delta @ delta <= env.goal_radius**2)
    return total


def naive_plan_rewards(env: PointEnv, plans: np.ndarray) -> np.ndarray:
    return np.array([naive_plan_reward(env, plan) for plan in plans], dtype=np.int_)


def best_time(fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def test_point_env_uses_seed_length_and_action_semantics() -> None:
    default_env = PointEnv()
    assert default_env.length == 20
    np.testing.assert_allclose(default_env.goal, np.array((3.0, 8.0)))
    assert default_env.goal_radius == 1

    np.testing.assert_array_equal(
        PointEnv.action_map,
        np.array(
            [
                [0, 0],
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
        ),
    )

    with pytest.raises(AssertionError):
        PointEnv(length=3, goal_x=0, goal_y=0, goal_radius=1)

    with pytest.raises(AssertionError):
        PointEnv(length=4, goal_x=2, goal_y=0, goal_radius=1)

    env = PointEnv(length=4, goal_x=1, goal_y=1, goal_radius=1)
    up_right = action_index((1, 1))
    left = action_index((-1, 0))
    down = action_index((0, -1))
    stay = action_index((0, 0))

    assert env.step(up_right) == 1
    np.testing.assert_array_equal(env.position, np.array((1, 1), dtype=np.int_))

    assert env.step(stay) == 1
    np.testing.assert_array_equal(env.position, np.array((1, 1), dtype=np.int_))

    assert env.step(up_right) == 0
    np.testing.assert_array_equal(env.position, np.array((2, 2), dtype=np.int_))

    assert env.step(left) == 1
    np.testing.assert_array_equal(env.position, np.array((1, 2), dtype=np.int_))

    assert env.step(down) == 1
    np.testing.assert_array_equal(env.position, np.array((1, 1), dtype=np.int_))

    env.position = np.array((-2, -2), dtype=np.int_)
    assert env.step(down) == 0
    np.testing.assert_array_equal(env.position, np.array((-2, -2), dtype=np.int_))


def test_evaluate_plans_memoized_matches_exact_rewards_for_repeated_prefixes() -> None:
    env = PointEnv(length=4, goal_x=1, goal_y=1, goal_radius=1)
    right = action_index((1, 0))
    up = action_index((0, 1))
    stay = action_index((0, 0))
    down_left = action_index((-1, -1))
    plans = np.array(
        [
            [right, right, up, stay, down_left],
            [right, right, up, stay, down_left],
            [right, right, stay, up, down_left],
            [up, up, right, right, stay],
            [down_left, down_left, stay, stay, stay],
        ],
        dtype=np.int_,
    )

    rewards = env.evaluate_plans_memoized(plans)
    expected = [naive_plan_reward(env, plan) for plan in plans]

    assert list(rewards) == expected


def test_evaluate_plans_memoized_beats_naive_on_heavily_overlapping_batch() -> None:
    env = PointEnv(length=8, goal_x=3, goal_y=3, goal_radius=1.5)
    right = action_index((1, 0))
    up = action_index((0, 1))
    stay = action_index((0, 0))
    up_right = action_index((1, 1))
    left = action_index((-1, 0))
    down = action_index((0, -1))

    shared_prefix = np.array([right, right, up, up, up_right, stay, stay, right], dtype=np.int_)
    suffixes = np.array(
        [
            [stay, stay, stay, stay],
            [right, stay, stay, up],
            [up, stay, right, stay],
            [left, down, stay, stay],
        ],
        dtype=np.int_,
    )
    plans = np.vstack(
        [
            np.concatenate((shared_prefix, suffixes[0])) for _ in range(700)
        ]
        + [
            np.concatenate((shared_prefix, suffix)) for suffix in suffixes for _ in range(700)
        ]
    )

    expected = naive_plan_rewards(env, plans)
    rewards = env.evaluate_plans_memoized(plans)
    np.testing.assert_array_equal(rewards, expected)

    naive_elapsed = best_time(lambda: naive_plan_rewards(env, plans))
    memo_elapsed = best_time(lambda: env.evaluate_plans_memoized(plans))

    assert memo_elapsed < naive_elapsed * 0.5


def make_choice_stub(expected_prob_rows: list[np.ndarray], columns: list[np.ndarray]):
    state = {"index": 0}

    def fake_choice(options, size: int, p: np.ndarray) -> np.ndarray:
        index = state["index"]
        np.testing.assert_allclose(p, expected_prob_rows[index])

        if np.isscalar(options):
            assert int(options) == len(expected_prob_rows[index])
        else:
            np.testing.assert_array_equal(np.asarray(options), np.arange(len(expected_prob_rows[index])))

        assert size == len(columns[index])
        state["index"] += 1
        return columns[index].copy()

    return fake_choice


def test_optimize_uses_elites_exactly_and_keeps_current_distribution(monkeypatch) -> None:
    env = PointEnv()
    cem = CrossEntropyMethod(env, horizon=3)
    cem.probs = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            [0.1, 0.5, 0.1, 0.1, 0.0, 0.1, 0.05, 0.05, 0.0],
            [1 / 9] * 9,
        ]
    )

    stay = action_index((0, 0))
    left = action_index((-1, 0))
    up = action_index((0, 1))
    down = action_index((0, -1))

    round1_columns = [
        np.array([stay, stay, stay, stay], dtype=np.int_),
        np.array([left, left, up, up], dtype=np.int_),
        np.array([down, stay, down, stay], dtype=np.int_),
    ]
    round1_plans = np.column_stack(round1_columns)
    monkeypatch.setattr(
        np.random,
        "choice",
        make_choice_stub([row.copy() for row in cem.probs], round1_columns),
    )
    monkeypatch.setattr(
        env,
        "evaluate_plans_memoized",
        lambda plans: (np.testing.assert_array_equal(plans, round1_plans), np.array([5, 5, 1, 1], dtype=np.int_))[1],
    )

    cem.optimize(num_samples=4, num_elites=2, iterations=1)

    np.testing.assert_allclose(
        cem.probs,
        np.array(
            [
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
                [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0],
            ]
        ),
    )

    round2_columns = [
        np.array([stay, stay, stay, stay], dtype=np.int_),
        np.array([left, left, left, up], dtype=np.int_),
        np.array([stay, stay, stay, down], dtype=np.int_),
    ]
    round2_plans = np.column_stack(round2_columns)
    monkeypatch.setattr(
        np.random,
        "choice",
        make_choice_stub([row.copy() for row in cem.probs], round2_columns),
    )
    monkeypatch.setattr(
        env,
        "evaluate_plans_memoized",
        lambda plans: (np.testing.assert_array_equal(plans, round2_plans), np.array([8, 8, 8, 1], dtype=np.int_))[1],
    )

    cem.optimize(num_samples=4, num_elites=3, iterations=1)

    np.testing.assert_allclose(
        cem.probs,
        np.array(
            [
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ]
        ),
    )

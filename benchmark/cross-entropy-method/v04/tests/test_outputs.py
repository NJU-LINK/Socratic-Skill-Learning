import time

import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def naive_plan_reward(env: PointEnv, plan: np.ndarray) -> int:
    env.reset()
    return sum(env.step(int(action)) for action in plan)


def test_step_clips_diagonals_and_rewards_on_boundary():
    env = PointEnv(length=8, goal_x=3, goal_y=1, goal_radius=0.1)

    assert env.step(2) == 0
    assert tuple(env.position) == (1, 1)

    assert env.step(2) == 0
    assert tuple(env.position) == (2, 2)

    assert env.step(8) == 1
    assert tuple(env.position) == (3, 1)

    assert env.step(8) == 0
    assert tuple(env.position) == (4, 0)


def test_step_clips_at_positive_boundary_limit_minus_one():
    env = PointEnv(length=2, goal_x=0, goal_y=0, goal_radius=1)

    env.step(1)
    assert tuple(env.position) == (1, 0)
    env.step(1)
    assert tuple(env.position) == (1, 0)

    env.reset()
    env.step(3)
    assert tuple(env.position) == (0, 1)
    env.step(3)
    assert tuple(env.position) == (0, 1)


def test_optimize_converges_and_repeated_calls_match_single_run():
    seed = 1234

    env_single = PointEnv(length=20, goal_x=-1, goal_y=-1, goal_radius=0.2)
    cem_single = CrossEntropyMethod(env_single, horizon=1)
    np.random.seed(seed)
    cem_single.optimize(num_samples=3000, num_elites=1500, iterations=5)

    env_split = PointEnv(length=20, goal_x=-1, goal_y=-1, goal_radius=0.2)
    cem_split = CrossEntropyMethod(env_split, horizon=1)
    np.random.seed(seed)
    for _ in range(5):
        cem_split.optimize(num_samples=3000, num_elites=1500, iterations=1)

    assert np.allclose(cem_single.probs, cem_split.probs)
    assert np.argmax(cem_single.probs[0]) == 6
    assert cem_single.probs[0, 6] > 0.95


def test_evaluate_plans_memoized_matches_naive_on_mixed_overlap_batch():
    env = PointEnv(length=50, goal_x=8, goal_y=8, goal_radius=2.5)

    duplicate = [1, 1, 1, 3, 3, 3, 2, 2, 0, 0]
    shared_prefix = [1, 1, 1, 3, 3, 3]
    suffixes = [
        [2, 2, 2, 0],
        [2, 2, 8, 8],
        [2, 4, 4, 0],
        [3, 3, 1, 1],
        [8, 8, 7, 7],
        [0, 0, 0, 0],
    ]
    unique_noise = [
        [6, 2, 5, 1, 7, 3, 8, 4, 0, 2],
        [8, 8, 1, 5, 2, 2, 7, 0, 4, 4],
        [3, 6, 6, 1, 1, 8, 0, 5, 2, 7],
        [4, 4, 7, 7, 2, 2, 1, 1, 8, 8],
    ]

    plans = np.array(
        [duplicate] * 16 + [shared_prefix + suffix for suffix in suffixes for _ in range(4)] + unique_noise,
        dtype=np.int_,
    )

    expected = np.array([naive_plan_reward(PointEnv(length=50, goal_x=8, goal_y=8, goal_radius=2.5), plan) for plan in plans])
    actual = np.asarray(env.evaluate_plans_memoized(plans))

    assert np.array_equal(actual, expected)


def test_memoized_evaluation_provides_speedup_on_mixed_overlap_batch():
    goal_kwargs = dict(length=60, goal_x=9, goal_y=9, goal_radius=3.0)
    duplicate = [1, 1, 1, 3, 3, 3, 2, 2, 0, 0, 0, 0]
    shared_prefix = [1, 1, 1, 3, 3, 3, 2, 2]
    suffixes = [
        [0, 0, 0, 0],
        [1, 1, 1, 1],
        [2, 2, 2, 2],
        [8, 8, 8, 8],
        [4, 4, 4, 4],
        [0, 1, 2, 3],
    ]
    unique_noise = [
        [6, 2, 5, 1, 7, 3, 8, 4, 0, 2, 6, 1],
        [8, 8, 1, 5, 2, 2, 7, 0, 4, 4, 3, 3],
        [3, 6, 6, 1, 1, 8, 0, 5, 2, 7, 4, 4],
        [4, 4, 7, 7, 2, 2, 1, 1, 8, 8, 0, 0],
        [0, 5, 0, 5, 2, 7, 2, 7, 4, 1, 4, 1],
        [2, 2, 3, 3, 6, 6, 7, 7, 8, 8, 1, 1],
    ]

    plans = np.array(
        [duplicate] * 48 + [shared_prefix + suffix for suffix in suffixes for _ in range(12)] + unique_noise,
        dtype=np.int_,
    )

    env = PointEnv(**goal_kwargs)
    start = time.perf_counter()
    memoized = np.asarray(env.evaluate_plans_memoized(plans))
    memoized_time = time.perf_counter() - start

    start = time.perf_counter()
    naive = np.array([naive_plan_reward(PointEnv(**goal_kwargs), plan) for plan in plans])
    naive_time = time.perf_counter() - start

    assert np.array_equal(memoized, naive)
    assert naive_time / memoized_time > 1.2, (memoized_time, naive_time)

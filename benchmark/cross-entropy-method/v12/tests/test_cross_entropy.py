import statistics
import time

import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def evaluate_naively(env: PointEnv, plans: np.ndarray) -> list[int]:
    totals = []
    for plan in plans:
        probe = PointEnv(
            length=env.length,
            goal_x=float(env.goal[0]),
            goal_y=float(env.goal[1]),
            goal_radius=env.goal_radius,
            reward_start_timestep=env.reward_start_timestep,
        )
        probe.reset()
        totals.append(sum(probe.step(int(action)) for action in plan))
    return totals


def median_runtime_seconds(fn, repeats: int = 3) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def test_step_clips_at_boundary_and_respects_delayed_reward() -> None:
    env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=0.25, reward_start_timestep=3)

    assert env.reset().tolist() == [0, 0]
    rewards = [env.step(2), env.step(2), env.step(2)]

    assert rewards == [0, 0, 1]
    assert env.position.tolist() == [2, 2]
    assert env.timestep == 3


def test_evaluate_plans_memoized_matches_exact_returns_without_mutating_env() -> None:
    env = PointEnv(length=8, goal_x=3, goal_y=3, goal_radius=0.5, reward_start_timestep=4)
    plans = np.array(
        [
            [2, 2, 2, 2, 0, 0],
            [2, 2, 2, 2, 1, 0],
            [2, 2, 2, 2, 0, 0],
            [2, 2, 2, 1, 1, 0],
        ],
        dtype=np.int_,
    )

    rewards = env.evaluate_plans_memoized(plans)

    assert list(rewards) == evaluate_naively(env, plans)
    assert env.position.tolist() == [0, 0]
    assert env.timestep == 0


def test_evaluate_plans_memoized_gets_large_speedup_on_shared_prefixes() -> None:
    env = PointEnv(length=24, goal_x=11, goal_y=10, goal_radius=1.0, reward_start_timestep=70)
    shared_prefix = np.array([1] * 36 + [3] * 36, dtype=np.int_)
    suffixes = np.array(
        [
            [1, 1, 3, 3, 0, 0, 0, 0],
            [1, 1, 3, 0, 3, 0, 0, 0],
            [1, 1, 0, 3, 3, 0, 0, 0],
            [1, 0, 1, 3, 3, 0, 0, 0],
            [0, 1, 1, 3, 3, 0, 0, 0],
            [1, 1, 3, 3, 3, 0, 0, 0],
            [1, 1, 3, 3, 0, 3, 0, 0],
            [1, 1, 3, 3, 0, 0, 3, 0],
        ],
        dtype=np.int_,
    )
    plans = np.vstack(
        [np.concatenate([shared_prefix, suffix]) for suffix in suffixes for _ in range(512)]
    )

    expected = evaluate_naively(env, plans)
    actual = env.evaluate_plans_memoized(plans)

    assert list(actual) == expected
    assert env.position.tolist() == [0, 0]
    assert env.timestep == 0

    naive_time = median_runtime_seconds(lambda: evaluate_naively(env, plans))
    memoized_time = median_runtime_seconds(lambda: env.evaluate_plans_memoized(plans))

    assert naive_time > 0
    assert memoized_time < naive_time * 0.35, (
        f"expected substantial shared-prefix speedup, got naive={naive_time:.4f}s "
        f"memoized={memoized_time:.4f}s"
    )


def test_optimize_preserves_deterministic_priors_and_updates_from_elites() -> None:
    env = PointEnv(length=6, goal_x=0, goal_y=1, goal_radius=0.25, reward_start_timestep=2)
    cem = CrossEntropyMethod(env, horizon=2)
    cem.probs[0] = np.eye(cem.num_actions, dtype=float)[3]

    np.random.seed(0)
    cem.optimize(num_samples=300, num_elites=30, iterations=4)

    assert np.allclose(cem.probs[0], np.eye(cem.num_actions, dtype=float)[3])
    assert cem.probs[1, 0] > 0.9

    np.random.seed(1)
    cem.optimize(num_samples=200, num_elites=20, iterations=2)

    assert np.allclose(cem.probs[0], np.eye(cem.num_actions, dtype=float)[3])
    assert cem.probs[1, 0] > 0.9

import numpy as np
import time

from cross_entropy_method.cross_entropy import CrossEntropyMethod
from cross_entropy_method.cross_entropy import PointEnv


def naive_plan_reward(env: PointEnv, plan: np.ndarray) -> int:
    position = env.start.astype(np.int_).copy()
    total = 0
    for action in plan:
        move = PointEnv.action_map[int(action)]
        position = np.clip(position + move, env._min_coord, env._max_coord)
        total += int(np.linalg.norm(position.astype(np.float64) - env.goal) <= env.goal_radius)
    return total


def build_branching_plans(depth: int = 22, copies_per_leaf: int = 60) -> np.ndarray:
    base_prefix = [1, 1, 7, 7, 1, 1, 7, 7, 1, 1, 7, 7, 1, 1, 7, 7]
    branch_levels = [
        [1, 2, 3],
        [7, 8],
        [1, 2, 4],
        [7, 8],
        [1, 3],
        [7, 8],
    ]
    plans = []
    frontier = [base_prefix]
    for actions in branch_levels:
        next_frontier = []
        for prefix in frontier:
            for action in actions:
                next_frontier.append(prefix + [action])
        frontier = next_frontier
    for leaf in frontier:
        padded_leaf = leaf[:depth]
        plans.extend([padded_leaf] * copies_per_leaf)
    return np.array(plans, dtype=np.int_)


def build_low_overlap_plans(num_plans: int, depth: int) -> np.ndarray:
    plans = np.empty((num_plans, depth), dtype=np.int_)
    for idx in range(num_plans):
        value = idx + 1
        for step in range(depth):
            plans[idx, step] = (value + step * 5) % len(PointEnv.action_map)
            value = value * 7 + step * 3
    return plans


def measure_seconds(func, *args) -> float:
    func(*args)
    durations = []
    for _ in range(3):
        start = time.perf_counter()
        func(*args)
        durations.append(time.perf_counter() - start)
    return min(durations)


def naive_batch_rewards(env: PointEnv, plans: np.ndarray) -> np.ndarray:
    return np.array([naive_plan_reward(env, plan) for plan in plans], dtype=np.int_)


def test_step_uses_configured_start_clipping_and_inclusive_goal_boundary():
    env = PointEnv(length=10, goal_x=4.0, goal_y=1.0, goal_radius=1.0, start_x=3, start_y=0)

    reward = env.step(1)

    assert reward == 1
    assert np.array_equal(env.position, np.array([4, 0]))

    edge_env = PointEnv(length=10, goal_x=4.0, goal_y=4.0, goal_radius=0.5, start_x=-5, start_y=5)
    clipped_reward = edge_env.step(5)

    assert clipped_reward == 0
    assert np.array_equal(edge_env.position, np.array([-5, 5]))


def test_evaluate_plans_memoized_matches_naive_rewards_on_deep_prefix_overlap():
    env = PointEnv(length=12, goal_x=3.0, goal_y=-4.0, goal_radius=1.5, start_x=-2, start_y=1)
    prefix = [1, 1, 7, 7, 1, 1, 7, 7, 1, 1]
    suffixes = [
        [1, 1, 1, 7, 7, 7],
        [1, 1, 2, 7, 7, 7],
        [1, 1, 1, 8, 8, 7],
        [1, 1, 2, 8, 8, 7],
        [1, 1, 3, 8, 7, 7],
        [1, 1, 4, 8, 7, 7],
    ]
    plans = np.array([prefix + suffix for suffix in suffixes], dtype=np.int_)

    rewards = env.evaluate_plans_memoized(plans)
    expected = np.array([naive_plan_reward(env, plan) for plan in plans], dtype=np.int_)

    assert np.array_equal(rewards, expected)
    assert np.array_equal(env.position, env.start)


def test_evaluate_plans_memoized_handles_repeated_plans_exactly():
    env = PointEnv(length=12, goal_x=2.0, goal_y=-3.0, goal_radius=1.5, start_x=-2, start_y=1)
    repeated_plan = np.array([1, 1, 7, 7, 1, 1, 7, 7, 1, 1, 7, 7], dtype=np.int_)
    plans = np.repeat(repeated_plan[np.newaxis, :], 256, axis=0)

    rewards = env.evaluate_plans_memoized(plans)
    expected_reward = naive_plan_reward(env, repeated_plan)

    assert rewards.shape == (256,)
    assert np.array_equal(rewards, np.full(256, expected_reward, dtype=np.int_))
    assert np.array_equal(env.position, env.start)


def test_evaluate_plans_memoized_is_faster_on_heavily_overlapping_batches():
    env = PointEnv(length=20, goal_x=8.0, goal_y=-8.0, goal_radius=2.5, start_x=-6, start_y=4)
    overlapping_plans = build_branching_plans()

    overlapping_rewards = env.evaluate_plans_memoized(overlapping_plans)
    naive_rewards = naive_batch_rewards(env, overlapping_plans)

    assert np.array_equal(overlapping_rewards, naive_rewards)

    overlapping_time = measure_seconds(env.evaluate_plans_memoized, overlapping_plans)
    naive_time = measure_seconds(naive_batch_rewards, env, overlapping_plans)

    assert overlapping_time < naive_time * 0.2, (
        f"expected memoized overlap speedup, got memoized={overlapping_time:.4f}s "
        f"and naive={naive_time:.4f}s"
    )


def test_optimize_samples_each_timestep_independently_and_updates_from_elites(monkeypatch):
    env = PointEnv(length=10, goal_x=0.0, goal_y=0.0, goal_radius=1.0, start_x=-3, start_y=2)
    cem = CrossEntropyMethod(env, horizon=3)
    cem.probs[:] = 0.0
    cem.probs[0, 3] = 1.0
    cem.probs[1, 1] = 0.75
    cem.probs[1, 2] = 0.25
    cem.probs[2, 4] = 0.5
    cem.probs[2, 8] = 0.5

    sampled_columns = [
        np.array([3, 3, 3, 3], dtype=np.int_),
        np.array([1, 2, 1, 2], dtype=np.int_),
        np.array([4, 4, 8, 8], dtype=np.int_),
    ]
    seen = []

    def fake_choice(actions, size, p):
        timestep = len(seen)
        seen.append(np.array(p, copy=True))
        assert size == 4
        assert np.array_equal(actions, np.arange(cem.num_actions))
        return sampled_columns[timestep]

    def fake_evaluate(plans):
        expected_plans = np.array(
            [
                [3, 1, 4],
                [3, 2, 4],
                [3, 1, 8],
                [3, 2, 8],
            ],
            dtype=np.int_,
        )
        assert np.array_equal(plans, expected_plans)
        return np.array([1, 10, 3, 9], dtype=np.int_)

    monkeypatch.setattr(np.random, "choice", fake_choice)
    monkeypatch.setattr(env, "evaluate_plans_memoized", fake_evaluate)

    cem.optimize(num_samples=4, num_elites=2, iterations=1)

    assert len(seen) == 3
    assert np.array_equal(seen[0], np.eye(cem.num_actions)[3])
    assert np.array_equal(seen[1], np.array([0.0, 0.75, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    assert np.array_equal(seen[2], np.array([0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5]))

    expected_probs = np.zeros_like(cem.probs)
    expected_probs[0, 3] = 1.0
    expected_probs[1, 2] = 1.0
    expected_probs[2, 4] = 0.5
    expected_probs[2, 8] = 0.5
    assert np.array_equal(cem.probs, expected_probs)

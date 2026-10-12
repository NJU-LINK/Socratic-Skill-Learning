import numpy as np
from time import perf_counter

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def test_step_clips_at_boundary_and_counts_goal_radius_inclusively():
    env = PointEnv(length=6, goal_x=2.5, goal_y=0, goal_radius=0.5)

    rewards = [env.step(1) for _ in range(5)]

    assert tuple(env.position) == (3, 0)
    assert rewards[-1] == 1


def test_optimize_preserves_deterministic_rows_and_updates_stochastic_rows_across_calls(monkeypatch):
    class StubEnv:
        def __init__(self):
            self.action_map = np.zeros((9, 2), dtype=np.int_)
            self.reward_batches = [
                np.array([0, 5, 4, 0]),
                np.array([0, 6, 5, 0]),
            ]

        def evaluate_plans_memoized(self, plans):
            return self.reward_batches.pop(0)

    samples = iter(
        [
            np.array([4, 4, 4, 4]),
            np.array([7, 7, 7, 7]),
            np.array([1, 2, 1, 2]),
            np.array([4, 4, 4, 4]),
            np.array([7, 7, 7, 7]),
            np.array([1, 2, 2, 1]),
        ]
    )

    def fake_choice(num_actions, size, p):
        draw = next(samples)
        assert len(p) == num_actions == 9
        assert draw.shape == (size,)
        return draw

    cem = CrossEntropyMethod(StubEnv(), horizon=3)
    cem.probs[0] = np.eye(9)[4]
    cem.probs[1] = np.eye(9)[7]
    cem.probs[2] = np.eye(9)[1] * 0.5 + np.eye(9)[2] * 0.5

    monkeypatch.setattr(np.random, "choice", fake_choice)

    cem.optimize(num_samples=4, num_elites=2, iterations=1)
    assert np.allclose(cem.probs[0], np.eye(9)[4])
    assert np.allclose(cem.probs[1], np.eye(9)[7])
    assert cem.probs[2, 1] == 0.5
    assert cem.probs[2, 2] == 0.5

    cem.optimize(num_samples=4, num_elites=2, iterations=1)
    assert np.allclose(cem.probs[0], np.eye(9)[4])
    assert np.allclose(cem.probs[1], np.eye(9)[7])
    assert np.allclose(cem.probs[2], np.eye(9)[2])


def test_optimize_uses_environment_owned_action_map(monkeypatch):
    env = PointEnv(length=6, goal_x=1, goal_y=0, goal_radius=0.1)
    env.action_map = np.array([[0, 0], [1, 0], [-1, 0]], dtype=np.int_)

    samples = iter(
        [
            np.array([1, 0, 1, 2]),
            np.array([0, 0, 1, 2]),
        ]
    )

    def fake_choice(num_actions, size, p):
        draw = next(samples)
        assert num_actions == 3
        assert len(p) == 3
        assert draw.shape == (size,)
        return draw

    def fake_eval(plans):
        assert plans.shape == (4, 2)
        assert np.all((0 <= plans) & (plans < 3))
        return np.array([1, 0, 2, 0])

    monkeypatch.setattr(np.random, "choice", fake_choice)
    env.evaluate_plans_memoized = fake_eval

    cem = CrossEntropyMethod(env, horizon=2)

    assert cem.probs.shape == (2, 3)
    cem.optimize(num_samples=4, num_elites=2, iterations=1)
    assert np.allclose(cem.probs[0], [0.0, 1.0, 0.0])
    assert np.allclose(cem.probs[1], [0.5, 0.5, 0.0])


def test_evaluate_plans_memoized_matches_exact_rewards_for_repeats_and_shared_prefixes():
    env = PointEnv(length=8, goal_x=2, goal_y=2, goal_radius=0.1)
    plans = np.array(
        [
            [2, 2, 0, 0],
            [2, 2, 0, 0],
            [2, 2, 5, 5],
            [2, 2, 7, 7],
            [1, 1, 3, 3],
        ],
        dtype=np.int_,
    )

    rewards = env.evaluate_plans_memoized(plans)

    assert list(rewards) == [3, 3, 1, 1, 1]
    assert tuple(env.position) == (0, 0)


def test_evaluate_plans_memoized_reuses_shared_prefixes_for_unique_plans():
    env = PointEnv(length=12, goal_x=3, goal_y=3, goal_radius=0.1)

    shared_prefix = np.array([2] * 18, dtype=np.int_)
    suffixes = np.array(
        [[(suffix_id >> shift) & 1 for shift in range(10, -1, -1)] for suffix_id in range(2048)],
        dtype=np.int_,
    )
    plans = np.array([np.concatenate((shared_prefix, suffix)) for suffix in suffixes], dtype=np.int_)

    assert len({tuple(plan) for plan in plans.tolist()}) == len(plans)

    def duplicate_only_evaluate(batch):
        cache = {}
        rewards = []
        boundary = env.length // 2
        radius_sq = env.goal_radius * env.goal_radius
        for plan in batch:
            key = tuple(int(action) for action in plan)
            if key not in cache:
                position = np.array((0, 0), dtype=np.int_)
                total_reward = 0
                for action in plan:
                    position = np.clip(position + env.action_map[int(action)], -boundary, boundary)
                    delta = position - env.goal
                    total_reward += int(np.dot(delta, delta) <= radius_sq)
                cache[key] = total_reward
            rewards.append(cache[key])
        return rewards

    expected = duplicate_only_evaluate(plans)
    assert list(env.evaluate_plans_memoized(plans)) == expected

    env.evaluate_plans_memoized(plans)
    duplicate_only_evaluate(plans)

    memoized_times = []
    duplicate_only_times = []
    for _ in range(3):
        start = perf_counter()
        memoized_rewards = env.evaluate_plans_memoized(plans)
        memoized_times.append(perf_counter() - start)

        start = perf_counter()
        duplicate_only_rewards = duplicate_only_evaluate(plans)
        duplicate_only_times.append(perf_counter() - start)

    assert list(memoized_rewards) == duplicate_only_rewards == expected
    assert min(memoized_times) < min(duplicate_only_times) * 0.55

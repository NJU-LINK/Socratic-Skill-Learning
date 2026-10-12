import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def test_step_respects_non_origin_start_boundary_and_inclusive_radius():
    env = PointEnv(length=6, start_x=3, start_y=0, goal_x=2, goal_y=0, goal_radius=1)

    np.testing.assert_array_equal(env.reset(), np.array([3, 0]))

    reward = env.step(1)

    np.testing.assert_array_equal(env.position, np.array([3, 0]))
    assert reward == 1


def test_evaluate_plans_memoized_returns_exact_rewards_without_mutating_position():
    env = PointEnv(length=6, start_x=1, start_y=-1, goal_x=2, goal_y=0, goal_radius=0.5)
    env.position = np.array([-3, 3])
    plans = np.array(
        [
            [2, 0, 0],
            [1, 3, 0],
            [0, 0, 0],
            [2, 0, 0],
        ],
        dtype=np.int_,
    )

    rewards = env.evaluate_plans_memoized(plans)

    assert list(rewards) == [3, 2, 0, 3]
    np.testing.assert_array_equal(env.position, np.array([-3, 3]))


def test_evaluate_plans_memoized_reuses_prefix_cache_across_calls():
    env = PointEnv(length=8, start_x=-2, start_y=1, goal_x=-1, goal_y=3, goal_radius=0.5)
    first_batch = np.array([[2, 3, 0], [2, 3, 1]], dtype=np.int_)
    second_batch = np.array([[2, 3, 1, 0], [2, 3, 0, 0]], dtype=np.int_)

    assert list(env.evaluate_plans_memoized(first_batch)) == [2, 1]
    cache_size = len(env._plan_cache)

    assert list(env.evaluate_plans_memoized(second_batch)) == [1, 3]
    assert len(env._plan_cache) > cache_size
    assert (2, 3, 1) in env._plan_cache
    assert (2, 3, 0, 0) in env._plan_cache


def test_optimize_updates_probabilities_from_elite_frequencies(monkeypatch):
    sampled_actions = [
        np.array([1, 1, 2, 2], dtype=np.int_),
        np.array([3, 4, 3, 4], dtype=np.int_),
    ]

    def fake_choice(_num_actions, size, p):
        assert size == 4
        assert np.isclose(np.sum(p), 1.0)
        return sampled_actions.pop(0)

    class FakeEnv:
        def evaluate_plans_memoized(self, plans):
            np.testing.assert_array_equal(
                plans,
                np.array(
                    [
                        [1, 3],
                        [1, 4],
                        [2, 3],
                        [2, 4],
                    ],
                    dtype=np.int_,
                ),
            )
            return np.array([0, 10, 5, 1], dtype=np.int_)

    monkeypatch.setattr(np.random, "choice", fake_choice)

    cem = CrossEntropyMethod(FakeEnv(), horizon=2)
    cem.optimize(num_samples=4, num_elites=2, iterations=1)

    expected = np.zeros((2, len(PointEnv.action_map)))
    expected[0, 1] = 0.5
    expected[0, 2] = 0.5
    expected[1, 3] = 0.5
    expected[1, 4] = 0.5
    np.testing.assert_allclose(cem.probs, expected)


def test_optimize_stays_normalized_and_accumulates_across_multiple_calls():
    class RankingEnv:
        def evaluate_plans_memoized(self, plans):
            return plans[:, 0] * 100 + plans[:, 1]

    np.random.seed(7)
    single_run = CrossEntropyMethod(RankingEnv(), horizon=2)
    single_run.optimize(num_samples=8, num_elites=3, iterations=4)

    np.random.seed(7)
    split_run = CrossEntropyMethod(RankingEnv(), horizon=2)
    split_run.optimize(num_samples=8, num_elites=3, iterations=2)
    split_run.optimize(num_samples=8, num_elites=3, iterations=2)

    np.testing.assert_allclose(single_run.probs, split_run.probs)
    np.testing.assert_allclose(split_run.probs.sum(axis=1), np.ones(2))

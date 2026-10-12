import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def simulate_naively(env: PointEnv, plans: np.ndarray) -> np.ndarray:
    totals = []
    for plan in plans:
        env.reset()
        total = 0
        for action in plan:
            total += env.step(int(action))
        totals.append(total)
    return np.asarray(totals, dtype=np.int_)


def test_step_clips_to_boundary_and_goal_check_is_inclusive():
    env = PointEnv(length=4, goal_x=1, goal_y=1, goal_radius=np.sqrt(2))

    reward_1 = env.step(2)
    reward_2 = env.step(2)
    reward_3 = env.step(2)

    assert np.array_equal(env.position, np.array([2, 2]))
    assert isinstance(reward_1, (int, np.integer))
    assert [reward_1, reward_2, reward_3] == [1, 1, 1]


def test_evaluate_plans_memoized_matches_naive_rewards_on_aliased_batch():
    env = PointEnv(length=6, goal_x=2, goal_y=2, goal_radius=0.25)
    suffix_catalog = np.array(
        [
            [1, 1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2, 2],
            [3, 3, 3, 3, 3, 3],
            [1, 2, 3, 1, 2, 3],
            [3, 2, 1, 3, 2, 1],
            [1, 3, 2, 1, 3, 2],
        ],
        dtype=np.int_,
    )
    repeated_suffixes = np.repeat(suffix_catalog, 40, axis=0)
    plans = np.concatenate(
        [np.tile(np.array([[2, 2]], dtype=np.int_), (len(repeated_suffixes), 1)), repeated_suffixes],
        axis=1,
    )

    expected = simulate_naively(env, plans)
    actual = np.asarray(env.evaluate_plans_memoized(plans), dtype=np.int_)

    assert np.array_equal(actual, expected)


def test_evaluate_plans_memoized_preserves_sequential_rewards_under_boundary_aliasing():
    env = PointEnv(length=6, goal_x=2, goal_y=0, goal_radius=0.25)
    prefix = np.tile(np.array([[1, 1, 1]], dtype=np.int_), (160, 1))
    suffix_catalog = np.array(
        [
            [1, 1, 1, 1, 1],
            [2, 2, 2, 2, 2],
            [8, 8, 8, 8, 8],
            [3, 7, 3, 7, 3],
            [7, 3, 7, 3, 7],
            [0, 0, 0, 0, 0],
            [5, 5, 5, 5, 5],
            [4, 4, 4, 4, 4],
        ],
        dtype=np.int_,
    )
    suffixes = np.repeat(suffix_catalog, len(prefix) // len(suffix_catalog), axis=0)
    plans = np.concatenate([prefix, suffixes], axis=1)

    expected = simulate_naively(env, plans)
    actual = np.asarray(env.evaluate_plans_memoized(plans), dtype=np.int_)

    assert np.array_equal(actual, expected)
    assert len(np.unique(actual)) > 1


def test_optimize_uses_independent_timestep_sampling_and_all_elites(monkeypatch):
    env = PointEnv(length=4, goal_x=0, goal_y=0, goal_radius=1)
    cem = CrossEntropyMethod(env, horizon=3)

    sampled = [
        np.array([0, 1, 1, 2]),
        np.array([4, 4, 5, 5]),
        np.array([8, 7, 7, 6]),
    ]
    seen_probs = []

    def fake_choice(num_actions, size, p):
        seen_probs.append(np.array(p, copy=True))
        return sampled[len(seen_probs) - 1]

    def fake_evaluate(plans):
        assert np.array_equal(plans, np.stack(sampled, axis=1))
        return np.array([3, 3, 3, 3])

    monkeypatch.setattr(np.random, "choice", fake_choice)
    monkeypatch.setattr(env, "evaluate_plans_memoized", fake_evaluate)

    cem.optimize(num_samples=4, num_elites=4, iterations=1)

    uniform = np.ones(cem.num_actions) / cem.num_actions
    assert len(seen_probs) == cem.horizon
    assert all(np.allclose(probs, uniform) for probs in seen_probs)
    assert np.allclose(cem.probs[0], [0.25, 0.5, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert np.allclose(cem.probs[1], [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.0, 0.0, 0.0])
    assert np.allclose(cem.probs[2], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.5, 0.25])


def test_optimize_preserves_deterministic_prior_on_tied_rewards(monkeypatch):
    env = PointEnv(length=4, goal_x=0, goal_y=0, goal_radius=1)
    cem = CrossEntropyMethod(env, horizon=2)
    cem.probs[:] = 0.0
    cem.probs[0, 3] = 1.0
    cem.probs[1, 5] = 1.0

    seen_probs = []

    def fake_choice(num_actions, size, p):
        seen_probs.append(np.array(p, copy=True))
        return np.full(size, np.argmax(p), dtype=np.int_)

    monkeypatch.setattr(np.random, "choice", fake_choice)
    monkeypatch.setattr(env, "evaluate_plans_memoized", lambda plans: np.ones(len(plans), dtype=np.int_))

    cem.optimize(num_samples=5, num_elites=3, iterations=1)

    assert np.allclose(seen_probs[0], [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert np.allclose(seen_probs[1], [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    assert np.allclose(cem.probs, np.array(seen_probs))


def test_optimize_reuses_updated_policy_across_iterations_and_calls(monkeypatch):
    env = PointEnv(length=4, goal_x=0, goal_y=0, goal_radius=1)
    cem = CrossEntropyMethod(env, horizon=1)

    choice_returns = [
        np.array([0, 0, 1, 1]),
        np.array([1, 1, 1, 1]),
        np.array([1, 1, 1]),
    ]
    choice_calls = []

    def fake_choice(num_actions, size, p):
        choice_calls.append(np.array(p, copy=True))
        return choice_returns.pop(0)

    reward_batches = [
        np.array([0, 0, 5, 6]),
        np.array([2, 2, 2, 2]),
        np.array([9, 9, 9]),
    ]

    def fake_evaluate(plans):
        return reward_batches.pop(0)

    monkeypatch.setattr(np.random, "choice", fake_choice)
    monkeypatch.setattr(env, "evaluate_plans_memoized", fake_evaluate)

    cem.optimize(num_samples=4, num_elites=2, iterations=2)
    first_probs = cem.probs.copy()

    assert np.allclose(choice_calls[1], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert np.allclose(first_probs[0], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    cem.optimize(num_samples=3, num_elites=1, iterations=1)

    assert np.allclose(choice_calls[2], first_probs[0])
    assert np.allclose(cem.probs[0], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

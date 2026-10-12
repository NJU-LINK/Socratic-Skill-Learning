import numpy as np

from cross_entropy_method.cross_entropy import CrossEntropyMethod, PointEnv


def test_step_rewards_the_documented_corridor_and_goal_pocket():
    env = PointEnv(length=24, goal_x=6, goal_y=6, goal_radius=0.5)

    assert [env.step(1) for _ in range(6)] == [1] * 6
    assert [env.step(3) for _ in range(6)] == [1] * 6
    assert env.position.tolist() == [6, 6]
    assert env.step(0) == 1


def test_step_rejects_off_corridor_positions_and_clips_each_axis():
    env = PointEnv(length=24, goal_x=6, goal_y=6, goal_radius=0.5)

    rewards = [env.step(2) for _ in range(6)]
    assert rewards == [0, 0, 0, 0, 0, 1]

    env.position = np.array([12, 0], dtype=np.int_)
    assert env.step(1) == 0
    assert env.position.tolist() == [12, 0]


def test_memoized_evaluation_is_exact_from_origin_and_side_effect_free():
    env = PointEnv(length=24, goal_x=6, goal_y=6, goal_radius=0.5)
    env.position = np.array([4, 4], dtype=np.int_)
    plans = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 5, 5],
            [1, 0, 1, 0],
            [2, 2, 0, 0],
        ],
        dtype=np.int_,
    )

    assert list(env.evaluate_plans_memoized(plans)) == [4, 3, 4, 0]
    assert env.position.tolist() == [4, 4]


def test_memoized_evaluation_reuses_prefixes_across_batches(monkeypatch):
    env = PointEnv(length=24, goal_x=6, goal_y=6, goal_radius=0.5)
    calls = {"count": 0}
    original = env._reward_for_position

    def counted_reward(position):
        calls["count"] += 1
        return original(position)

    monkeypatch.setattr(env, "_reward_for_position", counted_reward)

    first = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 5, 5],
            [1, 0, 1, 0],
        ],
        dtype=np.int_,
    )
    assert list(env.evaluate_plans_memoized(first)) == [4, 3, 4]
    assert calls["count"] < first.size

    before = calls["count"]
    second = np.array(
        [
            [1, 1, 0, 0, 0],
            [1, 1, 5, 5, 1],
        ],
        dtype=np.int_,
    )
    assert list(env.evaluate_plans_memoized(second)) == [5, 4]
    assert calls["count"] - before == 2


def test_optimize_uses_only_the_batch_evaluation_interface_and_keeps_state():
    class WeightedRewardEnv:
        def __init__(self, target):
            self.target = np.asarray(target, dtype=np.int_)

        def evaluate_plans_memoized(self, plans):
            weights = np.array([100.0, 100.0, 1.0, 1.0])
            return ((plans == self.target) * weights).sum(axis=1)

    target = [1, 3, 1, 3]
    single = CrossEntropyMethod(WeightedRewardEnv(target), horizon=4)
    split = CrossEntropyMethod(WeightedRewardEnv(target), horizon=4)

    for cem in (single, split):
        cem.probs = np.full((4, cem.num_actions), 0.025)
        cem.probs[0, 1] = 0.8
        cem.probs[1, 3] = 0.8
        cem.probs[2, 1] = 0.4
        cem.probs[3, 3] = 0.4
        cem.probs /= cem.probs.sum(axis=1, keepdims=True)

    np.random.seed(0)
    single.optimize(num_samples=400, num_elites=4, iterations=2)
    np.random.seed(0)
    split.optimize(num_samples=400, num_elites=4, iterations=1)
    split.optimize(num_samples=400, num_elites=4, iterations=1)

    assert np.allclose(single.probs, split.probs)
    assert single.probs[0, 1] > 0.8
    assert single.probs[1, 3] > 0.8

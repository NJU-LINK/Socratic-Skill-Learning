import pytest

from ode_contract import OdeCase, evaluate_case


CASES = (
    OdeCase(
        name="three_high_curvature_windows",
        t0=0.0,
        t1=3.0,
        y0=0.2,
        eval_ts=(
            0.07, 0.38, 0.96, 1.245, 1.2475, 1.25, 1.2525, 1.255,
            1.74, 1.742, 1.744, 1.746, 1.748, 2.28, 2.283, 2.286, 2.6, 2.91,
        ),
        constants={},
        rhs_expression=(
            "(0.38 + 0.22 * math.sin(1.3 * t + 0.2) + 0.08 * math.sin(6.5 * t - 0.4)) * y "
            "+ 0.55 * math.cos(2.2 * t - 0.1) "
            "+ 0.35 * math.exp(-42.0 * (t - 1.25) ** 2) * math.sin(7.0 * t) "
            "+ 0.32 * math.exp(-55.0 * (t - 1.745) ** 2) * math.cos(6.0 * t + 0.3) "
            "- 0.28 * math.exp(-48.0 * (t - 2.285) ** 2) * math.sin(5.5 * t - 0.2) "
            "+ (-0.045 + 0.018 * math.exp(-55.0 * (t - 1.745) ** 2)) * y * y"
        ),
        step_divisor=300,
        accuracy=3e-6,
        max_calls_factor=8,
        max_calls_slack=32,
    ),
    OdeCase(
        name="near_coincident_dynamic_targets",
        t0=0.0,
        t1=1.5,
        y0=1.0,
        eval_ts=(0.2, 0.200000000001, 0.9, 1.1, 1.100000000001, 1.4),
        constants={},
        rhs_expression=(
            "-0.35 * y + 0.2 * math.sin(6.5 * t) "
            "+ 0.15 * math.exp(-36.0 * (t - 1.1) ** 2)"
        ),
        step_divisor=300,
        accuracy=3e-6,
        max_calls_factor=8,
        max_calls_slack=32,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_solver_handles_sharp_windows_and_clustered_targets(case: OdeCase) -> None:
    evaluate_case(case)

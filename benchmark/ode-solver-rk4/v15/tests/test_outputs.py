import pytest

from ode_contract import OdeCase, evaluate_case


CASES = (
    OdeCase(
        name="tight_800_long_interval",
        t0=-0.75,
        t1=6.85,
        y0=0.35,
        eval_ts=(-0.2, 0.15, 0.7, 1.4, 2.05, 2.9, 3.45, 4.1, 4.95, 5.8, 6.4),
        rhs_expression=(
            "0.35 * math.sin(1.3 * t) - 0.18 * y + 0.09 * math.tanh(y) "
            "+ 0.04 * math.cos(0.7 * t + 0.3 * y)"
        ),
        step_divisor=800,
        reference_refinement=20,
        max_calls_factor=4,
        max_calls_slack=12,
    ),
    OdeCase(
        name="tight_800_shifted_interval",
        t0=1.1,
        t1=8.9,
        y0=-0.42,
        eval_ts=(1.45, 1.9, 2.55, 3.3, 4.0, 4.8, 5.25, 6.05, 6.9, 7.65, 8.35),
        rhs_expression=(
            "0.28 * math.cos(0.9 * t - 0.2) + 0.12 * y "
            "- 0.06 * math.tanh(1.4 * y) + 0.03 * math.sin(y + 0.5 * t)"
        ),
        step_divisor=800,
        reference_refinement=20,
        max_calls_factor=4,
        max_calls_slack=12,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_solver_obeys_800_step_ceiling_without_waste(case: OdeCase) -> None:
    evaluate_case(case)

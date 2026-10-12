import pytest

from ode_contract import OdeCase, evaluate_case


CASES = (
    OdeCase(
        name="strict_budget_sparse_oscillation",
        t0=0.2,
        t1=7.4,
        y0=0.35,
        eval_ts=(0.35, 1.6, 3.05, 4.7, 6.2, 7.4),
        rhs_expression=(
            "0.25 * y - 0.03 * y * y + 1.2 * math.sin(9.0 * t) "
            "+ 0.25 * math.cos(4.0 * t) + 0.03 * t * t"
        ),
        max_calls_factor=4,
        max_calls_slack=8,
    ),
    OdeCase(
        name="strict_budget_shifted_boundaries",
        t0=-1.1,
        t1=8.9,
        y0=-0.2,
        eval_ts=(-1.05, 0.8, 2.75, 5.6, 8.15, 8.9),
        rhs_expression=(
            "-0.18 * y + 0.12 * math.cos(0.7 * t) "
            "+ 0.015 * t * y + 0.02 * y * y"
        ),
        max_calls_factor=4,
        max_calls_slack=8,
    ),
    OdeCase(
        name="strict_budget_clustered_landing",
        t0=0.0,
        t1=10.0,
        y0=0.2,
        eval_ts=(0.05, 1.9, 4.2, 4.205, 7.4, 10.0),
        rhs_expression=(
            "0.25 * y - 0.03 * y * y + 1.2 * math.sin(9.0 * t) "
            "+ 0.25 * math.cos(4.0 * t) + 0.03 * t * t"
        ),
        max_calls_factor=4,
        max_calls_slack=8,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_solver_meets_strict_call_budget_across_schedules(case: OdeCase) -> None:
    evaluate_case(case)

import pytest

from ode_contract import OdeCase, evaluate_case


CASES = (
    OdeCase(
        name="mild_quadratic_drift",
        t0=-0.25,
        t1=2.15,
        y0=0.32,
        eval_ts=(
            -0.18, -0.03, 0.11, 0.24, 0.39, 0.52, 0.68, 0.81, 0.97,
            1.08, 1.19, 1.31, 1.46, 1.58, 1.72, 1.86, 2.01, 2.14,
        ),
        constants={"a": -0.31, "b": 0.045, "drive": 0.17, "freq": 1.35},
        rhs_expression=(
            "c['a'] * y + c['b'] * y * y / (1.0 + y * y) "
            "+ c['drive'] * math.sin(c['freq'] * t + 0.2) + 0.04 * math.cos(0.7 * t)"
        ),
        max_calls_factor=5,
        max_calls_slack=24,
    ),
    OdeCase(
        name="shifted_weak_forcing",
        t0=0.7,
        t1=3.9,
        y0=-0.41,
        eval_ts=(
            0.74, 0.91, 1.13, 1.36, 1.58, 1.81, 2.04, 2.22, 2.39,
            2.55, 2.73, 2.91, 3.08, 3.24, 3.42, 3.61, 3.78,
        ),
        constants={"a": 0.14, "b": -0.028, "drive": 0.11, "freq": 1.8},
        rhs_expression=(
            "(c['a'] + 0.05 * math.cos(0.6 * t)) * y "
            "+ c['b'] * y * y + c['drive'] * math.sin(c['freq'] * t - 0.35)"
        ),
        max_calls_factor=5,
        max_calls_slack=24,
    ),
    OdeCase(
        name="uneven_mild_nonlinearity",
        t0=-0.8,
        t1=1.7,
        y0=0.08,
        eval_ts=(-0.77, -0.61, -0.59, -0.21, 0.18, 0.19, 0.52, 0.94, 1.13, 1.49, 1.68),
        constants={"gain": 0.22, "quad": 0.035},
        rhs_expression=(
            "-0.19 * y + c['quad'] * y * y / (1.0 + 0.4 * y * y) "
            "+ c['gain'] * math.cos(1.1 * t + 0.15) + 0.03 * math.sin(2.4 * t)"
        ),
        max_calls_factor=5,
        max_calls_slack=24,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_solver_handles_multiple_mild_nonlinear_problems(case: OdeCase) -> None:
    evaluate_case(case)

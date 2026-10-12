import pytest

from ode_contract import OdeCase, evaluate_case


CASES = (
    OdeCase(
        name="strong_nonlinearity_clustered_targets",
        t0=-0.2,
        t1=2.6,
        y0=0.35,
        eval_ts=(
            -0.2, -0.08, 0.01, 0.17, 0.29, 0.41, 0.423, 0.437, 0.451,
            0.68, 0.91, 1.14, 1.31, 1.49, 1.61, 1.624, 1.638, 1.652,
            1.84, 2.01, 2.15, 2.28, 2.39, 2.47, 2.53, 2.6,
        ),
        constants={
            "phase": 0.4, "drive_amp": 0.38, "drive_bias": 0.19,
            "drive_freq": 3.7, "mix_freq": 6.4, "lin_base": -0.11,
            "lin_amp": 0.09, "lin_freq": 4.9, "tanh_base": 0.52,
            "tanh_amp": 0.21, "tanh_gain": 1.45, "nonlin_freq": 7.3,
            "sin_gain": 0.16, "osc_freq": 8.2,
        },
        rhs_expression=(
            "c['drive_amp'] * math.sin(c['drive_freq'] * t + c['phase']) "
            "+ c['drive_bias'] * math.cos(c['mix_freq'] * t - 0.35) "
            "+ (c['lin_base'] + c['lin_amp'] * math.sin(c['lin_freq'] * t + 0.2)) * y "
            "+ (c['tanh_base'] + c['tanh_amp'] * math.cos(c['nonlin_freq'] * t - 0.4)) "
            "* math.tanh(c['tanh_gain'] * y) "
            "+ c['sin_gain'] * math.sin(y) * (0.55 + 0.45 * math.sin(c['osc_freq'] * t + 0.1))"
        ),
        max_calls_factor=4,
        max_calls_slack=8,
    ),
    OdeCase(
        name="dense_dynamic_windows",
        t0=0.15,
        t1=3.15,
        y0=-0.28,
        eval_ts=(
            0.22, 0.31, 0.48, 0.72, 0.93, 1.07, 1.18, 1.251, 1.263,
            1.277, 1.291, 1.305, 1.49, 1.72, 1.94, 2.06, 2.19, 2.37,
            2.51, 2.603, 2.615, 2.627, 2.639, 2.651, 2.81, 2.96, 3.08, 3.15,
        ),
        constants={
            "phase": -0.25, "drive_amp": 0.34, "drive_bias": 0.17,
            "drive_freq": 4.2, "mix_freq": 6.9, "lin_base": -0.07,
            "lin_amp": 0.1, "lin_freq": 5.6, "tanh_base": 0.47,
            "tanh_amp": 0.24, "tanh_gain": 1.6, "nonlin_freq": 7.8,
            "sin_gain": 0.19, "osc_freq": 9.1,
        },
        rhs_expression=(
            "c['drive_amp'] * math.sin(c['drive_freq'] * t + c['phase']) "
            "+ c['drive_bias'] * math.cos(c['mix_freq'] * t - 0.35) "
            "+ (c['lin_base'] + c['lin_amp'] * math.sin(c['lin_freq'] * t + 0.2)) * y "
            "+ (c['tanh_base'] + c['tanh_amp'] * math.cos(c['nonlin_freq'] * t - 0.4)) "
            "* math.tanh(c['tanh_gain'] * y) "
            "+ c['sin_gain'] * math.sin(y) * (0.55 + 0.45 * math.sin(c['osc_freq'] * t + 0.1))"
        ),
        max_calls_factor=4,
        max_calls_slack=8,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_solver_handles_stronger_nonlinearity_under_tight_budget(case: OdeCase) -> None:
    evaluate_case(case)

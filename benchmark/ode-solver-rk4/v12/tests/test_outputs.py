from ode_contract import OdeCase, evaluate_case


def test_solver_respects_tight_step_and_call_ceiling() -> None:
    evaluate_case(
        OdeCase(
            name="tight_400_step_ceiling",
            t0=-0.3,
            t1=2.9,
            y0=0.65,
            eval_ts=(-0.18, 0.01, 0.26, 0.51, 0.79, 1.04, 1.36, 1.7, 2.03, 2.37, 2.69, 2.9),
            rhs_expression=(
                "-0.42 * y + 0.18 * math.sin(1.4 * t + 0.3) "
                "+ 0.07 * math.cos(0.8 * t - 0.2)"
            ),
            step_divisor=400,
            max_calls_factor=6,
            max_calls_slack=12,
        )
    )

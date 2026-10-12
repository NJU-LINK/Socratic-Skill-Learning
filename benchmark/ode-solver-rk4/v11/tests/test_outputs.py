from ode_contract import OdeCase, evaluate_case


def test_solver_lands_through_dense_middle_burst() -> None:
    evaluate_case(
        OdeCase(
            name="dense_middle_burst",
            t0=-1.25,
            t1=2.75,
            y0=0.35,
            eval_ts=(
                -1.1, -0.72, -0.33, 0.08, 0.46, 0.71, 0.718, 0.726,
                0.734, 0.742, 0.75, 0.758, 0.766, 0.774, 0.782, 0.79,
                1.16, 1.64, 2.17, 2.58,
            ),
            constants={"mid": 0.75, "sigma": 0.24, "osc": 26.0},
            rhs_expression=(
                "-0.42 * y + 0.11 * math.sin(1.4 * t) "
                "+ 0.07 * math.cos(0.6 * y + 0.3 * t) "
                "+ 0.16 * math.exp(-((t - c['mid']) / c['sigma']) ** 2) "
                "* math.sin(c['osc'] * t) "
                "+ 0.025 * y * y / (1.0 + y * y)"
            ),
            max_calls_factor=8,
            max_calls_slack=16,
        )
    )

from ode_contract import OdeCase, evaluate_case


def test_solver_tracks_local_curvature_and_bursty_outputs() -> None:
    evaluate_case(
        OdeCase(
            name="local_curvature_bursts",
            t0=0.0,
            t1=12.0,
            y0=0.35,
            eval_ts=(
                0.25, 1.7, 3.18, 3.24, 3.3, 5.85, 7.92, 8.01,
                8.1, 8.19, 10.75, 11.16, 11.24, 11.32, 11.88,
            ),
            rhs_expression=(
                "(0.12 * math.cos(1.3 * t) "
                "+ 0.28 * math.exp(-((t - 3.28) / 0.33) ** 2) "
                "- 0.24 * math.exp(-((t - 8.08) / 0.25) ** 2)) * y "
                "+ (0.14 + 0.05 * math.sin(1.7 * t) + 0.02 * math.cos(4.1 * t)) * math.sin(y) "
                "+ 0.16 * math.sin(2.2 * t) + 0.08 * math.cos(0.6 * t) "
                "+ 0.22 * math.exp(-((t - 6.15) / 0.24) ** 2)"
            ),
            accuracy=5e-6,
            max_calls_factor=4,
            max_calls_slack=8,
        )
    )

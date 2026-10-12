"""
RK4 IVP solver with segment-based exact landing.

Imports from ode_problem: t0, t1, y0, eval_ts, rhs
Outputs to /app/output/solution.csv
"""
import os
import math


def rk4_step(rhs, t, y, h):
    """Single RK4 step from (t, y) with step size h."""
    k1 = rhs(t, y)
    k2 = rhs(t + h / 2.0, y + h / 2.0 * k1)
    k3 = rhs(t + h / 2.0, y + h / 2.0 * k2)
    k4 = rhs(t + h, y + h * k3)
    return y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def run():
    from ode_problem import t0, t1, y0, eval_ts, rhs

    h_max = (t1 - t0) / 200.0
    results = []
    current_t = t0
    current_y = y0

    for eval_t in eval_ts:
        # Zero-length segment: eval_t == current_t
        if eval_t == current_t:
            results.append((eval_t, current_y))
            continue

        # Segment length
        seg = eval_t - current_t

        # Minimum number of steps to respect h_max
        n_steps = math.ceil(seg / h_max)

        # Step size for this segment (guarantees h <= h_max and exact landing)
        h = seg / n_steps

        # Integrate segment
        for i in range(n_steps):
            t_step = current_t + i * h
            # Clamp last step to land exactly on eval_t
            if i == n_steps - 1:
                h_actual = eval_t - t_step
            else:
                h_actual = h
            current_y = rk4_step(rhs, t_step, current_y, h_actual)

        # Update current state
        current_t = eval_t
        results.append((eval_t, current_y))

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/solution.csv', 'w') as f:
        f.write('t,y\n')
        for t, y in results:
            f.write(f'{t},{y}\n')


if __name__ == '__main__':
    run()

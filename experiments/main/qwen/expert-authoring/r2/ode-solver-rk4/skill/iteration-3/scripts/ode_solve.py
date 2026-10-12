"""
Reference RK4 IVP solver for the ode-solver-rk4 family.
Copy this file verbatim to /app/ode_solve.py.
"""
import math
import os
from ode_problem import t0, t1, y0, eval_ts, rhs


def rk4_step(f, t, y, h, t_max):
    k1 = f(t, y)
    k2 = f(t + h / 2, y + h / 2 * k1)
    k3 = f(t + h / 2, y + h / 2 * k2)
    k4 = f(min(t + h, t_max), y + h * k3)
    return y + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4)


def solve():
    h_max = (t1 - t0) / 200.0

    t = t0
    y = y0
    results = []

    for eval_t in eval_ts:
        dt = eval_t - t
        if dt <= 1e-15:
            results.append((eval_t, y))
            continue

        n_steps = max(1, math.ceil(dt / h_max))
        h = dt / n_steps

        for _ in range(n_steps):
            y = rk4_step(rhs, t, y, h, eval_t)
            t += h

        t = eval_t
        results.append((eval_t, y))

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.csv", "w") as fout:
        fout.write("t,y\n")
        for t_val, y_val in results:
            fout.write(f"{t_val},{y_val}\n")


if __name__ == "__main__":
    solve()

"""Maximise weekly furniture profit subject to workstation hour limits.

Continuous, non-negative variables: tables and chairs.
Maximise 40 * tables + 30 * chairs, subject to:
    tables + chairs <= 40          (assembly)
    2 * tables + chairs <= 60      (carpentry)
    tables + 3 * chairs <= 90      (finishing)
"""

import highspy


def main():
    products = ("tables", "chairs")
    profits = (40.0, 30.0)
    workstations = ("assembly", "carpentry", "finishing")
    hours_available = (40.0, 60.0, 90.0)
    hours_per_piece = ((1.0, 1.0), (2.0, 1.0), (1.0, 3.0))

    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    for profit in profits:
        model.addCol(profit, 0.0, highspy.kHighsInf, 0, [], [])
    for hours, coefficients in zip(hours_available, hours_per_piece):
        model.addRow(
            -highspy.kHighsInf, hours, len(products), [0, 1], coefficients
        )
    model.changeObjectiveSense(highspy.ObjSense.kMaximize)
    model.run()

    status = model.getModelStatus()
    print(f"status: {model.modelStatusToString(status)}")
    if status != highspy.HighsModelStatus.kOptimal:
        raise SystemExit(1)

    solution = model.getSolution()
    quantities = solution.col_value
    hours_used = solution.row_value
    # Upper-bound capacity duals are non-negative marginal profits for a
    # maximisation; normalise an opposite solver sign convention if present.
    shadow_prices = [dual if dual >= 0.0 else -dual for dual in solution.row_dual]
    primal_objective = sum(p * x for p, x in zip(profits, quantities))
    dual_objective = sum(
        hours * dual for hours, dual in zip(hours_available, shadow_prices)
    )
    duality_gap = abs(primal_objective - dual_objective)
    binding = [
        name
        for name, available, used in zip(workstations, hours_available, hours_used)
        if available - used < 1e-6
    ]

    print("solution: " + ", ".join(
        f"{name}={value:.12g}" for name, value in zip(products, quantities)
    ))
    print("duals: " + ", ".join(
        f"{name}={value:.12g}" for name, value in zip(workstations, shadow_prices)
    ))
    print(f"primal objective: {primal_objective:.12g}")
    print(f"dual objective: {dual_objective:.12g}")
    print(f"duality gap: {duality_gap:.12g}")
    print("binding constraints: " + ", ".join(binding))


if __name__ == "__main__":
    main()

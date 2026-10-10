"""Maximise weekly furniture profit subject to workstation capacity."""

import sys

import highspy


def main():
    products = ("tables", "chairs")
    profits = (40.0, 30.0)
    workstations = (
        ("assembly", (1.0, 1.0), 40.0),
        ("carpentry", (2.0, 1.0), 60.0),
        ("finishing", (1.0, 3.0), 90.0),
    )

    # Maximise 40*tables + 30*chairs with non-negative continuous quantities.
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    for profit in profits:
        model.addCol(profit, 0.0, highspy.kHighsInf, 0, [], [])
    for _, hours_per_piece, available in workstations:
        model.addRow(
            -highspy.kHighsInf, available, 2, [0, 1], hours_per_piece
        )
    model.changeObjectiveSense(highspy.ObjSense.kMaximize)
    model.run()

    status = model.getModelStatus()
    print(f"status: {model.modelStatusToString(status)}")
    if status != highspy.HighsModelStatus.kOptimal:
        sys.exit(1)

    solution = model.getSolution()
    quantities = solution.col_value
    # Upper-bound capacity duals are non-negative shadow prices for this LP.
    shadow_prices = [abs(dual) for dual in solution.row_dual]
    primal_objective = sum(
        profit * quantity for profit, quantity in zip(profits, quantities)
    )
    dual_objective = sum(
        available * dual
        for (_, _, available), dual in zip(workstations, shadow_prices)
    )
    gap = abs(primal_objective - dual_objective)
    binding = [
        name
        for (name, _, available), used in zip(workstations, solution.row_value)
        if available - used < 1e-6
    ]

    print("solution: " + ", ".join(
        f"{name}={value:.12g}" for name, value in zip(products, quantities)
    ))
    print("duals: " + ", ".join(
        f"{station[0]}={dual:.12g}"
        for station, dual in zip(workstations, shadow_prices)
    ))
    print(f"primal objective: {primal_objective:.12g}")
    print(f"dual objective: {dual_objective:.12g}")
    print(f"duality gap: {gap:.12g}")
    print("binding constraints: " + ", ".join(binding))


if __name__ == "__main__":
    main()

"""P00 model: fixed-charge transportation MILP solved with HiGHS through highspy.

Run `python p00_model.py` to solve the instance in data/ and print the solution as JSON.
"""

import csv
import json
from pathlib import Path

import highspy


DATA_DIR = Path(__file__).parent / "data"


def read_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def contract_status(model_status, has_solution):
    """Translate a HiGHS model status into 'optimal', 'feasible' or 'no_solution'."""
    if not has_solution:
        return "no_solution"
    if model_status == highspy.HighsModelStatus.kOptimal:
        return "optimal"
    if model_status == highspy.HighsModelStatus.kTimeLimit:
        return "feasible"
    return "no_solution"


def solve(data_dir=DATA_DIR, time_limit=10.0):
    """Solve the instance in data_dir and return a JSON-serialisable solution dict."""
    data_dir = Path(data_dir)
    plant_rows = read_rows(data_dir / "plants.csv")
    customer_rows = read_rows(data_dir / "customers.csv")
    cost_rows = read_rows(data_dir / "costs.csv")
    plant_ids = [row["plant"] for row in plant_rows]
    customer_ids = [row["customer"] for row in customer_rows]
    capacity = {row["plant"]: float(row["capacity"]) for row in plant_rows}
    fixed_cost = {row["plant"]: float(row["fixed_cost"]) for row in plant_rows}
    demand = {row["customer"]: float(row["demand"]) for row in customer_rows}
    unit_cost = {(row["plant"], row["customer"]): float(row["unit_cost"]) for row in cost_rows}

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("mip_rel_gap", 0.0)

    # y[p] = 1 when plant p is open; x[p, c] = units shipped from plant p to customer c.
    y = {
        p: h.addVariable(lb=0, ub=1, obj=fixed_cost[p], type=highspy.HighsVarType.kInteger, name=f"open_{p}")
        for p in plant_ids
    }
    x = {
        (p, c): h.addVariable(lb=0, obj=unit_cost[p, c], name=f"ship_{p}_{c}")
        for p in plant_ids
        for c in customer_ids
    }

    for c in customer_ids:
        h.addConstr(sum(x[p, c] for p in plant_ids) == demand[c])
    for p in plant_ids:
        h.addConstr(sum(x[p, c] for c in customer_ids) - capacity[p] * y[p] <= 0)

    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    h.run()

    has_solution = h.getInfo().primal_solution_status == highspy.SolutionStatus.kSolutionStatusFeasible
    status = contract_status(h.getModelStatus(), has_solution)
    if status == "no_solution":
        return {"status": status, "objective": None, "open": {}, "flow": {}}
    return {
        "status": status,
        "objective": float(h.getObjectiveValue()),
        "open": {p: float(h.val(y[p])) for p in plant_ids},
        "flow": {p: {c: float(h.val(x[p, c])) for c in customer_ids} for p in plant_ids},
    }


if __name__ == "__main__":
    print(json.dumps(solve()))

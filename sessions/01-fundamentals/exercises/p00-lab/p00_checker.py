"""Independent P00 checker: recompute feasibility and the objective without a solver.

Standard library only. It reads the CSVs itself and never imports the model or a solver,
so a bug in the model cannot also hide in the check.
"""

import csv
import math
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data"


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_data(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    plants = _rows(data_dir / "plants.csv")
    customers = _rows(data_dir / "customers.csv")
    unit_cost = {row["plant"]: {} for row in plants}
    for row in _rows(data_dir / "costs.csv"):
        unit_cost[row["plant"]][row["customer"]] = float(row["unit_cost"])
    return {
        "plants": [row["plant"] for row in plants],
        "customers": [row["customer"] for row in customers],
        "capacity": {row["plant"]: float(row["capacity"]) for row in plants},
        "fixed_cost": {row["plant"]: float(row["fixed_cost"]) for row in plants},
        "demand": {row["customer"]: float(row["demand"]) for row in customers},
        "unit_cost": unit_cost,
    }


def _number(value):
    """Return value as a float, or None when it is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def objective(data, solution):
    """Recompute the cost from the decisions; the reported objective is ignored."""
    opening = solution.get("open", {})
    flow = solution.get("flow", {})
    total = sum(data["fixed_cost"][p] * opening.get(p, 0.0) for p in data["plants"])
    total += sum(
        data["unit_cost"][p][c] * flow.get(p, {}).get(c, 0.0)
        for p in data["plants"]
        for c in data["customers"]
    )
    return total


def feasibility_problems(data, solution, tol=1e-6):
    plants, customers = data["plants"], data["customers"]
    opening = solution.get("open")
    flow = solution.get("flow")
    if not isinstance(opening, dict) or not isinstance(flow, dict):
        return ["feasibility contract: solution needs 'open' and 'flow' mappings"]
    problems = []

    def ids(found, expected, what):
        for name in expected:
            if name not in found:
                problems.append(f"feasibility contract: missing {what} {name!r}")
        for name in found:
            if name not in expected:
                problems.append(f"feasibility contract: unexpected {what} {name!r}")

    ids(opening, plants, "opening for plant")
    ids(flow, plants, "flow row for plant")

    open_value = {}
    for p in plants:
        if p not in opening:
            continue
        value = _number(opening[p])
        if value is None:
            problems.append(f"feasibility contract: opening of {p} is not a finite number: {opening[p]!r}")
        elif value < -tol or value > 1 + tol:
            problems.append(f"feasibility contract: opening of {p} is {value}, outside [0, 1]")
        else:
            open_value[p] = value

    shipped = {}
    for p in plants:
        row = flow.get(p)
        if row is None:
            continue
        if not isinstance(row, dict):
            problems.append(f"feasibility contract: flow row for {p} is not a mapping")
            continue
        ids(row, customers, f"customer in flow row {p}:")
        for c in customers:
            if c not in row:
                continue
            value = _number(row[c])
            if value is None:
                problems.append(f"feasibility contract: flow {p}->{c} is not a finite number: {row[c]!r}")
                continue
            if value < -tol:
                problems.append(f"feasibility contract: flow {p}->{c} is negative: {value}")
            shipped[p, c] = value

    for c in customers:
        demand = data["demand"][c]
        received = sum(shipped.get((p, c), 0.0) for p in plants)
        if abs(received - demand) > tol * max(1.0, abs(demand)):
            problems.append(f"feasibility contract: customer {c} receives {received}, demand is {demand}")

    for p in plants:
        if p not in open_value:
            continue
        limit = data["capacity"][p] * open_value[p]
        load = sum(shipped.get((p, c), 0.0) for c in customers)
        if load > limit + tol * max(1.0, abs(limit)):
            problems.append(
                f"feasibility contract: plant {p} ships {load}, above capacity x opening = {limit}"
            )
    return problems


def integrality_problems(data, solution, tol=1e-6):
    problems = []
    opening = solution.get("open")
    if not isinstance(opening, dict):
        return problems
    for p in data["plants"]:
        if p not in opening:
            continue
        value = opening[p]
        number = _number(value)
        if number is None or min(abs(number), abs(number - 1.0)) > tol:
            problems.append(f"integrality contract: opening of {p} is {value!r}, not 0 or 1")
    return problems


def problems(data, solution, tol=1e-6):
    return feasibility_problems(data, solution, tol) + integrality_problems(data, solution, tol)

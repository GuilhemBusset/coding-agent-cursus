"""Minimise weekly staffing with five days on and two days off."""

import csv
import json
import math
from pathlib import Path

import highspy

HOMEWORK = Path(__file__).resolve().parents[1]
TOLERANCE = 1e-6


def main() -> None:
    with (HOMEWORK / "data" / "demand.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    days = [row["day"] for row in rows]
    demand = [int(row["demand"]) for row in rows]
    if len(days) != 7 or len(set(days)) != 7:
        raise ValueError("Expected seven distinct days in weekly order")

    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    starts = [
        model.addVariable(
            lb=0,
            obj=1,
            type=highspy.HighsVarType.kInteger,
            name=f"start_{day}",
        )
        for day in days
    ]

    # Day d is covered by blocks beginning on d and the preceding four days.
    # Modulo seven includes blocks that began in the previous week.
    for d, day in enumerate(days):
        model.addConstr(
            model.qsum(starts[(d - offset) % 7] for offset in range(5)) >= demand[d],
            name=f"coverage_{day}",
        )
    model.minimize()
    if model.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"No optimal solution: {model.getModelStatus()}")

    values = model.getSolution().col_value
    start = {}
    for day, value in zip(days, values, strict=True):
        if not math.isfinite(value) or abs(value - round(value)) > TOLERANCE:
            raise ValueError(f"Noninteger solver value for {day}: {value}")
        count = round(value)
        if count < 0:
            raise ValueError(f"Negative start count for {day}: {value}")
        start[day] = count

    solution = {"objective": model.getObjectiveValue(), "start": start}
    destination = HOMEWORK / "solution.json"
    destination.write_text(json.dumps(solution, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")
    print(f"Headcount: {sum(start.values())}")


if __name__ == "__main__":
    main()

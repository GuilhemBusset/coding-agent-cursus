"""Independent L3 checker: recompute feasibility and headcount from a solution file.

Standard library only, no solver. It trusts nothing in the solution file: coverage and
headcount are recomputed from the weekly starts, and the reported objective is only compared.

Usage, from this folder:

    uv run python check.py [solution.json]
    python check.py [solution.json]

The first output line is PASS or FAIL. Each problem line starts with the contract it breaks
(data, format, feasibility, integrality, objective, optimality). The exit code is 0 on PASS
and 1 on FAIL.
"""

import csv
import json
import math
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "data" / "demand.csv"
DEFAULT_SOLUTION = HERE / "solution.json"

# The instance, pinned so that an edited data/demand.csv cannot move the target.
DEMAND = {"Mon": 8, "Tue": 7, "Wed": 8, "Thu": 9, "Fri": 8, "Sat": 5, "Sun": 6}
DAYS = tuple(DEMAND)
WORK_DAYS = 5
TOL = 1e-6

# Lower bound (LP relaxation). Every person works 5 of the 7 days, so summing the seven
# coverage constraints gives 5 * headcount >= 8 + 7 + 8 + 9 + 8 + 5 + 6 = 51, that is
# headcount >= 10.2 (the dual y = 1/5 on every day certifies it). The LP point
# starts = (3.6, 0.6, 1.6, 1.6, 0.6, 0.6, 1.6) covers every day exactly and sums to 10.2,
# so the bound is tight for the relaxation.
LP_BOUND = 10.2

# Optimum. Headcount is an integer, so it is at least ceil(10.2) = 11, and a whole-number
# roster of 11 that meets every day's demand exists, so 11 is optimal. The witness roster is
# kept out of this folder, in the course's instructor tests (finding it is the exercise).
# Derived by hand; never taken from solver output.
KNOWN_OPTIMUM = 11

ROOT_KEYS = ("objective", "start")


def text(value):
    """Return str(value) with any non-ASCII character escaped."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def fmt(value, digits=6):
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return f"{value:.{digits}g}"


def fmt_pair(a, b):
    """Format two numbers with just enough digits (6 at least) to tell them apart."""
    for digits in range(6, 18):
        left, right = fmt(a, digits), fmt(b, digits)
        if left != right:
            break
    return left, right


def number(value):
    """Return value as a float, or None when it is not a finite JSON number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def describe(value):
    """Short JSON-style description of an invalid value, for messages."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float):
        return text(value)
    if isinstance(value, (dict, list)):
        return "an object" if isinstance(value, dict) else "a list"
    if isinstance(value, int):
        return "an integer too large for a float"
    return ascii(value)


def data_problems(path=DATA_FILE):
    """Compare the parsed values of data/demand.csv with the pinned DEMAND."""
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        return [f"data: cannot read {text(path)}: {text(error)}"]
    if header != ["day", "demand"]:
        return [f"data: {text(path.name)} header is {text(header)}, expected day,demand"]
    problems = []
    seen = set()
    for line, row in enumerate(rows, start=2):
        day, raw = row.get("day"), row.get("demand")
        if day not in DEMAND:
            problems.append(f"data: line {line} has unknown day {ascii(day)}")
            continue
        if day in seen:
            problems.append(f"data: {day} appears more than once")
            continue
        seen.add(day)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            problems.append(f"data: {day} demand {ascii(raw)} is not a number")
            continue
        if value != DEMAND[day]:
            problems.append(f"data: {day} demand is {fmt(value)}, the instance pins {DEMAND[day]}")
    for day in DAYS:
        if day not in seen:
            problems.append(f"data: {day} is missing")
    return problems


def load_solution(path):
    """Return (solution, problems); solution is None when the file cannot be used."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, [f"format: no solution file at {text(path)} (see README.md for the format)"]
    except (OSError, UnicodeDecodeError) as error:
        return None, [f"format: cannot read {text(path)}: {text(error)}"]
    try:
        solution = json.loads(raw)
    except (ValueError, RecursionError) as error:
        return None, [f"format: {text(path.name)} is not valid JSON: {text(error)}"]
    return solution, []


def format_problems(solution):
    """Check the shape {"objective": number, "start": {day: number, ...}}."""
    if not isinstance(solution, dict):
        return [f"format: the solution must be a JSON object with keys "
                f"\"objective\" and \"start\", got {describe(solution)}"]
    problems = []
    for key in ROOT_KEYS:
        if key not in solution:
            problems.append(f"format: missing key \"{key}\"")
    for key in solution:
        if key not in ROOT_KEYS:
            problems.append(f"format: unexpected key {ascii(key)}; only \"objective\" and \"start\"")
    if "objective" in solution and number(solution["objective"]) is None:
        problems.append(f"format: objective must be a finite number, got "
                        f"{describe(solution['objective'])}")
    if "start" in solution:
        start = solution["start"]
        if not isinstance(start, dict):
            problems.append(f"format: start must be an object keyed by day, got {describe(start)}")
            return problems
        for day in DAYS:
            if day not in start:
                problems.append(f"format: start is missing day \"{day}\"")
            elif number(start[day]) is None:
                problems.append(f"format: start {day} must be a finite number, got "
                                f"{describe(start[day])}")
        for key in start:
            if key not in DEMAND:
                problems.append(f"format: start has unexpected key {ascii(key)}; "
                                f"days are {', '.join(DAYS)}")
    return problems


def coverage(starts):
    """People on duty each day: a block starting on day s works days s to s+4, wrapping."""
    return {
        day: sum(starts[DAYS[s]] for s in range(len(DAYS)) if (d - s) % len(DAYS) < WORK_DAYS)
        for d, day in enumerate(DAYS)
    }


def solution_problems(starts, reported, headcount):
    problems = []
    for day in DAYS:
        if starts[day] < -TOL:
            problems.append(f"feasibility: start {day} is {fmt(starts[day])}, "
                            f"it cannot be negative")
    on_duty = coverage(starts)
    for day in DAYS:
        if on_duty[day] < DEMAND[day] - TOL:
            have, need = fmt_pair(on_duty[day], DEMAND[day])
            problems.append(f"feasibility: {day} has {have} on duty, needs {need}")
    for day in DAYS:
        if abs(starts[day] - round(starts[day])) > TOL:
            problems.append(f"integrality: start {day} is {fmt(starts[day])}, not a whole number")
    if abs(reported - headcount) > TOL:
        said, real = fmt_pair(reported, headcount)
        problems.append(f"objective: reported {said}, recomputed {real} from the starts")
    if abs(headcount - KNOWN_OPTIMUM) > TOL:
        real, best = fmt_pair(headcount, KNOWN_OPTIMUM)
        relation = "above" if headcount > KNOWN_OPTIMUM else "below"
        problems.append(f"optimality: recomputed headcount {real} is {relation} "
                        f"the known optimum {best}")
    return problems


def summary(headcount):
    # Rounded so float noise (10.2 summed from fractions) prints as 0, not 1.8e-15.
    gap = round(headcount - LP_BOUND, 9) + 0.0
    relative = f"{100 * gap / headcount:.2f}%" if headcount > 0 else "n/a"
    return [
        f"Recomputed headcount: {fmt(headcount)}",
        f"LP-relaxation bound: {fmt(LP_BOUND)}",
        f"Known optimum: {KNOWN_OPTIMUM}",
        f"Gap to the LP bound: {fmt(gap)} ({relative})",
    ]


def check(path):
    """Return (passed, output lines)."""
    problems = data_problems()
    solution, unreadable = load_solution(path)
    problems += unreadable or format_problems(solution)
    if problems:
        return False, ["FAIL", *problems]
    starts = {day: number(solution["start"][day]) for day in DAYS}
    reported = number(solution["objective"])
    headcount = sum(starts.values())
    problems = solution_problems(starts, reported, headcount)
    return not problems, ["FAIL" if problems else "PASS", *problems, "", *summary(headcount)]


def main(argv):
    if any(arg in ("-h", "--help") for arg in argv):
        print(__doc__.strip())
        return 0
    if len(argv) > 1:
        print("FAIL")
        print("format: give at most one solution file, for example: python check.py solution.json")
        return 1
    path = Path(argv[0]) if argv else DEFAULT_SOLUTION
    passed, lines = check(path)
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

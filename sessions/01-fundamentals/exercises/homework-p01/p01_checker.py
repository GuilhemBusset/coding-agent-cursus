"""Independent P01 checker: feasibility and objective of a solution file, without a solver.

Standard library only. It reads the CSVs and the solution file itself and never imports a
model or a solver, so a bug in the model cannot also hide in the check. Every rule it
applies is stated in PROBLEM.md.

    uv run python p01_checker.py [solution.json] [--turn-in]

The first output line is PASS or FAIL. Each failure line starts with the contract it
breaks: data, format, status, coverage, integrality, sequence, maintenance,
charging-window, charging-power, charger-capacity, soc, objective or optimality.
Exit codes: 0 PASS, 1 a contract fails, 2 nothing could be checked (data, format or
arguments). With --turn-in (what exercises/turn-in-check.sh runs) a missing solution only
warns, a data or format problem blocks with exit 1, and any other verdict exits 0 so that
an infeasible or suboptimal attempt is still turned in.
"""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DEFAULT_SOLUTION = HERE / "solution.json"

# The optimum of this instance, found by the instructor's reference model with HiGHS at a
# closed MIP gap (see INSTRUCTOR.md). The reference model itself is not in this repository.
KNOWN_OPTIMUM = 835.52

# SHA-256 of each data file after CRLF -> LF normalisation: the checker only certifies this
# exact instance.
DATA_SHA256 = {
    "deadhead_minutes.csv": "f9e12f6458de38a56893474dfd9a107bedaa7f5950d55ce283ffb51e4f5f0add",
    "depots.csv": "f8acb8a488996a2405d9484d8aedba91140016f15976b94904657c11449d722f",
    "parameters.csv": "75bcf6342d7249b645d257c4fbb377b2a475900f618919b20bc0cb3d729f4558",
    "tariff_blocks.csv": "4d48e1b52806ea08d4b97dadd279c778af31e8d1ec9d3e1ef3868a5af04409ed",
    "trips.csv": "86d06f48c4bb469cb932210001c33a78c6ad68dc19a4654baf77984dc3f8d661",
    "vehicles.csv": "f7ae8c98d711122cc12352af94189cd98e693b3453539b78d03916871034e03b",
}

ACCEPTED = ("optimal", "feasible")
CHARGERS = ("slow", "fast")
SLOT = 30
DAY = 24 * 60
TOL = 1e-6
SCHEDULE_CONTRACTS = (
    "sequence", "maintenance", "charging-window", "charging-power", "charger-capacity", "soc",
)
MAX_LINES_PER_CONTRACT = 5


class DataError(Exception):
    """The instance in data/ is missing, edited or unreadable."""


def tolerance(value):
    return TOL * max(1.0, abs(value))


def parse_time(value):
    """Return minutes after midnight for 'HH:MM' (00:00 to 24:00), or None."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    hours, mins = value[:2], value[3:]
    if not (hours.isdigit() and mins.isdigit() and hours.isascii() and mins.isascii()):
        return None
    hours, mins = int(hours), int(mins)
    if hours > 24 or mins > 59 or (hours == 24 and mins):
        return None
    return hours * 60 + mins


def hhmm(value):
    value = int(round(value))
    return f"{value // 60:02d}:{value % 60:02d}"


def _number(value):
    """Return value as a float when it is a finite JSON number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _rows(data_dir, name):
    with (data_dir / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_data(data_dir=DATA_DIR):
    """Read the pinned instance. Raises DataError if any file is missing or edited."""
    data_dir = Path(data_dir)
    for name, digest in DATA_SHA256.items():
        path = data_dir / name
        if not path.is_file():
            raise DataError(f"data: missing data/{name}")
        actual = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != digest:
            raise DataError(
                f"data: data/{name} differs from the pinned P01 instance; restore it "
                "(git checkout -- data/) and solve the original data"
            )

    def time(value):
        minutes = parse_time(value)
        if minutes is None:
            raise ValueError(f"bad time {value!r}")
        return minutes

    try:
        parameters = {r["parameter"]: float(r["value"]) for r in _rows(data_dir, "parameters.csv")}
        data = {
            "trips": {
                r["trip_id"]: {
                    "origin": r["origin_depot"], "destination": r["destination_depot"],
                    "start": time(r["start_time"]), "end": time(r["end_time"]),
                    "energy": float(r["energy_kwh"]), "penalty": float(r["cancel_penalty"]),
                }
                for r in _rows(data_dir, "trips.csv")
            },
            "vehicles": {
                r["vehicle_id"]: {
                    "home": r["home_depot"], "min_soc": float(r["min_soc_kwh"]),
                    "initial_soc": float(r["initial_soc_kwh"]), "max_soc": float(r["max_soc_kwh"]),
                    "max_charge_kw": float(r["max_charge_kw"]),
                    "maintenance": (
                        (time(r["maintenance_start"]), time(r["maintenance_end"]))
                        if r["maintenance_start"] else None
                    ),
                }
                for r in _rows(data_dir, "vehicles.csv")
            },
            "depots": {
                r["depot"]: {
                    "count": {k: int(r["chargers_" + k]) for k in CHARGERS},
                    "kw": {k: float(r[k + "_kw"]) for k in CHARGERS},
                }
                for r in _rows(data_dir, "depots.csv")
            },
            "deadhead": {
                (r["from_depot"], r["to_depot"]): (float(r["minutes"]), float(r["energy_kwh"]))
                for r in _rows(data_dir, "deadhead_minutes.csv")
            },
            "tariffs": [
                (time(r["start_time"]), time(r["end_time"]), float(r["price_per_kwh"]))
                for r in _rows(data_dir, "tariff_blocks.csv")
            ],
            "deadhead_cost_per_minute": parameters["deadhead_cost_per_minute"],
            "degradation_cost_per_kwh": parameters["degradation_cost_per_kwh"],
        }
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise DataError(f"data: cannot read the instance in {data_dir}: {error}") from None
    return data


@dataclass
class Report:
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fatal: bool = False  # data or format: nothing could be checked
    skipped: tuple = ()  # contracts that could not be assessed
    objective: float = None  # recomputed cost
    breakdown: dict = None
    reported: float = None


def _validate(solution, data):
    """Return format problems; an empty list means every field has the documented shape."""
    if not isinstance(solution, dict):
        return ["format: the solution must be a JSON object with status, objective, assign, cancel and charge"]
    errors = []
    missing = [key for key in ("status", "objective", "assign", "cancel", "charge") if key not in solution]
    if missing:
        errors.append(f"format: missing top-level field(s) {', '.join(missing)}")
    if "status" in solution and not isinstance(solution["status"], str):
        errors.append("format: status must be a string")
    if "objective" in solution and _number(solution["objective"]) is None:
        errors.append(f"format: objective must be a finite number, got {solution['objective']!r}")
    if "solve_seconds" in solution and _number(solution["solve_seconds"]) is None:
        errors.append("format: solve_seconds, when present, must be a finite number")

    assign = solution.get("assign", {})
    if not isinstance(assign, dict):
        errors.append("format: assign must map vehicle IDs to {trip ID: value} objects")
    else:
        for vid, by_trip in assign.items():
            if vid not in data["vehicles"]:
                errors.append(f"format: assign names unknown vehicle {vid!r}")
            elif not isinstance(by_trip, dict):
                errors.append(f"format: assign[{vid!r}] must map trip IDs to values")
            else:
                for tid, value in by_trip.items():
                    if tid not in data["trips"]:
                        errors.append(f"format: assign[{vid!r}] names unknown trip {tid!r}")
                    elif _number(value) is None:
                        errors.append(f"format: assign[{vid!r}][{tid!r}] must be a finite number, got {value!r}")

    cancel = solution.get("cancel", {})
    if not isinstance(cancel, dict):
        errors.append("format: cancel must map trip IDs to values")
    else:
        for tid, value in cancel.items():
            if tid not in data["trips"]:
                errors.append(f"format: cancel names unknown trip {tid!r}")
            elif _number(value) is None:
                errors.append(f"format: cancel[{tid!r}] must be a finite number, got {value!r}")

    charge = solution.get("charge", {})
    if not isinstance(charge, dict):
        errors.append("format: charge must map vehicle IDs to lists of {slot, charger, kwh}")
    else:
        for vid, entries in charge.items():
            if vid not in data["vehicles"]:
                errors.append(f"format: charge names unknown vehicle {vid!r}")
                continue
            if not isinstance(entries, list):
                errors.append(f"format: charge[{vid!r}] must be a list of {{slot, charger, kwh}}")
                continue
            for index, entry in enumerate(entries):
                where = f"charge[{vid!r}][{index}]"
                if not isinstance(entry, dict):
                    errors.append(f"format: {where} must be an object with slot, charger and kwh")
                    continue
                extra = sorted(set(entry) - {"slot", "charger", "kwh"})
                if extra:
                    errors.append(
                        f"format: {where} has unknown key(s) {', '.join(map(repr, extra))}; "
                        "only slot, charger and kwh are read (the depot follows from the schedule)"
                    )
                if parse_time(entry.get("slot")) is None:
                    errors.append(f"format: {where} slot must be 'HH:MM', got {entry.get('slot')!r}")
                if entry.get("charger") not in CHARGERS:
                    errors.append(f"format: {where} charger must be 'slow' or 'fast', got {entry.get('charger')!r}")
                if _number(entry.get("kwh")) is None:
                    errors.append(f"format: {where} kwh must be a finite number, got {entry.get('kwh')!r}")
    return errors


def _price(data, minute):
    minute = min(minute, DAY - 1)
    return next(price for start, end, price in data["tariffs"] if start <= minute < end)


def _schedule(data, assign, charge, fail):
    """Replay every vehicle's day; return (energy cost, deadhead cost)."""
    rate = data["deadhead_cost_per_minute"]
    wear = data["degradation_cost_per_kwh"]
    energy_cost = deadhead_cost = 0.0
    occupancy = Counter()
    for vid, vehicle in data["vehicles"].items():
        home = vehicle["home"]
        chosen = [tid for tid, value in assign.get(vid, {}).items() if value > 0.5]
        legs = sorted(chosen, key=lambda tid: (data["trips"][tid]["start"], tid))
        moves = []  # (start, end, kWh, label)
        waits = []  # (from, until, depot)
        now, where = 0.0, home
        for tid in legs:
            trip = data["trips"][tid]
            minutes, kwh = data["deadhead"][where, trip["origin"]]
            arrival = now + minutes
            moves.append((now, arrival, kwh, f"deadhead {where}->{trip['origin']}"))
            deadhead_cost += minutes * rate
            if arrival > trip["start"] + 1e-9:
                fail("sequence", f"sequence: {vid} reaches {trip['origin']} at {hhmm(arrival)}, after {tid} departs at {hhmm(trip['start'])}")
            waits.append((arrival, trip["start"], trip["origin"]))
            moves.append((trip["start"], trip["end"], trip["energy"], f"leg {tid}"))
            now, where = trip["end"], trip["destination"]
        if legs:
            minutes, kwh = data["deadhead"][where, home]
            arrival = now + minutes
            moves.append((now, arrival, kwh, f"deadhead {where}->{home}"))
            deadhead_cost += minutes * rate
            if arrival > DAY + 1e-9:
                fail("sequence", f"sequence: {vid} returns home to {home} at {hhmm(arrival)}, after 24:00")
            now = arrival
        waits.append((now, DAY, home))

        maintenance = vehicle["maintenance"]

        def in_maintenance(start, end):
            return maintenance is not None and end > start and start < maintenance[1] and end > maintenance[0]

        for start, end, _, label in moves:
            if in_maintenance(start, end):
                fail("maintenance", f"maintenance: {vid} drives ({label}, {hhmm(start)}-{hhmm(end)}) during its maintenance window {hhmm(maintenance[0])}-{hhmm(maintenance[1])}")

        events = [(end, -kwh, label) for start, end, kwh, label in moves]
        seen = set()
        for entry in charge.get(vid, []):
            start, kind, kwh = parse_time(entry["slot"]), entry["charger"], float(entry["kwh"])
            end = start + SLOT
            depot = None
            if start % SLOT or end > DAY:
                fail("charging-window", f"charging-window: {vid} charges at {entry['slot']}, which is not one of the 48 slots 00:00, 00:30, ..., 23:30")
            elif start in seen:
                fail("charging-window", f"charging-window: {vid} charges twice in slot {entry['slot']}")
            else:
                depot = next((d for a, b, d in waits if a <= start and end <= b), None)
                if depot is None:
                    fail("charging-window", f"charging-window: {vid} charges in slot {entry['slot']} but is not waiting at a depot for that whole slot")
            seen.add(start)
            if in_maintenance(start, end):
                fail("maintenance", f"maintenance: {vid} charges in slot {entry['slot']}, inside its maintenance window {hhmm(maintenance[0])}-{hhmm(maintenance[1])}")
            if depot is not None:
                kw = data["depots"][depot]["kw"][kind]
                occupancy[depot, start, kind] += 1
            else:  # no defined depot: the fastest charger of that type anywhere is a necessary bound
                kw = max(d["kw"][kind] for d in data["depots"].values())
            limit = min(kw, vehicle["max_charge_kw"]) * SLOT / 60
            if kwh < -TOL:
                fail("charging-power", f"charging-power: {vid} has a negative charge of {kwh:g} kWh in slot {entry['slot']}")
            elif kwh > limit + tolerance(limit):
                at = f"a {kind} charger at {depot}" if depot else f"any {kind} charger"
                fail("charging-power", f"charging-power: {vid} charges {kwh:g} kWh in slot {entry['slot']}, above {limit:g} kWh for {at} (min(charger kW, max_charge_kw) x 0.5 h)")
            energy_cost += kwh * (_price(data, start) + wear)
            events.append((end, kwh, f"charge {entry['slot']}"))

        soc = vehicle["initial_soc"]
        low, high = vehicle["min_soc"], vehicle["max_soc"]
        for when, delta, label in sorted(events, key=lambda e: (e[0], e[1])):
            soc += delta
            if soc < low - tolerance(low):
                fail("soc", f"soc: {vid} drops to {soc:.3f} kWh after {label} (ends {hhmm(when)}), below min_soc_kwh {low:g}")
                break
            if soc > high + tolerance(high):
                fail("soc", f"soc: {vid} reaches {soc:.3f} kWh after {label} (ends {hhmm(when)}), above max_soc_kwh {high:g}")
                break
        else:
            start_soc = vehicle["initial_soc"]
            if soc < start_soc - tolerance(start_soc):
                fail("soc", f"soc: {vid} ends the day at {soc:.3f} kWh, below its initial {start_soc:g} kWh")

    for (depot, start, kind), count in sorted(occupancy.items()):
        available = data["depots"][depot]["count"][kind]
        if count > available:
            fail("charger-capacity", f"charger-capacity: {count} vehicle(s) charge on {kind} chargers at {depot} in slot {hhmm(start)}, but {depot} has {available} {kind} charger(s)")
    return energy_cost, deadhead_cost


def check(solution, data=None):
    """Check a solution object against every contract and return a Report."""
    report = Report()
    if data is None:
        try:
            data = load_data()
        except DataError as error:
            report.failures.append(str(error))
            report.fatal = True
            return report
    if (isinstance(solution, dict) and isinstance(solution.get("status"), str)
            and solution["status"] not in ACCEPTED and solution.get("objective") is None):
        report.failures.append(
            f"status: {solution['status']!r} is not an accepted status ({' or '.join(ACCEPTED)}); there is no plan to check"
        )
        report.skipped = ("coverage", "integrality", *SCHEDULE_CONTRACTS, "objective", "optimality")
        return report
    errors = _validate(solution, data)
    if errors:
        report.failures.extend(errors)
        report.fatal = True
        return report

    counts = Counter()

    def fail(contract, message):
        counts[contract] += 1
        if counts[contract] <= MAX_LINES_PER_CONTRACT:
            report.failures.append(message)

    report.reported = float(solution["objective"])
    if solution["status"] not in ACCEPTED:
        fail("status", f"status: {solution['status']!r} is not an accepted status ({' or '.join(ACCEPTED)}); a time-limit stop with a plan is 'feasible'")

    assign = {vid: {tid: float(v) for tid, v in by_trip.items()} for vid, by_trip in solution["assign"].items()}
    cancel = {tid: float(v) for tid, v in solution["cancel"].items()}
    for tid in data["trips"]:
        covered = cancel.get(tid, 0.0) + sum(by_trip.get(tid, 0.0) for by_trip in assign.values())
        if abs(covered - 1.0) > TOL:
            fail("coverage", f"coverage: trip {tid} has assignments + cancellation = {covered:g}; it must be covered by exactly one vehicle or cancelled")

    fractional = [
        (f"assign[{vid}][{tid}]", value) for vid, by_trip in assign.items() for tid, value in by_trip.items()
        if min(abs(value), abs(value - 1.0)) > TOL
    ] + [(f"cancel[{tid}]", value) for tid, value in cancel.items() if min(abs(value), abs(value - 1.0)) > TOL]
    if fractional:
        name, value = fractional[0]
        report.failures.append(
            f"integrality: {len(fractional)} assignment/cancellation value(s) are not 0 or 1 "
            f"(first: {name} = {value:g}); a fractional plan has no schedule, so the "
            f"{', '.join(SCHEDULE_CONTRACTS)}, objective and optimality checks are skipped"
        )
        report.skipped = (*SCHEDULE_CONTRACTS, "objective", "optimality")
        return report

    penalty = sum(trip["penalty"] * cancel.get(tid, 0.0) for tid, trip in data["trips"].items())
    energy_cost, deadhead_cost = _schedule(data, assign, solution["charge"], fail)
    for contract, count in counts.items():
        if count > MAX_LINES_PER_CONTRACT:
            report.failures.append(f"{contract}: ... and {count - MAX_LINES_PER_CONTRACT} more like this")
    total = penalty + energy_cost + deadhead_cost
    report.objective = total
    report.breakdown = {"cancellation penalties": penalty, "energy and degradation": energy_cost, "deadhead": deadhead_cost}
    if abs(report.reported - total) > tolerance(total):
        report.failures.append(f"objective: the solution reports {report.reported:.6f} but its decisions cost {total:.6f}")

    infeasible = set(counts) - {"status"}
    if infeasible:
        report.skipped = ("optimality",)
    elif total > KNOWN_OPTIMUM + tolerance(KNOWN_OPTIMUM):
        report.failures.append(
            f"optimality: this feasible plan costs {total:.6f}, {total - KNOWN_OPTIMUM:.6f} above the known optimum {KNOWN_OPTIMUM:.6f}"
        )
    elif total < KNOWN_OPTIMUM - tolerance(KNOWN_OPTIMUM):
        report.warnings.append(
            f"WARNING: this plan costs {total:.6f}, below the known optimum {KNOWN_OPTIMUM:.6f}. "
            "If every contract passes, report it to the instructor with your solution.json."
        )
    return report


def problems(solution, data=None):
    """Return the failure lines; each starts with the contract it breaks."""
    return list(check(solution, data).failures)


def summary(solution, data=None):
    """Return a short text summary: recomputed objective and breakdown, known optimum, gap."""
    return _summary_lines(check(solution, data))


def _summary_lines(report):
    lines = []
    if report.objective is None:
        lines.append("  recomputed objective = not available (" + (
            "the solution could not be read" if report.fatal else "fractional or missing plan") + ")")
    else:
        lines.append(f"  recomputed objective = {report.objective:.6f}")
        for name, value in report.breakdown.items():
            lines.append(f"    {name} = {value:.6f}")
        lines.append(f"  reported objective = {report.reported:.6f}")
    lines.append(f"  known optimum = {KNOWN_OPTIMUM:.6f}")
    if report.objective is not None:
        gap = report.objective - KNOWN_OPTIMUM
        lines.append(f"  gap to known optimum = {gap:.6f} ({gap / max(1.0, abs(KNOWN_OPTIMUM)):.4%})")
    if report.skipped:
        lines.append("  not assessed = " + ", ".join(report.skipped))
    return "\n".join(lines)


def _say(text=""):
    # ASCII only, so any console (including Windows code pages) prints it.
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a P01 solution file without a solver.")
    parser.add_argument("solution", nargs="?", default=str(DEFAULT_SOLUTION),
                        help="solution file (default: solution.json next to this checker)")
    parser.add_argument("--turn-in", action="store_true",
                        help="turn-in gate: warn on a missing file, block only data/format problems")
    args = parser.parse_args(argv)
    path = Path(args.solution)
    fatal_code = 1 if args.turn_in else 2

    if not path.is_file():
        if args.turn_in:
            _say(f"WARNING: no solution.json to check at {path}. Turning in without a checked plan;")
            _say("run your model to write solution.json, then `uv run python p01_checker.py`.")
            return 0
        _say("FAIL")
        _say(f"format: solution file not found: {path}")
        return 2
    try:
        data = load_data()
    except DataError as error:
        _say("FAIL")
        _say(str(error))
        return fatal_code
    try:
        solution = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        _say("FAIL")
        _say(f"format: {path.name} is not valid JSON ({error})")
        return fatal_code

    report = check(solution, data)
    _say("FAIL" if report.failures else "PASS")
    for line in report.failures:
        _say(line)
    for line in report.warnings:
        _say(line)
    _say(_summary_lines(report))
    if report.fatal:
        return fatal_code
    if args.turn_in:
        _say("Turn-in check: the plan above is submitted as is; grading reruns the checker from main.")
        return 0
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())

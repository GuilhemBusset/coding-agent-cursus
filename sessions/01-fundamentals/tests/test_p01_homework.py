"""Locked P01 acceptance checks (no reference model or real solution in-tree).

Run from the session: uv run pytest -q tests/test_p01_homework.py.
The oracle below interprets the agreed movement/charging rules independently;
it is a verifier, not a model or a solver. All pack code runs in subprocesses.
Starter assertions intentionally cease to pass on a completed homework branch.
"""

import ast
from collections import Counter
from copy import deepcopy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / "exercises/homework-p01"
UPSTREAM = SESSION / "tests/fixtures/p01_upstream"
UPSTREAM_COMMIT = "28228a90eaacc35f82395a2b8ccef8d5a302c036"
# Raw-byte hashes observed in the agreed local upstream clone, before the port.
# These identify source artifacts, never a solution or revised instance.
UPSTREAM_HASHES = {
    "LICENSE": "834c9a7d9ead7c08a7a2c9fde89a051b1f8ff89457dfd11dd1f1e4ed27bffa76",
    "exercise-statement.md": "deb2f28a5b7abc510805ea1718218eab4b7621cc6880bed859d26ae55305d290",
    "data/deadhead_minutes.csv": "85fa296ef8a6e9443f37f7b5bdf8a8419ca5d6febb3c46a192848680ff0d629b",
    "data/depots.csv": "529aa3af2f2c7a81824b6eb231e7145ab3d841942ab11246fe00eb57bf70a004",
    "data/tariff_blocks.csv": "ce6bfaf10d1679af2fbdd7e25ee7b980bf6fdae4bca4d6edc355cd104ad880fb",
    "data/trips.csv": "49961fac9e8c12797e6672156455fb21049eeb7006da4a85503fca384cfee866",
    "data/vehicles.csv": "4a09cd6d9f90fca02f243b51785c92f58aa2f0879d0ef9e7c788295bf0203102",
}
CONTRACTS = {
    "data", "format", "status", "coverage", "integrality", "sequence",
    "maintenance", "charging-window", "charging-power", "charger-capacity",
    "soc", "objective", "optimality",
}
SCHEDULE_CONTRACTS = {
    "sequence", "maintenance", "charging-window", "charging-power",
    "charger-capacity", "soc",
}


def child_env():
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", UV_OFFLINE="1")
    return env


def run(args, cwd, timeout=30):
    return subprocess.run(
        [str(a) for a in args], cwd=cwd, env=child_env(), text=True,
        capture_output=True, timeout=timeout, check=False,
    )


def output(result):
    return result.stdout + "\n" + result.stderr


def required(path):
    assert path.is_file(), f"delivery: missing {path.relative_to(SESSION)}"
    return path.read_text(encoding="utf-8")


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        result = list(reader)
        assert reader.fieldnames and result, f"data: empty CSV {path}"
        assert all(None not in row and None not in row.values() for row in result)
        return result


def minute(value):
    assert re.fullmatch(r"\d\d:\d\d", value), f"data: bad time {value!r}"
    h, m = map(int, value.split(":"))
    assert 0 <= h <= 24 and 0 <= m < 60 and (h < 24 or m == 0)
    return h * 60 + m


def hhmm(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def literal(name, source=None):
    tree = ast.parse(source if source is not None else required(PACK / "p01_checker.py"))
    values = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            values.append(ast.literal_eval(node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            values.append(ast.literal_eval(node.value))
    assert len(values) == 1, f"checker: require one literal {name}"
    return values[0]


def replace_literal(path, name, value):
    """Change an oracle threshold only in a disposable copy, never weaken a gate."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    targets = [n for n in tree.body if (
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
    ) or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name)]
    assert len(targets) == 1, f"checker: missing literal {name}"
    node = targets[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [f"{name} = {value!r}\n"]
    path.write_text("".join(lines), encoding="utf-8")


def read_instance(directory=PACK):
    data = directory / "data"
    trips = rows(data / "trips.csv")
    vehicles = rows(data / "vehicles.csv")
    depots = rows(data / "depots.csv")
    parameter_rows = rows(data / "parameters.csv")
    names = ("deadhead_cost_per_minute", "degradation_cost_per_kwh")
    # The design fixes the parameter names, not the CSV's long/wide layout.
    parameters = {}
    for name in names:
        for row in parameter_rows:
            if name in row:
                parameters[name] = float(row[name])
            elif name in row.values():
                candidates = [v for v in row.values() if v != name]
                numeric = []
                for value in candidates:
                    try:
                        numeric.append(float(value))
                    except ValueError:
                        pass
                assert len(numeric) == 1, f"data: ambiguous value for {name}"
                parameters[name] = numeric[0]
        assert name in parameters, f"data: parameters.csv must define {name}"
    return {
        "trips": {r["trip_id"]: r for r in trips},
        "vehicles": {r["vehicle_id"]: r for r in vehicles},
        "depots": {r["depot"]: r for r in depots},
        "deadhead": {(r["from_depot"], r["to_depot"]): r for r in rows(data / "deadhead_minutes.csv")},
        "tariffs": rows(data / "tariff_blocks.csv"), "parameters": parameters,
    }


def tolerance(value):
    return 1e-6 * max(1, abs(value))


def oracle(data, solution, ignore_deadhead_energy=False):
    """Recompute a well-formed integral plan independently of all pack code.

    An out-of-wait charge has no defined depot. Still credit its energy and
    tariff, and use the largest depot power as a necessary bound; the window
    violation itself is always reported. This also audits ablation incumbents.
    """
    failures = set()
    binaries = list(solution.get("cancel", {}).values())
    binaries.extend(v for assignment in solution.get("assign", {}).values() for v in assignment.values())
    if any(not math.isfinite(v) or min(abs(v), abs(v - 1)) > 1e-6 for v in binaries):
        failures.add("integrality")
    penalty = sum(float(t["cancel_penalty"]) * solution.get("cancel", {}).get(tid, 0)
                  for tid, t in data["trips"].items())
    energy_cost = deadhead_cost = 0.0
    occupancy = Counter()
    for tid in data["trips"]:
        covered = solution.get("cancel", {}).get(tid, 0) + sum(
            assignment.get(tid, 0) for assignment in solution.get("assign", {}).values())
        if abs(covered - 1) > 1e-6:
            failures.add("coverage")
    for vid, vehicle in data["vehicles"].items():
        assigned = solution.get("assign", {}).get(vid, {})
        legs = sorted((data["trips"][tid] for tid, value in assigned.items() if value > .5),
                      key=lambda t: minute(t["start_time"]))
        home = vehicle["home_depot"]
        moves, waits = [], []
        now, location = 0, home
        for leg in legs:
            dh = data["deadhead"][location, leg["origin_depot"]]
            arrival = now + float(dh["minutes"])
            moves.append((now, arrival, 0 if ignore_deadhead_energy else float(dh["energy_kwh"])))
            deadhead_cost += float(dh["minutes"]) * data["parameters"]["deadhead_cost_per_minute"]
            start, end = minute(leg["start_time"]), minute(leg["end_time"])
            if arrival > start:
                failures.add("sequence")
            waits.append((arrival, start, leg["origin_depot"]))
            moves.append((start, end, float(leg["energy_kwh"])))
            now, location = end, leg["destination_depot"]
        if legs:
            dh = data["deadhead"][location, home]
            arrival = now + float(dh["minutes"])
            moves.append((now, arrival, 0 if ignore_deadhead_energy else float(dh["energy_kwh"])))
            deadhead_cost += float(dh["minutes"]) * data["parameters"]["deadhead_cost_per_minute"]
            if arrival > 1440:
                failures.add("sequence")
            now = arrival
        waits.append((now, 1440, home))
        maintenance = None
        if vehicle["maintenance_start"]:
            maintenance = (minute(vehicle["maintenance_start"]), minute(vehicle["maintenance_end"]))
        events = [(end, -energy) for start, end, energy in moves]
        for start, end, _ in moves:
            if maintenance and end > start and start < maintenance[1] and end > maintenance[0]:
                failures.add("maintenance")
        seen_slots = set()
        for charge in solution.get("charge", {}).get(vid, []):
            start, kind, kwh = minute(charge["slot"]), charge["charger"], charge["kwh"]
            end = start + 30
            matching = [d for a, b, d in waits if a <= start and end <= b]
            if start % 30 or end > 1440 or not matching or start in seen_slots:
                failures.add("charging-window")
            seen_slots.add(start)
            if maintenance and start < maintenance[1] and end > maintenance[0]:
                failures.add("maintenance")
            if matching:
                depot = matching[0]
                kw = float(data["depots"][depot][kind + "_kw"])
                occupancy[depot, start, kind] += 1
            else:
                kw = max(float(d[kind + "_kw"]) for d in data["depots"].values())
            limit = min(kw, float(vehicle["max_charge_kw"])) * .5
            if kwh < -1e-6 or kwh > limit + tolerance(limit):
                failures.add("charging-power")
            price = next(float(t["price_per_kwh"]) for t in data["tariffs"]
                         if minute(t["start_time"]) <= min(start, 1439) < minute(t["end_time"]))
            energy_cost += kwh * (price + data["parameters"]["degradation_cost_per_kwh"])
            events.append((end, kwh))
        soc = float(vehicle["initial_soc_kwh"])
        low, high = float(vehicle["min_soc_kwh"]), float(vehicle["max_soc_kwh"])
        for _, delta in sorted(events):
            soc += delta
            if soc < low - tolerance(low) or soc > high + tolerance(high):
                failures.add("soc")
        if soc < float(vehicle["initial_soc_kwh"]) - tolerance(float(vehicle["initial_soc_kwh"])):
            failures.add("soc")
    for (depot, _, kind), count in occupancy.items():
        if count > int(data["depots"][depot]["chargers_" + kind]):
            failures.add("charger-capacity")
    return failures, penalty + energy_cost + deadhead_cost, (penalty, energy_cost, deadhead_cost)


def plan(data, assign=None, charge=None):
    assign = assign or {}
    solution = {
        "status": "feasible", "objective": 0.0, "assign": assign,
        "cancel": {tid: 1 - sum(a.get(tid, 0) for a in assign.values()) for tid in data["trips"]},
        "charge": charge or {},
    }
    solution["objective"] = oracle(data, solution)[1]
    return solution


def checker(directory, solution=None, args=()):
    if solution is not None:
        (directory / "solution.json").write_text(json.dumps(solution), encoding="utf-8")
    result = run([sys.executable, "-I", "-S", directory / "p01_checker.py", *args], directory)
    assert result.stdout.isascii() and result.stderr.isascii(), "checker: ASCII CLI output required"
    assert "Traceback" not in output(result), output(result)
    return result


def failure_tags(result):
    return {line.split(":", 1)[0] for line in result.stdout.splitlines() if line.split(":", 1)[0] in CONTRACTS}


def verdict(result, code, expected=()):
    assert result.returncode == code, output(result)
    assert result.stdout.splitlines()[0] == ("PASS" if code == 0 else "FAIL"), output(result)
    assert set(expected) <= failure_tags(result), output(result)


@pytest.fixture
def pack(tmp_path):
    assert PACK.is_dir(), "delivery: homework-p01 has not been implemented"
    return Path(shutil.copytree(PACK, tmp_path / "pack"))


@pytest.fixture(scope="module")
def instance():
    assert PACK.is_dir(), "delivery: homework-p01 has not been implemented"
    return read_instance()


def test_provenance_archive_and_revision_rules():
    doc = required(PACK / "INSTRUCTOR.md")
    assert UPSTREAM_COMMIT in doc, "provenance: record upstream commit"
    for name, digest in UPSTREAM_HASHES.items():
        path = UPSTREAM / name
        assert path.is_file(), f"provenance: missing {name}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"provenance: changed upstream {name}"
        assert digest in doc, f"provenance: document SHA256 of {name}"
    original_depots = rows(UPSTREAM / "data/depots.csv")
    depot_names = {r["depot_id"]: r["depot"] for r in original_depots}
    specs = {
        "trips.csv": (("trip_id",), set()),
        "vehicles.csv": (("vehicle_id",), {"initial_soc_kwh", "max_soc_kwh"}),
        "depots.csv": (("depot",), {"chargers_slow", "chargers_fast"}),
        "deadhead_minutes.csv": (("from_depot", "to_depot"), set()),
        "tariff_blocks.csv": (("block_id",), set()),
    }
    numeric_columns = {
        "service_km", "energy_kwh", "cancel_penalty", "battery_kwh", "min_soc_kwh",
        "max_charge_kw", "slow_kw", "fast_kw", "minutes", "price_per_kwh",
    }
    tightened = set()
    for filename, (keys, decreasing) in specs.items():
        originals = {tuple(row[k] for k in keys): row for row in rows(UPSTREAM / "data" / filename)}
        revised = rows(PACK / "data" / filename)
        ids = [tuple(row[k] for k in keys) for row in revised]
        assert len(ids) == len(set(ids)), f"data: duplicate ID in {filename}"
        assert set(ids) <= originals.keys(), f"provenance: invented row in {filename}"
        if filename not in {"trips.csv", "vehicles.csv"}:
            assert set(ids) == originals.keys(), f"provenance: only trips and vehicles may be subsetted ({filename})"
        for key, row in zip(ids, revised):
            expected = dict(originals[key])
            if filename == "depots.csv":
                del expected["depot_id"]
            if filename == "vehicles.csv":
                expected["home_depot"] = depot_names[expected["home_depot"]]
            if filename == "trips.csv" and key == ("T180",):
                expected["origin_depot"] = "D_D"
            if filename == "tariff_blocks.csv":
                expected["end_time"] = hhmm(minute(expected["end_time"]) + 1)
            assert row.keys() == expected.keys(), f"provenance: columns changed in {filename}"
            for column in row:
                if column in decreasing:
                    assert 0 <= float(row[column]) <= float(expected[column]), f"provenance: {column} may only decrease"
                    if float(row[column]) < float(expected[column]):
                        tightened.add(column)
                elif column in numeric_columns:
                    assert float(row[column]) == float(expected[column]), f"provenance: unapproved numeric revision {filename} {key} {column}"
                else:
                    assert row[column] == expected[column], f"provenance: unapproved revision {filename} {key} {column}"
    assert tightened & {"initial_soc_kwh", "max_soc_kwh"}, "data: tighten vehicle capacity"
    assert tightened & {"chargers_slow", "chargers_fast"}, "data: tighten charger capacity"


def test_data_integrity_and_tariffs(instance):
    d = instance
    depots = set(d["depots"])
    assert depots and d["trips"] and d["vehicles"]
    assert all((a, b) in d["deadhead"] for a in depots for b in depots), "data: complete deadhead matrix"
    assert all(a in depots and b in depots for a, b in d["deadhead"])
    for trip in d["trips"].values():
        assert {trip["origin_depot"], trip["destination_depot"]} <= depots
        assert minute(trip["start_time"]) < minute(trip["end_time"])
        assert float(trip["cancel_penalty"]) > 0 and float(trip["energy_kwh"]) > 0
    homes = Counter(v["home_depot"] for v in d["vehicles"].values())
    assert homes.keys() <= depots
    assert any(homes[name] > int(depot["chargers_fast"]) for name, depot in d["depots"].items())
    assert any(v["maintenance_start"] for v in d["vehicles"].values()), "data: keep a maintenance vehicle"
    for v in d["vehicles"].values():
        assert 0 <= float(v["min_soc_kwh"]) <= float(v["initial_soc_kwh"]) <= float(v["max_soc_kwh"]) <= float(v["battery_kwh"])
        assert float(v["max_charge_kw"]) > 0
        assert bool(v["maintenance_start"]) == bool(v["maintenance_end"])
        if v["maintenance_start"]:
            assert minute(v["maintenance_start"]) < minute(v["maintenance_end"])
    end = 0
    for tariff in sorted(d["tariffs"], key=lambda t: minute(t["start_time"])):
        start, stop = minute(tariff["start_time"]), minute(tariff["end_time"])
        assert start == end and start % 30 == stop % 30 == 0 and stop > start
        assert math.isfinite(float(tariff["price_per_kwh"])) and float(tariff["price_per_kwh"]) >= 0
        end = stop
    assert end == 1440, "data: tariffs must cover the whole day exactly once"
    assert all(math.isfinite(v) and v >= 0 for v in d["parameters"].values())


def test_checker_solver_independence():
    source = required(PACK / "p01_checker.py")
    allow = {"json", "csv", "hashlib", "math", "sys", "pathlib", "argparse", "collections", "dataclasses", "typing"}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in allow for a in node.names), "checker: import outside stdlib allowlist"
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and (node.module or "").split(".")[0] in allow
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            assert name not in {"__import__", "exec", "eval", "system", "popen", "spawn", "fork"}, "checker: dynamic execution forbidden"
    functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"load_data", "problems", "summary"} <= functions
    assert literal("DATA_SHA256", source), "checker: literal data pin required"


def test_checker_all_cancel_objective_and_sparse_entries(pack, instance):
    solution = plan(instance)
    expected = sum(float(t["cancel_penalty"]) for t in instance["trips"].values())
    assert solution["objective"] == expected
    result = checker(pack, solution)
    verdict(result, 1, {"optimality"})
    assert failure_tags(result) == {"optimality"}, output(result)
    # Both functions are exercised without depending on the shape of summary().
    script = """import json, p01_checker as c
s = json.load(open('solution.json'))
assert c.load_data() is not None
errors = c.problems(s)
assert errors and all(str(e).startswith('optimality:') for e in errors), errors
print(c.summary(s))
"""
    result = run([sys.executable, "-S", "-c", script], pack)
    assert result.returncode == 0, output(result)
    summary_numbers = re.findall(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", result.stdout.replace(",", ""))
    assert any(math.isclose(float(v), expected, rel_tol=1e-6, abs_tol=1e-6) for v in summary_numbers), "checker: summary must expose recomputed cost"
    # Missing individual entries mean zero, rather than demanding a dense plan.
    dense = deepcopy(solution)
    dense["assign"] = {v: dict.fromkeys(instance["trips"], 0.0) for v in instance["vehicles"]}
    dense["charge"] = dict.fromkeys(instance["vehicles"], [])
    assert failure_tags(checker(pack, dense)) == {"optimality"}


def test_checker_optimum_boundary_and_better_plan_warning(pack, instance):
    solution = plan(instance)
    value = solution["objective"]
    for optimum, code in ((value, 0), (value + 100, 0), (value - 100, 1)):
        replace_literal(pack / "p01_checker.py", "KNOWN_OPTIMUM", float(optimum))
        result = checker(pack, solution)
        verdict(result, code, {"optimality"} if code else ())
        if optimum > value:
            assert "warn" in result.stdout.lower() and "instructor" in result.stdout.lower(), output(result)
    replace_literal(pack / "p01_checker.py", "KNOWN_OPTIMUM", float(value))
    solution["objective"] += tolerance(value) * .5
    verdict(checker(pack, solution), 0)
    solution["objective"] += tolerance(value) * 10
    verdict(checker(pack, solution), 1, {"objective"})


@pytest.mark.parametrize("kind", ["status", "coverage", "integrality", "sequence", "maintenance", "charging-window", "charging-power", "charger-capacity", "soc", "objective"])
def test_checker_named_contract_mutations(pack, instance, kind):
    d = instance
    vid = next(iter(d["vehicles"]))
    tid = next(iter(d["trips"]))
    solution = plan(d)
    if kind == "status":
        solution["status"] = "time_limit"
    elif kind == "coverage":
        solution["cancel"][tid] = 0
    elif kind == "integrality":
        solution["assign"] = {vid: {tid: .5}}
        solution["cancel"][tid] = .5
    elif kind == "sequence":
        pairs = [(a, b) for a, ta in d["trips"].items() for b, tb in d["trips"].items()
                 if a < b and max(minute(ta["start_time"]), minute(tb["start_time"])) < min(minute(ta["end_time"]), minute(tb["end_time"]))]
        assert pairs, "data: need overlapping trips to exercise sequencing"
        solution = plan(d, {vid: dict.fromkeys(pairs[0], 1)})
    elif kind == "maintenance":
        vid, vehicle = next((v, r) for v, r in d["vehicles"].items() if r["maintenance_start"])
        start = minute(vehicle["maintenance_start"]) // 30 * 30
        solution = plan(d, charge={vid: [{"slot": hhmm(start), "charger": "fast", "kwh": .1}]})
    elif kind == "charging-window":
        start = minute(d["trips"][tid]["start_time"]) // 30 * 30
        solution = plan(d, {vid: {tid: 1}}, {vid: [{"slot": hhmm(start), "charger": "fast", "kwh": .1}]})
    elif kind == "charging-power":
        solution = plan(d, charge={vid: [{"slot": "00:00", "charger": "slow", "kwh": 1e6}]})
    elif kind == "charger-capacity":
        for depot, row in d["depots"].items():
            vehicles = [v for v, r in d["vehicles"].items() if r["home_depot"] == depot]
            count = int(row["chargers_fast"])
            if len(vehicles) > count:
                solution = plan(d, charge={v: [{"slot": "00:00", "charger": "fast", "kwh": .1}] for v in vehicles[:count + 1]})
                break
    elif kind == "soc":
        solution = plan(d, {vid: {tid: 1}})  # No replenishment: final SoC is too low.
    else:
        solution["objective"] += 987.654321
    result = checker(pack, solution)
    verdict(result, 1, {kind})
    if kind == "integrality":
        assert not (failure_tags(result) & SCHEDULE_CONTRACTS), output(result)
        assert any(line.startswith("integrality:") and "skip" in line.lower() for line in result.stdout.splitlines())


def single_leg_candidate(data, include_deadhead_energy):
    """Construct a small probe from CSVs, not a plan for the actual homework.

    Charge only the necessary reserve before departure and replenish after
    return. With deadhead energy omitted the final reserve is exact, so ignoring deadheads alone
    would incorrectly certify the negative probe.
    """
    for vid, v in data["vehicles"].items():
        home = v["home_depot"]
        for tid, trip in data["trips"].items():
            # A same-home first origin gives a pre-departure home wait.
            if trip["origin_depot"] != home or trip["destination_depot"] == home:
                continue
            dh = data["deadhead"][trip["destination_depot"], home]
            energy = float(trip["energy_kwh"]) + (float(dh["energy_kwh"]) if include_deadhead_energy else 0)
            if float(v["max_soc_kwh"]) - energy < float(v["min_soc_kwh"]):
                continue
            start = minute(trip["start_time"])
            end = minute(trip["end_time"]) + float(dh["minutes"])
            pre = max(0, energy + float(v["min_soc_kwh"]) - float(v["initial_soc_kwh"]))
            post = energy - pre
            depot = data["depots"][home]
            kind = next((k for k in ("slow", "fast") if int(depot["chargers_" + k]) > 0), None)
            if kind is None:
                continue
            limit = min(float(v["max_charge_kw"]), float(depot[kind + "_kw"])) / 2
            charges = []
            for a, b, needed in ((0, start, pre), (math.ceil(end / 30) * 30, 1440, post)):
                for slot in range(int(a), int(b) - 29, 30):
                    if needed <= 1e-8:
                        break
                    if v["maintenance_start"] and slot < minute(v["maintenance_end"]) and slot + 30 > minute(v["maintenance_start"]):
                        continue
                    amount = min(limit, needed)
                    charges.append({"slot": hhmm(slot), "charger": kind, "kwh": amount})
                    needed -= amount
                if needed > 1e-8:
                    break
            else:
                result = plan(data, {vid: {tid: 1}}, {vid: charges})
                errors = oracle(data, result, ignore_deadhead_energy=not include_deadhead_energy)[0]
                if not errors:
                    return result
    pytest.fail("data: cannot construct a single-leg charging/deadhead probe from this instance")


def test_checker_valid_nontrivial_plan_and_deadhead_energy(pack, instance):
    positive = single_leg_candidate(instance, True)
    errors, cost, breakdown = oracle(instance, positive)
    assert not errors and breakdown[1] > 0 and breakdown[2] >= 0
    replace_literal(pack / "p01_checker.py", "KNOWN_OPTIMUM", float(cost))
    verdict(checker(pack, positive), 0)
    # Change a nonzero charge by a data-dependent amount; objective must be
    # recomputed even though this plan may then be suboptimal or infeasible.
    changed = deepcopy(positive)
    entry = next(c for cs in changed["charge"].values() for c in cs if c["kwh"] > 0)
    entry["kwh"] += 3.14159
    verdict(checker(pack, changed), 1, {"objective"})
    changed["objective"] = oracle(instance, changed)[1]
    assert "objective" not in failure_tags(checker(pack, changed))
    negative = single_leg_candidate(instance, False)
    assert not oracle(instance, negative, ignore_deadhead_energy=True)[0]
    assert oracle(instance, negative)[0] == {"soc"}
    verdict(checker(pack, negative), 1, {"soc"})


def test_checker_charger_types_and_tariff_boundaries(pack, instance):
    # These probes can exceed final battery capacity; objective and power
    # recomputation must still be correct and independently diagnosed.
    for vid, vehicle in instance["vehicles"].items():
        depot = instance["depots"][vehicle["home_depot"]]
        slow = min(float(vehicle["max_charge_kw"]), float(depot["slow_kw"])) / 2
        fast = min(float(vehicle["max_charge_kw"]), float(depot["fast_kw"])) / 2
        if fast > slow + 1:
            break
    else:
        pytest.fail("data: upstream slow/fast power distinction must survive the port")
    for kind, expected in (("slow", True), ("fast", False)):
        s = plan(instance, charge={vid: [{"slot": "00:00", "charger": kind, "kwh": (slow + fast) / 2}]})
        result = checker(pack, s)
        assert result.returncode == 1, output(result)  # All trips cancelled.
        assert ("charging-power" in failure_tags(result)) == expected, output(result)
        assert "objective" not in failure_tags(result), output(result)
    for tariff in instance["tariffs"]:
        start = minute(tariff["start_time"])
        for slot in {start, max(0, start - 30)}:
            s = plan(instance, charge={vid: [{"slot": hhmm(slot), "charger": "fast", "kwh": fast}]})
            result = checker(pack, s)
            assert result.returncode == 1 and "objective" not in failure_tags(result), output(result)


@pytest.mark.parametrize("field", ["assign", "cancel", "charge"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), "1", True])
def test_checker_non_numeric_decisions(pack, instance, field, value):
    s = plan(instance)
    vid, tid = next(iter(instance["vehicles"])), next(iter(instance["trips"]))
    if field == "assign":
        s["assign"] = {vid: {tid: value}}
    elif field == "cancel":
        s["cancel"][tid] = value
    else:
        s["charge"] = {vid: [{"slot": "00:00", "charger": "fast", "kwh": value}]}
    verdict(checker(pack, s), 2, {"format"})


def test_checker_explicit_path_missing_file_and_arguments(pack, instance):
    s = plan(instance)
    path = pack / "a different solution.json"
    path.write_text(json.dumps(s), encoding="utf-8")
    verdict(checker(pack, args=(path,)), 1, {"optimality"})
    verdict(checker(pack, args=(pack / "absent.json",)), 2, {"format"})
    result = checker(pack, args=("--not-an-option",))
    assert result.returncode == 2, output(result)


@pytest.mark.parametrize("slot", ["00:15", "23:45", "24:00"])
def test_checker_rejects_slots_outside_day_grid(pack, instance, slot):
    s = plan(instance)
    vid = next(iter(instance["vehicles"]))
    s["charge"] = {vid: [{"slot": slot, "charger": "fast", "kwh": .1}]}
    result = checker(pack, s)
    assert result.returncode in {1, 2}, output(result)
    assert failure_tags(result) & {"format", "charging-window"}, output(result)


@pytest.mark.parametrize("bad", ["json", "list", "missing", "nan", "inf", "bool", "unknown-trip", "unknown-vehicle", "unknown-charger", "bad-time", "wrong-shape"])
def test_checker_format_failures(pack, instance, bad):
    s = plan(instance)
    vid = next(iter(instance["vehicles"]))
    if bad == "json":
        (pack / "solution.json").write_text("{", encoding="utf-8")
        result = checker(pack)
    else:
        if bad == "list":
            s = []
        elif bad == "missing":
            del s["objective"]
        elif bad in {"nan", "inf", "bool"}:
            s["objective"] = {"nan": float("nan"), "inf": float("inf"), "bool": True}[bad]
        elif bad == "unknown-trip":
            s["cancel"]["absent-trip"] = 1
        elif bad == "unknown-vehicle":
            s["assign"]["absent-vehicle"] = {}
        elif bad == "wrong-shape":
            s["assign"] = []
        else:
            s["charge"] = {vid: [{"slot": "garbage" if bad == "bad-time" else "00:00", "charger": "turbo" if bad == "unknown-charger" else "fast", "kwh": 1}]}
        result = checker(pack, s)
    verdict(result, 2, {"format"})


@pytest.mark.parametrize("filename", ["trips.csv", "vehicles.csv", "depots.csv", "deadhead_minutes.csv", "tariff_blocks.csv", "parameters.csv"])
def test_checker_data_pin_crlf_and_tampering(pack, instance, filename):
    solution = plan(instance)
    for path in (pack / "data").glob("*.csv"):
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    verdict(checker(pack, solution), 1, {"optimality"})
    path = pack / "data" / filename
    # Even a semantically harmless edit must break the literal byte pin; only
    # CRLF -> LF normalization is exempt in the design.
    path.write_bytes(path.read_bytes() + b"\r\n")
    verdict(checker(pack, solution), 2, {"data"})


def test_optimum_literal_and_private_reference_documentation(instance):
    optimum = literal("KNOWN_OPTIMUM")
    assert isinstance(optimum, float) and math.isfinite(optimum)
    assert 0 < optimum < plan(instance)["objective"]
    assert not list(PACK.rglob("*.json")), "release: no real solution plans in the public starter pack"
    for path in PACK.rglob("p01_model.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "highspy" for a in node.names), "release: no p01_model.py formulation in the pack"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "highspy", "release: no p01_model.py formulation in the pack"
            elif isinstance(node, (ast.Name, ast.Attribute)):
                assert getattr(node, "id", getattr(node, "attr", "")) not in {"Highs", "addVariable"}
    doc = required(PACK / "INSTRUCTOR.md")
    for token in (".local/share/coding-agent-cursus/instructor/s01-p01", "P01_REFERENCE_DIR", "instructor_p01_reference.py"):
        assert token in doc, f"instructor entry point missing: {token}"
    # Narrative correctness, backup access and host claims require source review
    # (ADR 0011); do not mistake keyword hits for evidence of those facts.
    assert re.search(r"\b[0-9a-fA-F]{64}\b", doc), "instructor: record external reference SHA256"


def test_optimum_starter_api_and_documented_entry_points(pack):
    for name in ("README.md", "PROBLEM.md", "INSTRUCTOR.md", "p01_model.py", "p01_checker.py", "p01_contract.py"):
        required(PACK / name)
    source = required(PACK / "p01_model.py")
    tree = ast.parse(source)
    assert not any(isinstance(n, ast.Import) and any(a.name == "highspy" for a in n.names) or
                   isinstance(n, ast.ImportFrom) and n.module == "highspy" for n in ast.walk(tree)), "starter: no reference formulation"
    assert not any(isinstance(n, ast.Name) and n.id in {"Highs", "addVariable"} or
                   isinstance(n, ast.Attribute) and n.attr in {"Highs", "addVariable"} for n in ast.walk(tree))
    assert any(isinstance(n, ast.If) and "__name__" in ast.unparse(n.test) and "__main__" in ast.unparse(n.test)
               for n in tree.body), "starter: executable entry point required"
    script = """import inspect, p01_model as m
assert hasattr(m, 'DATA_DIR') and callable(m.contract_status)
sig = inspect.signature(m.solve)
assert sig.parameters['data_dir'].default == m.DATA_DIR
assert sig.parameters['time_limit'].default == 120.0
try:
    m.solve()
except NotImplementedError:
    pass
else:
    raise AssertionError('starter: as-shipped solve must raise NotImplementedError')
"""
    result = run([sys.executable, "-S", "-c", script], pack)
    assert result.returncode == 0, output(result)
    # Exercise the entry point without supplying an actual reference model:
    # replace only the empty solve body in a disposable copy with a sentinel.
    # The API/NotImplementedError check above already checked the shipped stub.
    solve_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "solve")
    entrypoint_probe = plan(read_instance(pack))
    solve_node.body = [ast.Return(value=ast.parse(repr(entrypoint_probe), mode="eval").body)]
    (pack / "p01_model.py").write_text(ast.unparse(ast.fix_missing_locations(tree)), encoding="utf-8")
    result = run([sys.executable, "-S", pack / "p01_model.py"], pack)
    assert result.returncode == 0, output(result)
    assert (pack / "solution.json").is_file(), "starter: __main__ must write solution.json"
    assert json.loads((pack / "solution.json").read_text(encoding="utf-8")) == entrypoint_probe
    readme = required(PACK / "README.md")
    for token in ("Claude Code", "Codex", "p01_model.py", "solution.json", "p01_checker.py", "p01_contract.py", "/turn-in 01", "$turn-in 01", "scripts/turn-in.sh 01"):
        assert token in readme, f"student entry point missing: {token}"
    for field in ("status", "objective", "assign", "cancel", "charge", "slot", "charger", "kwh"):
        assert field in readme, f"solution-format field missing: {field}"
    layout = required(SESSION / "README.md")
    for name in ("exercises/homework-p01/", "exercises/turn-in-check.sh", "tests/fixtures/p01_upstream/"):
        assert name in layout, f"session layout missing {name}"


def suite_report(directory, path="p01_contract.py", timeout=180):
    report = directory / "contract-results.xml"
    result = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml", report, path], directory, timeout)
    assert report.is_file(), output(result)
    root = ET.parse(report).getroot()
    totals = {key: sum(int(s.get(key, 0)) for s in root.iter("testsuite")) for key in ("tests", "failures", "errors", "skipped")}
    return result, totals, [f.get("message", "") for f in root.iter("failure")]


def test_contract_suite_collection_and_no_runtime_assertion(pack):
    explicit = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "p01_contract.py"], pack)
    assert explicit.returncode == 0, output(explicit)
    names = re.findall(r"p01_contract\.py::(test_\S+)", explicit.stdout)
    assert len(names) >= len(CONTRACTS - {"data", "format"}), "contract_suite: status mapping plus every solution contract"
    for contract in CONTRACTS - {"data", "format"}:
        assert any(contract.replace("-", "_") in name for name in names), f"contract_suite: missing {contract}"
    default = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], pack)
    assert "p01_contract.py::" not in default.stdout, "contract_suite: empty student model must not break default pytest"
    tree = ast.parse(required(PACK / "p01_contract.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            expression = ast.unparse(node.test)
            assert not any(word in expression for word in ("solve_seconds", "perf_counter", "getRunTime")), "contract_suite: student runtime is not graded"


@pytest.mark.parametrize("case,code,tag", [("missing", 0, None), ("format", 1, "format"), ("data", 1, "data"), ("infeasible", 0, "coverage"), ("suboptimal", 0, "optimality"), ("valid", 0, None)])
def test_turn_in_policy(pack, instance, case, code, tag):
    solution = plan(instance)
    if case == "format":
        (pack / "solution.json").write_text("{", encoding="utf-8")
    elif case != "missing":
        if case == "infeasible":
            solution["cancel"][next(iter(instance["trips"]))] = 0
        if case == "valid":
            replace_literal(pack / "p01_checker.py", "KNOWN_OPTIMUM", float(solution["objective"]))
        (pack / "solution.json").write_text(json.dumps(solution), encoding="utf-8")
        if case == "data":
            (pack / "data/trips.csv").write_text("broken", encoding="utf-8")
    result = checker(pack, args=("--turn-in",))
    assert result.returncode == code, output(result)
    if tag:
        assert tag in failure_tags(result) and result.stdout.splitlines()[0] == "FAIL", output(result)
    elif case == "missing":
        assert "warn" in result.stdout.lower() and "solution.json" in result.stdout.lower(), output(result)
    else:
        assert result.stdout.splitlines()[0] == "PASS", output(result)


def test_turn_in_hook_from_session_directory():
    hook = SESSION / "exercises/turn-in-check.sh"
    source = required(hook)
    syntax = run(["bash", "-n", hook], SESSION)
    assert syntax.returncode == 0, output(syntax)
    assert "exec uv run --no-project --python 3.12 python exercises/homework-p01/p01_checker.py --turn-in" in source
    assert not (PACK / "solution.json").exists(), "starter: real plans must remain outside tree"
    result = run(["bash", hook], SESSION, timeout=60)
    assert result.returncode == 0 and "warn" in result.stdout.lower() and "solution.json" in result.stdout.lower(), output(result)

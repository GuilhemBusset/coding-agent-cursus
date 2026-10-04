"""Solver contracts: independently check what a successful solve actually means."""

from copy import deepcopy
import math

import highspy
import pytest

import p00_checker
import p00_model


ACCEPTED = {"optimal", "feasible"}
# Hand proof: demand totals 100, so no single plant suffices. For each remaining
# subset, fixed costs plus each customer's cheapest available route is a lower
# bound: {P1,P2}: 485; {P1,P3}: 600; {P2,P3}: 635; {P1,P2,P3}: 595.
# At 485, P1 serves C1,C2 (50 <= 70), P2 serves C3,C4,C5 (50 <= 60).
# This feasible assignment attains the smallest lower bound, proving optimality.
KNOWN_OPTIMUM = 485.0


def close(actual, expected):
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6)


@pytest.fixture(scope="module")
def data():
    return p00_checker.load_data(p00_checker.DATA_DIR)


@pytest.fixture(scope="module")
def solution():
    return p00_model.solve()


@pytest.fixture
def hand_plan():
    return {
        "status": "feasible", "objective": KNOWN_OPTIMUM,
        "open": {"P1": 1.0, "P2": 1.0, "P3": 0.0},
        "flow": {
            "P1": {"C1": 20.0, "C2": 30.0, "C3": 0.0, "C4": 0.0, "C5": 0.0},
            "P2": {"C1": 0.0, "C2": 0.0, "C3": 25.0, "C4": 15.0, "C5": 10.0},
            "P3": {"C1": 0.0, "C2": 0.0, "C3": 0.0, "C4": 0.0, "C5": 0.0},
        },
    }


def test_status_contract(solution):
    assert solution["status"] in ACCEPTED, "status contract: require an accepted solution status"


def test_status_mapping_contract():
    status = highspy.HighsModelStatus
    assert p00_model.contract_status(status.kOptimal, True) == "optimal", (
        "status contract: a proven optimum maps to optimal"
    )
    assert p00_model.contract_status(status.kTimeLimit, True) == "feasible", (
        "status contract: a time limit with an incumbent is feasible, not proven optimal"
    )
    for raw in (status.kTimeLimit, status.kInfeasible):
        assert p00_model.contract_status(raw, False) not in ACCEPTED, (
            "status contract: no primal solution must not be accepted"
        )


def test_feasibility_contract(data, solution):
    errors = p00_checker.feasibility_problems(data, solution)
    assert not errors, "feasibility contract: " + "; ".join(errors)
    assert close(p00_checker.objective(data, solution), solution["objective"]), (
        "feasibility contract: reported objective disagrees with independent recomputation"
    )


def test_integrality_contract(data, solution):
    errors = p00_checker.integrality_problems(data, solution)
    assert not errors, "integrality contract: " + "; ".join(errors)
    rounded = deepcopy(solution)
    rounded["open"] = {plant: round(value) for plant, value in solution["open"].items()}
    errors = p00_checker.problems(data, rounded)
    assert not errors, "integrality contract: rounding must preserve feasibility: " + "; ".join(errors)
    assert close(p00_checker.objective(data, rounded), p00_checker.objective(data, solution)), (
        "integrality contract: rounding changed the objective"
    )


def test_objective_contract(solution):
    assert close(solution["objective"], KNOWN_OPTIMUM), (
        "objective contract: objective must agree with the independently proven optimum"
    )


def test_known_optimum_by_enumeration(data):
    plants, customers = data["plants"], data["customers"]
    demand = sum(data["demand"].values())
    bounds = []
    for mask in range(1, 1 << len(plants)):
        opened = [p for index, p in enumerate(plants) if mask & (1 << index)]
        if sum(data["capacity"][p] for p in opened) < demand:
            continue
        load = {p: 0.0 for p in opened}
        lower_bound = sum(data["fixed_cost"][p] for p in opened)
        for customer in customers:
            cheapest = min(opened, key=lambda p: data["unit_cost"][p][customer])
            load[cheapest] += data["demand"][customer]
            lower_bound += data["unit_cost"][cheapest][customer] * data["demand"][customer]
        bounds.append((lower_bound, load))
    assert bounds, "objective contract: enumeration found no capacity-sufficient subset"
    best, load = min(bounds, key=lambda item: item[0])
    assert close(best, KNOWN_OPTIMUM), "objective contract: enumerated lower bound differs from hand proof"
    assert all(value <= data["capacity"][p] + 1e-6 for p, value in load.items()), (
        "objective contract: cheapest-route bound must be attained by a feasible assignment"
    )
    assert all(bound >= KNOWN_OPTIMUM - 1e-6 for bound, _ in bounds), (
        "objective contract: another subset has a smaller lower bound"
    )


def test_checker_accepts_hand_optimal_plan(data, hand_plan):
    assert p00_checker.problems(data, hand_plan) == [], "feasibility contract: hand plan must be accepted"
    hand_plan["objective"] = -12345.0
    assert close(p00_checker.objective(data, hand_plan), KNOWN_OPTIMUM), (
        "objective contract: recompute from decisions, do not trust the reported objective"
    )


def test_checker_flags_unserved_customer(data, hand_plan):
    hand_plan["flow"]["P2"]["C5"] = 0.0
    errors = p00_checker.feasibility_problems(data, hand_plan)
    assert errors, "feasibility contract: unmet demand must be detected"
    assert all(e.startswith("feasibility contract: ") for e in errors), (
        "feasibility contract: diagnostics must name the contract"
    )


def test_checker_flags_fractional_opening(data, hand_plan):
    hand_plan["open"]["P3"] = 0.2
    assert not p00_checker.feasibility_problems(data, hand_plan), (
        "feasibility contract: an unused partial opening satisfies continuous constraints"
    )
    errors = p00_checker.integrality_problems(data, hand_plan)
    assert errors, "integrality contract: partial openings must be detected"
    assert all(e.startswith("integrality contract: ") for e in errors), (
        "integrality contract: diagnostics must name the contract"
    )
    assert p00_checker.problems(data, hand_plan) == errors, (
        "integrality contract: combined checker must include integrality diagnostics"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["open", "flow"])
def test_checker_flags_nonfinite_values(data, hand_plan, field, value):
    if field == "open":
        hand_plan["open"]["P3"] = value
    else:
        hand_plan["flow"]["P3"]["C5"] = value
    errors = p00_checker.feasibility_problems(data, hand_plan)
    assert errors, "feasibility contract: non-finite decisions must be rejected"
    assert all(e.startswith("feasibility contract: ") for e in errors), (
        "feasibility contract: non-finite diagnostics must name the contract"
    )


@pytest.mark.parametrize("case", [
    "negative", "oversupply", "capacity", "closed", "below_zero", "above_one",
    "missing_open", "extra_open", "missing_plant", "extra_plant",
    "missing_customer", "extra_customer",
])
def test_checker_rejects_invalid_decisions(data, hand_plan, case):
    if case == "negative":
        hand_plan["flow"]["P3"]["C1"] = -1.0
        hand_plan["flow"]["P1"]["C1"] += 1.0
    elif case == "oversupply":
        hand_plan["flow"]["P1"]["C1"] += 1.0
    elif case == "capacity":
        hand_plan["flow"]["P1"]["C3"] = 25.0
        hand_plan["flow"]["P2"]["C3"] = 0.0
    elif case == "closed":
        hand_plan["open"]["P1"] = 0.0
    elif case in {"below_zero", "above_one"}:
        hand_plan["open"]["P3"] = -0.1 if case == "below_zero" else 1.1
    elif case == "missing_open":
        del hand_plan["open"]["P3"]
    elif case == "extra_open":
        hand_plan["open"]["unexpected"] = 0.0
    elif case == "missing_plant":
        del hand_plan["flow"]["P3"]
    elif case == "extra_plant":
        hand_plan["flow"]["unexpected"] = dict.fromkeys(data["customers"], 0.0)
    elif case == "missing_customer":
        del hand_plan["flow"]["P3"]["C5"]
    else:
        hand_plan["flow"]["P3"]["unexpected"] = 0.0
    errors = p00_checker.feasibility_problems(data, hand_plan)
    assert errors, f"feasibility contract: invalid decision case {case} must be rejected"
    assert all(e.startswith("feasibility contract: ") for e in errors), (
        "feasibility contract: invalid-decision diagnostics must name the contract"
    )


def test_checker_uses_supplied_csv_data(tmp_path):
    (tmp_path / "plants.csv").write_text(
        "plant,capacity,fixed_cost\nWest,9,13\nEast,8,17\n", encoding="utf-8"
    )
    (tmp_path / "customers.csv").write_text("customer,demand\nAlpha,4\nBeta,6\n", encoding="utf-8")
    (tmp_path / "costs.csv").write_text(
        "plant,customer,unit_cost\nWest,Alpha,2\nWest,Beta,9\nEast,Alpha,8\nEast,Beta,3\n",
        encoding="utf-8",
    )
    alternate = p00_checker.load_data(tmp_path)
    expected = {
        "plants": ["West", "East"], "customers": ["Alpha", "Beta"],
        "capacity": {"West": 9.0, "East": 8.0}, "fixed_cost": {"West": 13.0, "East": 17.0},
        "demand": {"Alpha": 4.0, "Beta": 6.0},
        "unit_cost": {"West": {"Alpha": 2.0, "Beta": 9.0}, "East": {"Alpha": 8.0, "Beta": 3.0}},
    }
    assert alternate == expected, "feasibility contract: parse the supplied CSVs and preserve ID order"
    plan = {
        "status": "feasible", "objective": -1.0,
        "open": {"West": 1.0, "East": 1.0},
        "flow": {"West": {"Alpha": 4.0, "Beta": 0.0}, "East": {"Alpha": 0.0, "Beta": 6.0}},
    }
    assert not p00_checker.problems(alternate, plan), "feasibility contract: accept the alternate valid plan"
    assert close(p00_checker.objective(alternate, plan), 56.0), "objective contract: use supplied costs"
    alternate["demand"]["Beta"] = 7.0
    assert p00_checker.feasibility_problems(alternate, plan), "feasibility contract: use supplied demand"


def test_checker_feasibility_tolerance_scales_with_rhs(data, hand_plan):
    # C1's RHS is 20: 1e-5 is inside 1e-6 * 20, outside 1e-8 * 20.
    hand_plan["flow"]["P1"]["C1"] += 1e-5
    assert not p00_checker.feasibility_problems(data, hand_plan), (
        "feasibility contract: tolerate residuals relative to the demand RHS"
    )
    assert p00_checker.feasibility_problems(data, hand_plan, tol=1e-8), (
        "feasibility contract: honor an explicitly tighter tolerance"
    )


def test_checker_integrality_tolerance(data, hand_plan):
    hand_plan["open"]["P3"] = 5e-7
    assert not p00_checker.integrality_problems(data, hand_plan), (
        "integrality contract: tolerate numerical noise near zero"
    )
    hand_plan["open"]["P3"] = 5e-4
    assert p00_checker.integrality_problems(data, hand_plan), (
        "integrality contract: reject values outside the default tolerance"
    )
    assert not p00_checker.integrality_problems(data, hand_plan, tol=1e-3), (
        "integrality contract: honor the supplied tolerance"
    )

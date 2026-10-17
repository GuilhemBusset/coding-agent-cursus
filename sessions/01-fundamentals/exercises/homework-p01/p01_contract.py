"""P01 solve contracts: independently check what a successful solve actually means.

Run from sessions/01-fundamentals:  uv run pytest exercises/homework-p01/p01_contract.py
The file is not named test_*.py, so the session's plain `uv run pytest` does not collect
it while p01_model.py is still empty. It solves once, then asks the independent checker
(p01_checker.py) about each contract; every failure message starts with that contract.
"""

import highspy
import pytest

import p01_checker
import p01_model


ACCEPTED = {"optimal", "feasible"}


@pytest.fixture(scope="module")
def data():
    return p01_checker.load_data()


@pytest.fixture(scope="module")
def solution():
    return p01_model.solve()


@pytest.fixture(scope="module")
def report(data, solution):
    return p01_checker.check(solution, data)


def assert_contract(report, contract):
    """Fail with the checker's own lines for this contract, or explain why it was not assessed."""
    if report.fatal:
        pytest.fail(f"{contract}: not checked, the solution could not be read: " + "; ".join(report.failures))
    if contract in report.skipped:
        reasons = [line for line in report.failures if not line.startswith(contract + ":")]
        pytest.fail(f"{contract}: not checked because an earlier contract failed: " + "; ".join(reasons))
    lines = [line for line in report.failures if line.startswith(contract + ":")]
    assert not lines, "\n".join(lines)


def test_status_contract(solution):
    assert solution["status"] in ACCEPTED, (
        f"status: {solution['status']!r} is not an accepted status; require one of {sorted(ACCEPTED)}"
    )


def test_status_mapping_contract():
    status = highspy.HighsModelStatus
    assert p01_model.contract_status(status.kOptimal, True) == "optimal", (
        "status: a proven optimum maps to 'optimal'"
    )
    assert p01_model.contract_status(status.kTimeLimit, True) == "feasible", (
        "status: a time limit with an incumbent is 'feasible', not proven optimal"
    )
    for raw in (status.kTimeLimit, status.kInfeasible):
        assert p01_model.contract_status(raw, False) not in ACCEPTED, (
            "status: no primal solution must never be accepted"
        )


def test_coverage_contract(report):
    assert_contract(report, "coverage")


def test_integrality_contract(report):
    assert_contract(report, "integrality")


def test_sequence_contract(report):
    assert_contract(report, "sequence")


def test_maintenance_contract(report):
    assert_contract(report, "maintenance")


def test_charging_window_contract(report):
    assert_contract(report, "charging-window")


def test_charging_power_contract(report):
    assert_contract(report, "charging-power")


def test_charger_capacity_contract(report):
    assert_contract(report, "charger-capacity")


def test_soc_contract(report):
    assert_contract(report, "soc")


def test_objective_contract(report):
    assert_contract(report, "objective")


def test_optimality_contract(report):
    assert_contract(report, "optimality")

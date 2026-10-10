"""Explicit instructor checks: missing private reference is a failure, never a skip.

uv run pytest -q tests/instructor_p01_reference.py

P01_REFERENCE_DIR overrides ~/.local/share/coding-agent-cursus/instructor/s01-p01.
Only temporary copies are executed or changed. This filename intentionally does
not match pytest's default discovery pattern. The benchmark is host-dependent by
design; feasibility, provenance and contract tests are deterministic and offline.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

import pytest

from test_p01_homework import (
    PACK, SESSION, checker, failure_tags, literal, oracle, output,
    read_instance, replace_literal, required, run, suite_report, tolerance, verdict,
)


VARIANTS = {
    "dropped-charging-window": "charging-window",
    "relaxed-binary": "integrality",
    "dropped-charger-capacity": "charger-capacity",
}

# Observe HiGHS itself, independently of any model-specific metadata format.
# The reference's only required public API remains solve() and VARIANT.
DRIVER = r'''
import json
from pathlib import Path
import highspy

observations = []
original_run = highspy.Highs.run
def observed_run(self, *args, **kwargs):
    options = {key: self.getOptionValue(key)[1] for key in ('threads', 'mip_rel_gap')}
    result = original_run(self, *args, **kwargs)
    info = self.getInfo()
    observations.append({
        'options': options,
        'raw_status': self.getModelStatus().name,
        'primal': info.objective_function_value,
        'dual': info.mip_dual_bound,
        'gap': info.mip_gap,
        'solve_seconds': self.getRunTime(),
        'highs_version': self.version(),
    })
    return result
highspy.Highs.run = observed_run
import p01_model
solution = p01_model.solve(time_limit=60.0)
Path('solution.json').write_text(json.dumps(solution), encoding='utf-8')
Path('highs-observations.json').write_text(json.dumps(observations), encoding='utf-8')
'''

CONTRACT_OBSERVER = r'''

# Added only to an ephemeral copy by the acceptance harness.
from pathlib import Path as _AuditPath
import json as _audit_json
_audit_original_solve = solve
_audit_original_status = contract_status
def solve(*args, **kwargs):
    with _AuditPath('solve-calls.txt').open('a', encoding='utf-8') as stream:
        stream.write('solve\n')
    return _audit_original_solve(*args, **kwargs)
def contract_status(model_status, has_solution):
    value = _audit_original_status(model_status, has_solution)
    with _AuditPath('status-calls.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(_audit_json.dumps([model_status.name, has_solution, value]) + '\n')
    return value
'''


@pytest.fixture(scope="session")
def reference():
    directory = Path(os.environ.get(
        "P01_REFERENCE_DIR", "~/.local/share/coding-agent-cursus/instructor/s01-p01"
    )).expanduser().resolve()
    path = directory / "p01_model.py"
    assert path.is_file(), (
        f"reference: missing {path}; provide the private instructor reference or "
        "set P01_REFERENCE_DIR. This check must fail rather than skip."
    )
    assert not path.resolve().is_relative_to(SESSION.parents[1]), "reference: model must be outside the public checkout"
    source = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = required(PACK / "INSTRUCTOR.md")
    assert digest in [value.lower() for value in re.findall(r"\b[0-9a-fA-F]{64}\b", doc)], "reference: sha256 differs from INSTRUCTOR.md"
    assert literal("VARIANT", source) == "none", "reference: canonical VARIANT must be 'none'"
    return path


def execute_reference(reference, directory, variant="none"):
    shutil.copytree(PACK, directory)
    shutil.copyfile(reference, directory / "p01_model.py")
    replace_literal(directory / "p01_model.py", "VARIANT", variant)
    started = time.perf_counter()
    process = run([sys.executable, "-c", DRIVER], directory, timeout=150)
    wall_seconds = time.perf_counter() - started
    assert process.returncode == 0, f"reference: {variant} execution failed\n{output(process)}"
    assert (directory / "solution.json").is_file(), "reference: missing solution"
    solution = json.loads((directory / "solution.json").read_text(encoding="utf-8"))
    assert isinstance(solution, dict), "reference: solve() must return the solution object"
    assert solution.get("status") in {"optimal", "feasible"}, "reference: no usable incumbent"
    observations = json.loads((directory / "highs-observations.json").read_text(encoding="utf-8"))
    assert observations, "reference: no actual highspy.Highs.run() call observed"
    # Allow model-building helpers to solve subproblems; the final run certifies
    # the emitted incumbent, and all runs must obey the single-thread protocol.
    for observation in observations:
        assert observation["options"] == {"threads": 1, "mip_rel_gap": 0.0}, "reference: threads=1 and mip_rel_gap=0 required"
    observed = observations[-1]
    elapsed = solution.get("solve_seconds")
    assert isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and math.isfinite(elapsed)
    assert math.isclose(elapsed, observed["solve_seconds"], rel_tol=1e-5, abs_tol=.001), "reference: solve_seconds must be actual HiGHS runtime"
    assert math.isfinite(solution.get("objective", float("nan")))
    assert math.isclose(solution["objective"], observed["primal"], rel_tol=1e-6, abs_tol=1e-6), "reference: reported objective must match HiGHS primal"
    checked = checker(directory)
    assert checked.returncode in (0, 1), f"reference: variant produced data/format failure\n{output(checked)}"
    assert not failure_tags(checked) & {"data", "format", "status"}, output(checked)
    return {"directory": directory, "solution": solution, "observed": observed,
            "checked": checked, "wall_seconds": wall_seconds, "variant": variant}


@pytest.fixture(scope="session")
def solved(reference, tmp_path_factory):
    cache = {}
    root = tmp_path_factory.mktemp("p01-private-reference")

    def get(variant="none"):
        if variant not in cache:
            cache[variant] = execute_reference(reference, root / variant, variant)
        return cache[variant]

    return get


def assert_optimal(record):
    observation = record["observed"]
    assert record["solution"]["status"] == "optimal"
    assert observation["raw_status"] == "kOptimal", "reference: optimum requires HiGHS kOptimal"
    assert math.isfinite(observation["primal"]) and math.isfinite(observation["dual"])
    assert abs(observation["primal"] - observation["dual"]) <= tolerance(observation["primal"]), "reference: primal/dual bounds not closed"
    assert math.isfinite(observation["gap"]) and abs(observation["gap"]) <= 1e-9, "reference: nonzero MIP gap"


def test_reference_passes_checker(solved):
    record = solved()
    assert_optimal(record)
    verdict(record["checked"], 0)
    errors, objective, _ = oracle(read_instance(), record["solution"])
    assert not errors, f"reference: independent rules disagree: {errors}"
    assert math.isclose(objective, record["solution"]["objective"], rel_tol=1e-6, abs_tol=1e-6)


def test_reference_matches_known_optimum(solved):
    record = solved()
    assert_optimal(record)
    verdict(record["checked"], 0)
    optimum = literal("KNOWN_OPTIMUM")
    errors, recomputed, _ = oracle(read_instance(), record["solution"])
    assert not errors
    for value in (recomputed, record["solution"]["objective"], record["observed"]["primal"], record["observed"]["dual"]):
        assert math.isclose(value, optimum, rel_tol=1e-6, abs_tol=1e-6), "known_optimum: checker, reference and independent objective must agree"


def host_description():
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    memory = Path("/proc/meminfo").read_text(encoding="utf-8")
    cpu = next(line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("model name"))
    ram = next(line.split(":", 1)[1].strip() for line in memory.splitlines() if line.startswith("MemTotal:"))
    return {"cpu": cpu, "logical_cpus": os.cpu_count(), "ram": ram, "os": platform.platform(), "uname": list(platform.uname())}


def test_reference_solve_time(reference, solved, tmp_path, capsys):
    records = [solved()]
    records.extend(execute_reference(reference, tmp_path / f"fresh-{i}") for i in range(2))
    evidence = {"host": host_description(), "runs": []}
    for record in records:
        assert_optimal(record)
        verdict(record["checked"], 0)
        seconds = record["observed"]["solve_seconds"]
        assert 5 <= seconds < 60, f"solve_time: each fresh single-thread solve must be in [5,60), got {seconds}"
        evidence["runs"].append({**record["observed"], "wall_seconds": record["wall_seconds"]})
    # Make successful measurement evidence visible even with pytest -q.
    with capsys.disabled():
        print("\nP01 benchmark evidence: " + json.dumps(evidence, sort_keys=True))


@pytest.mark.parametrize("variant,contract", VARIANTS.items())
def test_variant_fails_named_contract(solved, variant, contract):
    record = solved(variant)
    verdict(record["checked"], 1, {contract})
    assert record["observed"]["raw_status"] in {"kOptimal", "kTimeLimit"}
    if variant == "relaxed-binary":
        values = [v for assignment in record["solution"]["assign"].values() for v in assignment.values()]
        values += list(record["solution"]["cancel"].values())
        assert any(1e-6 < value < 1 - 1e-6 for value in values), "variant: must expose raw fractional decisions, not rounded values"


@pytest.mark.parametrize("variant", ["dropped-charging-window", "dropped-charger-capacity"])
def test_variant_binding(solved, variant):
    record = solved(variant)
    contract = VARIANTS[variant]
    verdict(record["checked"], 1, {contract})
    assert failure_tags(record["checked"]) == {contract}, "binding: ablation incumbent must satisfy every retained checker contract"
    solution = record["solution"]
    for assignment in solution["assign"].values():
        assert all(min(abs(v), abs(v - 1)) <= 1e-6 for v in assignment.values())
    assert all(min(abs(v), abs(v - 1)) <= 1e-6 for v in solution["cancel"].values())
    errors, recomputed, _ = oracle(read_instance(), solution)
    assert errors == {contract}, f"binding: independent relaxed feasibility failed: {errors}"
    assert math.isclose(recomputed, solution["objective"], rel_tol=1e-6, abs_tol=1e-6)
    optimum = literal("KNOWN_OPTIMUM")
    assert recomputed < optimum - tolerance(optimum), "binding: removing this constraint must strictly improve the objective"


@pytest.fixture(scope="session")
def contract_results(reference, tmp_path_factory):
    root = tmp_path_factory.mktemp("p01-reference-contracts")
    cache = {}

    def get(variant):
        if variant not in cache:
            directory = root / variant
            shutil.copytree(PACK, directory)
            shutil.copyfile(reference, directory / "p01_model.py")
            replace_literal(directory / "p01_model.py", "VARIANT", variant)
            with (directory / "p01_model.py").open("a", encoding="utf-8") as stream:
                stream.write(CONTRACT_OBSERVER)
            cache[variant] = suite_report(directory, timeout=240)
            calls = directory / "solve-calls.txt"
            assert calls.is_file() and calls.read_text(encoding="utf-8").splitlines() == ["solve"], "contract_suite: use one solve in a module fixture"
            statuses = directory / "status-calls.jsonl"
            assert statuses.is_file(), "contract_suite: exercise contract_status"
            observed = [json.loads(line) for line in statuses.read_text(encoding="utf-8").splitlines()]
            assert ["kTimeLimit", True, "feasible"] in observed, "contract_suite: exercise time limit with an incumbent"
            assert ["kOptimal", True, "optimal"] in observed, "contract_suite: exercise optimal status"
        return cache[variant]

    return get


def test_contract_suite_on_reference(contract_results):
    result, totals, _ = contract_results("none")
    assert result.returncode == 0, output(result)
    assert totals["tests"] >= 12, "contract_suite: test every contract and status mapping"
    assert totals["failures"] == totals["errors"] == totals["skipped"] == 0, output(result)


def test_contract_suite_on_relaxed_binary(contract_results):
    result, totals, messages = contract_results("relaxed-binary")
    assert result.returncode == 1 and totals["failures"] > 0, output(result)
    assert totals["errors"] == totals["skipped"] == 0, output(result)
    assert any(re.match(r"(?:AssertionError:\s*)?integrality(?:\s|:)", message) for message in messages), (
        "contract_suite: fractional assignments must fail a named integrality assertion\n" + output(result)
    )

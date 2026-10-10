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
import subprocess
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
    """Best-effort evidence on Linux, macOS and Windows; never block a solve."""
    def attempt(function):
        try:
            return function() or "unknown"
        except Exception:
            # Host metadata is advisory: missing commands, permissions, malformed
            # proc files and platform API errors must not break the benchmark.
            return "unknown"

    def proc_value(filename, key):
        path = Path(filename)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                name, separator, value = line.partition(":")
                if separator and name.strip() == key:
                    return value.strip()
        return "unknown"

    def sysctl(key):
        result = subprocess.run(
            ["sysctl", "-n", key], capture_output=True, text=True,
            check=False, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    cpu = attempt(lambda: proc_value("/proc/cpuinfo", "model name"))
    ram = attempt(lambda: proc_value("/proc/meminfo", "MemTotal"))
    if attempt(platform.system) == "Darwin":
        if cpu == "unknown":
            cpu = attempt(lambda: sysctl("machdep.cpu.brand_string"))
        if ram == "unknown":
            memory = attempt(lambda: sysctl("hw.memsize"))
            ram = memory + " bytes" if memory.isdigit() else "unknown"
    if cpu == "unknown":
        cpu = attempt(platform.processor)
    if cpu == "unknown":
        cpu = attempt(platform.machine)
    return {
        "cpu": cpu, "logical_cpus": attempt(os.cpu_count), "ram": ram,
        "os": attempt(platform.platform), "uname": attempt(lambda: list(platform.uname())),
    }


def test_laptop_benchmark(reference, tmp_path, capsys):
    """A2 evidence protocol; the owner must attest this was an actual laptop.

    Unlike D1 sizing, a laptop solve faster than five seconds is acceptable.
    Never reuse the session-scoped solved fixture: collect three fresh runs.
    """
    try:
        revision = run(["git", "rev-parse", "HEAD"], SESSION, timeout=10)
        checkout_revision = revision.stdout.strip() if revision.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        checkout_revision = "unknown"
    evidence = {
        "host": host_description(), "python": platform.python_version(),
        "checkout_revision": checkout_revision or "unknown",
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        # Match the checker's LF-normalised pins across Windows Git checkouts.
        "data_sha256": {
            path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for path in sorted((PACK / "data").glob("*.csv"))
        },
        "data_sha256_normalisation": "CRLF -> LF (matches checker pins)",
        "runs": [],
    }
    assert evidence["data_sha256"], "laptop: no data CSVs to identify"
    for i in range(3):
        record = execute_reference(reference, tmp_path / f"laptop-fresh-{i}")
        assert_optimal(record)
        verdict(record["checked"], 0)
        observed = record["observed"]
        seconds = observed["solve_seconds"]
        assert math.isfinite(seconds) and seconds < 60, (
            f"laptop: each fresh single-thread solve must finish under 60 s, got {seconds}"
        )
        evidence["highs_version"] = observed["highs_version"]
        evidence["runs"].append({
            **observed, "wall_seconds": record["wall_seconds"],
            "status": record["solution"]["status"], "checker_exit": record["checked"].returncode,
        })
    with capsys.disabled():
        print("\n" + json.dumps(evidence, sort_keys=True))


def normalised_source_lines(source):
    """Ignore indentation, comments, docstrings, imports and short boilerplate.

    Work on text rather than requiring Python syntax, so snippets copied into
    Markdown or another source language are checked too.
    """
    lines = []
    docstring_quote = None
    for raw in source.splitlines():
        line = raw.strip()
        if docstring_quote:
            if docstring_quote in line:
                docstring_quote = None
            continue
        start = re.match(r"(?i)^[ru]?(\"\"\"|''')", line)
        if start:
            quote = start[1]
            if quote not in line[start.end():]:
                docstring_quote = quote
            continue
        if len(line) < 25 or line.startswith("#") or re.match(r"^(?:import|from)\s", line):
            continue
        lines.append(line)
    return lines


def test_reference_not_disclosed(reference):
    """Detect copied reference fragments throughout the public checkout.

    This supports, but cannot replace, full-diff review for reformulations and
    committed optimal plans. Never print the matching private source on failure.
    """
    private_lines = normalised_source_lines(reference.read_text(encoding="utf-8"))
    assert len(private_lines) >= 4, "release: reference has too few substantive lines to audit"
    windows = {tuple(private_lines[i:i + 4]) for i in range(len(private_lines) - 3)}
    root = SESSION.parents[1]
    excluded = {".git", ".venv", "node_modules", "__pycache__", "artifacts"}
    disclosed = []

    def walk_error(error):
        raise error  # An unreadable subtree must not silently pass the audit.

    for directory, subdirectories, filenames in os.walk(root, onerror=walk_error):
        subdirectories[:] = sorted(name for name in subdirectories if name not in excluded)
        for name in sorted(filenames):
            if name in excluded:
                continue
            path = Path(directory) / name
            content = path.read_bytes()
            if b"\x00" in content:
                continue
            try:
                source = content.decode("utf-8")
            except UnicodeDecodeError:
                continue  # Binary assets are outside this source-disclosure check.
            lines = normalised_source_lines(source)
            if any(tuple(lines[i:i + 4]) in windows for i in range(len(lines) - 3)):
                disclosed.append(str(path.relative_to(root)))
    assert not disclosed, f"release: private reference source disclosed in {disclosed}"


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

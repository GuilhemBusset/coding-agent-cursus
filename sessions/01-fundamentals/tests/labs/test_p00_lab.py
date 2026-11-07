"""The P00 lab: the reference solves, each planted bug fails its named contract, and the export
hands students a clean standalone repository. The pack runs in isolated subprocesses."""

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
PACK = SESSION / "exercises" / "p00-lab"
COURSE = next(parent for parent in PACK.parents if (parent / ".git").exists())
CONTRACTS = {
    "flipped-sense": "objective contract",
    "dropped-demand": "feasibility contract",
    "relaxed-binary": "integrality contract",
    "timelimit-as-optimal": "status contract",
}
SELECTORS = ("none", *CONTRACTS)
EXPORT_FILES = {
    "README.md", "p00_model.py", "p00_checker.py", "test_p00_contract.py",
    "data/plants.csv", "data/customers.csv", "data/costs.csv",
    "pyproject.toml", "uv.lock", "mise.toml", "AGENTS.md", "CLAUDE.md", ".gitignore",
    ".vscode/settings.json", ".vscode/extensions.json", "setup/editor.py", "setup/editor.json",
}


def child_env():
    env = os.environ.copy()
    for key in (
        "PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "GIT_DIR", "GIT_WORK_TREE",
        "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
    ):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return env


def run(args, cwd, timeout=30):
    return subprocess.run(
        [str(arg) for arg in args], cwd=cwd, env=child_env(),
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def success(args, cwd):
    result = run(args, cwd)
    assert result.returncode == 0, f"command contract: {args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def read_csv(directory, name):
    with (directory / name).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def independently_check(directory, solution, expected):
    """Do not use either pack module to certify the CLI's numerical result."""
    _, plants = read_csv(directory, "plants.csv")
    _, customers = read_csv(directory, "customers.csv")
    _, routes = read_csv(directory, "costs.csv")
    pids = {row["plant"] for row in plants}
    cids = {row["customer"] for row in customers}
    assert solution["status"] in {"optimal", "feasible"}, "status contract: CLI must return a solution"
    assert set(solution["open"]) == pids, "feasibility contract: opening IDs"
    assert set(solution["flow"]) == pids, "feasibility contract: flow plant IDs"
    for plant in plants:
        p = plant["plant"]
        opening = solution["open"][p]
        assert math.isfinite(opening) and min(abs(opening), abs(opening - 1)) <= 1e-6, (
            "integrality contract: CLI returned a non-binary opening"
        )
        assert set(solution["flow"][p]) == cids, "feasibility contract: flow customer IDs"
        assert all(math.isfinite(x) and x >= -1e-6 for x in solution["flow"][p].values()), (
            "feasibility contract: finite nonnegative shipments"
        )
        assert sum(solution["flow"][p].values()) <= float(plant["capacity"]) * opening + 1e-6, (
            "feasibility contract: capacity linked to opening"
        )
    for customer in customers:
        received = sum(solution["flow"][p][customer["customer"]] for p in pids)
        assert math.isclose(received, float(customer["demand"]), abs_tol=1e-6), (
            "feasibility contract: every customer's demand must be met"
        )
    recomputed = sum(float(p["fixed_cost"]) * solution["open"][p["plant"]] for p in plants)
    recomputed += sum(
        float(r["unit_cost"]) * solution["flow"][r["plant"]][r["customer"]] for r in routes
    )
    for value in (recomputed, solution["objective"]):
        assert math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-6), (
            f"objective contract: expected {expected}, got {value}"
        )


def test_reference_solves_on_highspy(tmp_path):
    solution = json.loads(success([sys.executable, "p00_model.py"], PACK))
    independently_check(PACK / "data", solution, 485.0)
    # Doubling every cost preserves the optimizer and doubles the objective.
    # This exercises solve(data_dir=...) instead of only the obvious fixed answer.
    for name, cost_field in [("plants.csv", "fixed_cost"), ("customers.csv", None), ("costs.csv", "unit_cost")]:
        headers, rows = read_csv(PACK / "data", name)
        if cost_field:
            for row in rows:
                row[cost_field] = str(2 * float(row[cost_field]))
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    source = (
        "import json, sys; from pathlib import Path; import p00_model; "
        "print(json.dumps(p00_model.solve(data_dir=Path(sys.argv[1]), time_limit=10.0)))"
    )
    alternate = json.loads(success([sys.executable, "-c", source, tmp_path], PACK))
    independently_check(tmp_path, alternate, 970.0)


def test_checker_is_solver_free():
    # -S: no site-packages, so the checker certifies a solution without highspy.
    source = """
import p00_checker
data = p00_checker.load_data(p00_checker.DATA_DIR)
solution = {
    'status': 'feasible', 'objective': 999.0,
    'open': {p: 0.0 for p in data['plants']},
    'flow': {p: {c: 0.0 for c in data['customers']} for p in data['plants']},
}
assert p00_checker.objective(data, solution) == 0.0, 'objective contract: recompute without a solver'
assert p00_checker.feasibility_problems(data, solution), 'feasibility contract: detect unmet demand without a solver'
assert not p00_checker.integrality_problems(data, solution), 'integrality contract: zero is integral'
assert p00_checker.problems(data, solution), 'feasibility contract: combined checker runs without a solver'
"""
    success([sys.executable, "-S", "-c", source], PACK)


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    root = tmp_path_factory.mktemp("p00-exports")
    assert not root.resolve().is_relative_to(COURSE), "export contract: test exports must be outside course checkout"
    result = {}
    for index, selector in enumerate(SELECTORS):
        target = root / f"lab-{index}"
        success([sys.executable, PACK / "export.py", "--bug", selector, "--out", target], root)
        result[selector] = target
    return result


def contract_suite(directory, report):
    started = time.perf_counter()
    process = run([
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--junitxml", report, "test_p00_contract.py",
    ], directory)
    elapsed = time.perf_counter() - started
    assert report.is_file(), f"suite contract: JUnit missing\n{process.stdout}\n{process.stderr}"
    xml = ET.parse(report).getroot()
    suites = list(xml.iter("testsuite"))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    assert elapsed < 10, f"runtime contract: student suite took {elapsed:.3f}s"
    return {
        **totals, "process": process,
        "cases": [(case.get("classname"), case.get("name")) for case in xml.iter("testcase")],
        "messages": [failure.get("message", "") for failure in xml.iter("failure")],
    }


def test_contract_suite_passes_reference_and_names_each_planted_bug(exports, tmp_path):
    # One test for the five suite runs, so parallel workers do not each repeat them.
    results = {selector: contract_suite(directory, tmp_path / f"suite-{index}.xml")
               for index, (selector, directory) in enumerate(exports.items())}
    reference = results["none"]
    assert reference["process"].returncode == 0, reference["process"].stdout + reference["process"].stderr
    assert reference["tests"] > 0, "suite contract: must collect student tests"
    assert reference["failures"] == reference["errors"] == reference["skipped"] == 0, (
        "suite contract: reference must pass every test without skips"
    )
    for selector, contract in CONTRACTS.items():
        result = results[selector]
        assert result["process"].returncode == 1, f"{selector}: expected assertion failures, not collection/usage errors"
        assert result["errors"] == result["skipped"] == 0, f"{selector}: no errors or skips in variants"
        assert result["cases"] == reference["cases"], f"{selector}: identical collected tests"
        assert result["failures"] > 0 and any(contract in message for message in result["messages"]), (
            f"{selector}: assertion failure must name {contract}\n{result['process'].stdout}"
        )


def tree(directory):
    skip = {".git", "__pycache__", ".pytest_cache"}
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in directory.rglob("*")
            if path.is_file() and not skip.intersection(path.relative_to(directory).parts)}


@pytest.fixture(scope="module")
def tests_dir_exports(tmp_path_factory):
    # The recorded agent runs (cursus/fixtures/runs) export with --tests-dir: the suite moves to tests/.
    root = tmp_path_factory.mktemp("p00-tests-dir")
    result = {}
    for index, selector in enumerate(SELECTORS):
        target = root / f"lab-{index}"
        success([sys.executable, PACK / "export.py", "--tests-dir", "--bug", selector, "--out", target], root)
        result[selector] = target
    return result


def test_tests_dir_layout_moves_only_the_suite(exports, tests_dir_exports):
    default, moved = tree(exports["none"]), tree(tests_dir_exports["none"])
    assert set(moved) == (set(default) - {"test_p00_contract.py"}) | {"tests/test_p00_contract.py", "tests/__init__.py"}
    assert moved["tests/test_p00_contract.py"] == default["test_p00_contract.py"] and moved["tests/__init__.py"] == b""
    assert moved[".gitignore"] == default[".gitignore"] + b".claude/settings.local.json\n"
    assert all(moved[name] == default[name] for name in set(default) - {"test_p00_contract.py", "AGENTS.md", ".gitignore"})
    assert "tests/" in moved["AGENTS.md"].decode("utf-8")


@pytest.mark.parametrize("selector", SELECTORS)
def test_tests_dir_variant_changes_only_the_model_and_fails_its_contract(selector, tests_dir_exports):
    reference, variant = tree(tests_dir_exports["none"]), tree(tests_dir_exports[selector])
    assert variant.keys() == reference.keys()
    assert [name for name in variant if variant[name] != reference[name]] == ([] if selector == "none" else ["p00_model.py"])
    assert success(["git", "status", "--short"], tests_dir_exports[selector]) == ""
    suite = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rN"], tests_dir_exports[selector])
    summary = suite.stdout.strip().splitlines()[-1]
    assert "skipped" not in summary and "error" not in summary, suite.stdout
    if selector == "none":
        assert suite.returncode == 0 and "passed" in summary and "failed" not in summary, suite.stdout
    else:
        assert suite.returncode == 1 and "failed" in summary and CONTRACTS[selector] in suite.stdout, suite.stdout


def test_dropped_demand_is_strictly_better(exports):
    reference = json.loads(success([sys.executable, "p00_model.py"], exports["none"]))
    other = json.loads(success([sys.executable, "p00_model.py"], exports["dropped-demand"]))
    assert other["status"] in {"optimal", "feasible"}, "status contract: variant must return a solution"
    assert other["objective"] < reference["objective"], "objective contract: missing demand must appear better"
    assert math.isclose(reference["objective"], 485, abs_tol=1e-6), "objective contract: reference objective"
    assert math.isclose(other["objective"], 425, abs_tol=1e-6), "objective contract: expected missing-C5 objective"


def exported_files(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(directory).parts
    }


def test_export_hides_planted_bug(exports):
    baseline = exported_files(exports["none"])
    assert set(baseline) == EXPORT_FILES, "export contract: explicit student-file allowlist"
    logs = []
    for selector, directory in exports.items():
        files = exported_files(directory)
        assert files.keys() == baseline.keys(), "export contract: identical filenames across variants"
        for name, content in files.items():
            if name != "p00_model.py":
                assert content == baseline[name], f"export contract: unexpected variant in {name}"
            lowered = name.lower().encode() + b"\n" + content.lower()
            for forbidden in (*CONTRACTS, "planted", str(COURSE), str(PACK)):
                assert forbidden.lower().encode() not in lowered, f"export contract: hint or source path in {name}"
        if selector != "none":
            assert files["p00_model.py"] != baseline["p00_model.py"], "export contract: variant must change the model"
        assert success(["git", "rev-list", "--count", "HEAD"], directory).strip() == "1", (
            "export contract: exactly one initial commit"
        )
        logs.append(success(["git", "log", "--format=%B"], directory))
        assert not success(["git", "remote"], directory).strip(), "export contract: no course remote"
    assert all(log.strip() == "Initial commit" for log in logs), "export contract: identical neutral commit messages"


def test_export_is_standalone_repo(exports):
    for directory in exports.values():
        assert (directory / ".git").is_dir(), "export contract: standalone git metadata"
        root = success(["git", "rev-parse", "--show-toplevel"], directory).strip()
        assert Path(root).resolve() == directory.resolve(), "export contract: repository root must be the export"
        assert not success(["git", "status", "--porcelain", "--untracked-files=all"], directory).strip(), (
            "export contract: clean committed working tree"
        )
        assert success(["git", "branch", "--show-current"], directory).strip() == "main", "export contract: initial main branch"
        for name in ("pyproject.toml", "uv.lock", "mise.toml"):
            assert (directory / name).read_bytes() == (SESSION / name).read_bytes(), (
                f"setup contract: copy pinned session {name} byte-for-byte"
            )
        for name in (".vscode/settings.json", ".vscode/extensions.json"):
            assert (directory / name).read_bytes() == (SESSION / name).read_bytes(), (
                f"editor contract: portable session configuration must survive export: {name}"
            )
        for name in ("setup/editor.py", "setup/editor.json"):
            assert (directory / name).read_bytes() == (COURSE / name).read_bytes(), (
                f"editor contract: the standalone installer must survive export: {name}"
            )
        for name in ("p00_checker.py", "test_p00_contract.py", "data/plants.csv", "data/customers.csv", "data/costs.csv"):
            assert (directory / name).read_bytes() == (PACK / name).read_bytes(), f"export contract: preserve {name}"
        assert (directory / "README.md").read_bytes() == (PACK / "PROBLEM.md").read_bytes(), (
            "export contract: student statement replaces instructor README"
        )
        assert (directory / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md", (
            "navigation contract: Claude imports the same instructions"
        )
        ignored = (directory / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert {".venv/", "__pycache__/", ".pytest_cache/"} <= set(ignored), "export contract: ignore generated local files"


def test_export_rejects_bad_arguments(tmp_path):
    unknown = tmp_path / "unknown"
    result = run([sys.executable, PACK / "export.py", "--bug", "invalid-choice", "--out", unknown], tmp_path)
    assert result.returncode != 0 and not unknown.exists(), "export contract: reject unknown selector without writing"
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_bytes(b"do not replace\n")
    before = exported_files(occupied)
    result = run([sys.executable, PACK / "export.py", "--bug", "none", "--out", occupied], tmp_path)
    assert result.returncode != 0, "export contract: refuse nonempty output"
    assert exported_files(occupied) == before and not (occupied / ".git").exists(), (
        "export contract: leave nonempty output untouched"
    )
    # An empty target exercises the checkout boundary independently of the
    # nonempty-directory guard, including checkouts whose .git is a file.
    with tempfile.TemporaryDirectory(prefix="p00-boundary-", dir=SESSION) as inside:
        target = Path(inside)
        result = run([sys.executable, PACK / "export.py", "--bug", "none", "--out", target], tmp_path)
        assert result.returncode != 0, "export contract: refuse output inside the course checkout"
        assert list(target.iterdir()) == [], "export contract: leave refused checkout target untouched"

"""Locked instructor acceptance checks for the L3 cyclic staffing exercise.

The reference model and witness rosters live here, outside the student pack.
Run from the session with ``uv run pytest -q tests/test_l3_word_problem.py``.
The checker is always a subprocess; no implementation module is imported.
"""

import ast
import csv
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import pytest


SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / "exercises" / "l3-word-problem"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEMAND = dict(zip(DAYS, (8, 7, 8, 9, 8, 5, 6)))
OPTIMAL = (4, 1, 2, 1, 1, 1, 1)
LP_POINT = (3.6, 0.6, 1.6, 1.6, 0.6, 0.6, 1.6)
TOL = 1e-6
CONTRACTS = ("data", "format", "feasibility", "integrality", "objective", "optimality")
NUMBER = r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.])"


def child_env():
    env = os.environ.copy()
    for key in (
        "PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
    ):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return env


def payload(starts=OPTIMAL, objective=None):
    return {"objective": sum(starts) if objective is None else objective,
            "start": dict(zip(DAYS, starts))}


def write_solution(directory, solution, name="candidate.json"):
    path = directory / name
    path.write_text(json.dumps(solution), encoding="utf-8")
    return path


def run_check(path, *, pack=PACK, cwd=None, no_site=False):
    script = pack / "check.py"
    assert script.is_file(), f"D2: missing independent checker: {script}"
    args = [sys.executable]
    if no_site:
        args.append("-S")
    args.append(str(script))
    if path is not None:
        args.append(str(path))
    return subprocess.run(
        args, cwd=cwd or pack, env=child_env(), capture_output=True,
        text=True, encoding="utf-8", timeout=10, check=False,
    )


def verdict(result, passed, expected_contracts=()):
    diagnostic = result.stdout + "\n" + result.stderr
    assert "Traceback" not in diagnostic, diagnostic
    assert diagnostic.isascii(), "CLI must use ASCII output on every platform"
    assert result.returncode == (0 if passed else 1), diagnostic
    lines = result.stdout.splitlines()
    assert lines and lines[0] == ("PASS" if passed else "FAIL"), diagnostic
    messages = {
        kind: [line for line in lines[1:] if line.startswith(kind + ":")]
        for kind in CONTRACTS
    }
    assert {kind for kind, rows in messages.items() if rows} == set(expected_contracts), diagnostic
    return messages


def has_number(text, value, tolerance=5e-5):
    return any(abs(float(token) - value) <= tolerance for token in re.findall(NUMBER, text))


def assert_summary(result, headcount):
    # Check labels and values, without prescribing punctuation or line layout.
    lines = result.stdout.splitlines()[1:]
    lines = [line for line in lines if not any(line.startswith(k + ":") for k in CONTRACTS)]
    head_lines = [line for line in lines if re.search(r"headcount|recomputed", line, re.I)]
    bound_lines = [line for line in lines if re.search(r"\bLP\b|relaxation", line, re.I)]
    gap_lines = [line for line in lines if re.search(r"gap", line, re.I)]
    assert any(has_number(line, headcount) for line in head_lines), result.stdout
    assert any(has_number(line, 10.2) for line in bound_lines), result.stdout
    assert any(has_number(line, headcount - 10.2) for line in gap_lines), result.stdout
    if headcount > 0:
        percentages = re.findall(r"([-+]?\d+(?:\.\d+)?)\s*%", "\n".join(gap_lines))
        expected = 100 * (headcount - 10.2) / headcount
        assert any(abs(float(value) - expected) <= 0.011 for value in percentages), result.stdout
    else:
        assert any("n/a" in line.lower() for line in gap_lines), result.stdout


def coverage(starts):
    # Construct each shift's five working days, independently of the checker.
    return tuple(sum(starts[s] for s in range(7) if (day - s) % 7 < 5) for day in range(7))


def compositions(total, parts):
    """Yield nonnegative integer compositions in lexicographic order."""
    if parts == 1:
        yield (total,)
    else:
        for first in range(total + 1):
            for tail in compositions(total - first, parts - 1):
                yield (first, *tail)


def short_days(starts):
    return [day for day, value in zip(DAYS, coverage(starts)) if value < DEMAND[day] - TOL]


def demand_from_csv(pack=PACK):
    with (pack / "data" / "demand.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["day", "demand"], "D1: CSV header must be day,demand"
        rows = list(reader)
    assert [row["day"] for row in rows] == list(DAYS), "D1: exactly seven rows, Mon through Sun"
    values = {row["day"]: float(row["demand"]) for row in rows}
    assert values == DEMAND, "D1: instance demand must be 8,7,8,9,8,5,6"
    return values


def checker_constants():
    tree = ast.parse((PACK / "check.py").read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id in {"LP_BOUND", "KNOWN_OPTIMUM", "TOL", "DEMAND"}:
                constants[target.id] = ast.literal_eval(node.value)
    assert constants == {"LP_BOUND": 10.2, "KNOWN_OPTIMUM": 11, "TOL": TOL, "DEMAND": DEMAND}, (
        "D2/D3: pin the agreed instance, tolerance, LP bound and optimum as literal constants"
    )
    return constants


def section(markdown, title):
    heading = re.search(rf"(?mi)^(#{{1,6}})\s+{re.escape(title)}\s*#*\s*$", markdown)
    assert heading, f"Documentation needs a {title!r} section"
    rest = markdown[heading.end():]
    end = re.search(rf"(?m)^#{{1,{len(heading[1])}}}\s+", rest)
    return rest[:end.start() if end else len(rest)].strip()


def test_layout_and_statement():
    for name in ("README.md", "check.py", "data/demand.csv"):
        assert (PACK / name).is_file(), f"D1: missing {name}"
    demand_from_csv()
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    problem = section(readme, "Problem")
    assert len(re.split(r"\n\s*\n", problem)) == 1 and problem, "D1: one prose paragraph"
    assert not re.search(r"(?m)^\s*(?:[-*] |\d+\. |```|#)", problem), "D1: prose, not a list or code"
    # Broad semantic markers for the agreed statement; editorial quality is reviewed.
    assert re.search(r"\b(?:5|five)\b", problem, re.I) and re.search(r"consecutive|successive|in a row", problem, re.I)
    assert re.search(r"\b(?:2|two)\b", problem, re.I) and re.search(r"off|rest", problem, re.I)
    assert re.search(r"wrap|cycl|repeat|Sun\w*.*Mon", problem, re.I | re.S)
    assert re.search(r"minimi[sz]|minimum|fewest|as few", problem, re.I)
    assert re.search(r"headcount|staff|people|employees|workers", problem, re.I)
    assert "data/demand.csv" in readme and "solution.json" in readme
    assert re.search(r"uv\s+run\s+python\s+check\.py", readme)
    assert re.search(r"(?m)(?:^|`)\s*python\s+check\.py", readme), "D1: document plain Python too"
    assert '"objective"' in readme and '"start"' in readme
    assert all(f'"{day}"' in readme for day in DAYS), "D1: example must show all seven day keys"
    assert "PASS" in readme and re.search(r"gap", readme, re.I), "D1: document the done criterion"
    assert has_number(readme, 10.2) and has_number(readme, 11), "D1: publish bound and optimum"
    layout = section((SESSION / "README.md").read_text(encoding="utf-8"), "Layout")
    assert any("exercises/l3-word-problem/" in line and "|" in line for line in layout.splitlines())
    assert {p.name for p in PACK.glob("*.py")} == {"check.py"}, "D1: the student pack ships no reference model"
    assert not (PACK / "solution.json").exists(), "D1: students must build their own solution"


def test_checker_is_solver_free(tmp_path):
    tree = ast.parse((PACK / "check.py").read_text(encoding="utf-8"))
    allowed = {"json", "csv", "math", "sys", "pathlib", "argparse"}
    forbidden = {"subprocess", "os", "ctypes", "multiprocessing", "importlib",
                 "__import__", "eval", "exec", "compile"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and (node.module or "").split(".")[0] in allowed
            assert all(alias.name not in forbidden for alias in node.names)
        elif isinstance(node, ast.Name):
            assert node.id not in forbidden, f"D2: forbidden reference {node.id}"
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, f"D2: forbidden attribute {node.attr}"
    result = run_check(write_solution(tmp_path, payload()), no_site=True, cwd=tmp_path)
    verdict(result, True)
    assert_summary(result, 11)


@pytest.mark.parametrize("target", DAYS)
def test_checker_detects_each_days_coverage(target, tmp_path):
    starts = next((row for row in compositions(11, 7) if short_days(row) == [target]), None)
    assert starts is not None, f"Test premise: an isolated shortfall for {target} exists"
    result = run_check(write_solution(tmp_path, payload(starts)))
    messages = verdict(result, False, {"feasibility"})
    assert len(messages["feasibility"]) == 1, result.stdout
    line = messages["feasibility"][0]
    assert target in line and has_number(line, coverage(starts)[DAYS.index(target)])
    assert has_number(line, DEMAND[target]), line
    assert_summary(result, 11)


def test_checker_rejects_feasible_fractional_headcount_eleven(tmp_path):
    starts = (4.4, 0.6, 1.6, 1.6, 0.6, 0.6, 1.6)
    assert not short_days(starts) and abs(sum(starts) - 11) < TOL
    result = run_check(write_solution(tmp_path, payload(starts, 11)))
    messages = verdict(result, False, {"integrality"})
    for day, value in zip(DAYS, starts):
        assert any(day in line and has_number(line, value) for line in messages["integrality"]), result.stdout
    assert_summary(result, 11)


@pytest.mark.parametrize("reported", [0, 10.2, 12, 999])
def test_checker_recomputes_objective(tmp_path, reported):
    result = run_check(write_solution(tmp_path, payload(objective=reported)))
    messages = verdict(result, False, {"objective"})
    assert any(has_number(line, reported) and has_number(line, 11) for line in messages["objective"])
    assert_summary(result, 11)


@pytest.mark.parametrize("case", [
    "missing-file", "malformed", "null-root", "list-root", "missing-objective", "missing-start",
    "extra-root", "missing-day", "extra-day", "null-start", "list-start",
    "string-start", "null-value", "bool-start", "nan-start", "inf-start", "minus-inf-start",
    "string-objective", "null-objective", "bool-objective", "nan-objective", "inf-objective",
])
def test_checker_bad_format(tmp_path, case):
    solution = payload()
    path = tmp_path / "input.json"
    if case == "missing-file":
        pass
    elif case == "malformed":
        path.write_text('{"start":', encoding="utf-8")
    else:
        if case == "null-root":
            solution = None
        elif case == "list-root":
            solution = []
        elif case.startswith("missing-"):
            if case == "missing-day":
                del solution["start"]["Wed"]
            else:
                del solution[case.removeprefix("missing-")]
        elif case == "extra-root":
            solution["unrecognized"] = 0
        elif case == "extra-day":
            solution["start"]["Holiday"] = 0
        elif case == "null-start":
            solution["start"] = None
        elif case == "list-start":
            solution["start"] = list(OPTIMAL)
        else:
            invalid = {"string": "4", "null": None, "bool": True, "nan": float("nan"),
                       "inf": float("inf"), "minus-inf": float("-inf")}
            if case.endswith("-objective"):
                solution["objective"] = invalid[case.removesuffix("-objective")]
            else:
                kind = case.removesuffix("-start").removesuffix("-value")
                solution["start"]["Mon"] = invalid[kind]
        write_solution(tmp_path, solution, path.name)
    messages = verdict(run_check(path), False, {"format"})
    assert all(len(line.removeprefix("format:").strip()) > 0 for line in messages["format"])


def test_checker_reports_multiple_format_problems(tmp_path):
    solution = payload()
    solution["objective"] = False
    solution["start"]["Mon"] = "four"
    del solution["start"]["Tue"]
    result = run_check(write_solution(tmp_path, solution))
    messages = verdict(result, False, {"format"})
    assert len(messages["format"]) >= 3, result.stdout
    assert all(word in "\n".join(messages["format"]) for word in ("objective", "Mon", "Tue"))


@pytest.mark.parametrize("starts", [(0,) * 7, (5, 1, 2, 1, 1, 2, -1)])
def test_checker_negative_and_zero_rosters(tmp_path, starts):
    result = run_check(write_solution(tmp_path, payload(starts)))
    contracts = {"feasibility"} | ({"optimality"} if sum(starts) != 11 else set())
    messages = verdict(result, False, contracts)
    for day in short_days(starts):
        assert any(day in line and has_number(line, DEMAND[day]) for line in messages["feasibility"])
    if min(starts) < 0:
        assert any("Sun" in line and has_number(line, -1) for line in messages["feasibility"])
    assert_summary(result, sum(starts))


@pytest.mark.parametrize("reported_offset,expected", [(5e-7, True), (-5e-7, True), (2e-6, False)])
def test_checker_objective_tolerance(tmp_path, reported_offset, expected):
    result = run_check(write_solution(tmp_path, payload(objective=11 + reported_offset)))
    verdict(result, expected, () if expected else {"objective"})


@pytest.mark.parametrize("offset", [-5e-7, 5e-7])
def test_checker_accepts_numerical_noise(tmp_path, offset):
    starts = list(OPTIMAL)
    starts[0] += offset
    result = run_check(write_solution(tmp_path, payload(starts)))
    verdict(result, True)
    assert_summary(result, sum(starts))


def test_checker_nonnegativity_and_coverage_tolerance(tmp_path):
    # Find an integral optimum with a zero start and a tight day served by it.
    witness = next((
        (row, s) for row in compositions(11, 7) if not short_days(row)
        for s in range(7) if row[s] == 0
        and any(coverage(row)[d] == DEMAND[DAYS[d]] and (d - s) % 7 < 5 for d in range(7))
    ), None)
    assert witness is not None, "Test premise: zero start with a tight covered day"
    row, index = witness
    for delta in (-5e-7, -2e-6):
        starts = list(row)
        starts[index] = delta
        result = run_check(write_solution(tmp_path, payload(starts)))
        if abs(delta) < TOL:
            verdict(result, True)
        else:
            messages = verdict(result, False, {"feasibility", "integrality", "optimality"})
            assert any(DAYS[index] in line for line in messages["integrality"])
            assert len(messages["feasibility"]) >= 2, result.stdout


@pytest.fixture
def copied_pack(tmp_path):
    assert PACK.is_dir(), "D1: missing L3 exercise directory"
    return Path(shutil.copytree(PACK, tmp_path / "copied exercise"))


@pytest.mark.parametrize("mutation", ["changed-demand", "missing-day", "bad-number"])
def test_checker_pins_data(copied_pack, tmp_path, mutation):
    path = copied_pack / "data" / "demand.csv"
    rows = list(DEMAND.items())
    if mutation == "changed-demand":
        rows[0] = ("Mon", 0)
    elif mutation == "missing-day":
        rows.pop()
    else:
        rows[0] = ("Mon", "eight")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["day", "demand"])
        writer.writerows(rows)
    result = run_check(write_solution(tmp_path, payload()), pack=copied_pack, cwd=tmp_path)
    verdict(result, False, {"data"})


def test_checker_pins_parsed_values_not_bytes(copied_pack, tmp_path):
    path = copied_pack / "data" / "demand.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(["day", "demand"])
        writer.writerows((day, str(value)) for day, value in reversed(list(DEMAND.items())))
    result = run_check(write_solution(tmp_path, payload()), pack=copied_pack, cwd=tmp_path)
    verdict(result, True)


def test_optimum_and_bound_certificate():
    constants = checker_constants()
    demand = demand_from_csv()
    dual = Fraction(1, 5)
    assert all(sum(dual for d in range(7) if (d - s) % 7 < 5) == 1 for s in range(7))
    bound = sum(Fraction(str(value)) for value in demand.values()) * dual
    point = tuple(Fraction(str(value)) for value in LP_POINT)
    assert coverage(point) == tuple(demand.values())
    assert sum(point) == Fraction(51, 5)
    assert float(bound) == constants["LP_BOUND"]
    assert math.ceil(bound) == constants["KNOWN_OPTIMUM"] == sum(OPTIMAL)
    assert not short_days(OPTIMAL)


def solve_reference(*, integral):
    """Instructor-only HiGHS model; timing includes CSV loading and model build."""
    import highspy

    started = time.perf_counter()
    demand = demand_from_csv()
    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    # Keep default threads: P00 may already have initialized HiGHS's
    # process-wide scheduler before this reference model runs.
    model.setOptionValue("time_limit", 4.0)
    model.setOptionValue("mip_rel_gap", 0.0)
    variable_type = highspy.HighsVarType.kInteger if integral else highspy.HighsVarType.kContinuous
    starts = [model.addVariable(lb=0, obj=1, type=variable_type) for _ in DAYS]
    for d, day in enumerate(DAYS):
        model.addConstr(sum(starts[(d - offset) % 7] for offset in range(5)) >= demand[day])
    model.changeObjectiveSense(highspy.ObjSense.kMinimize)
    model.run()
    elapsed = time.perf_counter() - started
    assert model.getModelStatus() == highspy.HighsModelStatus.kOptimal, model.modelStatusToString(model.getModelStatus())
    values = tuple(float(model.val(var)) for var in starts)
    assert not short_days(values), "Reference model must satisfy the independently computed coverage"
    return payload(values, float(model.getObjectiveValue())), elapsed


def test_optimum_and_bound_highs_lp_relaxation():
    solution, _ = solve_reference(integral=False)
    assert abs(solution["objective"] - checker_constants()["LP_BOUND"]) <= TOL
    assert abs(sum(solution["start"].values()) - 10.2) <= TOL


def test_highs_solves_reference_under_five_seconds():
    solution, elapsed = solve_reference(integral=True)
    assert elapsed < 5.0, f"A2: reference build and solve took {elapsed:.3f}s"
    assert abs(solution["objective"] - checker_constants()["KNOWN_OPTIMUM"]) <= TOL
    assert all(abs(value - round(value)) <= TOL for value in solution["start"].values())


def test_check_command_passes_raw_highs_solution(tmp_path):
    solution, _ = solve_reference(integral=True)
    result = run_check(write_solution(tmp_path, solution))
    verdict(result, True)
    assert_summary(result, 11)


def test_check_command_accepts_other_optimal_rosters(tmp_path):
    alternatives = [row for row in compositions(11, 7) if row != OPTIMAL and not short_days(row)]
    assert len(alternatives) >= 4
    for starts in alternatives[::max(1, len(alternatives) // 4)][:4]:
        result = run_check(write_solution(tmp_path, payload(starts)))
        verdict(result, True)
        assert_summary(result, 11)


@pytest.mark.parametrize("extra", [1, 3, 7])
def test_check_command_suboptimal_feasible_gap(tmp_path, extra):
    starts = list(OPTIMAL)
    starts[2] += extra
    result = run_check(write_solution(tmp_path, payload(starts)))
    messages = verdict(result, False, {"optimality"})
    assert any(has_number(line, 11 + extra) and has_number(line, 11) for line in messages["optimality"])
    assert_summary(result, 11 + extra)


def test_check_command_default_and_override(copied_pack, tmp_path):
    write_solution(copied_pack, payload(), "solution.json")
    # The default is next to the script, even when launched from another cwd.
    verdict(run_check(None, pack=copied_pack, cwd=tmp_path), True)
    alternate = write_solution(tmp_path, payload(objective=99), "other solution.json")
    verdict(run_check(alternate, pack=copied_pack, cwd=tmp_path), False, {"objective"})


@pytest.mark.parametrize("name,starts,reported,contracts", [
    ("understaffed", (4, 1, 2, 1, 1, 1, 0), 10, {"feasibility", "optimality"}),
    ("fractional", LP_POINT, 10.2, {"integrality", "optimality"}),
    ("misreported", (4, 1, 2, 2, 1, 1, 1), 11, {"objective", "optimality"}),
])
def test_seeded_wrong_solution(name, starts, reported, contracts):
    path = PACK / "wrong" / f"{name}.json"
    assert path.is_file(), f"A1: missing seeded wrong solution {name}"
    assert json.loads(path.read_text(encoding="utf-8")) == payload(starts, reported)
    result = run_check(path)
    messages = verdict(result, False, contracts)
    if name == "understaffed":
        assert len(messages["feasibility"]) == 3, result.stdout
        for day, observed, required in (("Mon", 7, 8), ("Thu", 8, 9), ("Sun", 5, 6)):
            assert any(day in line and has_number(line, observed) and has_number(line, required)
                       for line in messages["feasibility"]), result.stdout
    elif name == "fractional":
        assert any("Mon" in line and has_number(line, 3.6) for line in messages["integrality"])
    else:
        assert any(has_number(line, 11) and has_number(line, 12) for line in messages["objective"])
    assert_summary(result, sum(starts))

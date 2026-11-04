"""Act IV's #catch and #l3 slides, checked against what P00 really does (the deck's Node suite checks the rest).

#catch: three fixes to a P00 export of the planted relaxed-binary bug, each in its own fresh export: A edits the
tests, B is the one-line model fix, C returns P00's known best plan as a constant. The fixes are the deck's own,
illustrative; every output the slide shows is real, and this test reruns them: L2's three done commands and the
fourth check. Fix C must pass all three done commands, which is the slide's point.

#l3: P00's five versions, the reference and the four planted bugs. HiGHS reports every one optimal; only the
reference passes the contract. The objectives on the slide are the ones each version's own model returns.
"""
import html
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

SESSION = Path(__file__).resolve().parents[1]
DECK = SESSION / "cursus/04-evidence.html"
P00 = SESSION / "exercises/p00-lab"
BUG = "relaxed-binary"
DONE = ["git diff --stat -- tests/", "uv run pytest", "git status --short"]
FOURTH = "git diff -- p00_model.py"

# The three fixes, as the deck's generator applies them: (file in the export, old text, new text), old occurring once.
FIXES = {
    "A": {
        "label": "edits the tests",
        "what": "Weakens two contract tests in tests/test_p00_contract.py: the objective may be at most "
                "485 instead of equal to it, and the openings need only lie in [0, 1]. p00_model.py is "
                "untouched, so the LP relaxation (openings continuous) is still what it solves.",
        "patches": [
            (
                "tests/test_p00_contract.py",
                "    assert close(solution[\"objective\"], KNOWN_OPTIMUM), (\n",
                "    assert solution[\"objective\"] <= KNOWN_OPTIMUM + 1e-6, (\n",
            ),
            (
                "tests/test_p00_contract.py",
                "    errors = p00_checker.integrality_problems(data, solution)\n"
                "    assert not errors, \"integrality contract: \" + \"; \".join(errors)\n"
                "    rounded = deepcopy(solution)\n"
                "    rounded[\"open\"] = {plant: round(value) for plant, value in solution[\"open\"].items()}\n"
                "    errors = p00_checker.problems(data, rounded)\n"
                "    assert not errors, \"integrality contract: rounding must preserve feasibility: \" + \"; \".join(errors)\n"
                "    assert close(p00_checker.objective(data, rounded), p00_checker.objective(data, solution)), (\n"
                "        \"integrality contract: rounding changed the objective\"\n"
                "    )\n",
                "    assert all(0.0 <= value <= 1.0 for value in solution[\"open\"].values()), (\n"
                "        \"integrality contract: openings must lie in [0, 1]\"\n"
                "    )\n",
            ),
        ],
    },
    "B": {
        "label": "fixes the model line",
        "what": "The honest one-line fix in p00_model.py: the opening variables go back to integers.",
        "patches": [
            ("p00_model.py", "type=highspy.HighsVarType.kContinuous", "type=highspy.HighsVarType.kInteger"),
        ],
    },
    "C": {
        "label": "returns the best plan as a constant",
        "what": "Leaves the bug in place and makes solve() return P00's known best plan (485: P1 ships C1 "
                "and C2, P2 ships C3, C4 and C5) as a constant. The status still comes from HiGHS through "
                "the real contract_status.",
        "patches": [
            (
                "p00_model.py",
                "DATA_DIR = Path(__file__).parent / \"data\"\n",
                "DATA_DIR = Path(__file__).parent / \"data\"\n"
                "BEST_FLOW = {(\"P1\", \"C1\"): 20.0, (\"P1\", \"C2\"): 30.0,\n"
                "             (\"P2\", \"C3\"): 25.0, (\"P2\", \"C4\"): 15.0, (\"P2\", \"C5\"): 10.0}\n",
            ),
            (
                "p00_model.py",
                "        \"objective\": float(h.getObjectiveValue()),\n"
                "        \"open\": {p: float(h.val(y[p])) for p in plant_ids},\n"
                "        \"flow\": {p: {c: float(h.val(x[p, c])) for c in customer_ids} for p in plant_ids},\n",
                "        \"objective\": 485.0,\n"
                "        \"open\": {\"P1\": 1.0, \"P2\": 1.0, \"P3\": 0.0},\n"
                "        \"flow\": {p: {c: BEST_FLOW.get((p, c), 0.0) for c in customer_ids} for p in plant_ids},\n",
            ),
        ],
    },
}


VERSIONS = {"none": None, "relaxed-binary": "integrality", "dropped-demand": "feasibility",
            "timelimit-as-optimal": "status mapping", "flipped-sense": "objective"}
TEST_CONTRACT = {"test_status_contract": "status", "test_status_mapping_contract": "status mapping",
                 "test_feasibility_contract": "feasibility", "test_integrality_contract": "integrality",
                 "test_objective_contract": "objective"}
SPY = (
    "import json, p00_model\n"
    "seen = {}\n"
    "orig = p00_model.contract_status\n"
    "def spy(ms, has):\n"
    "    seen['highs'] = p00_model.highspy.Highs().modelStatusToString(ms)\n"
    "    return orig(ms, has)\n"
    "p00_model.contract_status = spy\n"
    "r = p00_model.solve()\n"
    "print(json.dumps({'highs_status': seen['highs'], 'objective': r['objective']}))\n"
)


def env():
    import os
    drop = {"VIRTUAL_ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "PYTHONPATH",
            "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    return {**{k: v for k, v in os.environ.items() if k not in drop}, "NO_COLOR": "1", "GIT_PAGER": "cat",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def run(args, cwd):
    # "uv run pytest" runs with this test run's own locked environment, as test_lab_ladder.py does.
    if args == "uv run pytest":
        args = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"]
    elif isinstance(args, str):
        args = args.split()
    return subprocess.run(args, cwd=cwd, env=env(), capture_output=True, text=True, encoding="utf-8", timeout=120)


def export(bug, out):
    result = run([sys.executable, str(P00 / "export.py"), "--tests-dir", "--bug", bug, "--out", str(out)], out.parent)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def section(slide_id):
    raw = DECK.read_text(encoding="utf-8")
    match = re.search(r'<section\b[^>]*id="%s"[^>]*>(.*?)</section>' % slide_id, raw, re.S)
    assert match, f"No slide {slide_id}"
    return match.group(1)


def cells():
    """The #catch grid as the slide shows it: (command, fix) -> the text in its cell's output block, or None where
    the cell says, and only says, that the command prints nothing."""
    out = {}
    for cmd, row in re.findall(r'<tr[^>]*data-ca-cmd="([^"]+)"[^>]*>(.*?)</tr>', section("catch"), re.S):
        for fix, cell in re.findall(r'<td[^>]*data-ca-fix="([ABC])"[^>]*>(.*?)</td>', row, re.S):
            key = (html.unescape(cmd), fix)
            assert key not in out, key
            pre = re.findall(r'<pre class="ca-out">(.*?)</pre>', cell, re.S)
            none = re.findall(r'<span class="ca-none">(.*?)</span>', cell, re.S)
            assert len(pre) + len(none) == 1, (key, cell)
            if none:
                assert none[0].strip() == "prints nothing", (key, none)
                out[key] = None
            else:
                out[key] = html.unescape(re.sub(r"<[^>]+>", "", pre[0]))
    return out


@pytest.fixture(scope="module")
def fixed(tmp_path_factory):
    root = tmp_path_factory.mktemp("catch exports")
    outputs = {}
    for name, fix in FIXES.items():
        directory = export(BUG, root / f"fix {name}")
        for relative, old, new in fix["patches"]:
            path = directory / relative
            text = path.read_text(encoding="utf-8")
            assert text.count(old) == 1, (name, relative, old[:60])
            path.write_text(text.replace(old, new), encoding="utf-8")
        outputs[name] = {cmd: run(cmd, directory) for cmd in DONE + [FOURTH]}
    return outputs


def test_catch_shows_the_real_outputs_of_l2s_done_commands(fixed):
    shown = cells()
    assert set(shown) == {(cmd, fix) for cmd in DONE + [FOURTH] for fix in "ABC"}, sorted(shown)
    for (cmd, fix), text in shown.items():
        real = fixed[fix][cmd].stdout
        if text is None:
            assert real.strip() == "", (cmd, fix, real)
        elif cmd == "uv run pytest":
            summary = [line for line in real.splitlines() if line.strip()][-1].strip("= ")
            assert re.sub(r" in [\d.]+s", "", text.strip()) == re.sub(r" in [\d.]+s", "", summary), (fix, summary)
        elif cmd == FOURTH:
            # The slide shows excerpts of the diff: each shown line, split at its elisions, sits in a real line.
            lines = real.splitlines()
            for line in filter(str.strip, text.splitlines()):
                sign, body = line.strip()[0], line.strip()[1:].strip()
                parts = [p.strip() for p in body.split("…") if p.strip()]
                assert any(l.startswith(sign) and all(p in l for p in parts) for l in lines), (fix, line)
        else:
            assert text.strip() == real.strip(), (cmd, fix, real)


def test_catch_starts_from_two_of_thirty_tests_failing(tmp_path):
    # The face's "had": P00 with the planted relaxed-binary bug, before any fix.
    directory = export(BUG, tmp_path / "before")
    summary = [line for line in run("uv run pytest", directory).stdout.splitlines() if line.strip()][-1]
    assert re.search(r"\b2 failed, 28 passed\b", summary), summary
    assert "2 of 30 tests failing" in html.unescape(re.sub(r"<[^>]+>", "", section("catch")))


def test_fix_c_passes_every_done_command_and_only_the_model_diff_shows_it(fixed):
    c = fixed["C"]
    assert c["git diff --stat -- tests/"].stdout.strip() == ""
    assert c["uv run pytest"].returncode == 0
    assert c["git status --short"].stdout.strip() == "M p00_model.py"
    assert '"objective": 485.0' in c[FOURTH].stdout and "-" in c[FOURTH].stdout
    # A is caught by the tests' diff and by git status; B is the honest fix.
    assert "tests/test_p00_contract.py" in fixed["A"]["git diff --stat -- tests/"].stdout
    assert fixed["B"]["uv run pytest"].returncode == 0 and "kInteger" in fixed["B"][FOURTH].stdout


@pytest.fixture(scope="module")
def versions(tmp_path_factory):
    root = tmp_path_factory.mktemp("five versions")
    out = {}
    for bug in VERSIONS:
        directory = export(bug, root / bug)
        solved = run([sys.executable, "-c", SPY], directory)
        assert solved.returncode == 0, solved.stderr
        tests = run([sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider"], directory)
        failed = re.findall(r"^FAILED tests/test_p00_contract\.py::(\w+)", tests.stdout, flags=re.M)
        out[bug] = {**json.loads(solved.stdout), "broken": {TEST_CONTRACT[name] for name in failed},
                    "pytest_exit": tests.returncode}
    return out


# Each row of #l3 names the contract its version breaks; the reference row says none broken.
ROW_CONTRACT = {"none · 30 passed": "none", "integrality": "relaxed-binary", "feasibility": "dropped-demand",
                "status mapping": "timelimit-as-optimal", "objective": "flipped-sense"}
AXIS_X0, AXIS_LEN, AXIS_MAX = 280, 495, 1100


def rows():
    """#l3's five rows as drawn: the cost printed beside the dot, the dot's position, what HiGHS says, the contract."""
    out = []
    # A row ends where the next row (or the figure's "?" box) starts: a row may hold a nested group.
    for row in re.findall(r'<g class="v5-row[^"]*">(.*?)</g>\s*(?=<g class="(?:v5-row|rp-q-mark)[ "])', section("l3"), re.S):
        text = lambda cls: html.unescape(re.search(r'<text class="%s[^"]*"[^>]*>(.*?)</text>' % cls, row, re.S).group(1)).strip()
        status = re.findall(r'<text class="v5-st rp-ans"[^>]*>(.*?)</text>', row)
        dot = re.search(r'<circle class="v5-dot[^"]*" cx="([\d.]+)"', row)
        assert dot, row
        out.append({"value": text("v5-val"), "status": status, "contract": text("v5-ct"),
                    "cx": float(dot.group(1))})
    return out


def test_l3_draws_highs_optimal_five_times_and_the_contract_passes_only_the_reference(versions):
    drawn = rows()
    assert sorted(ROW_CONTRACT[row["contract"]] for row in drawn) == sorted(VERSIONS), [r["contract"] for r in drawn]
    for row in drawn:
        bug = ROW_CONTRACT[row["contract"]]
        seen = versions[bug]
        assert seen["highs_status"] == "Optimal" and row["status"] == ["optimal"], (bug, seen, row)
        assert seen["pytest_exit"] == (0 if VERSIONS[bug] is None else 1), (bug, seen)
        assert (not seen["broken"]) == (VERSIONS[bug] is None), (bug, seen["broken"])
        if VERSIONS[bug]:
            assert VERSIONS[bug] in seen["broken"], (bug, seen["broken"])
        objective = seen["objective"]
        assert row["value"] == (f"{objective:.2f}" if objective != round(objective) else f"{objective:.0f}"), (bug, row)
        # Drawn to scale on the 0 .. 1100 axis.
        assert abs(row["cx"] - (AXIS_X0 + objective * AXIS_LEN / AXIS_MAX)) < 0.01, (bug, row["cx"])

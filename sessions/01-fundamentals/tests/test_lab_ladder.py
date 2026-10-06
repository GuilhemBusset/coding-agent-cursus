"""Issue 43 acceptance checks, authored before the lab ladder implementation.

Run with ``uv run pytest -q tests/test_lab_ladder.py`` from the session.
These checks support, but do not replace, review of the teaching content,
screenshots, CLI help evidence and authentic rehearsal transcripts (ADR 0011).

The engine executes command checks only, but accounts for every test here.
Keep the L3 location and rehearsal checks in the ``done_commands`` selection
used by A2 as well as the ``l3``/``rehearsal`` artifact-review selections.
These check where the done commands run and their recorded completion times.

The agreed HTML interface is section[data-level][data-box], data-agent and
data-done. A done block contains newline-separated commands in pre/code;
L4 alternatives use separate blocks marked data-option="rule", "skill", or
"headless"; every command in the selected block is executed. Working directories
are the exported repo for L1/L2/L4 and the L3 pack for L3, as specified in the
design. Review must check that these directories and expected outputs are
explained to students.

Git status/diff normally exit zero even when they display violations. Thus
"done" below means exit status AND the prescribed output predicate, not exit
status alone. L4 alternatives are evaluated separately. A symbol placeholder
in L1's git grep is filled with a real symbol from the existing reference.
Only uv's interpreter selection is replaced: the commands themselves execute
in real temporary repos, with this pytest run's locked Python environment.

Rehearsal evidence uses a Markdown table. Minimal columns (case/punctuation
insensitive): CLI, level, version, date, minutes, done exit. Common aliases
are accepted below. Start/end timestamps may be additional columns; when
present they must agree with minutes. Model, revision, prompts, transitions,
outputs and diffs must also be reviewed in the linked per-CLI transcripts.
Missing or 'not measured' rows FAIL; tests never invent live-agent evidence.
"""

from datetime import date, datetime
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


SESSION = Path(__file__).resolve().parents[1]
PAGE = SESSION / "exercises/lab-ladder.html"
P00 = SESSION / "exercises/p00-lab"
L3 = SESSION / "exercises/l3-word-problem"
REHEARSAL = SESSION / "cursus/labs/lab-ladder-rehearsal.md"
BUGS = {
    "flipped-sense": "objective contract",
    "dropped-demand": "feasibility contract",
    "relaxed-binary": "integrality contract",
    "timelimit-as-optimal": "status contract",
}
BOXES = {"L1": 8, "L2": 12, "L3": 15, "L4": 5}


class Element:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self):
        return "".join(child.text() if isinstance(child, Element) else child
                       for child in self.children)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag == "br":
            self.stack[-1].children.append("\n")
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


@pytest.fixture(scope="module")
def page():
    assert PAGE.is_file(), "D1: missing exercises/lab-ladder.html"
    return Document(PAGE.read_text(encoding="utf-8")).root


def level(page, name):
    found = [node for node in page.walk() if node.attrs.get("data-level") == name]
    assert len(found) == 1 and found[0].tag == "section", f"D1: one section for {name}"
    assert found[0].attrs.get("id") == name.lower(), f"D1: anchor #{name.lower()}"
    return found[0]


def child_env():
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               GIT_TERMINAL_PROMPT="0")
    return env


def run(args, cwd):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=child_env(),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60, check=False)


def success(args, cwd):
    result = run(args, cwd)
    assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def snapshot(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()
            and not {".git", ".pytest_cache", "__pycache__"}.intersection(
                path.relative_to(directory).parts)}


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    root = tmp_path_factory.mktemp("ladder exports")
    result = {}
    for index, bug in enumerate(("none", *BUGS)):
        directory = root / f"student {index}"
        success([sys.executable, P00 / "export.py", "--tests-dir", "--bug", bug,
                 "--out", directory], root)
        result[bug] = directory
    return result


def test_tests_dir_preserves_contract_and_default_export(exports, tmp_path):
    default = tmp_path / "original layout"
    success([sys.executable, P00 / "export.py", "--bug", "none", "--out", default], tmp_path)
    original = snapshot(default)
    reference = snapshot(exports["none"])
    assert "test_p00_contract.py" in original and "tests/test_p00_contract.py" not in original
    expected = (set(original) - {"test_p00_contract.py"}) | {
        "tests/test_p00_contract.py", "tests/__init__.py"}
    assert set(reference) == expected, "D3: opt-in relocates only the suite and adds its package marker"
    assert reference["tests/__init__.py"] == b""
    assert reference["tests/test_p00_contract.py"] == original["test_p00_contract.py"]
    assert reference["tests/test_p00_contract.py"] == (P00 / "test_p00_contract.py").read_bytes()
    assert reference[".gitignore"] == original[".gitignore"] + b".claude/settings.local.json\n"
    for name in set(original) - {"test_p00_contract.py", "AGENTS.md", ".gitignore"}:
        assert reference[name] == original[name], f"D3: opt-in unexpectedly changes {name}"
    agents = reference["AGENTS.md"].decode("utf-8")
    for contract in ("tests/", "p00_checker.py", "data/", "mise install", "uv sync", "uv run pytest"):
        assert contract in agents, f"D3: exported agent instructions must name {contract}"
    for bug, directory in exports.items():
        files = snapshot(directory)
        assert files.keys() == reference.keys()
        for name, content in files.items():
            if name != "p00_model.py":
                assert content == reference[name], f"D3: variant changes contract file {name}"
            assert not any(selector.encode() in content.lower() for selector in BUGS), (
                f"D3: variant identity leaked in student file {name}")
        if bug != "none":
            assert files["p00_model.py"] != reference["p00_model.py"]
        assert success(["git", "status", "--short"], directory) == ""
        assert success(["git", "rev-list", "--count", "HEAD"], directory).strip() == "1"


@pytest.fixture(scope="module")
def suite_results(exports, tmp_path_factory):
    reports = tmp_path_factory.mktemp("ladder reports")
    result = {}
    for index, (bug, directory) in enumerate(exports.items()):
        report = reports / f"result-{index}.xml"
        process = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "--junitxml", report], directory)
        assert report.is_file(), process.stdout + process.stderr
        xml = ET.parse(report).getroot()
        totals = {key: sum(int(suite.get(key, "0")) for suite in xml.iter("testsuite"))
                  for key in ("tests", "failures", "errors", "skipped")}
        result[bug] = (process, totals, [case.get("name") for case in xml.iter("testcase")],
                       "\n".join(failure.get("message", "") for failure in xml.iter("failure")))
    return result


@pytest.mark.parametrize("bug", ["none", *BUGS])
def test_tests_dir_collects_and_exposes_real_assertions(bug, suite_results):
    process, counts, cases, messages = suite_results[bug]
    assert counts["tests"] > 0 and counts["errors"] == counts["skipped"] == 0
    assert cases == suite_results["none"][2], "D3: every variant runs exactly the same tests"
    assert process.returncode == (0 if bug == "none" else 1), process.stdout + process.stderr
    if bug == "none":
        assert counts["failures"] == 0
    else:
        assert counts["failures"] > 0 and BUGS[bug] in messages, process.stdout


def test_both_agents_page_structure(page):
    for name, minutes in BOXES.items():
        section = level(page, name)
        assert float(section.attrs.get("data-box", "nan")) == minutes
        for agent in ("claude", "codex"):
            blocks = [node for node in section.walk() if node.attrs.get("data-agent") == agent]
            assert blocks and all(node.text().strip() for node in blocks), f"D1: {name} / {agent}"
    ids = [node.attrs["id"] for node in page.walk() if "id" in node.attrs]
    assert len(ids) == len(set(ids)), "D1: duplicate anchors"
    assert {"pair-protocol", "signals", "debrief", "references"} <= set(ids)


def test_instructor_hints_closed_and_no_bug_selectors(page):
    for name in BOXES:
        hints = [node for node in level(page, name).walk()
                 if node.tag == "details" and "data-instructor" in node.attrs]
        assert hints, f"D7: {name} needs an instructor disclosure"
        for hint in hints:
            assert "open" not in hint.attrs, f"D7: {name} hints must start collapsed"
            summaries = [node for node in hint.children
                         if isinstance(node, Element) and node.tag == "summary"]
            assert len(summaries) == 1 and summaries[0].text().strip()
    for selector in BUGS:
        assert selector not in PAGE.read_text(encoding="utf-8").lower()
        assert selector not in page.text().lower(), "D7: encoded selector leaked on page"
    links = relative_targets(page)
    assert (P00 / "README.md").resolve() in links
    assert REHEARSAL.resolve() in links


def relative_targets(element):
    hrefs = [node.attrs.get("href", "").split("#")[0]
             for node in element.walk() if node.tag == "a"]
    return {(PAGE.parent / href).resolve() for href in hrefs
            if href and not re.match(r"(?:[a-zA-Z][\w+.-]*:|/)", href)}


def test_done_commands_l3_relative_problem_link(page):
    assert (L3 / "README.md").resolve() in relative_targets(level(page, "L3"))
    assert (L3 / "README.md").is_file()


def done_blocks(page, name):
    """Preserve block boundaries and option markers, including command order."""
    blocks = [node for node in level(page, name).walk() if "data-done" in node.attrs]
    assert blocks, f"A2: {name} needs a data-done block"
    parsed = []
    for block in blocks:
        commands = []
        code = [node for node in block.walk() if node.tag == "code"]
        if not code:
            code = [block]
        for node in code:
            for line in node.text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Students substitute their cited symbol; never execute a shell redirection.
                if line.startswith("git grep "):
                    line = re.sub(r"<[^<>]+>", "ObjSense", line)
                assert not re.search(r"[&|;<>*?`]|\$\(|\\$", line), (
                    f"A2: one portable command per line, no shell syntax: {line}")
                args = shlex.split(line)
                assert args and args[0] in {"git", "uv"}, f"A2: not a done command: {line}"
                commands.append(args)
        assert commands, f"A2: empty done block for {name}"
        parsed.append((block.attrs.get("data-option"), commands))
    return parsed


def done_commands(page, name):
    return [args for _, commands in done_blocks(page, name) for args in commands]


def command_kind(args):
    """Recognize the agreed public CLI checks, never substitute a canned verdict."""
    if args == ["uv", "run", "pytest"]:
        return "pytest"
    if args in (["uv", "run", "python", "check.py"],
                ["uv", "run", "python", "check.py", "solution.json"]):
        return "certificate"
    if args == ["git", "status", "--short"]:
        return "status"
    if args == ["git", "diff", "--exit-code", "HEAD"]:
        return "head-diff"
    if args[:3] == ["git", "grep", "-n"] and len(args) >= 4:
        return "citation"
    if args == ["git", "diff", "HEAD", "--", "AGENTS.md"]:
        return "rule"
    if args[:4] == ["git", "diff", "--stat", "--"]:
        paths = {arg.rstrip("/") for arg in args[4:]}
        if paths == {"tests"}:
            return "tests-diff"
        if paths == {"tests", "data", "p00_checker.py"}:
            return "contract-diff"
    if args[:3] == ["git", "status", "--short"] and "--" in args:
        paths = {arg.rstrip("/") for arg in args[args.index("--") + 1:]}
        if paths == {"check.py", "data", "wrong"}:
            return "l3-contract"
        if paths == {".claude/skills", ".agents/skills"}:
            return "skill"
    pytest.fail(f"A2: unexpected done command (expected the agreed Git/pytest/check.py interface): {args}")


REQUIRED = {
    "L1": {"status", "head-diff", "citation"},
    "L2": {"tests-diff", "pytest", "status"},
    "L3": {"certificate", "l3-contract"},
    "L4": {"rule", "skill", "contract-diff", "tests-diff", "pytest", "status"},
}


L4_REQUIRED = {
    "rule": {"rule", "contract-diff", "status"},
    "skill": {"skill", "contract-diff", "status"},
    "headless": {"tests-diff", "pytest", "status"},
}


def commands_for(page, name, option=None):
    if name == "L4":
        blocks = done_blocks(page, name)
        markers = [marker for marker, _ in blocks]
        assert len(markers) == len(L4_REQUIRED) and set(markers) == set(L4_REQUIRED), (
            "A2: L4 needs one data-option block each for rule, skill and headless")
        assert option in L4_REQUIRED
        for marker, commands in blocks:
            kinds = {command_kind(args) for args in commands}
            assert kinds == L4_REQUIRED[marker], f"A2: wrong checks for L4 {marker}: {kinds}"
        return next(commands for marker, commands in blocks if marker == option)
    commands = done_commands(page, name)
    kinds = {command_kind(args) for args in commands}
    assert REQUIRED[name] <= kinds, f"A2: missing {name} done checks: {REQUIRED[name] - kinds}"
    assert kinds <= REQUIRED[name], f"A2: unrelated done checks in {name}: {kinds}"
    return commands


def execute_done(commands, cwd, name, option=None, executed=None):
    outcomes = []
    for args in commands:
        kind = command_kind(args)
        invocation = ([sys.executable, "-m", "pytest"] if kind == "pytest" else
                      [sys.executable, *args[3:]] if kind == "certificate" else args)
        result = run(invocation, cwd)
        if executed is not None:
            executed.append(list(args))
        passed = result.returncode == 0
        if kind in {"tests-diff", "contract-diff", "l3-contract"}:
            passed = passed and not result.stdout.strip()
        elif kind == "status":
            lines = result.stdout.splitlines()
            paths = {line[3:] for line in lines}
            if name == "L1":
                allowed = not lines
            elif name == "L4" and option == "rule":
                allowed = paths == {"AGENTS.md", "p00_model.py"}
            elif name == "L4" and option == "skill":
                allowed = "p00_model.py" in paths and all(
                    path == "p00_model.py" or path in {".claude/", ".agents/"}
                    or path.startswith((".claude/", ".agents/")) for path in paths)
            else:
                allowed = all(path == "p00_model.py" for path in paths)
            passed = passed and allowed
        elif kind in {"rule", "skill", "citation"}:
            passed = passed and bool(result.stdout.strip())
        elif kind == "certificate":
            passed = passed and bool(re.search(r"^PASS\s*$", result.stdout, re.M))
            passed = passed and bool(re.search(r"gap.*bound", result.stdout, re.I))
        outcomes.append((kind, passed, result))
    return outcomes


def execute_l4(page, cwd, option):
    """Audit execution against the whole selected page block, not a kind filter."""
    commands = commands_for(page, "L4", option)
    block_commands = next(commands for marker, commands in done_blocks(page, "L4")
                          if marker == option)
    executed = []
    outcomes = execute_done(commands, cwd, "L4", option, executed)
    assert executed == block_commands, "A2: execute every block command in page order"
    assert len(outcomes) == len(executed) == len(block_commands)
    assert {kind for kind, _, _ in outcomes} == L4_REQUIRED[option]
    return outcomes


def assert_done(outcomes, expected):
    passed = all(outcome[1] for outcome in outcomes)
    diagnostic = "\n".join(f"{kind}: exit={r.returncode}\n{r.stdout}\n{r.stderr}"
                           for kind, _, r in outcomes)
    assert passed == expected, diagnostic


def copy_export(exports, tmp_path, bug="none"):
    return Path(shutil.copytree(exports[bug], tmp_path / "student task"))


@pytest.mark.parametrize("mutation", ["stray", "tracked", "staged"])
def test_done_commands_l1_read_only(page, exports, tmp_path, mutation):
    commands = commands_for(page, "L1")
    directory = copy_export(exports, tmp_path)
    assert_done(execute_done(commands, directory, "L1"), True)
    target = directory / ("unexpected.txt" if mutation == "stray" else "p00_model.py")
    with target.open("a", encoding="utf-8") as stream:
        stream.write("\n# read-only violation\n")
    if mutation == "staged":
        success(["git", "add", target.name], directory)
    assert_done(execute_done(commands, directory, "L1"), False)


@pytest.mark.parametrize("mutation", ["tests", "checker", "staged-tests", "data", "new-file"])
def test_done_commands_l2_repair_and_tampering(page, exports, tmp_path, mutation):
    commands = commands_for(page, "L2")
    directory = copy_export(exports, tmp_path, "dropped-demand")
    assert_done(execute_done(commands, directory, "L2"), False)
    # Repair fixture: restore the already-proven reference; live agent repairs
    # are separately reviewed in the rehearsal. Tests are never edited to pass.
    shutil.copyfile(P00 / "p00_model.py", directory / "p00_model.py")
    assert_done(execute_done(commands, directory, "L2"), True)
    assert "p00_model.py" in success(["git", "status", "--short"], directory)
    paths = {"tests": "tests/test_p00_contract.py", "checker": "p00_checker.py",
             "staged-tests": "tests/test_p00_contract.py", "data": "data/costs.csv",
             "new-file": "unexpected.txt"}
    target = directory / paths[mutation]
    with target.open("a", encoding="utf-8") as stream:
        stream.write("\n" if mutation == "data" else "\n# forbidden edit\n")
    if mutation == "staged-tests":
        success(["git", "add", paths[mutation]], directory)
    assert_done(execute_done(commands, directory, "L2"), False)


def test_done_commands_l2_clean_reference(page, exports, tmp_path):
    commands = commands_for(page, "L2")
    directory = copy_export(exports, tmp_path)
    assert_done(execute_done(commands, directory, "L2"), True)


def init_fixture_repo(directory):
    """Only synthetic temp fixtures, never the loop worktree or its Git history."""
    success(["git", "init", "-q", "-b", "fixture"], directory)
    success(["git", "add", "."], directory)
    success(["git", "-c", "user.name=Acceptance fixture", "-c",
             "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
             "commit", "-q", "-m", "Fixture baseline"], directory)


def compositions(total, width):
    if width == 1:
        yield (total,)
    else:
        for first in range(total + 1):
            for rest in compositions(total - first, width - 1):
                yield (first, *rest)


def l3_witness():
    # Generate a feasible certificate from the stated coverage constraints,
    # rather than teaching the test a single expected solution.json.
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    demand = (8, 7, 8, 9, 8, 5, 6)
    starts = next(row for row in compositions(11, 7)
                  if all(sum(row[(day - offset) % 7] for offset in range(5)) >= need
                         for day, need in enumerate(demand)))
    return {"objective": sum(starts), "start": dict(zip(days, starts))}


@pytest.mark.parametrize("wrong", ["understaffed", "fractional", "misreported"])
def test_done_commands_l3_certificate(page, tmp_path, wrong):
    commands = commands_for(page, "L3")
    directory = Path(shutil.copytree(L3, tmp_path / "weekly staffing"))
    init_fixture_repo(directory)
    (directory / "solution.json").write_text(json.dumps(l3_witness()), encoding="utf-8")
    result = execute_done(commands, directory, "L3")
    assert_done(result, True)
    summary = next(r.stdout for kind, _, r in result if kind == "certificate")
    for label, number in (("headcount", "11"), ("bound", "10.2"), ("gap", "0.8")):
        assert any(label in line.lower() and re.search(rf"\b{re.escape(number)}\b", line)
                   for line in summary.splitlines()), summary
    shutil.copyfile(directory / "wrong" / f"{wrong}.json", directory / "solution.json")
    result = execute_done(commands, directory, "L3")
    assert_done(result, False)
    check = next(r for kind, _, r in result if kind == "certificate")
    assert check.returncode != 0 and re.search(r"^FAIL\s*$", check.stdout, re.M)
    assert re.search(r"gap.*bound", check.stdout, re.I), check.stdout
    assert re.search(r"headcount", check.stdout, re.I), check.stdout


def test_done_commands_l3_protects_checker(page, tmp_path):
    commands = commands_for(page, "L3")
    directory = Path(shutil.copytree(L3, tmp_path / "weekly staffing"))
    init_fixture_repo(directory)
    (directory / "solution.json").write_text(json.dumps(l3_witness()), encoding="utf-8")
    with (directory / "check.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# unauthorized checker edit\n")
    success(["git", "add", "check.py"], directory)
    assert_done(execute_done(commands, directory, "L3"), False)


@pytest.mark.parametrize("option", ["rule", "claude-skill", "codex-skill", "headless"])
@pytest.mark.parametrize("mutation", ["tests", "data", "checker", "staged-tests",
                                      "untracked-tests", "stray"])
def test_done_commands_l4_options(page, exports, tmp_path, option, mutation):
    selected = "skill" if option.endswith("-skill") else option
    directory = copy_export(exports, tmp_path, "dropped-demand")
    shutil.copyfile(P00 / "p00_model.py", directory / "p00_model.py")
    for harness in (".claude", ".agents"):
        assert not (directory / harness).exists(), "Exercise Git's collapsed untracked-directory status"
    if selected != "headless":
        before = execute_l4(page, directory, selected)
        assert_done(before, False)
        assert not next(passed for kind, passed, _ in before if kind == selected)
    if option == "rule":
        with (directory / "AGENTS.md").open("a", encoding="utf-8") as stream:
            stream.write("\nAlways report the command and exit status used to verify a repair.\n")
    elif selected == "skill":
        harness = ".claude" if option == "claude-skill" else ".agents"
        skill = directory / harness / "skills" / "verify-repair" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: verify-repair\ndescription: Verify a repair.\n---\n"
                         "Run uv run pytest and report its exit status.\n", encoding="utf-8")
    valid = execute_l4(page, directory, selected)
    assert_done(valid, True)
    if selected == "skill":
        status = next(result.stdout for kind, _, result in valid if kind == "status")
        assert f"?? {harness}/" in status.splitlines(), status
    if selected == "rule":
        # HEAD-relative rule evidence must also work for a staged-only rule.
        success(["git", "add", "AGENTS.md"], directory)
        assert success(["git", "diff", "--", "AGENTS.md"], directory) == ""
        assert_done(execute_l4(page, directory, selected), True)
    paths = {"tests": "tests/test_p00_contract.py", "data": "data/costs.csv",
             "checker": "p00_checker.py", "staged-tests": "tests/test_p00_contract.py",
             "untracked-tests": "tests/extra_test.py", "stray": "unexpected.txt"}
    with (directory / paths[mutation]).open("a", encoding="utf-8") as stream:
        stream.write("\n")
    if mutation == "staged-tests":
        success(["git", "add", paths[mutation]], directory)
    tampered = execute_l4(page, directory, selected)
    assert_done(tampered, False)
    if mutation in {"staged-tests", "untracked-tests", "stray"}:
        diff_kind = "tests-diff" if selected == "headless" else "contract-diff"
        assert next(passed for kind, passed, _ in tampered if kind == diff_kind), (
            "The mutation must be invisible to the unstaged diff")
        assert {kind for kind, passed, _ in tampered if not passed} == {"status"}, (
            "Full status must reject staged-only and untracked contract changes")


@pytest.mark.parametrize("option", ["l2", "rule", "headless"])
def test_done_commands_l2_l4_claude_local_settings(page, exports, tmp_path, option):
    directory = copy_export(exports, tmp_path, "dropped-demand")
    shutil.copyfile(P00 / "p00_model.py", directory / "p00_model.py")
    settings = directory / ".claude/settings.local.json"
    settings.parent.mkdir()
    settings.write_text("{}\n", encoding="utf-8")
    ignored = success(["git", "check-ignore", "--verbose", ".claude/settings.local.json"], directory)
    assert re.fullmatch(r"\.gitignore:\d+:\.claude/settings\.local\.json\t"
                        r"\.claude/settings\.local\.json\n?", ignored), (
        "The exported .gitignore must ignore local settings without relying on global Git config")
    if option == "rule":
        with (directory / "AGENTS.md").open("a", encoding="utf-8") as stream:
            stream.write("\nReport the verification command and its observed exit status.\n")
        success(["git", "add", "AGENTS.md"], directory)
    outcomes = (execute_done(commands_for(page, "L2"), directory, "L2") if option == "l2"
                else execute_l4(page, directory, option))
    assert_done(outcomes, True)


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def rehearsal_rows(source):
    aliases = {
        "cli": {"cli", "agent", "harness"}, "level": {"level"},
        "version": {"version", "cliversion", "agentversion"},
        "date": {"date", "rundate"},
        "minutes": {"minutes", "elapsedminutes", "elapsedmin", "durationminutes", "durationmin"},
        "exit": {"doneexit", "doneexitcode", "exit", "exitcode", "donecommandexit"},
        "start": {"start", "started", "starttimestamp", "startedat", "startutc"},
        "end": {"end", "ended", "endtimestamp", "endedat", "endutc"},
    }
    required = {"cli", "level", "version", "date", "minutes", "exit"}
    rows = []
    columns = None
    for line in source.splitlines():
        if not line.lstrip().startswith("|"):
            columns = None
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        header = [next((key for key, names in aliases.items() if normalized(cell) in names), None)
                  for cell in cells]
        if required <= set(header):
            columns = header
        elif columns is not None:
            assert len(cells) == len(columns), "A1: malformed timing-table row"
            rows.append({key: value for key, value in zip(columns, cells) if key is not None})
    assert rows, "A1: provide the machine-readable Markdown timing table; see this file's docstring"
    return rows


def test_done_commands_rehearsal_both_clis_within_page_boxes(page):
    assert REHEARSAL.is_file(), "A1 unproven: missing rehearsal report"
    rows = rehearsal_rows(REHEARSAL.read_text(encoding="utf-8"))
    observed = set()
    for row in rows:
        agent = normalized(row["cli"])
        agent = {"claudecode": "claude", "codexcli": "codex"}.get(agent, agent)
        name = row["level"].upper()
        assert agent in {"claude", "codex"} and name in {"L1", "L2", "L3"}, row
        assert (agent, name) not in observed, f"A1: duplicate timing row: {row}"
        observed.add((agent, name))
        assert re.search(r"\d+\.\d+", row["version"]), f"A1: missing CLI version: {row}"
        date.fromisoformat(row["date"])
        assert re.fullmatch(r"\d+(?:\.\d+)?", row["minutes"]), (
            f"A1 unproven: need measured minutes, not estimates or 'not measured': {row}")
        minutes = float(row["minutes"])
        box = float(level(page, name).attrs["data-box"])
        assert math.isfinite(minutes) and 0 < minutes <= box, f"A1: outside {name}'s {box}-minute box: {row}"
        assert row["exit"] == "0", f"A1: done commands did not pass: {row}"
        if "start" in row or "end" in row:
            assert "start" in row and "end" in row, "A1: record both timestamps"
            start = datetime.fromisoformat(row["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(row["end"].replace("Z", "+00:00"))
            elapsed = (end - start).total_seconds() / 60
            assert 0 < elapsed <= box and abs(elapsed - minutes) <= 0.02, row
        transcript = REHEARSAL.parent / "lab-ladder-evidence" / f"{agent}.txt"
        assert transcript.is_file() and transcript.read_text(encoding="utf-8").strip(), (
            f"A1: missing transcript for {agent}; table alone is not evidence")
    assert observed == {(agent, name) for agent in ("claude", "codex") for name in ("L1", "L2", "L3")}

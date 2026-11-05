"""The selector behind scripts/check-changed.sh and CI's `changes` job (ADR 0013).

Synthetic rules check the selection logic; the real impact.toml is checked for its shape and for
a few changes whose right answer is known.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impact
from impact import Change, glob_re, select

RULES = {
    "all": {"paths": [".github/workflows/**", "tools/test-impact/**"]},
    "none": {"paths": ["LICENSE", "docs/*.md"]},
    "units": {"engine": {"paths": ["tools/implementation-loop/**"]}, "turn-in": {"paths": ["scripts/**"]}},
    "sessions": {"shared": ["scripts/turn-in.sh"]},
    "pages": {"shared": ["tools/html-pages/check-page.mjs"]},
    "node": {"shared": ["tools/html-pages/browser.mjs"],
             "suites": {"deck": ["sessions/01-x/cursus/00-deck.html"], "lab": ["sessions/01-x/cursus/labs/*.html"]}},
}
SUITES = [f"tools/html-pages/tests/{n}.test.mjs" for n in ("deck", "lab", "new")]
SESSIONS = ["sessions/01-x"]
PAGES = ["sessions/01-x/cursus/00-deck.html", "sessions/01-x/cursus/labs/lab.html"]


# 00-deck.html loads labs/data.json and links to labs/lab.html; lab.html loads nothing.
REFS = {PAGES[0]: ({"sessions/01-x/cursus/labs/data.json"}, {PAGES[1]}), PAGES[1]: (set(), set())}


def plan(*paths, gone=()):
    return select(Change(set(paths) | set(gone), set(gone)), RULES, SUITES, SESSIONS, PAGES, refs=REFS)


@pytest.mark.parametrize("pattern,path,expected", [
    ("docs/*.md", "docs/a.md", True),
    ("docs/*.md", "docs/adr/a.md", False),
    ("docs/**", "docs/adr/a.md", True),
    ("a/**/b.md", "a/b.md", True),
    ("a/**/b.md", "a/x/y/b.md", True),
    ("tests/probe_*.py", "tests/probe_1.py", True),
    ("tests/probe_*.py", "tests/sub/probe_1.py", False),
    ("x.y", "xzy", False),
])
def test_globs_keep_star_inside_one_directory(pattern, path, expected):
    assert bool(glob_re(pattern).match(path)) is expected


def test_a_global_path_or_all_runs_everything():
    for result in (plan(".github/workflows/ci.yml"), select(Change(), RULES, SUITES, SESSIONS, PAGES, everything=True, refs=REFS)):
        assert result.everything
        assert result.units == {"engine", "turn-in"} and result.sessions == SESSIONS
        assert result.suites == SUITES and result.pages == PAGES


def test_a_path_in_no_rule_runs_everything_and_says_why():
    result = plan("somewhere/new.txt")
    assert result.everything and result.reasons == ["somewhere/new.txt is in no rule of impact.toml"]


def test_deleting_a_path_in_no_rule_also_runs_everything():
    result = plan(gone=["somewhere/old.txt"])
    assert result.everything and result.reasons == ["somewhere/old.txt is in no rule of impact.toml"]


def test_prose_in_none_runs_nothing_but_unmapped_suites():
    result = plan("LICENSE", "docs/notes.md")
    assert not result.everything
    assert (result.units, result.sessions, result.pages) == (set(), [], [])
    assert result.suites == ["tools/html-pages/tests/new.test.mjs"], "a suite the map does not know always runs"


def test_an_engine_change_runs_only_the_engine():
    result = plan("tools/implementation-loop/implement_loop/engine.py")
    assert result.units == {"engine"} and result.sessions == [] and result.pages == []


def test_a_deck_change_runs_its_session_its_suites_and_its_page():
    result = plan("sessions/01-x/cursus/00-deck.html")
    assert result.units == set() and result.sessions == SESSIONS
    assert result.suites == ["tools/html-pages/tests/deck.test.mjs", "tools/html-pages/tests/new.test.mjs"]
    assert result.pages == [PAGES[0]]


def test_a_loaded_file_rechecks_the_pages_that_load_it():
    assert plan("sessions/01-x/cursus/labs/data.json").pages == [PAGES[0]]


def test_a_link_target_rechecks_linking_pages_only_when_it_goes():
    assert plan("sessions/01-x/cursus/labs/lab.html").pages == [PAGES[1]]
    assert plan(gone=["sessions/01-x/cursus/labs/lab.html"]).pages == [PAGES[0]], "the deleted page itself is not checked"


def test_shared_paths_select_their_whole_family():
    assert plan("tools/html-pages/browser.mjs").suites == SUITES
    assert plan("tools/html-pages/check-page.mjs").pages == PAGES
    assert plan("scripts/turn-in.sh").sessions == SESSIONS


def test_a_suite_runs_when_its_own_file_changes():
    assert "tools/html-pages/tests/lab.test.mjs" in plan("tools/html-pages/tests/lab.test.mjs").suites


def test_github_outputs(tmp_path):
    out = tmp_path / "out"
    impact.github_output(plan("sessions/01-x/cursus/00-deck.html"), out)
    values = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert values == {
        "everything": "false", "engine": "false", "sessions": '["sessions/01-x"]', "session_tests": "true",
        "suites": "tools/html-pages/tests/deck.test.mjs tools/html-pages/tests/new.test.mjs",
        "shards": "[1, 2]", "pages": PAGES[0], "html": "true",
    }
    out.write_text("")
    impact.github_output(plan("tools/implementation-loop/x.py"), out)
    values = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert (values["engine"], values["shards"], values["html"], values["pages"]) == ("true", "[1]", "true", "none")
    out.write_text("")
    impact.github_output(select(Change(), RULES, SUITES, SESSIONS, PAGES, everything=True, refs=REFS), out)
    values = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert (values["suites"], values["pages"], values["shards"]) == ("all", "all", "[1, 2]"), "3 suites, 2 shards"
    many = impact.Plan(suites=[f"s{i}.test.mjs" for i in range(6)])
    out.write_text("")
    impact.github_output(many, out)
    assert dict(line.split("=", 1) for line in out.read_text().splitlines())["shards"] == "[1, 2, 3]"


def test_type_checks_run_without_an_inherited_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/elsewhere/tools/implementation-loop")
    plan = impact.Plan(units={"typecheck", "turn-in"}, sessions=["sessions/01-x"])
    for label, command, _ in impact.commands(plan):
        env = impact.command_env(command)
        assert ("PYTHONPATH" in env) == ("ty" not in command), label


def test_node_suites_run_as_many_at_once_as_on_a_ci_shard():
    plan = impact.Plan(suites=["tools/html-pages/tests/a.test.mjs", "tools/html-pages/tests/b.test.mjs"])
    [(_, command, _)] = impact.commands(plan)
    assert command[:3] == ["node", "--test", "--test-concurrency=3"] and command[3:] == plan.suites


def test_commands_type_check_the_repository_and_each_session():
    plan = impact.Plan(units={"typecheck", "imports"}, sessions=["sessions/01-x"])
    run = {label: (command, cwd) for label, command, cwd in impact.commands(plan)}
    assert run["types"] == (["uv", "run", "--project", "setup", "--locked", "ty", "check"], impact.ROOT)
    assert run["sessions/01-x types"] == (["uv", "run", "--locked", "--group", "typecheck", "ty", "check"],
                                          impact.ROOT / "sessions/01-x")
    for platform in ("linux", "darwin", "win32"):
        command, cwd = run[f"sessions/01-x exercise types ({platform})"]
        assert command[-3:] == ["--python-platform", platform, "exercises"] and cwd == impact.ROOT / "sessions/01-x"
    labels = list(run)
    assert labels.index("sessions/01-x types") < labels.index("sessions/01-x"), "the seconds-long check first"
    # The same commands CI runs.
    workflows = impact.ROOT / ".github/workflows"
    checks = (workflows / "checks.yml").read_text(encoding="utf-8")
    assert " ".join(run["types"][0]) in checks
    assert run["imports"] == ("uv run --project setup --locked ruff check --select I .".split(), impact.ROOT)  # noqa: SIM905 - the command as checks.yml writes it
    assert " ".join(run["imports"][0]) in checks
    sessions = (workflows / "session-tests.yml").read_text(encoding="utf-8")
    assert " ".join(run["sessions/01-x types"][0]) in sessions
    assert '--python-platform "$platform" exercises' in sessions and " ".join(impact.PLATFORMS) in sessions


def test_every_path_ty_checks_selects_the_type_check():
    with (impact.ROOT / "ty.toml").open("rb") as f:
        include = impact.tomllib.load(f)["src"]["include"]
    for entry in include:
        path = entry if entry.endswith(".py") else f"{entry}/x.py"
        plan = impact.select(Change({path}))
        assert plan.everything or "typecheck" in plan.units, f"{path}: add {entry} to [units.typecheck]"


def test_any_python_file_and_ruff_toml_select_the_import_order():
    for path in ("x.py", "tests/probe_x.py", "setup/browser-libs.py", "tools/implementation-loop/implement_loop/engine.py",
                 "sessions/01-fundamentals/exercises/p00-lab/p00_model.py", "ruff.toml"):
        plan = impact.select(Change({path}))
        assert not plan.everything and "imports" in plan.units, path


def test_ruff_toml_requires_the_ruff_setup_pins():
    with (impact.ROOT / "ruff.toml").open("rb") as f:
        required = impact.tomllib.load(f)["required-version"]
    with (impact.ROOT / "setup/pyproject.toml").open("rb") as f:
        pins = impact.tomllib.load(f)["project"]["dependencies"]
    assert f"ruff{required}" in pins, "bump Ruff in setup/pyproject.toml and ruff.toml together"


def test_name_status_counts_both_sides_of_a_rename_and_marks_deletions():
    change = impact.parse_name_status("M\ta.txt\nR087\told.html\tnew.html\nD\tgone.py\n")
    assert change.paths == {"a.txt", "old.html", "new.html", "gone.py"}
    assert change.gone == {"old.html", "gone.py"}


def test_a_path_recreated_after_its_deletion_is_not_gone(tmp_path, monkeypatch):
    (tmp_path / "back.html").write_text("again")
    outputs = {("merge-base", "origin/main", "HEAD"): "abc\n",
               ("diff", "--name-status", "-M", "abc"): "D\tback.html\nD\tgone.html\n",
               ("ls-files", "--others", "--exclude-standard"): "back.html\n"}
    monkeypatch.setattr(impact, "ROOT", tmp_path)
    monkeypatch.setattr(impact, "git", lambda *args: outputs[args])
    change = impact.local_change("origin/main")
    assert change.paths == {"back.html", "gone.html"} and change.gone == {"gone.html"}


# The real map.

def test_the_map_names_only_suites_that_exist():
    names = {Path(s).name[:-len(impact.SUITE_SUFFIX)] for s in impact.discover_suites()}
    assert set(impact.load_map()["node"]["suites"]) <= names, "rename the map entry with its suite"


def test_the_map_has_every_section_the_selector_reads():
    rules = impact.load_map()
    assert rules["all"]["paths"] and rules["none"]["paths"] and rules["units"]
    assert {"engine", "turn-in", "ship", "repo-config", "typecheck", "imports"} <= set(rules["units"])
    assert "shared" in rules["sessions"] and "shared" in rules["pages"] and "shared" in rules["node"]


def test_references_split_loaded_files_from_links():
    loads, links = impact.references("sessions/01-fundamentals/index.html")
    assert "sessions/01-fundamentals/cursus/02-thinking.html" in links
    assert not any(p.startswith(("http", "/")) for p in loads | links)


def test_references_are_decoded_like_urls(tmp_path, monkeypatch):
    page = tmp_path / "sessions/01-x/page.html"
    page.parent.mkdir(parents=True)
    page.write_text('<img src="plot%20one.svg"><a href="next&amp;more.html">n</a><link rel="stylesheet" href="../a%2Bb.css">')
    monkeypatch.setattr(impact, "ROOT", tmp_path)
    loads, links = impact.references("sessions/01-x/page.html")
    assert loads == {"sessions/01-x/plot one.svg", "sessions/a+b.css"}
    assert links == {"sessions/01-x/next&more.html"}


def test_the_real_map_on_known_changes():
    deck = impact.select(Change({"sessions/01-fundamentals/cursus/02-thinking.html"}))
    assert not deck.everything and "engine" not in deck.units
    assert "sessions/01-fundamentals/cursus/02-thinking.html" in deck.pages
    assert "tools/html-pages/tests/thinking.test.mjs" in deck.suites
    assert "tools/html-pages/tests/world-model.test.mjs" not in deck.suites
    fixture = impact.select(Change({"sessions/01-fundamentals/cursus/fixtures/next_token.json"}))
    for suite in ("next-token", "tokenizer", "sampler"):
        assert f"tools/html-pages/tests/{suite}.test.mjs" in fixture.suites, suite
    engine = impact.select(Change({"tools/implementation-loop/implement_loop/engine.py"}))
    assert engine.units == {"engine", "typecheck", "imports"} and not engine.sessions and not engine.pages
    assert impact.select(Change({"ty.toml"})).units == {"typecheck"}
    for path in ("setup/pyproject.toml", "setup/uv.lock"):
        types = impact.select(Change({path}))
        assert not types.everything and types.units == {"typecheck", "imports"} and not types.sessions, path
    session = impact.select(Change({"sessions/01-fundamentals/pyproject.toml"}))
    assert session.sessions == ["sessions/01-fundamentals"] and "typecheck" not in session.units
    assert impact.select(Change({".github/workflows/ci.yml"})).everything

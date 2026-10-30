"""The selector behind scripts/check-changed.sh and CI's `changes` job (ADR 0013).

Synthetic rules check the selection logic; the real impact.toml is checked for its shape and for
a few changes whose right answer is known.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impact  # noqa: E402
from impact import Change, glob_re, select  # noqa: E402

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
    assert (values["suites"], values["pages"], values["shards"]) == ("all", "all", "[1, 2]")


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
    assert {"engine", "turn-in", "ship", "repo-config"} <= set(rules["units"])
    assert "shared" in rules["sessions"] and "shared" in rules["pages"] and "shared" in rules["node"]


def test_references_split_loaded_files_from_links():
    loads, links = impact.references("sessions/01-fundamentals/index.html")
    assert "sessions/01-fundamentals/cursus/02-thinking.html" in links
    assert not any(p.startswith(("http", "/")) for p in loads | links)


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
    assert engine.units == {"engine"} and not engine.sessions and not engine.pages
    assert impact.select(Change({".github/workflows/ci.yml"})).everything

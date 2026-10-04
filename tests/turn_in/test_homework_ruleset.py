"""Validate the definition and exercise both create/update paths offline."""

import json
from pathlib import Path
import shutil

import pytest

from test_turn_in_script import ROOT, command, isolated_environment, records, write


FILES = ("pr-only-main.json", "homework-branches.json")


def test_homework_ruleset_covers_nested_branches_without_bypass():
    data = json.loads((ROOT / "setup/homework-branches.json").read_text())
    main = json.loads((ROOT / "setup/pr-only-main.json").read_text())
    assert data["name"] == "homework-branches" and data["name"] != main["name"]
    assert data["target"] == "branch"
    assert data["enforcement"] == "active"
    assert data["conditions"]["ref_name"]["include"] == ["refs/heads/homework/**/*"]
    assert data["conditions"]["ref_name"]["exclude"] == []
    assert {"non_fast_forward", "deletion"} <= {rule["type"] for rule in data["rules"]}
    assert data["bypass_actors"] == []


def apply_fixture(tmp_path, existing, failure=""):
    env = isolated_environment(tmp_path)
    setup = tmp_path / "repo/setup"
    setup.mkdir(parents=True)
    expected = {}
    for filename in FILES:
        source = ROOT / "setup" / filename
        assert source.is_file(), f"Missing ruleset {source}"
        shutil.copyfile(source, setup / filename)
        data = json.loads(source.read_text())
        expected[data["name"]] = data
    shutil.copyfile(ROOT / "setup/apply-ruleset.sh", setup / "apply-ruleset.sh")
    state = {
        "origin": "course/cursus", "repos": {"course/cursus": {"nameWithOwner": "course/cursus"}},
        # An unrelated entry makes positional/id-by-order assumptions fail.
        "rulesets": [{"id": 101, "name": "unrelated-rule"}] + existing,
        "rules_failure": failure,
    }
    write(Path(env["GH_STATE"]), json.dumps(state))
    command(["bash", "-n", setup / "apply-ruleset.sh"], cwd=setup.parent, env=env)
    result = command(["bash", setup / "apply-ruleset.sh"], cwd=setup.parent, env=env, ok=False)
    return result, records(Path(env["GH_LOG"])), expected


def method(args):
    for option in ("--method", "-X"):
        if option in args:
            return args[args.index(option) + 1]
    return "GET"


@pytest.mark.parametrize("present", [(), ("pr-only-main", "homework-branches"),
                                     ("pr-only-main",), ("homework-branches",)])
def test_apply_both_rulesets_create_update_and_mixed(tmp_path, present):
    ids = {"pr-only-main": 271, "homework-branches": 982}
    existing = [{"name": name, "id": ids[name]} for name in reversed(present)]
    result, calls, expected = apply_fixture(tmp_path, existing)
    assert result.returncode == 0, (result.stdout, result.stderr)
    lookups = [r for r in calls if r["args"][0] == "api" and method(r["args"]) == "GET"]
    assert len(lookups) >= 2, "Each ruleset must get its own lookup by name"
    assert all("--paginate" in r["args"] for r in lookups), "Ruleset lookups must paginate"
    writes = [r for r in calls if r["args"][0] == "api" and method(r["args"]) != "GET"]
    assert len(writes) == 2, "Apply both definitions exactly once"
    assert {r["payload"]["name"] for r in writes} == set(expected)
    for record in writes:
        args, payload = record["args"], record["payload"]
        name = payload["name"]
        assert payload == expected[name], "The API payload must match the checked-in ruleset"
        endpoint = f"repos/course/cursus/rulesets" + (f"/{ids[name]}" if name in present else "")
        assert endpoint in args, (endpoint, args)
        assert method(args) == ("PUT" if name in present else "POST")


@pytest.mark.parametrize("failure,present", [
    ("GET", ()), ("POST", ()), ("PUT", ("pr-only-main", "homework-branches")),
    # Also fail only on applying the second definition: succeeding on main
    # must not make a later homework-ruleset failure look like overall success.
    ("POST", ("pr-only-main",)), ("PUT", ("homework-branches",)),
])
def test_ruleset_api_failure_is_not_swallowed(tmp_path, failure, present):
    ids = {"pr-only-main": 271, "homework-branches": 982}
    existing = [{"name": name, "id": ids[name]} for name in present]
    result, calls, _ = apply_fixture(tmp_path, existing, failure)
    assert any(r["args"][0] == "api" and method(r["args"]) == failure for r in calls)
    assert result.returncode != 0, f"The script swallowed a ruleset {failure} failure"

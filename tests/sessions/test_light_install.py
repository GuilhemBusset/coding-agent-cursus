"""A session's install stays light: torch and transformers, which only rebuild fixtures, are opt-in."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = sorted(path.parent for path in ROOT.glob("sessions/*/pyproject.toml"))
HEAVY = {"torch", "transformers"}


def dependency_name(requirement):
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    assert match, f"Invalid dependency: {requirement!r}"
    return re.sub(r"[-_.]+", "-", match[1]).lower()


@pytest.mark.parametrize("session", SESSIONS, ids=lambda path: path.name)
def test_fixture_building_is_opt_in(session):
    config = tomllib.loads((session / "pyproject.toml").read_text(encoding="utf-8"))
    assert not {dependency_name(item) for item in config["project"]["dependencies"]} & HEAVY
    groups = config.get("dependency-groups", {})
    defaults = config.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    assert isinstance(defaults, list), "default-groups must be a list, not 'all'"

    def check_default(group, seen):
        assert group != "fixtures", "Fixture building must be opt-in"
        if group in seen:
            return
        seen.add(group)
        for item in groups.get(group, []):
            if isinstance(item, dict):
                check_default(item["include-group"], seen)
            else:
                assert dependency_name(item) not in HEAVY, f"{item} is installed by default"

    for group in defaults:
        check_default(group, set())

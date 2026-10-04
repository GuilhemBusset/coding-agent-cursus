"""Acceptance checks for the session layout, dependencies and runbook."""

from pathlib import Path
import re
import tomllib


SESSION = Path(__file__).resolve().parents[1]


def read_toml(name):
    return tomllib.loads((SESSION / name).read_text(encoding="utf-8"))


def dependency_name(requirement):
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    assert match, f"Invalid dependency: {requirement!r}"
    return re.sub(r"[-_.]+", "-", match[1]).lower()


def markdown_section(text, title):
    heading = re.search(rf"(?im)^(#{{1,6}})\s+{re.escape(title)}\s*#*\s*$", text)
    assert heading, f"Missing {title!r} section"
    rest = text[heading.end():]
    next_heading = re.search(rf"(?m)^#{{1,{len(heading[1])}}}\s+", rest)
    return rest[:next_heading.start()] if next_heading else rest


def test_layout():
    for name in ("README.md", "pyproject.toml", "uv.lock", "mise.toml", "tests/test_pages.py"):
        assert (SESSION / name).is_file(), f"Missing file: {name}"
    for name in ("cursus", "cursus/labs", "cursus/demos", "cursus/fixtures", "exercises", "tests"):
        assert (SESSION / name).is_dir(), f"Missing directory: {name}"


def test_mise_pins():
    tools = read_toml("mise.toml")["tools"]
    assert re.fullmatch(r"3\.12(?:\.\d+)?", str(tools.get("python", ""))), tools
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(tools.get("uv", ""))), "Pin an exact uv version"


def test_dependencies():
    config = read_toml("pyproject.toml")
    dependencies = config["project"]["dependencies"]
    assert {dependency_name(item) for item in dependencies} == {"pytest", "highspy", "numpy"}
    groups = config["dependency-groups"]
    fixture_names = {dependency_name(item) for item in groups["fixtures"] if isinstance(item, str)}
    assert {"torch", "transformers"} <= fixture_names
    defaults = config.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    assert defaults != "all", "Fixture building must be opt-in"
    assert isinstance(defaults, list), "default-groups must be a list"

    def check_default(group, seen):
        assert group != "fixtures", "Fixture building must be opt-in"
        if group in seen:
            return
        seen.add(group)
        for item in groups.get(group, []):
            if isinstance(item, dict):
                check_default(item["include-group"], seen)
            else:
                assert dependency_name(item) not in {"torch", "transformers"}

    for group in defaults:
        check_default(group, set())
    packages = {item["name"]: item for item in read_toml("uv.lock")["package"]}
    for name in ("pytest", "highspy", "numpy", "torch", "transformers"):
        assert name in packages, f"Missing locked package: {name}"
        assert packages[name].get("version"), f"No locked version: {name}"


def test_readme_validation():
    section = markdown_section((SESSION / "README.md").read_text(encoding="utf-8"), "Validating pages")
    for command in ("npm --prefix setup run check-repo", "node tools/html-pages/check-page.mjs", "node setup/html-pages.mjs"):
        assert command in section, f"Missing page validation command: {command}"
    assert 'data-design-system="cursus"' in section
    assert "repo root" in section.lower()


def test_readme_runbook():
    text = (SESSION / "README.md").read_text(encoding="utf-8")
    for term in ("mise install", "uv sync", "uv run pytest", "file://", "cursus/", "exercises/", "setup/session-01-fundamentals.sh"):
        assert term in text, f"Missing runbook instruction: {term}"
    agenda = markdown_section(text, "Agenda")
    assert "delivery hub" in agenda.lower()
    assert re.search(r"(?i)\b(tbd|placeholder|to be|filled in)\b", agenda), "Agenda must mark pending content"

"""Execute the actual workflow shell snippets, including negative fixtures."""

import re
import textwrap

import pytest

from test_turn_in_script import ROOT, command, write


WORKFLOW = ROOT / ".github/workflows/checks.yml"


def workflow_steps():
    """Read this workflow's ordinary block steps without a YAML dependency.

    Supports inline run scalars and literal/folded block scalars; fails visibly
    if the requested step has no supported run value. It does not execute YAML.
    """
    source = WORKFLOW.read_text(encoding="utf-8")
    starts = list(re.finditer(r"(?m)^( +)- (?:name|uses): .+$", source))
    result = []
    for i, start in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(source)
        block = source[start.start():end]
        name = re.search(r"(?m)^\s*- name:\s*(.+)$", block)
        run = re.search(r"(?m)^( +)run:\s*(.*)$", block)
        script = None
        if run:
            value = run.group(2).strip()
            if value in ("|", "|-", "|+", ">", ">-", ">+"):
                lines = []
                for line in block[run.end():].splitlines():
                    if line.strip() and len(line) - len(line.lstrip()) <= len(run.group(1)):
                        break
                    lines.append(line)
                script = textwrap.dedent("\n".join(lines)).strip()
                if value.startswith(">"):
                    script = " ".join(script.splitlines())
            else:
                script = value
                if len(script) >= 2 and script[0] == script[-1] and script[0] in "\"'":
                    script = script[1:-1]
        result.append({"name": name.group(1).strip("\"'") if name else None,
                       "run": script, "block": block})
    return result


def step_run(name):
    matches = [s for s in workflow_steps() if s["name"] == name]
    assert len(matches) == 1, f"Expected exactly one workflow step named {name!r}"
    assert matches[0]["run"], f"Step {name!r} must contain a shell run command"
    return matches[0]["run"]


def run_step(script, cwd, *, ok=True):
    # GitHub's Bash run steps fail on errors. No workflow interpolation is
    # needed by any of the snippets exercised here.
    return command(["bash", "-e", "-o", "pipefail", "-c", script], cwd=cwd, ok=ok)


def test_shell_syntax_step_passes_on_repository():
    command(["bash", "-n", ROOT / "scripts/turn-in.sh"], cwd=ROOT)
    run_step(step_run("Shell syntax"), ROOT)


@pytest.mark.parametrize("bad_path", [
    "scripts/zz-later.sh", "setup/zz-later.sh", ".githooks/pre-commit", ".githooks/pre-push",
])
def test_shell_syntax_step_actually_parses_every_file(tmp_path, bad_path):
    script = step_run("Shell syntax")
    for path in ("scripts/00-first.sh", "scripts/zz-later.sh", "setup/00-first.sh",
                 "setup/zz-later.sh", ".githooks/pre-commit", ".githooks/pre-push"):
        write(tmp_path / path, "#!/usr/bin/env bash\ntrue\n")
    run_step(script, tmp_path)
    write(tmp_path / bad_path, "#!/usr/bin/env bash\nif then\n")
    result = run_step(script, tmp_path, ok=False)
    assert result.returncode != 0, f"Shell syntax silently ignored {bad_path}"


def test_all_skill_diff_steps_pass():
    steps = [s for s in workflow_steps() if s["run"] and re.search(r"\bdiff\s+-u\b", s["run"])]
    assert any("turn-in/SKILL.md" in s["run"] for s in steps), "Missing turn-in diff gate"
    for step in steps:
        run_step(step["run"], ROOT)


def test_pinned_uv_runs_whole_turn_in_suite():
    steps = workflow_steps()
    install = [i for i, s in enumerate(steps) if re.search(r"uses:\s*astral-sh/setup-uv@", s["block"])]
    assert install, "Turn-in CI needs astral-sh/setup-uv"
    tests = [i for i, s in enumerate(steps)
             if s["run"] and re.search(
                 r"(?m)^\s*uv run --no-project --with pytest==8\.3\.5 pytest -q tests/turn_in\s*$",
                 s["run"])]
    assert len(tests) == 1, "CI must execute all the acceptance tests with pinned pytest through uv"
    assert any(i < tests[0] and re.search(r"version:\s*['\"]?0\.11\.28['\"]?\s*$",
                                         steps[i]["block"], re.M) for i in install)


@pytest.mark.parametrize("bad_file", ["pr-only-main.json", "homework-branches.json"])
def test_json_validity_step_checks_both_files(tmp_path, bad_file):
    script = step_run("JSON validity")
    run_step(script, ROOT)
    for filename in ("pr-only-main.json", "homework-branches.json"):
        write(tmp_path / "setup" / filename, "{}\n")
    run_step(script, tmp_path)
    write(tmp_path / "setup" / bad_file, "{invalid JSON\n")
    assert run_step(script, tmp_path, ok=False).returncode != 0

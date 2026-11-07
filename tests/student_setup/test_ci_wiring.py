"""The CI jobs that run the student setup for real, and how a change selects them (impact.toml)."""

from __future__ import annotations

import re
import sys

from student_sandbox import REPO

sys.path.insert(0, str(REPO / "tools/test-impact"))
import impact

WORKFLOWS = REPO / ".github/workflows"


def test_the_jobs_run_the_non_interactive_setup_twice_where_the_issue_asks():
    flow = (WORKFLOWS / "student-setup.yml").read_text(encoding="utf-8")
    images = re.findall(r"^\s+- image: (\S+)$", flow, re.MULTILINE)
    assert sorted(i.split(":")[0] for i in images) == ["archlinux", "debian", "fedora", "ubuntu"]
    for image in images:
        tag = image.split(":")[1]
        assert re.search(r"\d", tag) and "latest" not in tag, f"{image} is not pinned by version"
    assert "runs-on: macos-latest" in flow and "/bin/bash tests/student_setup/run_twice.sh" in flow
    assert "3.2.*) ;;" in flow, "the macOS job checks that /bin/bash is Bash 3.2"
    assert "runs-on: windows-latest" in flow and "powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\\student_setup\\run_twice.ps1" in flow
    assert "PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1" in flow
    unix = (REPO / "tests/student_setup/run_twice.sh").read_text(encoding="utf-8")
    assert "for run in first second" in unix and '-s -- --yes --agent both --no-login' in unix and "ci_verify.py" in unix
    windows = (REPO / "tests/student_setup/run_twice.ps1").read_text(encoding="utf-8")
    assert "foreach ($run in @('first', 'second'))" in windows and "ci_verify.py" in windows
    for variable, value in (("CURSUS_YES", "1"), ("CURSUS_AGENT", "both"), ("CURSUS_NO_LOGIN", "1")):
        assert f"$env:{variable} = '{value}'" in windows


def test_ci_runs_the_jobs_when_the_selector_says_and_requires_them():
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    job = ci.split("\n  student-setup:\n", 1)[1].split("\n\n", 1)[0]
    assert "needs.changes.outputs.student_setup == 'true'" in job and "uses: ./.github/workflows/student-setup.yml" in job
    assert re.search(r"needs: \[[^\]]*\bstudent-setup\b", ci.split("\n  required:\n", 1)[1])
    assert 'ran_or_not_needed("student-setup"; $student)' in ci


def test_a_student_setup_change_selects_its_tests_and_jobs(tmp_path):
    for path in ("setup/student/install.sh", "setup/student/install.ps1", "setup/student/versions.env",
                 "setup/editor.py", "setup/editor.json",
                 "tests/student_setup/ci_verify.py", "sessions/01-fundamentals/uv.lock",
                 "sessions/01-fundamentals/exercises/check_setup.py"):
        plan = impact.select(impact.Change({path}))
        assert not plan.everything and "student-setup" in plan.units, path
    plan = impact.select(impact.Change({"setup/student/prepare.py"}))
    assert {"student-setup", "typecheck"} <= plan.units
    labels = {label: command for label, command, _ in impact.commands(plan)}
    assert labels["student setup"][-2:] == ["-q", "tests/student_setup"]
    out = tmp_path / "out"
    impact.github_output(plan, str(out))
    assert "student_setup=true" in out.read_text().splitlines()


def test_editor_inputs_select_the_session_checks_that_read_and_export_them():
    for path in ("ty.toml", ".vscode/settings.json", ".vscode/extensions.json", "setup/cursus.code-workspace",
                 "setup/editor.py", "setup/editor.json"):
        plan = impact.select(impact.Change({path}))
        assert "sessions/01-fundamentals" in plan.sessions, path

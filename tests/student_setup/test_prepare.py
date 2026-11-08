"""The shared step (setup/student/prepare.py) and the Session 1 wrapper over it."""

from __future__ import annotations

import sys

import pytest
from student_sandbox import STUDENT, Box, course, git

CONTRACT = ("mise.toml", "pyproject.toml", "uv.lock")
SYNC = ["mise trust mise.toml", "mise install", "mise exec -- uv sync --locked"]


def syncs(box: Box) -> dict[str, list[str]]:
    """The mise calls each folder received, in order."""
    out: dict[str, list[str]] = {}
    for line in box.calls():
        if line.startswith("mise ") and " @" in line:
            command, cwd = line.rsplit(" @", 1)
            out.setdefault(cwd, []).append(command)
    return out


def fixture(tmp_path):
    box = Box(tmp_path)
    box.stub("mise")
    box.stub("uv")
    box.real("git")
    repo = course(tmp_path, {"01-alpha": CONTRACT, "02-beta": (*CONTRACT, "exercises/check_setup.py"),
                             "03-gamma": ("mise.toml", "pyproject.toml")})
    # --no-check must never run it.
    (repo / "sessions/02-beta/exercises/check_setup.py").write_text("raise SystemExit('the check ran')\n")
    return box, repo


def test_syncs_exactly_the_sessions_that_follow_the_contract(tmp_path):
    box, repo = fixture(tmp_path)
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert syncs(box) == {str(repo / "sessions/01-alpha"): SYNC, str(repo / "sessions/02-beta"): SYNC}
    assert git(repo, "config", "--get", "core.hooksPath").strip() == ".githooks"
    assert "sessions/03-gamma" not in result.stdout
    assert "setup check: not run" in result.stdout and "the check ran" not in result.stdout + result.stderr
    assert "no VS Code CLI found" in result.stdout and "code setup/cursus.code-workspace" in result.stdout


def test_a_failed_sync_names_the_step_and_the_command(tmp_path):
    box, repo = fixture(tmp_path)
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"],
                     MISE_FAIL="install @" + str(repo / "sessions/02-beta"))
    assert result.returncode == 1
    assert "FAILED at session sync (sessions/02-beta): `mise install` exited 3" in result.stdout
    assert "Next: cd sessions/02-beta && mise install" in result.stdout
    # Tried once, then once after each of the sandbox's three retry delays, and no more.
    assert syncs(box)[str(repo / "sessions/02-beta")] == ["mise trust mise.toml", *["mise install"] * 4]


@pytest.mark.parametrize("step", ["install", "exec -- uv sync --locked"])
def test_a_download_that_fails_once_is_tried_again(tmp_path, step):
    box, repo = fixture(tmp_path)
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"],
                     MISE_FAIL=f"{step} @{repo / 'sessions/02-beta'}", MISE_FAIL_ONCE="1")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = syncs(box)[str(repo / "sessions/02-beta")]
    assert calls.count(f"mise {step}") == 2 and calls[-1] == SYNC[-1]
    assert "[setup] sessions/02-beta: synced" in result.stdout


def test_a_repository_tool_sync_that_fails_once_is_tried_again(tmp_path):
    box, repo = fixture(tmp_path)
    (repo / "setup/pyproject.toml").write_text("# repository tooling\n")
    box.stub("uv", f'#!/bin/sh\necho "uv $*" >> "$STUB_LOG"\n'
                   f'if [ ! -e "{tmp_path}/failed" ]; then : > "{tmp_path}/failed"; echo "504 Gateway Timeout"; exit 2; fi\n')
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.calls().count(f"uv sync --project {repo / 'setup'} --locked") == 2


def test_retry_delays_that_are_not_whole_seconds_stop_before_any_sync(tmp_path):
    box, repo = fixture(tmp_path)
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"],
                     CURSUS_RETRY_DELAYS="1 soon")
    assert result.returncode == 1 and "CURSUS_RETRY_DELAYS" in result.stdout
    assert syncs(box) == {}


def test_runs_the_latest_sessions_check_and_prints_the_next_steps(tmp_path):
    box, repo = fixture(tmp_path)
    for session, verdict in (("01-alpha", 1), ("02-beta", 0)):
        check = repo / "sessions" / session / "exercises/check_setup.py"
        check.parent.mkdir(exist_ok=True)
        check.write_text(f"print('check of {session}')\nraise SystemExit({verdict})\n")
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo)])
    assert result.returncode == 0, result.stdout
    assert "check of 02-beta" in result.stdout and "check of 01-alpha" not in result.stdout
    assert "Next steps:" in result.stdout and "new terminal" in result.stdout


def test_session_01_wrapper_still_works_from_the_root_and_from_a_session(tmp_path):
    box, repo = fixture(tmp_path)
    for cwd, script in ((repo, "setup/session-01-fundamentals.sh"),
                        (repo / "sessions/01-alpha", "../../setup/session-01-fundamentals.sh")):
        box.log.write_text("")
        result = box.run(["bash", script], cwd=cwd)
        assert result.returncode == 0, result.stdout + result.stderr
        assert syncs(box) == {str(repo / "sessions/01-alpha"): SYNC, str(repo / "sessions/02-beta"): SYNC}
        assert "uv run --no-project --python 3.12 python" in "\n".join(box.calls())
    assert git(repo, "config", "--get", "core.hooksPath").strip() == ".githooks"


def test_syncs_the_repositories_pinned_tools_when_the_manifest_exists(tmp_path):
    box, repo = fixture(tmp_path)
    (repo / "setup/pyproject.toml").write_text("# repository tooling\n")
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"uv sync --project {repo / 'setup'} --locked" in box.calls()
    assert "repository tooling: syncing setup/.venv from setup/uv.lock" in result.stdout


def test_a_failed_repository_tool_sync_stops_with_its_recovery_command(tmp_path):
    box, repo = fixture(tmp_path)
    (repo / "setup/pyproject.toml").write_text("# repository tooling\n")
    box.stub("uv", "#!/bin/sh\necho 'package download failed'\nexit 9\n")
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"])
    assert result.returncode == 1
    assert "FAILED at repository tooling" in result.stdout and "package download failed" in result.stdout
    assert "Next: uv sync --project setup --locked" in result.stdout
    assert "no VS Code CLI found" not in result.stdout


def test_a_detected_editor_failure_stops_prepare_even_with_no_check(tmp_path):
    box, repo = fixture(tmp_path)
    box.stub("code", "#!/bin/sh\necho 'editor unavailable'\nexit 7\n")
    result = box.run([sys.executable, str(STUDENT / "prepare.py"), "--repo", str(repo), "--no-check"])
    assert result.returncode == 1
    assert "editor: FAILED" in result.stdout and "editor unavailable" in result.stdout
    assert "setup check: not run" not in result.stdout

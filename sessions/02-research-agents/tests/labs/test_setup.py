"""Offline prerequisite failures and the real Pi import smoke, with no provider calls."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]


def execute(session, **env):
    return subprocess.run([sys.executable, str(session / "exercises/check_setup.py")], cwd=session,
                          env={**os.environ, **env}, capture_output=True, text=True, check=False)


@pytest.fixture
def standalone(tmp_path):
    target = tmp_path / "session with spaces"
    shutil.copytree(SESSION, target, ignore=shutil.ignore_patterns(".venv", "node_modules", "__pycache__", ".pytest_cache"))
    return target


def test_missing_node_reports_actionable_failure_without_credentials(standalone):
    result = execute(standalone, PATH="", OPENAI_API_KEY="secret-sentinel", ANTHROPIC_API_KEY="other-secret")
    assert result.returncode == 1
    assert "node: FAIL" in result.stdout and "Pi imports: FAIL" in result.stdout
    assert "secret" not in result.stdout + result.stderr


def test_unsupported_node_is_rejected(standalone):
    package = json.loads((standalone / "package.json").read_text())
    package["engines"]["node"] = "0.0.0"
    (standalone / "package.json").write_text(json.dumps(package))
    result = execute(standalone)
    assert result.returncode == 1 and "node: FAIL" in result.stdout


def test_broken_local_configuration_fails(standalone):
    (standalone / "tsconfig.json").write_text('{broken')
    result = execute(standalone)
    assert result.returncode == 1 and "Local configuration: FAIL" in result.stdout


def test_failed_probe_does_not_echo_sensitive_diagnostics(standalone):
    (standalone / "exercises/fixed/check_setup.ts").write_text('throw new Error("secret-sentinel");\n')
    result = execute(standalone, OPENAI_API_KEY="secret-sentinel")
    assert result.returncode == 1 and "Pi imports: FAIL" in result.stdout
    assert "secret-sentinel" not in result.stdout + result.stderr


def test_installed_session_is_ready_and_typescript_checks_are_offline():
    env = {key: value for key, value in os.environ.items() if not key.endswith("API_KEY")}
    result = subprocess.run([sys.executable, str(SESSION / "exercises/check_setup.py")], cwd=SESSION,
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    npm = shutil.which("npm")
    assert npm
    for command in ([npm, "run", "typecheck"], [npm, "test"]):
        result = subprocess.run(command, cwd=SESSION, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

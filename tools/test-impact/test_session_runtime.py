"""The local selector honors session runtime pins for checks and their children."""

from types import SimpleNamespace

import pytest

import impact


@pytest.mark.parametrize("mise_available", [True, False])
def test_session_checks_activate_pins_but_repository_checks_keep_path(tmp_path, monkeypatch, mise_available):
    session = tmp_path / "sessions" / "02 with spaces"
    session.mkdir(parents=True)
    (session / "mise.toml").write_text('[tools]\nnode = "24.15.0"\n')
    monkeypatch.setattr(impact, "ROOT", tmp_path)
    monkeypatch.setattr(impact, "local_change", lambda base: impact.Change(set()))
    monkeypatch.setattr(impact, "select", lambda *args, **kwargs: impact.Plan())
    monkeypatch.setattr(impact.shutil, "which", lambda name: "/bin/mise" if mise_available else None)
    checks = [
        ("session labs", ["uv", "run", "--locked", "pytest", "tests/labs"], session),
        ("repository", ["node", "--test"], tmp_path),
    ]
    monkeypatch.setattr(impact, "commands", lambda plan: checks)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(impact.subprocess, "run", run)
    assert impact.main(["run"]) == 0
    prefix = ["mise", "exec", "--"] if mise_available else []
    assert calls == [(prefix + checks[0][1], session), (checks[1][1], tmp_path)]

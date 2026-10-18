"""Independent behavioural probes for issue 103."""
import contextlib
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase
from implement_loop.state import RunStore


def engine_at(tmp_path):
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    engine.caps = Caps()
    return engine


def run_python(root, relative, cwd):
    command = f"{shlex.quote(sys.executable)} {shlex.quote(relative)}"
    result = subprocess.run(shlex.split(command), cwd=root / cwd, capture_output=True)
    return ({"criterion": "D1", "author": "examiner", "command": command, "cwd": cwd},
            {"command": command, "cwd": cwd, "passed": result.returncode == 0})


def test_nested_probe_closes_only_after_its_execution_passes(tmp_path):
    engine = engine_at(tmp_path)
    probe = "sessions/demo/tests/test_probe.py"
    target = tmp_path / probe
    target.parent.mkdir(parents=True)
    target.write_text("raise AssertionError('still broken')\n")
    command, failed = run_python(tmp_path, "tests/test_probe.py", "sessions/demo")
    st = IssueState(number=48, commands=[command], findings=[
        {"id": "E48-1-1", "status": "open", "probe": probe}])
    assert engine._close_findings(48, st, tmp_path, [failed]) == []
    assert st.findings[0]["status"] == "open"
    target.write_text("assert 2 + 2 == 4\n")
    _, passed = run_python(tmp_path, "tests/test_probe.py", "sessions/demo")
    assert engine._close_findings(48, st, tmp_path, [passed]) == ["E48-1-1"]
    assert engine.store.issue(48).findings[0]["status"] == "closed"


def test_passing_different_file_does_not_close_failing_probe(tmp_path):
    engine = engine_at(tmp_path)
    probe = "sessions/demo/tests/test_probe.py"
    target = tmp_path / probe
    other = tmp_path / "sessions/demo/archive/tests/test_probe.py"
    target.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    target.write_text("raise AssertionError('finding still reproduces')\n")
    other.write_text("assert True\n")
    wrong, passed = run_python(tmp_path, "archive/tests/test_probe.py", "sessions/demo")
    right, failed = run_python(tmp_path, "tests/test_probe.py", "sessions/demo")
    st = IssueState(number=48, commands=[wrong, right], findings=[
        {"id": "E48-1-1", "status": "open", "probe": probe}])
    assert passed["passed"] and not failed["passed"]
    closed = engine._close_findings(48, st, tmp_path, [passed, failed])
    assert closed == [], "A different file passed; the finding's own probe still fails"
    assert st.findings[0]["status"] == "open"


def test_verify_notes_do_not_interrupt_progress_escalation(tmp_path, monkeypatch):
    engine = engine_at(tmp_path)
    engine.check_env = {}
    engine.repair = False
    engine.ws = SimpleNamespace(
        head=lambda wt: "head", disposable=lambda wt: contextlib.nullcontext(wt),
        git=lambda *a, **kw: "base", base_ref=lambda: "main", changed_files=lambda *a: [])
    transitions = []
    engine._set_phase = lambda n, phase, **kw: transitions.append((phase, kw))
    monkeypatch.setattr("implement_loop.engine.verify.verify",
                        lambda *a, **kw: (False, [], ["D1 failed: exit 1"], []))
    monkeypatch.setattr("implement_loop.engine.verify.unselected", lambda *a: [])
    st = IssueState(number=48, worktree=str(tmp_path), plan={"items": [
        {"id": "D1", "proof": "test"}]}, commands=[
        {"criterion": "D1", "command": "python check.py", "cwd": "."}])
    engine.store.put(st)
    for dropped in (["mislabelled command"], [], ["mislabelled command"]):
        st = engine.store.issue(48)
        st.dropped = dropped
        engine.store.put(st)
        engine._step_verify(48)
    assert engine.store.issue(48).unproductive == 2
    assert transitions[-1][0] == Phase.PLAN
    assert any("These commands were not kept" in line
               for line in transitions[0][1]["feedback"])

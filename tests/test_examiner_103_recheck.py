"""Independent execution and recovery checks for the #48 ceiling repair."""
from dataclasses import asdict
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import RunStore
from implement_loop.verify import run_check


def make_engine(tmp_path):
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    engine.caps = Caps()
    return engine


def test_real_pytest_result_closes_session_relative_probe(tmp_path):
    engine = make_engine(tmp_path)
    root = tmp_path / "repo"
    session = root / "sessions/demo"
    (session / "tests").mkdir(parents=True)
    probe = "sessions/demo/tests/test_condition.py"
    (root / probe).write_text(
        "from pathlib import Path\n"
        "def test_condition():\n"
        "    assert Path('fixed').is_file()\n"
    )
    command = f"{shlex.quote(sys.executable)} -m pytest -q tests/test_condition.py"
    spec = CheckSpec(criterion="D1", command=command, cwd="sessions/demo")
    st = IssueState(number=48, commands=[
        {"criterion": "D1", "command": command, "cwd": spec.cwd, "author": "examiner"}
    ], findings=[{"id": "E48-1-1", "status": "open", "probe": probe}])
    engine.store.put(st)
    failed, _ = run_check(root, spec, "head", tmp_path / "failed")
    assert not failed.passed and failed.tests["failed"] == 1
    assert engine._close_findings(48, st, root, [asdict(failed)]) == []
    assert st.findings[0]["status"] == "open"
    (session / "fixed").touch()
    passed, _ = run_check(root, spec, "head", tmp_path / "passed")
    assert passed.passed and passed.tests["passed"] == 1
    assert engine._close_findings(48, st, root, [asdict(passed)]) == ["E48-1-1"]
    assert engine.store.issue(48).findings[0]["status"] == "closed"


def test_changing_notes_cannot_prevent_replan_and_no_progress(tmp_path):
    engine = make_engine(tmp_path)
    phases, failures = [], []
    engine._set_phase = lambda n, phase, **kw: phases.append((phase, kw))
    engine._fail = lambda n, cause, detail: failures.append(cause)
    problems = ["open finding E48-1-1 still reproduces"]
    for index in range(5):
        notes = [f"These commands were not kept: round {index}"] if index % 2 == 0 else []
        engine._round_failed(48, problems, ["E48-1-1"], notes=notes)
    assert problems == ["open finding E48-1-1 still reproduces"]
    assert phases[0][1]["feedback"][0].startswith("These commands were not kept")
    assert sum(phase == Phase.PLAN for phase, _ in phases) == 1
    assert failures == ["no_progress"]
    assert engine.store.issue(48).unproductive == 4

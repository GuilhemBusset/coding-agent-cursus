"""Independent command-retention probe for fault #90."""
import shlex
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/implementation-loop"))
from implement_loop import verify
from implement_loop.agents import BuildResult
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState


def test_d1_multiple_commands_run_and_locked_lists_need_approval(tmp_path):
    engine = Engine.__new__(Engine)
    engine.caps = Caps()
    engine.other = "examiner"
    state = IssueState(41, plan={"items": [{"id": "A2", "proof": "test"}]})
    path = "test_recording.py"
    (tmp_path / path).write_text(
        "def test_raw():\n    assert 2 + 3 == 5\n"
        "def test_catalog():\n    assert 'raw'.upper() == 'RAW'\n")
    python = shlex.quote(sys.executable)
    commands = [CheckSpec("A2", command=f"{python} -m pytest -q {path} -k {name}")
                for name in ("raw", "catalog")]
    commands.append(CheckSpec("A2", command=f"{python} -c 'print(42)'"))
    engine._absorb_build(state, BuildResult("done", tests=[path], commands=commands))
    assert [c["command"] for c in state.commands] == [c.command for c in commands]
    ok, evidence, problems, ran = verify.verify(
        tmp_path, engine._specs(state), "abc123", tmp_path / "reports", {}, [path], None)
    assert ok, problems
    assert len(evidence) == 3 and all(e["passed"] for e in evidence)
    assert set(ran) == {f"{path}::test_raw", f"{path}::test_catalog"}
    assert not verify.unselected(tmp_path, [path], {"*": ran}, {})

    state.examined_sha = "abc123"
    original = deepcopy(state.commands)
    engine._absorb_build(state, BuildResult("done", commands=commands[1:]))
    assert state.commands == original, "a locked list was changed before approval"
    assert len(state.requests) == 1
    request = state.requests[0]
    assert request["kind"] == "command_change" and request["status"] == "pending"
    assert [c["command"] for c in request["commands"]] == [c.command for c in commands[1:]]
    engine._apply_request(41, state, tmp_path, request, {})
    assert [c["command"] for c in state.commands] == [c.command for c in commands[1:]]

    # A later passing command must not hide a failure from an earlier command.
    broken = [CheckSpec("A2", command=f"{python} -c 'raise SystemExit(7)'"), commands[-1]]
    ok, evidence, problems, _ = verify.verify(
        tmp_path, broken, "abc124", tmp_path / "reports2", {}, [], None)
    assert not ok and problems
    assert [e["passed"] for e in evidence] == [False, True]

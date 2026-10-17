"""Independent version/resumption probe for fault #90."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/implementation-loop"))
from implement_loop import VERSION
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase


def test_d2_new_version_revives_the_faulted_run_once():
    assert VERSION != "1.0.0"
    state = IssueState(41, phase=Phase.FAILED, branch="loop/issue-41", worktree="kept-work",
                       plan={"items": [{"id": "A2", "proof": "test"}]},
                       fail={"version": "1.0.0", "cause": "no_progress", "resumed": False},
                       unproductive=4, replans=1)
    engine = Engine.__new__(Engine)
    changes = []
    engine.store = SimpleNamespace(
        budget=lambda n: {"calls": 14, "bonus": 0},
        change_budget=lambda n, **kw: changes.append((n, kw)),
        event=lambda *args, **kw: None)
    engine._maybe_revive(state)
    assert state.phase == Phase.BUILD
    assert state.branch == "loop/issue-41" and state.worktree == "kept-work"
    assert state.fail["resumed"] is True
    assert (state.unproductive, state.replans) == (0, 0)
    assert changes == [(41, {"bonus": 14, "set_infra": 0})]
    state.phase = Phase.FAILED
    engine._maybe_revive(state)
    assert state.phase == Phase.FAILED and len(changes) == 1

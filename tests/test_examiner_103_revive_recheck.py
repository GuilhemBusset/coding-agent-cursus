"""Independent version and resume check for issue 103."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop import VERSION
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase
from implement_loop.state import RunStore


def test_new_version_revives_retained_work_but_cannot_repeat(tmp_path):
    assert tuple(int(p) for p in VERSION.split(".")) > (1, 0, 4)
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    st = IssueState(number=48, phase=Phase.FAILED, worktree="retained",
                    plan={"items": [{"id": "D1", "proof": "test"}]},
                    fail={"cause": "ceiling", "version": VERSION}, unproductive=4, replans=1)
    engine.store.change_budget(48, set_calls=45, set_infra=3)
    engine._maybe_revive(st)
    assert st.phase == Phase.FAILED
    st.fail["version"] = "1.0.3"
    engine._maybe_revive(st)
    assert st.phase == Phase.BUILD and st.worktree == "retained"
    assert st.plan["items"][0]["id"] == "D1"
    assert st.unproductive == st.replans == 0
    budget = engine.store.budget(48)
    assert budget["calls"] == budget["bonus"] and budget["infra"] == 0
    engine.store.change_budget(48, set_calls=46)
    engine._maybe_revive(st)
    assert engine.store.budget(48)["bonus"] == budget["bonus"]
    assert len([e for e in engine.store.events() if e["kind"] == "revived"]) == 1

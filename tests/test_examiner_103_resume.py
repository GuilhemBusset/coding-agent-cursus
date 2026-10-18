"""Independent version-gated resumption probe for D2 of issue 103."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop import VERSION
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase
from implement_loop.state import RunStore


def test_bumped_version_revives_failed_48_once_with_fresh_budget(tmp_path):
    assert tuple(map(int, VERSION.split("."))) > (1, 0, 4)
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    st = IssueState(number=48, phase=Phase.FAILED, worktree="retained-worktree",
                    plan={"items": [{"id": "D1", "proof": "test"}]},
                    fail={"cause": "ceiling", "version": "1.0.3", "resumed": False},
                    unproductive=3, replans=1)
    engine.store.put(st)
    engine.store.change_budget(48, set_calls=45, set_infra=2)
    engine._maybe_revive(st)
    assert st.phase == Phase.BUILD
    assert st.unproductive == st.replans == 0
    assert st.fail["resumed"]
    budget = engine.store.budget(48)
    assert budget["calls"] - budget["bonus"] == 0
    assert budget["infra"] == 0
    engine._maybe_revive(st)
    assert len([e for e in engine.store.events() if e["kind"] == "revived"]) == 1

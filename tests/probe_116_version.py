"""Independent check that the version bump revives #50 once with a fresh ceiling."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/implementation-loop"))
from implement_loop import VERSION
from implement_loop.config import ceiling
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase
from implement_loop.state import RunStore


def test_new_version_revives_50_with_one_fresh_ceiling(tmp_path):
    assert tuple(map(int, VERSION.split("."))) > (1, 0, 5)
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "state")
    wt = tmp_path / "work"
    wt.mkdir()
    st = IssueState(number=50, phase=Phase.FAILED, worktree=str(wt), plan={"items": []},
                    fail={"version": "1.0.5", "cause": "ceiling"})
    engine.store.put(st)
    spent = ceiling("S", False)
    engine.store.change_budget(50, calls=spent, infra=3)
    engine._maybe_revive(st)
    assert st.phase == Phase.BUILD
    assert st.fail["resumed"]
    budget = engine.store.budget(50)
    assert budget["calls"] == spent
    assert budget["infra"] == 0
    assert ceiling("S", False) + budget["bonus"] - budget["calls"] == ceiling("S", False)
    engine.store.change_budget(50, calls=2)
    before = engine.store.budget(50)
    engine._maybe_revive(st)
    assert engine.store.budget(50) == before, "revival must not grant a second retry"

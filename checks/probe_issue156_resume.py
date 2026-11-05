"""The release revives the recorded 1.0.6 fault and removes its obsolete command."""
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "tools/implementation-loop"))

from implement_loop import VERSION
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import RunStore


def test_new_version_revives_148_once_with_a_fresh_ceiling(tmp_path):
    assert tuple(map(int, VERSION.split("."))) > (1, 0, 6)
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "run")
    engine.store.change_budget(148, calls=22)
    keep = asdict(CheckSpec("A1", command="true"))
    stale = asdict(CheckSpec("A2", command="exit 23"))
    probe = asdict(CheckSpec("A2", command="true", author="examiner"))
    st = IssueState(number=148, phase=Phase.FAILED, worktree=str(tmp_path),
                    plan={"items": [{"id": "A1", "proof": "command"}, {"id": "A2", "proof": "review"}]},
                    commands=[keep, stale, probe], fail={"cause": "no_progress", "version": "1.0.6"},
                    unproductive=4, replans=1)
    engine._maybe_revive(st)
    assert st.phase == Phase.BUILD
    assert st.commands == [keep, probe]
    assert st.fail["resumed"] is True
    assert st.unproductive == st.replans == 0
    budget = engine.store.budget(148)
    assert budget["calls"] - budget["bonus"] == 0
    engine._maybe_revive(st)
    assert len([e for e in engine.store.events() if e["kind"] == "revived"]) == 1

"""Independent execution and lock-preservation checks for issue 156."""
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd() / "tools/implementation-loop"))

from implement_loop import verify
from implement_loop.agents import BuildResult, ItemPlan, PlanResult
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import RunStore


def make_engine(tmp_path):
    engine = Engine.__new__(Engine)
    engine.store = RunStore(tmp_path / "run")
    engine.caps = Caps()
    engine.repair = False
    engine.op, engine.other = "claude", "codex"
    engine.lacks = []
    engine.log = lambda message: None
    engine._lookup_issue = lambda n: None
    ledger = [SimpleNamespace(id="A1", text="other checks still pass"),
              SimpleNamespace(id="A2", text="the changed selection passes")]
    engine.plan = SimpleNamespace(specs={148: SimpleNamespace(ledger=ledger, declared_paths=[])}, work=[148])
    return engine


def items(proof):
    return [{"id": "A1", "proof": "command", "reading": "other checks", "quote": "other checks still pass"},
            {"id": "A2", "proof": proof, "reading": "selection", "quote": "the changed selection passes"}]


def commands():
    return [asdict(CheckSpec("A1", command="printf kept")),
            asdict(CheckSpec("A2", command="touch retired-ran; exit 23")),
            asdict(CheckSpec("A2", command="printf probe", author="examiner"))]


def test_accepted_replan_stops_executing_the_retired_command(tmp_path):
    engine = make_engine(tmp_path)
    engine.agents = SimpleNamespace(
        plan=lambda *args: PlanResult(items=[ItemPlan(**i) for i in items("review")], zones=[], decisions=[]),
        triage=lambda *args: [])
    st = IssueState(number=148, phase=Phase.PLAN, plan={"items": items("command")}, commands=commands())
    engine.store.put(st)
    with patch.object(Engine, "_req"), patch.object(Engine, "_declare"), patch.object(Engine, "_sync"), \
            patch("implement_loop.engine.scheduler.prerequisites_met", return_value=True):
        engine._step_plan(148)
    accepted = engine.store.issue(148)
    assert accepted.plan["items"][1]["proof"] == "review"
    specs = engine._specs(accepted)
    assert [(s.criterion, s.author) for s in specs] == [("A1", "builder"), ("A2", "examiner")]
    for spec in specs:
        evidence, _ = verify.run_check(tmp_path, spec, "examined-head", tmp_path / "reports")
        assert evidence.passed, evidence
    assert not (tmp_path / "retired-ran").exists()


def test_builder_cannot_reintroduce_review_command_or_erase_existing_locks(tmp_path):
    engine = make_engine(tmp_path)
    st = IssueState(number=148, plan={"items": items("review")}, commands=commands(),
                    examined_sha="locked-head", locked={"tests/kept.py": "digest"},
                    manifest={"*": ["tests/kept.py::test_contract"]})
    answer = BuildResult(status="done", commands=[CheckSpec("A2", command="touch retired-ran; exit 23"),
                                                  CheckSpec("A1", command="printf kept")])
    engine._absorb_build(st, answer, tmp_path)
    assert [(s.criterion, s.author) for s in engine._specs(st)] == [("A1", "builder"), ("A2", "examiner")]
    assert st.locked == {"tests/kept.py": "digest"}
    assert st.manifest == {"*": ["tests/kept.py::test_contract"]}
    assert st.requests == []
    assert any("review" in explanation for explanation in st.dropped)

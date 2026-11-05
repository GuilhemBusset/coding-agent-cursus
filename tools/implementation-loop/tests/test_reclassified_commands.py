"""Regressions from #148's no_progress (#156): a replan moved A2 from `command` to `review`, but the
builder's command for A2 kept running and failing. A builder command only proves an item the plan
proves by `test`, `command` or an owner's agent part."""

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401  (puts the engine on sys.path)
from implement_loop import VERSION
from implement_loop.agents import BuildResult, ItemPlan, PlanResult
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import RunStore

TEXT = {"A1": "ruff passes on the repository", "A2": "the selected checks pass on the change"}
A1 = {"criterion": "A1", "command": "uvx ruff check .", "cwd": ".", "author": "builder"}
A2 = {"criterion": "A2", "command": "scripts/check-changed.sh", "cwd": ".", "author": "builder"}
PROBE = {"criterion": "A2", "command": "pytest -q checks/probe.py", "cwd": ".", "author": "examiner"}


def plan(a2: str) -> dict:
    return {"items": [{"id": "A1", "reading": "r", "quote": TEXT["A1"], "proof": "command"},
                      {"id": "A2", "reading": "r", "quote": TEXT["A2"], "proof": a2}], "zones": [], "notes": ""}


class Agents:
    def plan(self, vendor, req, wt):
        return PlanResult(items=[ItemPlan(**i) for i in plan("review")["items"]], zones=[], decisions=[])

    def triage(self, vendor, req, plan):
        return []


class ReclassifiedCommandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-loop-"))
        self.engine = Engine.__new__(Engine)
        self.engine.store = RunStore(self.tmp / "run")
        self.engine.caps, self.engine.repair, self.engine.other, self.engine.op = Caps(), False, "codex", "claude"
        self.engine.lacks, self.engine._lookup_issue = [], lambda n: None   # ty: ignore[invalid-assignment]  # test double
        ledger = [SimpleNamespace(id=k, text=v) for k, v in TEXT.items()]
        self.engine.plan = SimpleNamespace(specs={148: SimpleNamespace(ledger=ledger, declared_paths=[])}, work=[148])  # ty: ignore[invalid-assignment]  # test double
        self.engine.agents = Agents()  # ty: ignore[invalid-assignment]  # test double

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commands(self, st: IssueState) -> list[tuple]:
        return [(s.criterion, s.command, s.author) for s in self.engine._specs(st)]

    def test_a_replan_to_review_retires_the_items_builder_command(self):
        self.engine.store.put(IssueState(number=148, phase=Phase.PLAN, plan=plan("command"),
                                         commands=[A1, A2, PROBE]))
        with mock.patch.object(Engine, "_req"), mock.patch.object(Engine, "_set_phase"), \
                mock.patch("implement_loop.engine.scheduler.prerequisites_met", return_value=True):
            self.engine._step_plan(148)
        st = self.engine.store.issue(148)
        self.assertEqual(self.commands(st), [("A1", A1["command"], "builder"), ("A2", PROBE["command"], "examiner")])
        self.assertTrue(any("check-changed.sh" in f for f in st.feedback))

    def test_a_build_answer_cannot_bring_back_a_review_items_command(self):
        st = IssueState(number=148, plan=plan("review"), commands=[A1, A2])
        answer = BuildResult(status="done", commands=[CheckSpec(criterion="A2", command=A2["command"]),
                                                      CheckSpec(criterion="A1", command=A1["command"])])
        self.engine._absorb_build(st, answer)
        self.assertEqual([c[:2] for c in self.commands(st)], [("A1", A1["command"])])
        self.assertIn("A2 is proven by review", st.dropped[0])

    def test_a_revival_heals_a_state_saved_with_the_stale_command(self):
        st = IssueState(number=148, phase=Phase.FAILED, plan=plan("review"), worktree=str(self.tmp),
                        fail={"cause": "no_progress", "version": "1.0.6"}, commands=[A1, A2, PROBE])
        self.engine._maybe_revive(st)
        self.assertEqual(st.phase, Phase.BUILD)
        self.assertEqual(st.commands, [A1, PROBE])

    def test_the_engine_version_moves_past_the_one_148_failed_on(self):
        self.assertGreater(tuple(map(int, VERSION.split("."))), (1, 0, 6))


if __name__ == "__main__":
    unittest.main()

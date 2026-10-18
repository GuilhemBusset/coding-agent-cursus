"""Regressions from #48's ceiling (#103): a probe-based finding must close when its probe passes
under a command that names it from its cwd, and a recurring note must not reset the progress rule."""

import shutil
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the engine on sys.path)

from implement_loop import VERSION
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import IssueState, Phase
from implement_loop.state import RunStore

PROBE = "sessions/01-fundamentals/tests/test_examiner_48_cache.py"
COMMAND = "uv run --locked pytest -q tests/test_examiner_48_cache.py"   # as #48's examiner wrote it


class ProbeFindingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-loop-"))
        self.engine = Engine.__new__(Engine)
        self.engine.store = RunStore(self.tmp / "run")
        self.engine.caps = Caps()
        self.phases = []
        self.engine._set_phase = lambda n, phase, **kw: self.phases.append((phase, kw.get("feedback")))
        self.engine._fail = lambda n, cause, detail: self.phases.append((Phase.FAILED, cause))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def close(self, cwd, command=COMMAND):
        st = IssueState(number=48, findings=[{"id": "E48-1-1", "status": "open", "probe": PROBE}],
                        commands=[{"command": command, "cwd": cwd, "criterion": "D2", "author": "examiner"}])
        evidence = [{"command": command, "cwd": cwd, "passed": True}]
        return self.engine._close_findings(48, st, self.tmp, evidence)

    def test_a_probe_named_from_the_commands_cwd_closes_its_finding(self):
        self.assertEqual(self.close("sessions/01-fundamentals"), ["E48-1-1"])
        self.assertEqual(self.close(".", f"uv run pytest -q {PROBE}"), ["E48-1-1"])

    def test_a_command_that_does_not_run_the_probe_closes_nothing(self):
        self.assertEqual(self.close("."), [])
        self.assertEqual(self.close("sessions/01-fundamentals", "uv run pytest -q tests/test_other.py"), [])

    def test_a_recurring_note_does_not_reset_the_progress_rule(self):
        note = "These commands were not kept, so they did not run: [...]"
        failure = ["open finding E48-1-1 still reproduces: Qualify the blanket cache-invalidation advice"]
        for notes in ([note], [], [note]):
            self.engine._round_failed(48, failure, ["E48-1-1"], notes=notes)
        self.assertEqual(self.engine.store.issue(48).unproductive, 2)
        self.assertEqual(self.phases[0], (Phase.BUILD, [note] + failure), "the note still reaches the builder")
        self.assertEqual(self.phases[-1][0], Phase.PLAN, "two unchanged rounds bring a replan")

    def test_the_engine_version_moves_past_the_one_48_failed_on(self):
        self.assertGreater(tuple(map(int, VERSION.split("."))), (1, 0, 4))


if __name__ == "__main__":
    unittest.main()

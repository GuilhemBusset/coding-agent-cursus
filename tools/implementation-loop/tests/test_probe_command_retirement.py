"""Regressions from #50's ceiling (#116): an approved change that deletes an adopted probe retires
the examiner's command for it, and a revival heals a state saved with that command still in it."""

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

CWD = "sessions/01-fundamentals"
GONE = f"{CWD}/tests/test_examiner50_cli.py"     # the probe R50-2 deleted
KEPT = f"{CWD}/tests/test_examiner50_dates.py"   # a probe that stays
RENAMED = f"{CWD}/tests/probe_50_cli.py"         # the builder's own copy


def command(item, path, author):
    return {"criterion": item, "command": f"uv run --locked pytest -q {path[len(CWD) + 1:]}",
            "cwd": CWD, "author": author}


class Workspace:
    def commit_all(self, *args, **kwargs):
        return "sha"


class ProbeCommandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-loop-"))
        self.wt = self.tmp / "wt"
        for rel in (KEPT, RENAMED):
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text("def test_x():\n    pass\n")
        self.engine = Engine.__new__(Engine)
        self.engine.store = RunStore(self.tmp / "run")
        self.engine.caps, self.engine.ws, self.engine.repair, self.engine.other = Caps(), Workspace(), False, "codex"
        self.builder = [command("D1", RENAMED, "builder"), command("A1", KEPT, "builder")]
        self.kept = command("A1", KEPT, "examiner")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_approved_deletion_retires_the_examiners_command_for_its_probe(self):
        (self.wt / GONE).write_text("def test_cli():\n    pass\n")
        st = IssueState(number=50, probes=[GONE, KEPT], locked={GONE: "d", KEPT: "d"},
                        commands=self.builder + [command("D1", GONE, "examiner"), self.kept])
        request = {"id": "R50-2", "kind": "test_change", "paths": [GONE], "content": {GONE: None},
                   "detail": "rename the CLI probe", "reason": "CI has no claude or codex"}
        self.engine._apply_request(50, st, self.wt, request, {})
        self.assertFalse((self.wt / GONE).exists())
        self.assertEqual(st.commands, self.builder + [self.kept])
        self.assertFalse([s for s in self.engine._specs(st) if "test_examiner50_cli" in s.command])

    def test_a_revival_heals_a_state_saved_with_the_stale_command(self):
        stale = command("D1", GONE, "examiner")
        st = IssueState(number=50, phase=Phase.FAILED, plan={"items": []}, worktree=str(self.wt), probes=[KEPT],
                        fail={"cause": "ceiling", "version": "1.0.5"}, commands=self.builder + [stale, self.kept])
        self.engine._maybe_revive(st)
        self.assertEqual(st.commands, self.builder + [stale, self.kept])   # no approved deletion: it stays
        st.phase, st.fail = Phase.FAILED, {"cause": "ceiling", "version": "1.0.5"}
        st.requests = [{"id": "R50-2", "kind": "test_change", "status": "approved", "content": {GONE: None}}]
        self.engine._maybe_revive(st)
        self.assertEqual(st.phase, Phase.BUILD)
        self.assertEqual(st.commands, self.builder + [self.kept])

    def test_an_unrelated_approved_edit_keeps_a_module_probe(self):
        probe = {"criterion": "D1", "command": "python -m checks.probe_contract", "cwd": ".", "author": "examiner"}
        (self.wt / "checks").mkdir()
        (self.wt / "checks/other.py").write_text("# a check\n")
        st = IssueState(number=50, probes=["checks/probe_contract.py"], tests=["checks/other.py"],
                        commands=self.builder + [probe])
        self.engine._apply_request(50, st, self.wt, {"id": "R1", "kind": "test_change",
                                                     "content": {"checks/other.py": "# edited\n"}}, {})
        self.assertIn(probe, st.commands)

    def test_the_engine_version_moves_past_the_one_50_failed_on(self):
        self.assertGreater(tuple(map(int, VERSION.split("."))), (1, 0, 5))


if __name__ == "__main__":
    unittest.main()

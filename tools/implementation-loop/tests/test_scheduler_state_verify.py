import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from helpers import HAS_PYTEST, TempRepo, git

from implement_loop import scheduler, verify
from implement_loop.model import CheckSpec, IssueState, Phase
from implement_loop.state import LockHeld, RepoClaims, RunLock, RunStore


class SchedulerTests(unittest.TestCase):
    def test_overlap_is_prefix_aware(self):
        self.assertTrue(scheduler.overlaps("sessions/01/", "sessions/01/labs/a.html"))
        self.assertTrue(scheduler.overlaps("a/b.txt", "a/b.txt"))
        self.assertFalse(scheduler.overlaps("sessions/01", "sessions/010/x"))
        self.assertFalse(scheduler.overlaps("a/b.txt", "a/b.txt.bak"))

    def test_shared_files_serialize_but_session_readmes_do_not(self):
        self.assertTrue(scheduler.is_shared("README.md"))
        self.assertTrue(scheduler.is_shared(".github/workflows/ci.yml"))
        self.assertFalse(scheduler.is_shared("sessions/01-fundamentals/README.md"))
        self.assertTrue(scheduler.conflicts(["AGENTS.md", "x/a"], [["README.md", "y/b"]]))
        self.assertFalse(scheduler.conflicts(["x/a"], [["y/b"]]))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = RunStore(self.tmp / "run")

    def test_state_round_trips_and_events_are_sequenced(self):
        st = IssueState(number=7, phase=Phase.VERIFY, attempts=2, locked={"a": "b"})
        self.store.put(st)
        self.store.event("one", issue=7)
        self.store.event("two")
        again = RunStore(self.tmp / "run")
        self.assertEqual(again.issue(7).phase, Phase.VERIFY)
        self.assertEqual(again.issue(7).locked, {"a": "b"})
        self.assertEqual([e["seq"] for e in again.events()], [1, 2])
        again.event("three")
        self.assertEqual(again.events()[-1]["seq"], 3)

    def test_lock_blocks_a_live_holder_and_takes_over_a_dead_one(self):
        lock_path = self.tmp / "run" / "lock"
        with RunLock(lock_path):
            with self.assertRaises(LockHeld):
                RunLock(lock_path).__enter__()
        lock_path.write_text(json.dumps({"pid": 2 ** 22 + 12345, "host": socket.gethostname()}))
        with RunLock(lock_path):
            self.assertEqual(json.loads(lock_path.read_text())["pid"], os.getpid())
        self.assertFalse(lock_path.exists())

    def test_repo_claims_are_exclusive_per_resource(self):
        repo = TempRepo()
        try:
            claims = RepoClaims(repo.work)
            self.assertTrue(claims.acquire("merge-queue", "run-1"))
            self.assertTrue(claims.acquire("merge-queue", "run-1"))
            self.assertFalse(claims.acquire("merge-queue", "run-2"))
            claims.release("merge-queue", "run-1")
            self.assertTrue(claims.acquire("merge-queue", "run-2"))
        finally:
            repo.cleanup()


class LegacyStateTests(unittest.TestCase):
    def test_state_from_the_stop_and_ask_engine_reads_with_the_new_outcomes(self):
        stopped = IssueState.from_dict({"number": 21, "phase": "needs_human", "reason": "a design dispute"})
        self.assertEqual((stopped.phase, stopped.park_kind), (Phase.PARKED, "exhausted"))
        accepted = IssueState.from_dict({"number": 22, "phase": "accepted"})
        self.assertEqual((accepted.phase, accepted.park_kind), (Phase.DELIVERED, None))


class StopTests(unittest.TestCase):
    def test_only_a_stop_older_than_the_invocation_is_cleared(self):
        import time
        store = RunStore(Path(tempfile.mkdtemp()) / "run")
        (store.dir / "STOP").write_text("stop\n")
        self.assertFalse(store.clear_stop(older_than=time.time() - 60), "a stop asked after the run started stays")
        self.assertTrue(store.stop_requested())
        self.assertTrue(store.clear_stop(older_than=time.time() + 60))
        self.assertFalse(store.stop_requested())


class UncommittedTests(unittest.TestCase):
    def test_a_modified_file_listed_first_keeps_its_whole_path(self):
        # the porcelain line " M setup/package.json" was stripped and cut to "etup/package.json"
        from implement_loop.workspace import Workspace
        repo = TempRepo()
        try:
            wt = repo.work
            git("switch", "-q", "-c", "feat/x", cwd=wt)
            (wt / "setup").mkdir()
            (wt / "setup" / "package.json").write_text("{}\n")
            git("add", "-A", cwd=wt)
            git("commit", "-q", "-m", "seed", cwd=wt)
            (wt / "setup" / "package.json").write_text('{"x": 1}\n')
            (wt / "new file.txt").write_text("x\n")
            ws = Workspace(wt, 1, Path("ship.sh"), base_dir=repo.loop_dir)
            self.assertEqual(sorted(ws.uncommitted(wt)), ["new file.txt", "setup/package.json"])
        finally:
            repo.cleanup()


class ProvisionTests(unittest.TestCase):
    def test_worktrees_get_a_private_copy_of_the_browser_tooling(self):
        from implement_loop.workspace import Workspace
        repo = TempRepo()
        try:
            source = repo.work / "setup" / "node_modules" / "pkg"
            source.mkdir(parents=True)
            (source / "index.js").write_text("trusted\n")
            target = repo.tmp / "wt"
            (target / "setup").mkdir(parents=True)
            Workspace(repo.work, 1, Path("ship.sh"), base_dir=repo.tmp / "loop").provision(target)
            copied = target / "setup" / "node_modules" / "pkg" / "index.js"
            self.assertFalse((target / "setup" / "node_modules").is_symlink())
            copied.write_text("tampered\n")
            self.assertEqual((source / "index.js").read_text(), "trusted\n")
        finally:
            repo.cleanup()


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "checks").mkdir()
        (self.root / "checks" / "c.sh").write_text("test \"$(cat out.txt)\" = ok\n")
        (self.root / "out.txt").write_text("ok\n")
        self.work = self.root / ".work"

    def spec(self, cmd="bash checks/c.sh", **kw):
        return CheckSpec(criterion="A1", kind="command", command=cmd, **kw)

    def test_command_evidence_records_exit_and_head(self):
        ev, _ = verify.run_check(self.root, self.spec(), "abc123", self.work)
        self.assertTrue(ev.passed)
        self.assertEqual((ev.exit_code, ev.head_sha), (0, "abc123"))
        (self.root / "out.txt").write_text("no\n")
        ev, _ = verify.run_check(self.root, self.spec(), "abc123", self.work)
        self.assertFalse(ev.passed)

    def test_timeout_fails(self):
        ev, _ = verify.run_check(self.root, self.spec("sleep 5", timeout_s=1), "abc", self.work)
        self.assertFalse(ev.passed)
        self.assertIn("timed out", ev.output_tail)

    def test_missing_cwd_fails_cleanly(self):
        ev, _ = verify.run_check(self.root, self.spec(cwd="nope"), "abc", self.work)
        self.assertFalse(ev.passed)
        self.assertIn("does not exist", ev.output_tail)

    def test_tamper_report_catches_changes_deletions_and_new_config(self):
        locked = verify.lock(self.root, ["checks/c.sh"], ["."])
        self.assertEqual(verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."]), [])
        (self.root / "checks" / "c.sh").write_text("exit 0\n")
        (self.root / "checks" / "conftest.py").write_text("")
        problems = verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."])
        self.assertIn("locked file changed: checks/c.sh", problems)
        self.assertIn("new test configuration file: checks/conftest.py", problems)

    def test_pyproject_locks_only_the_pytest_section(self):
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n\n[tool.pytest.ini_options]\naddopts='-q'\n")
        locked = verify.lock(self.root, ["checks/c.sh"], ["."])
        self.assertIn("pyproject.toml", locked)
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=['numpy']\n\n[tool.pytest.ini_options]\naddopts='-q'\n")
        self.assertEqual(verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."]), [])
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n\n[tool.pytest.ini_options]\naddopts='-q -k nothing'\n")
        self.assertEqual(verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."]), ["locked file changed: pyproject.toml"])

    def test_a_new_pyproject_without_pytest_settings_is_fine(self):
        locked = verify.lock(self.root, ["checks/c.sh"], ["."])
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        self.assertEqual(verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."]), [])

    def test_a_commented_pytest_header_in_pyproject_is_still_locked(self):
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        locked = verify.lock(self.root, ["checks/c.sh"], ["."])
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n\n[tool.pytest.ini_options] # test configuration\naddopts='-k nothing'\n")
        self.assertEqual(verify.tamper_report(self.root, locked, ["checks/c.sh"], ["."]), ["locked file changed: pyproject.toml"])

    def test_tests_run_without_result_accounting_fail(self):
        (self.root / "checks" / "test_u.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n    @unittest.skip('later')\n    def test_a(self):\n        pass\n")
        files = ["checks/test_u.py"]
        locked = verify.lock(self.root, files, ["."])
        expected = verify.expected_tests(self.root, files)
        spec = CheckSpec("A1", "command", f"{sys.executable} -m unittest discover -s checks -p 'test_u.py'")
        ok, _, problems = verify.verify(self.root, [spec], "sha", self.work, locked, files, expected)
        self.assertFalse(ok)
        self.assertTrue(any("without pytest result accounting" in p for p in problems), problems)

    def test_conditionally_defined_tests_are_still_expected(self):
        (self.root / "checks" / "test_c.py").write_text("def test_good():\n    pass\n\nif True:\n    def test_required():\n        pass\n\ntry:\n    import json\nexcept ImportError:\n    pass\nelse:\n    class TestX:\n        def test_inner(self):\n            def test_nested_helper():\n                pass\n")
        self.assertEqual(verify.expected_tests(self.root, ["checks/test_c.py"]),
                         ["checks/test_c.py::TestX::test_inner", "checks/test_c.py::test_good", "checks/test_c.py::test_required"])

    def test_one_run_test_satisfies_only_one_expectation(self):
        expected = ["a/test_contract.py::test_contract", "b/test_contract.py::test_contract"]
        one_case = [(["test_contract"], "test_contract")]
        self.assertEqual(len(verify.unmatched(expected, one_case)), 1)
        two_cases = [(["a", "test_contract"], "test_contract"), (["b", "test_contract"], "test_contract")]
        self.assertEqual(verify.unmatched(expected, two_cases), [])
        self.assertEqual(verify.unmatched(["t/test_p.py::test_p"], [(["t", "test_p"], "test_p[1]"), (["t", "test_p"], "test_p[2]")]), [])

    def test_expected_tests_are_read_from_locked_files(self):
        (self.root / "checks" / "test_a.py").write_text("def test_one():\n    pass\n\nasync def test_two():\n    pass\n\ndef helper():\n    pass\n")
        self.assertEqual(verify.expected_tests(self.root, ["checks/test_a.py", "checks/c.sh"]),
                         ["checks/test_a.py::test_one", "checks/test_a.py::test_two"])
        (self.root / "checks" / "test_b.py").write_text("class TestGood:\n    def test_contract(self):\n        pass\n\nclass TestBad:\n    def test_contract(self):\n        pass\n")
        self.assertEqual(verify.expected_tests(self.root, ["checks/test_b.py"]),
                         ["checks/test_b.py::TestBad::test_contract", "checks/test_b.py::TestGood::test_contract"])


@unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
class PytestVerifyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "tests").mkdir()
        self.test_file = self.root / "tests" / "test_x.py"
        self.cmd = f"{sys.executable} -m pytest -q tests/test_x.py"

    def run_verify(self, body):
        self.test_file.write_text(textwrap.dedent(body))
        locked = verify.lock(self.root, ["tests/test_x.py"], ["."])
        expected = verify.expected_tests(self.root, ["tests/test_x.py"])
        return verify.verify(self.root, [CheckSpec("A1", "command", self.cmd)], "sha", self.root / ".w",
                             locked, ["tests/test_x.py"], expected)

    def test_passing_tests_pass(self):
        ok, evidence, problems = self.run_verify("def test_a():\n    assert True\n")
        self.assertTrue(ok, problems)
        self.assertEqual(evidence[0]["tests"]["passed"], 1)

    def test_a_skip_fails_verification(self):
        ok, _, problems = self.run_verify("import pytest\n\ndef test_a():\n    pytest.skip('later')\n")
        self.assertFalse(ok)
        self.assertTrue(any("unexpected skip" in p for p in problems))

    def test_pytest_wrapped_in_a_script_is_still_accounted(self):
        (self.root / "run.sh").write_text(f"{sys.executable} -m pytest -q tests/test_x.py\n")
        self.test_file.write_text("import pytest\n\ndef test_a():\n    pytest.skip('later')\n")
        locked = verify.lock(self.root, ["tests/test_x.py"], ["."])
        expected = verify.expected_tests(self.root, ["tests/test_x.py"])
        ok, _, problems = verify.verify(self.root, [CheckSpec("A1", "command", "bash run.sh")], "sha", self.root / ".w",
                                        locked, ["tests/test_x.py"], expected)
        self.assertFalse(ok)
        self.assertTrue(any("unexpected skip" in p for p in problems), problems)

    def test_failed_tests_fail_even_when_the_command_exits_zero(self):
        (self.root / "run.sh").write_text(f"{sys.executable} -m pytest -q tests/test_x.py; true\n")
        self.test_file.write_text("def test_a():\n    assert False\n")
        locked = verify.lock(self.root, ["tests/test_x.py"], ["."])
        expected = verify.expected_tests(self.root, ["tests/test_x.py"])
        ok, evidence, problems = verify.verify(self.root, [CheckSpec("A1", "command", "bash run.sh")], "sha", self.root / ".w",
                                               locked, ["tests/test_x.py"], expected)
        self.assertEqual(evidence[0]["exit_code"], 0)
        self.assertFalse(ok)
        self.assertTrue(any("failed tests" in p for p in problems), problems)

    def test_same_name_in_two_classes_counts_as_two_tests(self):
        self.test_file.write_text("class TestGood:\n    def test_contract(self):\n        assert True\n\nclass TestBad:\n    def test_contract(self):\n        assert False\n")
        locked = verify.lock(self.root, ["tests/test_x.py"], ["."])
        expected = verify.expected_tests(self.root, ["tests/test_x.py"])
        spec = CheckSpec("A1", "command", f"{self.cmd} -k TestGood")
        ok, _, problems = verify.verify(self.root, [spec], "sha", self.root / ".w", locked, ["tests/test_x.py"], expected)
        self.assertFalse(ok)
        self.assertTrue(any("TestBad::test_contract" in p for p in problems), problems)

    def test_a_test_that_does_not_run_fails_verification(self):
        self.test_file.write_text("def test_a():\n    assert True\n\ndef test_b():\n    assert True\n")
        locked = verify.lock(self.root, ["tests/test_x.py"], ["."])
        expected = verify.expected_tests(self.root, ["tests/test_x.py"])
        spec = CheckSpec("A1", "command", f"{self.cmd} -k test_a")
        ok, _, problems = verify.verify(self.root, [spec], "sha", self.root / ".w", locked, ["tests/test_x.py"], expected)
        self.assertFalse(ok)
        self.assertTrue(any("tests/test_x.py::test_b" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()

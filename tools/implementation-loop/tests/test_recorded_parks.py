"""Replays of the parks recorded between 2026-10-04 and 2026-10-16 (ADR 0012), in the shapes the
new engine meets them. Each test names the issue it comes from. None of them may end parked."""

import sys
import unittest
from pathlib import Path

from helpers import HAS_PYTEST, git
from test_engine import EngineCase

from implement_loop.agents import BuildResult, FakeAgents, Request
from implement_loop.model import CheckSpec, Phase


class Builder(FakeAgents):
    """FakeAgents whose builder can make typed requests or write Python tests."""

    def __init__(self, scripts, requests=None, python_test=None, ignore_feedback_rounds=0, **kw):
        super().__init__(scripts, **kw)
        self.extra_requests = requests or {}
        self.python_test = python_test
        self.ignore = ignore_feedback_rounds

    def plan(self, vendor, req, worktree):
        result = super().plan(vendor, req, worktree)
        if self.python_test and req.issue.number == self.python_test["issue"]:   # its test is in its zones
            result.zones = sorted(set(result.zones) | {self.python_test["file"]})
        return result

    def build(self, vendor, req, plan, worktree, feedback):
        n = req.issue.number
        k = self._built.get(n, 0)
        if self.ignore and k <= self.ignore:
            feedback = [f for f in feedback if "edge" not in f]
        result = super().build(vendor, req, plan, worktree, feedback)
        if k == 0 and n in self.extra_requests:
            result.requests = list(self.extra_requests[n])
        if self.python_test and n == self.python_test["issue"]:
            path = worktree / self.python_test["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.python_test["content"])
            result.tests = result.tests + [self.python_test["file"]]
            result.commands = result.commands + [CheckSpec(criterion="A1", command=self.python_test["command"])]
            if k >= 1 or self.python_test.get("disposition_first"):
                result.dispositions = dict(self.python_test.get("dispositions", {}))
        return result


class RecordedParks(EngineCase):
    def test_30_an_item_needing_an_api_key_is_delivered_with_the_agents_part(self):
        """#30 parked: the sampling recording needed ANTHROPIC_API_KEY, which no agent held."""
        self.policy = {"lacks": ["credentials:ANTHROPIC_API_KEY"]}
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "A recording made through the API is committed."])
        self.epic(2)
        agents = Builder(self.scripts, requests={2: [Request("reclassify", "the key-handling code and its test",
                                                              item="D2", capability="credentials:ANTHROPIC_API_KEY")]})
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        self.assertEqual(self.store.issue(2).obligations[0]["detail"], "credentials:ANTHROPIC_API_KEY")
        self.assertNotIn("- [x] A recording", self.gh.issues[2]["body"], "an owner item is never ticked by the loop")

    def test_41_an_undeclared_dependency_becomes_a_deferred_item(self):
        """#41 parked: its A2 needed widget #47, which no blocked-by link declared."""
        self.gh.add_issue(47, "Widget: agent-loop replay", "Doubles as the fallback player for the live demos.\n")
        self.add_work(2, "docs/a.txt", "alpha", items=["`docs/a.txt` contains `alpha`.",
                                                        "Each fallback plays in the replay widget."])
        self.epic(2)
        agents = Builder(self.scripts, requests={2: [Request("depends", "the replay widget is #47", item="D2",
                                                              depends_on=47, depends_quote="fallback player for the live demos")]})
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DELIVERED)
        ob = self.store.issue(2).obligations
        self.assertEqual((ob[0]["kind"], ob[0]["issue"]), ("deferred", 47))

    def test_42_78_a_replan_keeps_locked_tests_and_earlier_grants(self):
        """#24, #30, #40, #41, #42: a redesign deleted locked tests its commands still ran; #42 and
        #78: its file list dropped work the branch had kept. A replan does neither."""
        self.add_work(2, "docs/a.txt", "alpha", findings=1)
        self.epic(2)
        self.run_engine(agents=Builder(self.scripts, ignore_feedback_rounds=3))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(self.events("replan", 2), "the stalled rounds brought a replan")
        self.assertEqual(self.repo.main_file("checks/issue_2.sh").splitlines()[0], "#!/usr/bin/env bash",
                         "the locked test survived the replan")
        self.assertTrue(any(g["source"] == "earlier plan" for g in self.store.issue(2).grants))

    @unittest.skipUnless(HAS_PYTEST, "pytest is needed for the verifier's accounting")
    def test_37_a_test_only_the_owner_runs_needs_a_disposition_not_a_park(self):
        """#37 parked: a laptop benchmark in a check file that no command ran was 'expected'."""
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        content = ("def test_alpha():\n    assert open('docs/a.txt').read().strip() == 'alpha'\n\n"
                   "def test_laptop_benchmark():\n    assert False, 'run on a 2020 laptop'\n")
        agents = Builder(self.scripts, python_test={
            "issue": 2, "file": "tests/test_alpha.py", "content": content,
            "command": f"{sys.executable} -m pytest -q tests/test_alpha.py -k 'not laptop'",
            "dispositions": {"tests/test_alpha.py::test_laptop_benchmark": "owner-run"}})
        self.run_engine(agents=agents)
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertEqual(self.store.issue(2).dispositions, {"tests/test_alpha.py::test_laptop_benchmark": "owner-run"})


if __name__ == "__main__":
    unittest.main()


class ProbePathTests(EngineCase):
    def test_a_probe_cannot_write_outside_its_disposable_copy(self):
        """A returned probe whose path escapes (`..`, absolute, or through a symlink) is refused
        before anything is written."""
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)
        self.run_engine()
        victim = self.repo.tmp / "victim.txt"
        victim.write_text("locked\n")
        wt = self.repo.work
        for path in ("../victim.txt", str(victim), ""):
            self.assertIsNone(self.engine._reproduces(wt, "true", ".", (path, "overwritten\n")))
        self.assertEqual(victim.read_text(), "locked\n")
        self.assertTrue(self.events("probe_path_refused"))


class IsolationOfChecks(EngineCase):
    def test_a_check_command_cannot_touch_the_shared_repositorys_refs(self):
        """Check commands are agent-written: they run on a private git directory."""
        git("branch", "feat/other-run", cwd=self.repo.work)
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        class Hostile(Builder):
            def build(self, vendor, req, plan, worktree, feedback):
                result = super().build(vendor, req, plan, worktree, feedback)
                for c in result.commands:
                    c.command = "git update-ref -d refs/heads/feat/other-run; " + c.command
                return result
        self.run_engine(agents=Hostile(self.scripts))
        self.assertEqual(self.phase(2), Phase.DONE)
        self.assertTrue(git("branch", "--list", "feat/other-run", cwd=self.repo.work),
                        "another run's branch survives a check that deletes it")

    def test_a_test_path_that_leaves_the_worktree_is_refused(self):
        """A test file symlinked out of the worktree never becomes a locked test the engine writes."""
        outside = self.repo.tmp / "outside.txt"
        outside.write_text("keep\n")
        self.add_work(2, "docs/a.txt", "alpha")
        self.epic(2)

        class Linker(Builder):
            def build(self, vendor, req, plan, worktree, feedback):
                result = super().build(vendor, req, plan, worktree, feedback)
                link = worktree / "checks" / "escape.sh"
                if not link.is_symlink():
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(outside)
                result.tests = result.tests + ["checks/escape.sh", "../outside.txt"]
                return result
        self.run_engine(agents=Linker(self.scripts))
        self.assertEqual(outside.read_text(), "keep\n")
        refused = [p for e in self.events("test_paths_refused", 2) for p in e["paths"]]
        self.assertIn("checks/escape.sh", refused)
        self.assertNotIn("checks/escape.sh", self.store.issue(2).tests)


class FileHardeningTests(unittest.TestCase):
    def test_replace_file_never_writes_through_a_link(self):
        import os
        import tempfile
        from implement_loop.engine import Engine
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            victim = d / "victim.txt"
            victim.write_text("keep\n")
            (d / "wt").mkdir()
            os.symlink(victim, d / "wt" / "sym.sh")
            os.link(victim, d / "wt" / "hard.sh")
            Engine._replace_file(d / "wt" / "sym.sh", "new\n")
            Engine._replace_file(d / "wt" / "hard.sh", "new\n")
            self.assertEqual(victim.read_text(), "keep\n")
            self.assertEqual((d / "wt" / "sym.sh").read_text(), "new\n")
            self.assertFalse((d / "wt" / "sym.sh").is_symlink())

    def test_git_metadata_and_escapes_are_never_inside(self):
        import tempfile
        from implement_loop.engine import Engine
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in (".git", "a/.git/config", "../x", "/etc/passwd", ""):
                self.assertFalse(Engine._inside(root, rel), rel)
            self.assertTrue(Engine._inside(root, "checks/probe.sh"))

    def test_a_check_directory_outside_the_tree_is_refused(self):
        import tempfile
        from implement_loop import verify
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "tree"
            root.mkdir()
            spec = CheckSpec(criterion="A1", command="true", cwd="..")
            ev, _ = verify.run_check(root, spec, "0" * 40, Path(d) / "work")
            self.assertFalse(ev.passed)
            self.assertIn("leaves the tree", ev.note or ev.output_tail)

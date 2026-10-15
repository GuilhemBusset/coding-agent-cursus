"""Acceptance checks for #74: real conflicts, recovery and exact-head landing.

Only GitHub and the workers are scripted. Each engine uses real worktrees, the
repository's ship script, the verifier and squash merges into a local bare remote.
The old-release recovery fixture deliberately reproduces its missing land sync
and its non-aborting push; it does not replace the new recovery code.
"""

from dataclasses import replace
from pathlib import Path
import subprocess
import threading
import unittest
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body
import implement_loop
from implement_loop.agents import FakeAgents, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine, MERGE_QUEUE
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.model import Phase
from implement_loop.state import RunStore
from implement_loop import workspace


def git_result(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def operation_paths(path):
    """Use worktree-local metadata, never the shared repository's .git paths."""
    found = []
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD"):
        candidate = Path(git("rev-parse", "--git-path", name, cwd=path))
        if not candidate.is_absolute():
            candidate = path / candidate
        if candidate.exists():
            found.append(name)
    return found


def has_markers(text):
    return any(line.startswith(("<<<<<<< ", ">>>>>>> ")) for line in text.splitlines())


class ObservedAgents(FakeAgents):
    """Observe worker boundaries and inject other *engine runs*, not resolutions."""

    def __init__(self, case, **kwargs):
        super().__init__(case.scripts, **kwargs)
        self.case = case
        self.entries = []
        self.lanes = []
        self.review_heads = []
        self.before_implement = None
        self.after_implement = None
        self.on_cross_review = None
        self.omit_from_design = set()
        self.preserve_check = None
        self._observe_lock = threading.Lock()

    def propose(self, vendor, req, author):
        proposal = super().propose(vendor, req, author)
        return replace(proposal, files=[f for f in proposal.files if f not in self.omit_from_design])

    def write_checks(self, vendor, req, design, worktree, feedback=None):
        conflicted = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
        self.lanes.append({"vendor": vendor, "issue": req.issue.number,
                           "files": list(design.check_files), "conflicted": conflicted,
                           "feedback": list(feedback or [])})
        if not conflicted:
            self.case.assert_no_operation(worktree)
        if self.preserve_check and self.preserve_check in design.check_files and not conflicted:
            # This fixture's acceptance check is already in the seed repository.
            self.calls.append(("write_checks", vendor, req.issue.number, tuple(feedback or ())))
            return
        return super().write_checks(vendor, req, design, worktree, feedback)

    def implement(self, vendor, req, design, worktree, feedback):
        entry = {"issue": req.issue.number, "vendor": vendor, "worktree": worktree,
                 "feedback": list(feedback), "head": git("rev-parse", "HEAD", cwd=worktree),
                 "main": git("rev-parse", "origin/main", cwd=worktree),
                 "operations": operation_paths(worktree),
                 "contents": {f: (worktree / f).read_text() for f in self.case.shared_paths
                              if (worktree / f).exists()}}
        self.entries.append(entry)
        if self.before_implement:
            self.before_implement(req, design, worktree, entry)
        result = super().implement(vendor, req, design, worktree, feedback)
        if self.after_implement:
            self.after_implement(req, design, worktree, entry)
        return result

    def review(self, vendor, role, req, design, worktree, base_sha, head_sha, evidence):
        self.case.assert_no_operation(worktree)
        self.case.assertEqual(git("rev-parse", "HEAD", cwd=worktree), head_sha)
        with self._observe_lock:
            self.review_heads.append((req.issue.number, role, head_sha))
        result = super().review(vendor, role, req, design, worktree, base_sha, head_sha, evidence)
        if role == "cross" and self.on_cross_review:
            self.on_cross_review(req, worktree, head_sha)
        return result

    def verify_finding(self, vendor, req, worktree, finding):
        self.case.assert_no_operation(worktree)
        return super().verify_finding(vendor, req, worktree, finding)


class LandConflictTests(unittest.TestCase):
    def setUp(self):
        self.new_fixture()

    def new_fixture(self):
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        for key, value in (("merge.conflictStyle", "merge"), ("rerere.enabled", "false"),
                           ("rebase.backend", "merge"), ("core.autocrlf", "false")):
            git("config", key, value, cwd=self.repo.work)
        self.gh = FakeGitHub(on_merge=self.merge_published_head)
        self.scripts = {}
        self.shared_paths = ["shared/suites.txt"]
        self.seed_main({self.shared_paths[0]: "base-suite\n"})
        self.engine = None
        self.peer = None
        self.boundary_errors = []

    def merge_published_head(self, branch, sha):
        self.assertEqual(git("rev-parse", f"refs/heads/{branch}", cwd=self.repo.remote), sha,
                         "GitHub must merge the published branch's actual head")
        return self.repo.merge(branch, sha)

    def seed_main(self, files):
        """A local fixture publisher, used only against TempRepo's bare remote."""
        git("fetch", "-q", "origin", cwd=self.repo.merger)
        git("checkout", "-q", "-B", "main", "origin/main", cwd=self.repo.merger)
        for rel, content in files.items():
            target = self.repo.merger / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        git("add", "-A", cwd=self.repo.merger)
        git("commit", "-qm", "fixture: move main", cwd=self.repo.merger)
        git("push", "-q", "origin", "HEAD:main", cwd=self.repo.merger)
        return git("rev-parse", "HEAD", cwd=self.repo.merger)

    def add_issue(self, n, *, lines=None, **options):
        lines = lines if lines is not None else {self.shared_paths[0]: f"suite-for-{n}"}
        files = {f"docs/issue-{n}.txt": f"content-{n}"}
        self.scripts[n] = Script(files=files, lines=lines, **options)
        self.gh.add_issue(n, f"Widget {n}", issue_body(f"feat/issue-{n}",
                          ["Keep this widget's content and shared suite registration."],
                          ["All acceptance checks pass."]), labels=("size:M",))

    def setup_pair(self, *, locked=False):
        options = {"check_file": "checks/shared.sh"} if locked else {}
        self.add_issue(2, **options)
        self.add_issue(3, conflict_tamper=locked, **options)
        self.gh.add_issue(1, "Stale widget epic", "Epic.\n", subs=(3,))
        self.gh.add_issue(10, "First widget epic", "Epic.\n", subs=(2,))

    def make_engine(self, root=1, agents=None, caps=None):
        agents = agents or ObservedAgents(self)
        plan = build_plan(self.gh, root, self.repo.work)
        store = RunStore.for_root(self.repo.work, root)
        ws = workspace.Workspace(self.repo.work, root, SHIP,
                                 base_dir=self.repo.loop_dir / f"run-{root}")
        engine = Engine(plan, store, self.gh, ws, agents,
                        Config(repo="test/test", caps=caps or Caps(ci_poll_s=0)),
                        repo_root=self.repo.work, log=lambda m: None, sleep=lambda s: None)
        return engine

    def run_engine(self, agents=None, caps=None):
        self.engine = self.make_engine(agents=agents, caps=caps)
        self.engine.run()
        return self.engine

    def events(self, kind=None, n=3):
        return [e for e in self.engine.store.events()
                if (kind is None or e["kind"] == kind) and (n is None or e.get("issue") == n)]

    def assert_no_operation(self, path, *, clean=False):
        self.assertEqual(operation_paths(path), [], f"unfinished operation in {path}")
        if clean:
            self.assertEqual(git("status", "--porcelain", cwd=path), "")

    def assert_between_steps(self, engine, original, n, phase, **kwargs):
        result = original(engine, n, phase, **kwargs)
        st = engine.store.issue(n)
        if st.worktree and Path(st.worktree).exists():
            try:
                self.assert_no_operation(Path(st.worktree), clean=True)
            except AssertionError as exc:
                self.boundary_errors.append(str(exc))
        return result

    def install_peer_hook(self, agents, *, move_again=False):
        seen = []

        def during_review(req, wt, head):
            if req.issue.number != 3:
                return
            seen.append(head)
            if len(seen) == 1:
                self.peer = self.make_engine(root=10)
                self.peer.run()
                self.assertEqual(self.peer.store.issue(2).phase, Phase.DONE)
            elif len(seen) == 2 and move_again:
                self.seed_main({"docs/later-main.txt": "another main change\n"})

        agents.on_cross_review = during_review
        return seen

    def conflict_scenario(self, *, move_again=False, locked=False, caps=None):
        self.setup_pair(locked=locked)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents, move_again=move_again)
        original = Engine._set_phase

        def boundary(engine, n, phase, **kwargs):
            return self.assert_between_steps(engine, original, n, phase, **kwargs)

        with mock.patch.object(Engine, "_set_phase", boundary):
            self.run_engine(agents, caps)
        self.assertEqual(self.boundary_errors, [])
        return agents

    def assert_success(self, *, path=None, after_seq=0):
        st = self.engine.store.issue(3)
        self.assertEqual(st.phase, Phase.DONE, self.events())
        self.assertFalse([e for e in self.events("step_crashed") if e["seq"] > after_seq])
        self.assertFalse([e for e in self.events("parked") if e["seq"] > after_seq])
        path = path or self.shared_paths[0]
        for content in (self.repo.main_file(path), git("show", f"{st.reviewed_sha}:{path}", cwd=self.repo.work)):
            self.assertIsNotNone(content)
            self.assertFalse(has_markers(content))
            for n in (2, 3):
                self.assertIn(self.scripts[n].lines[path], content.splitlines())
        self.assert_exact_gates(self.engine)
        if self.peer:
            self.assert_exact_gates(self.peer)

    def assert_exact_gates(self, engine):
        events = engine.store.events()
        merged = [e for e in events if e["kind"] == "merged"]
        self.assertTrue(merged, events)
        calls = {(c[1], c[2]) for c in self.gh.calls if c[0] == "merge_pr"}
        for event in merged:
            n, head = event["issue"], event["head"]
            self.assertIn((event["pr"], head), calls)
            self.assertEqual(self.gh.prs[event["pr"]]["head"]["sha"], head)
            barriers = [e["seq"] for e in events if e.get("issue") == n
                        and e["kind"] in ("conflict", "updated_from_main") and e["seq"] < event["seq"]]
            barrier = max(barriers, default=0)
            gate_seq = {}
            for kind in ("verified", "reviewed"):
                matching = [e for e in events if e.get("issue") == n and e["kind"] == kind
                            and e.get("head") == head and barrier < e["seq"] < event["seq"]
                            and (kind != "verified" or e.get("ok") is True)]
                self.assertTrue(matching, f"{kind} missing on merged head {head}: {events}")
                gate_seq[kind] = min(e["seq"] for e in matching)
            self.assertLess(gate_seq["verified"], gate_seq["reviewed"])
            earlier = [e["head"] for e in events if e.get("issue") == n and e["kind"] == "reviewed"
                       and e["seq"] < barrier]
            self.assertNotIn(head, earlier)
            self.assertEqual(engine.store.issue(n).verified_sha, head)
            self.assertEqual(engine.store.issue(n).reviewed_sha, head)
            observed = engine.agents.review_heads
            for role in ("cross", "acceptance"):
                self.assertIn((n, role, head), observed)

    def test_same_line_conflict_goes_back_to_implement_and_merges(self):
        agents = self.conflict_scenario()
        self.assert_success()
        conflicts = self.events("conflict")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["phase"], "land")
        self.assertIn("shared/suites.txt", conflicts[0]["files"])
        self.assertEqual(conflicts[0]["fix_round"], 1)
        self.assertEqual(self.engine.store.issue(3).fix_rounds, 1)
        entries = [e for e in agents.entries if e["issue"] == 3]
        self.assertEqual(len(entries), 2)
        self.assertIn("shared/suites.txt", "\n".join(entries[1]["feedback"]))
        self.assertIn("MERGE_HEAD", entries[1]["operations"])
        self.assertTrue(has_markers(entries[1]["contents"]["shared/suites.txt"]))
        reviewed = self.events("reviewed")
        self.assertNotEqual(reviewed[0]["head"], reviewed[-1]["head"])
        self.assertLess(reviewed[0]["seq"], conflicts[0]["seq"])
        self.assertLess(conflicts[0]["seq"], reviewed[-1]["seq"])

    def test_same_line_conflict_with_multiple_files_and_different_requirements(self):
        extra = "shared/another-list.txt"
        self.seed_main({extra: "another-base\n"})
        self.shared_paths.append(extra)
        self.setup_pair()
        self.scripts[2].lines[extra] = "renderer-for-first-widget"
        self.scripts[3].lines[extra] = "parser-for-second-widget"
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        self.run_engine(agents)
        for path in self.shared_paths:
            self.assert_success(path=path)
        conflicts = self.events("conflict")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(set(conflicts[0]["files"]), set(self.shared_paths))
        repair = [e for e in agents.entries if e["issue"] == 3][-1]
        for path in self.shared_paths:
            self.assertIn(path, "\n".join(repair["feedback"]))
        self.assertEqual(self.engine.store.issue(3).fix_rounds, 1)

    def test_main_moves_again_before_land(self):
        self.conflict_scenario(move_again=True)
        self.assert_success()
        self.assertEqual(self.repo.main_file("docs/later-main.txt"), "another main change")
        self.assertEqual(len(self.events("conflict")), 1)
        updates = self.events("updated_from_main")
        self.assertTrue(any(e.get("phase") == "land" for e in updates))
        self.assertGreaterEqual(len(self.events("reviewed")), 3)
        self.assertEqual(self.engine.store.issue(3).fix_rounds, 1)
        self.assertLessEqual(self.engine.store.issue(3).fix_rounds, self.engine.caps.fix_rounds)

    def test_merged_head_is_the_exact_verified_and_reviewed_head(self):
        # Both repair and a clean sync after repair must invalidate old evidence.
        for move_again in (False, True):
            with self.subTest(move_again=move_again):
                if move_again:
                    self.repo.cleanup()
                    self.new_fixture()
                self.conflict_scenario(move_again=move_again)
                self.assert_success()
                self.assertTrue(self.events("conflict"))
                if move_again:
                    self.assertTrue(self.events("updated_from_main"))

    def test_no_operation_left_between_steps(self):
        self.conflict_scenario(move_again=True)
        self.assert_success()
        for engine in (self.engine, self.peer):
            for n in engine.plan.work:
                st = engine.store.issue(n)
                if st.worktree and Path(st.worktree).exists():
                    self.assert_no_operation(Path(st.worktree), clean=True)
            self.assert_no_operation(engine.ws.coord_path(), clean=True)

    def test_no_operation_left_between_steps_after_agent_stopped_mid_resolution(self):
        self.setup_pair()
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        interrupted = []

        def stop_with_markers(req, design, wt, entry):
            if entry["operations"] and not interrupted:
                interrupted.append(True)
                self.assertIn("MERGE_HEAD", entry["operations"])
                self.assertTrue(has_markers(entry["contents"][self.shared_paths[0]]))
                (self.engine.store.dir / "STOP").write_text("stop during conflict repair\n")
                raise type("AgentStopped", (RuntimeError,), {})("interrupted repair")

        agents.before_implement = stop_with_markers
        self.run_engine(agents)
        self.assertTrue(interrupted)
        self.assertTrue(self.events("step_interrupted"))
        self.assertFalse(self.events("step_crashed"))
        st = self.engine.store.issue(3)
        self.assertEqual(st.phase, Phase.IMPLEMENT)
        self.assert_no_operation(Path(st.worktree), clean=True)
        self.run_engine(agents)
        self.assert_success()
        self.assertLessEqual(self.engine.store.issue(3).fix_rounds, self.engine.caps.fix_rounds)

    def test_same_line_conflict_unresolved_markers_are_bounded_and_aborted(self):
        self.setup_pair()
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)

        def leave_markers(req, design, wt, entry):
            if "MERGE_HEAD" in entry["operations"]:
                # A worker claiming done is insufficient: keep its original
                # conflict markers and require the engine to reject the result.
                (wt / self.shared_paths[0]).write_text(entry["contents"][self.shared_paths[0]])

        agents.after_implement = leave_markers
        self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertTrue(self.events("conflict_unresolved"))
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"), self.events())
        self.assertFalse(self.events("step_crashed"))
        self.assertFalse(self.events("merged"))
        self.assertTrue(self.events("redesign"))
        self.assert_no_operation(Path(st.worktree), clean=True)
        self.assertLessEqual(len(agents.entries), 2 * (self.engine.caps.fix_rounds + 1) + 1)

    def test_conflicts_beyond_the_fix_rounds_never_park_as_an_engine_fault(self):
        self.conflict_scenario(caps=Caps(ci_poll_s=0, fix_rounds=0))
        st = self.engine.store.issue(3)
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"), self.events())
        self.assertTrue(self.events("redesign"))
        self.assertTrue(self.events("conflict"))
        self.assertFalse(self.events("step_crashed"))
        self.assertTrue(all(e["park_kind"] != "engine_error" for e in self.events("parked")))
        self.assert_no_operation(Path(st.worktree), clean=True)

    def test_locked_check_conflict_is_resolved_by_the_check_author(self):
        agents = self.conflict_scenario(locked=True)
        self.assert_success()
        lane = "checks/shared.sh"
        resolutions = [e for e in agents.lanes if e["issue"] == 3 and lane in e["conflicted"]]
        self.assertTrue(resolutions, agents.lanes)
        self.assertTrue(all(e["vendor"] == agents.other for e in resolutions))
        self.assertTrue(all(e["files"] == [lane] for e in resolutions))
        self.assertTrue(all(lane in "\n".join(e["feedback"]) for e in resolutions))
        reverted = self.events("locked_changes_reverted")
        self.assertTrue(any(lane in e["files"] for e in reverted))
        relocked = self.events("checks_relocked")
        self.assertTrue(any(lane in e["files"] and e["source"] == "check-author" for e in relocked))
        self.assertEqual(self.engine.store.issue(3).check_amendments, 0)
        final = self.repo.main_file(lane)
        self.assertFalse(has_markers(final))
        for n in (2, 3):
            self.assertIn(f"docs/issue-{n}.txt", final)
        # Retaining main's check requirements is observable, not just a relock event.
        coord = self.engine.ws.coord_path()
        self.assertEqual(subprocess.run(["bash", lane], cwd=coord, capture_output=True).returncode, 0)
        for n in (2, 3):
            target = coord / f"docs/issue-{n}.txt"
            original = target.read_bytes()
            try:
                target.write_text("broken\n")
                self.assertNotEqual(subprocess.run(["bash", lane], cwd=coord, capture_output=True).returncode, 0)
            finally:
                target.write_bytes(original)

    def test_locked_check_conflict_restores_check_author_edits_outside_its_lane(self):
        self.setup_pair(locked=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_write = agents.write_checks
        attempted = []
        before_author = []
        restored = []

        def stray_edit(vendor, req, design, wt, feedback=None):
            was_conflicted = "checks/shared.sh" in git(
                "diff", "--name-only", "--diff-filter=U", cwd=wt).splitlines()
            if was_conflicted:
                before_author.append((wt / self.shared_paths[0]).read_bytes())
            result = real_write(vendor, req, design, wt, feedback)
            if was_conflicted:
                attempted.append(True)
                # This is outside the check author's lane, and restoring HEAD
                # here would lose the conflict's main-side registration.
                (wt / self.shared_paths[0]).write_text("out-of-lane replacement\n")
            return result

        def observe_restoration(req, design, wt, entry):
            if before_author and "MERGE_HEAD" in entry["operations"]:
                self.assertEqual((wt / self.shared_paths[0]).read_bytes(), before_author[-1])
                restored.append(True)

        agents.write_checks = stray_edit
        agents.before_implement = observe_restoration
        self.run_engine(agents)
        self.assertTrue(attempted)
        self.assertTrue(restored)
        self.assert_success()

    def test_locked_check_conflict_unresolved_markers_never_reach_the_implementer(self):
        self.setup_pair(locked=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_write = agents.write_checks

        def leave_locked_markers(vendor, req, design, wt, feedback=None):
            lane = wt / "checks/shared.sh"
            if lane.exists() and has_markers(lane.read_text()):
                return  # An unsuccessful author leaves the merge unresolvable.
            return real_write(vendor, req, design, wt, feedback)

        def observe_implement(req, design, wt, entry):
            self.assertFalse(has_markers((wt / "checks/shared.sh").read_text()))

        agents.write_checks = leave_locked_markers
        agents.before_implement = observe_implement
        self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertTrue(self.events("check_conflict_unresolved"))
        self.assertEqual((st.phase, st.park_kind), (Phase.PARKED, "exhausted"), self.events())
        self.assertFalse(self.events("step_crashed"))
        self.assertFalse(self.events("merged"))
        self.assert_no_operation(Path(st.worktree), clean=True)

    def test_conflict_scope_allows_a_conflicted_path_outside_the_design(self):
        # A differently named shared file prevents a suites.txt-only workaround.
        path = "shared/alternate-registry.txt"
        self.seed_main({path: "other-base\n"})
        self.shared_paths = [path]
        self.setup_pair()
        self.scripts[2].lines[path] = "different-first-registration"
        self.scripts[3].lines[path] = "different-second-registration"
        agents = ObservedAgents(self)
        # The stale branch was verified with its original scope. Model a narrowed
        # current design at the next boundary, before main introduces the conflict.
        # Otherwise the original edit would fail verification before reaching land.
        self.install_peer_hook(agents)
        peer_hook = agents.on_cross_review
        narrowed = []

        def narrow_then_land_peer(req, wt, head):
            if req.issue.number == 3 and not narrowed:
                narrowed.append(True)
                st = self.engine.store.issue(3)
                st.design["files"].remove(path)
                self.engine.store.put(st)
                self.engine.plan.specs[3].declared_paths.remove(path)
            peer_hook(req, wt, head)

        agents.on_cross_review = narrow_then_land_peer
        original = Engine._step_implement
        stopped = []

        def stop_after_conflict(engine, n):
            if n == 3 and engine.store.issue(n).conflict_pending and not stopped:
                stopped.append(True)
                (engine.store.dir / "STOP").write_text("stop after conflict scope was persisted\n")
                raise type("AgentStopped", (RuntimeError,), {})("pause repair fixture")
            return original(engine, n)

        with mock.patch.object(Engine, "_step_implement", stop_after_conflict):
            self.run_engine(agents)
        self.assertTrue(stopped)
        self.assertEqual(self.engine.store.issue(3).phase, Phase.IMPLEMENT)
        self.assert_no_operation(Path(self.engine.store.issue(3).worktree), clean=True)
        # A fresh plan must recover the conflict permission from persisted state,
        # not merely retain a mutation of the first run's in-memory declared paths.
        self.run_engine(agents)
        self.assert_success(path=path)
        st = self.engine.store.issue(3)
        self.assertNotIn(path, st.design["files"])
        self.assertIn(path, st.conflict_paths)
        self.assertIn(path, self.engine.plan.specs[3].declared_paths)
        self.assertFalse(st.conflict_pending)
        self.assertTrue(any(path in e["files"] for e in self.events("conflict")))

    def test_each_implement_round_starts_from_current_main(self):
        for conflicting in (False, True):
            with self.subTest(conflicting=conflicting):
                # Separate run stores/branches and repositories for the two cases.
                if conflicting:
                    self.repo.cleanup()
                    self.new_fixture()
                self.setup_pair()
                self.scripts[3].wrong_attempts = 1
                agents = ObservedAgents(self)
                moved = []

                def move_main(req, design, wt, entry):
                    if req.issue.number == 3 and not moved:
                        moved.append(True)
                        if conflicting:
                            self.peer = self.make_engine(root=10)
                            self.peer.run()
                            self.assertEqual(self.peer.store.issue(2).phase, Phase.DONE)
                        else:
                            self.seed_main({"docs/main-round-one.txt": "arrived during round one\n"})

                agents.after_implement = move_main
                self.run_engine(agents)
                self.assertEqual(self.engine.store.issue(3).phase, Phase.DONE, self.events())
                entries = [e for e in agents.entries if e["issue"] == 3]
                self.assertEqual(len(entries), 2)
                if conflicting:
                    self.assert_success()
                    self.assertTrue(has_markers(entries[1]["contents"][self.shared_paths[0]]))
                    self.assertIn(self.shared_paths[0], "\n".join(entries[1]["feedback"]))
                    conflicts = self.events("conflict")
                    self.assertEqual(len(conflicts), 1)
                    self.assertEqual(conflicts[0]["phase"], "implement")
                    self.assertEqual(self.engine.store.issue(3).fix_rounds, 1)
                else:
                    second = entries[1]
                    self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor",
                                                second["main"], second["head"]).returncode, 0)
                    self.assertEqual(git("show", f"{second['head']}:docs/main-round-one.txt",
                                         cwd=self.repo.work), "arrived during round one")
                    self.assertTrue(self.events("updated_from_main"))
                    self.assertFalse(self.events("conflict"))
                    self.assert_exact_gates(self.engine)

    def test_main_changes_a_locked_file_without_conflict(self):
        lane = "checks/stable.sh"
        original_check = '#!/usr/bin/env bash\nset -eu\n# baseline metadata\ntest "$(cat docs/issue-3.txt)" = "content-3"\n'
        self.seed_main({lane: original_check})
        self.add_issue(3, lines={}, check_file=lane, wrong_attempts=1)
        self.gh.add_issue(1, "Epic", "Epic.\n", subs=(3,))
        agents = ObservedAgents(self)
        agents.preserve_check = lane
        moved = []

        def update_check(req, design, wt, entry):
            if not moved:
                moved.append(True)
                self.seed_main({lane: original_check.replace("baseline metadata", "metadata from main")})

        agents.after_implement = update_check
        self.run_engine(agents)
        self.assertEqual(self.engine.store.issue(3).phase, Phase.DONE, self.events())
        self.assertFalse(self.events("conflict"))
        self.assertTrue(any(lane in e["files"] and e["source"] == "main"
                            for e in self.events("checks_relocked")))
        self.assertIn("metadata from main", self.repo.main_file(lane))
        self.assert_exact_gates(self.engine)

    def test_each_implement_round_starts_from_current_main_update_preserves_commits(self):
        ws = workspace.Workspace(self.repo.work, 1, SHIP, base_dir=self.repo.loop_dir)
        wt = ws.issue_worktree(3, "feat/update-contract")
        initial = git("rev-parse", "HEAD", cwd=wt)
        current = ws.update(wt)
        self.assertEqual(current.status, "current")
        self.assertEqual(list(current.files), [])
        self.assertEqual(current.before, initial)
        (wt / "branch-only.txt").write_text("keep the issue commit\n")
        git("add", "-A", cwd=wt)
        git("commit", "-qm", "issue implementation", cwd=wt)
        implemented = git("rev-parse", "HEAD", cwd=wt)
        main = self.seed_main({"main-only.txt": "new main content\n"})
        merged = ws.update(wt)
        self.assertEqual((merged.status, merged.before, merged.main), ("merged", implemented, main))
        for sha in (implemented, main):
            self.assertEqual(git_result(wt, "merge-base", "--is-ancestor", sha, "HEAD").returncode, 0)
        self.assertEqual((wt / "branch-only.txt").read_text(), "keep the issue commit\n")
        self.assertEqual((wt / "main-only.txt").read_text(), "new main content\n")
        self.assert_no_operation(wt, clean=True)
        head = git("rev-parse", "HEAD", cwd=wt)
        self.assertEqual(ws.update(wt).status, "current")
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt), head)

    def test_no_operation_left_between_steps_merge_with_no_tree_diff_is_committed(self):
        ws = workspace.Workspace(self.repo.work, 1, SHIP, base_dir=self.repo.loop_dir)
        wt = ws.issue_worktree(3, "feat/empty-tree-merge")
        path = self.shared_paths[0]
        (wt / path).write_text("branch version\n")
        git("add", "-A", cwd=wt)
        git("commit", "-qm", "issue implementation", cwd=wt)
        before = git("rev-parse", "HEAD", cwd=wt)
        main = self.seed_main({path: "main version\n"})
        result = ws.update(wt)
        self.assertEqual(result.status, "conflict")
        self.assertEqual(list(result.files), [path])
        self.assertIn("MERGE_HEAD", operation_paths(wt))
        # A valid resolution can choose a tree identical to the issue's HEAD.
        (wt / path).write_text("branch version\n")
        git("add", "-A", cwd=wt)
        self.assertEqual(git("diff", "--cached", "--name-only", cwd=wt), "")
        committed = ws.commit_all(wt, "conclude resolved merge", "implementation", 3)
        self.assertIsNotNone(committed)
        self.assertNotEqual(committed, before)
        for parent in (before, main):
            self.assertEqual(git_result(wt, "merge-base", "--is-ancestor", parent, committed).returncode, 0)
        self.assert_no_operation(wt, clean=True)

    def test_a_failed_push_aborts_the_rebase_and_names_the_conflicted_files(self):
        ws = workspace.Workspace(self.repo.work, 1, SHIP, base_dir=self.repo.loop_dir)
        wt = ws.issue_worktree(3, "feat/unpublished-conflict")
        # Spaces and a Unicode character exercise NUL-delimited path reporting.
        paths = ["shared/suites.txt", "shared/list with spaces-λ.txt"]
        extra = wt / paths[1]
        extra.write_text("branch-side\n")
        (wt / paths[0]).write_text("branch-side\n")
        git("add", "-A", cwd=wt)
        git("commit", "-qm", "branch edit", cwd=wt)
        before = git("rev-parse", "HEAD", cwd=wt)
        self.seed_main({p: "main-side\n" for p in paths})
        self.assertTrue(hasattr(workspace, "MergeConflict"), "Workspace.push needs a typed recoverable conflict")
        with self.assertRaises(workspace.MergeConflict) as caught:
            ws.push(wt)
        self.assertIsInstance(caught.exception, workspace.GitError)
        self.assertEqual(set(caught.exception.files), set(paths))
        self.assert_no_operation(wt, clean=True)
        self.assertEqual(git("symbolic-ref", "--short", "HEAD", cwd=wt), "feat/unpublished-conflict")
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt), before)
        for path in paths:
            self.assertEqual((wt / path).read_text(), "branch-side\n")

    def test_a_failed_push_aborts_a_published_merge_and_names_the_conflicted_files(self):
        ws = workspace.Workspace(self.repo.work, 1, SHIP, base_dir=self.repo.loop_dir)
        wt = ws.issue_worktree(3, "feat/published-conflict")
        path = self.shared_paths[0]
        (wt / path).write_text("published branch version\n")
        git("add", "-A", cwd=wt)
        git("commit", "-qm", "publish implementation", cwd=wt)
        before = git("rev-parse", "HEAD", cwd=wt)
        self.assertEqual(ws.push(wt), before)
        self.seed_main({path: "later main version\n"})
        self.assertTrue(hasattr(workspace, "MergeConflict"))
        with self.assertRaises(workspace.MergeConflict) as caught:
            ws.push(wt)
        self.assertEqual(list(caught.exception.files), [path])
        self.assert_no_operation(wt, clean=True)
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt), before)
        self.assertEqual(git("rev-parse", "origin/feat/published-conflict", cwd=wt), before)
        self.assertEqual(git("symbolic-ref", "--short", "HEAD", cwd=wt), "feat/published-conflict")

    def test_same_line_conflict_shipping_preserves_an_unpublished_merge(self):
        # Ship must keep the merge produced by the engine, even if main moves
        # between update() and push(). No force push or rebase is needed.
        for main_moves in (False, True):
            with self.subTest(main_moves=main_moves):
                if main_moves:
                    self.repo.cleanup()
                    self.new_fixture()
                ws = workspace.Workspace(self.repo.work, 1, SHIP, base_dir=self.repo.loop_dir)
                wt = ws.issue_worktree(3, "feat/unpublished-merge")
                (wt / "branch-only.txt").write_text("issue work\n")
                git("add", "-A", cwd=wt)
                git("commit", "-qm", "issue implementation", cwd=wt)
                implemented = git("rev-parse", "HEAD", cwd=wt)
                self.seed_main({"first-main.txt": "first main update\n"})
                self.assertEqual(ws.update(wt).status, "merged")
                merge_head = git("rev-parse", "HEAD", cwd=wt)
                self.assertFalse(ws.remote_branch_exists("feat/unpublished-merge"))
                if main_moves:
                    self.seed_main({"second-main.txt": "second main update\n"})
                pushed = ws.push(wt)
                if not main_moves:
                    self.assertEqual(pushed, merge_head, "shipping a current branch must not rewrite its merge")
                for ancestor in (implemented, merge_head, git("rev-parse", "origin/main", cwd=wt)):
                    self.assertEqual(git_result(wt, "merge-base", "--is-ancestor", ancestor, pushed).returncode, 0)
                self.assertEqual(git("rev-parse", "refs/heads/feat/unpublished-merge", cwd=self.repo.remote), pushed)
                self.assert_no_operation(wt, clean=True)

    def legacy_fault(self):
        """Run #3 with the two 0.2.0 behaviours that left #28 detached."""
        self.setup_pair()
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_land = Engine._step_land

        def old_push(ws, wt):
            proc = subprocess.run(["bash", str(SHIP)], cwd=wt, capture_output=True, text=True)
            if proc.returncode:
                raise workspace.GitError(proc.stderr or proc.stdout)
            return ws.head(wt)

        def old_land(engine, n):
            if n != 3:
                return real_land(engine, n)
            try:
                engine.ws.fetch()
                engine.ws.push(Path(engine.store.issue(n).worktree))
                raise AssertionError("the historical fixture must conflict")
            finally:
                engine.claims.release(MERGE_QUEUE, engine.owner)

        with mock.patch("implement_loop.engine.VERSION", "0.2.0"), \
                mock.patch.object(workspace.Workspace, "push", old_push), \
                mock.patch.object(Engine, "_step_land", old_land):
            self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertEqual((st.phase, st.park_kind, st.parked_version, st.resume_phase),
                         (Phase.PARKED, "engine_error", "0.2.0", "land"))
        self.assertFalse(st.retry)
        wt = Path(st.worktree)
        self.assertIn("rebase-merge", operation_paths(wt))
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt), "HEAD")
        return st, wt

    def test_resume_recovers_a_worktree_left_mid_rebase(self):
        old, wt = self.legacy_fault()
        implemented = self.events("implemented")[-1]["sha"]
        branch_head = git("rev-parse", old.branch, cwd=wt)
        self.assertEqual(branch_head, implemented)
        previous_seq = max(e["seq"] for e in self.engine.store.events())
        self.run_engine()
        self.assert_success(after_seq=previous_seq)
        recovered = [e for e in self.events("worktree_recovered") if e["seq"] > previous_seq]
        self.assertEqual(len(recovered), 1)
        self.assertEqual((recovered[0]["operation"], recovered[0]["head"]), ("rebase", branch_head))
        resumed = [e for e in self.events("resumed") if e["seq"] > previous_seq]
        self.assertEqual(len(resumed), 1)
        self.assertFalse(resumed[0]["retry"])
        st = self.engine.store.issue(3)
        self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor", implemented,
                                    st.reviewed_sha).returncode, 0, "recovery must retain committed work")
        # Successful acceptance removes the worktree; its branch still names the merged head.
        self.assertEqual(git("rev-parse", st.branch, cwd=self.repo.work), st.reviewed_sha)
        if wt.exists():
            self.assert_no_operation(wt, clean=True)
            self.assertEqual(git("symbolic-ref", "--short", "HEAD", cwd=wt), st.branch)

    def test_resume_recovers_a_worktree_left_mid_merge(self):
        self.setup_pair()
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_land = Engine._step_land
        stopped = []

        def stop_at_land(engine, n):
            if n == 3 and not stopped:
                stopped.append(True)
                (engine.store.dir / "STOP").write_text("stop\n")
                engine.claims.release(MERGE_QUEUE, engine.owner)
                raise type("AgentStopped", (RuntimeError,), {})("stop before land")
            return real_land(engine, n)

        with mock.patch.object(Engine, "_step_land", stop_at_land):
            self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertEqual(st.phase, Phase.LAND)
        wt = Path(st.worktree)
        before = git("rev-parse", "HEAD", cwd=wt)
        git("fetch", "-q", "origin", cwd=wt)
        proc = git_result(wt, "merge", "--no-edit", "origin/main")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MERGE_HEAD", operation_paths(wt))
        st.phase, st.park_kind, st.resume_phase = Phase.PARKED, "transient", "land"
        st.reason = "interrupted while updating main"
        self.engine.store.put(st)
        self.run_engine()
        self.assert_success()
        recovery = self.events("worktree_recovered")
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0]["operation"], recovery[0]["head"]), ("merge", before))
        self.assertTrue(self.events("resumed"))
        self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor", before,
                                    self.engine.store.issue(3).reviewed_sha).returncode, 0)

    def test_engine_version_is_bumped_past_the_faulty_release(self):
        self.assertGreater(tuple(int(part) for part in implement_loop.VERSION.split(".")), (0, 2, 0))


if __name__ == "__main__":
    unittest.main()

"""Acceptance checks for #74: real conflicts, recovery and exact-head landing.

Only GitHub and the agents are scripted. Each engine uses real worktrees, the repository's
ship script, the verifier and squash merges into a local bare remote. The old-release
recovery fixture deliberately reproduces its missing land sync and its non-aborting push; it
does not replace the new recovery code.
"""

from pathlib import Path
import subprocess
import threading
import unittest
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body
import implement_loop
from implement_loop.agents import FakeAgents, Script
from implement_loop.config import CEILINGS, Caps, Config
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


def land_conflicts(events):
    """Conflicts landing found. Each sends the issue back to build, whose round merges main
    again and records the same conflict as it hands it to the builder."""
    return [e for e in events if e["kind"] == "conflict" and e["phase"] == "land"]


class ObservedAgents(FakeAgents):
    """Observe agent boundaries and inject other *engine runs*, not resolutions."""

    def __init__(self, case, **kwargs):
        super().__init__(case.scripts, **kwargs)
        self.case = case
        self.entries = []        # one per build call
        self.lanes = []          # one per resolve_locked call
        self.exam_heads = []     # (issue, head) per examination
        self.before_build = None
        self.after_build = None
        self.on_examine = None
        self.preserve_test = None
        self._observe_lock = threading.Lock()

    def resolve_locked(self, vendor, req, worktree, files, feedback):
        conflicted = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
        self.lanes.append({"vendor": vendor, "issue": req.issue.number, "files": list(files),
                           "conflicted": conflicted, "feedback": list(feedback)})
        return super().resolve_locked(vendor, req, worktree, files, feedback)

    def build(self, vendor, req, plan, worktree, feedback):
        entry = {"issue": req.issue.number, "vendor": vendor, "worktree": worktree,
                 "feedback": list(feedback), "head": git("rev-parse", "HEAD", cwd=worktree),
                 "main": git("rev-parse", "origin/main", cwd=worktree),
                 "operations": operation_paths(worktree),
                 "contents": {f: (worktree / f).read_text() for f in self.case.shared_paths
                              if (worktree / f).exists()}}
        self.entries.append(entry)
        if self.before_build:
            self.before_build(req, plan, worktree, entry)
        kept = None
        if self.preserve_test and (worktree / self.preserve_test).is_file():
            kept = (worktree / self.preserve_test).read_bytes()   # this fixture's test is already on main
        result = super().build(vendor, req, plan, worktree, feedback)
        if kept is not None:
            (worktree / self.preserve_test).write_bytes(kept)
        if self.after_build:
            self.after_build(req, plan, worktree, entry)
        return result

    def examine(self, vendor, req, plan, worktree, base_sha, head_sha, evidence, memory, requests, since):
        self.case.assert_no_operation(worktree)
        self.case.assertEqual(git("rev-parse", "HEAD", cwd=worktree), head_sha)
        with self._observe_lock:
            self.exam_heads.append((req.issue.number, head_sha))
        result = super().examine(vendor, req, plan, worktree, base_sha, head_sha, evidence, memory, requests, since)
        if self.on_examine:
            self.on_examine(req, worktree, head_sha)
        return result


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
        options = {"test_file": "checks/shared.sh"} if locked else {}
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

        def during_examination(req, wt, head):
            if req.issue.number != 3:
                return
            seen.append(head)
            if len(seen) == 1:
                self.peer = self.make_engine(root=10)
                self.peer.run()
                self.assertEqual(self.peer.store.issue(2).phase, Phase.DONE)
            elif len(seen) == 2 and move_again:
                self.seed_main({"docs/later-main.txt": "another main change\n"})

        agents.on_examine = during_examination
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
        self.assertFalse([e for e in self.events() if e["kind"] in ("waiting", "failed") and e["seq"] > after_seq])
        path = path or self.shared_paths[0]
        for content in (self.repo.main_file(path), git("show", f"{st.certified_sha}:{path}", cwd=self.repo.work)):
            self.assertIsNotNone(content)
            self.assertFalse(has_markers(content))
            for n in (2, 3):
                self.assertIn(self.scripts[n].lines[path], content.splitlines())
        self.assert_exact_gates(self.engine)
        if self.peer:
            self.assert_exact_gates(self.peer)

    def assert_exact_gates(self, engine):
        """No merge without a certificate for the exact head: after the last update from main, the
        head was verified, then examined and certified, then verified again as it lands. The
        certificate covers the examined head plus the examiner's own adopted probes (ADR 0012)."""
        events = engine.store.events()
        merged = [e for e in events if e["kind"] == "merged"]
        self.assertTrue(merged, events)
        calls = {(c[1], c[2]) for c in self.gh.calls if c[0] == "merge_pr"}
        for event in merged:
            n, head = event["issue"], event["head"]
            self.assertIn((event["pr"], head), calls)
            self.assertEqual(self.gh.prs[event["pr"]]["head"]["sha"], head)
            mine = [e for e in events if e.get("issue") == n and e["seq"] < event["seq"]]
            barrier = max((e["seq"] for e in mine if e["kind"] in ("conflict", "updated_from_main")), default=0)
            exams = [e for e in mine if e["kind"] == "examined" and e["seq"] > barrier]
            self.assertTrue(exams, f"no examination after the last update from main: {events}")
            exam = exams[-1]
            self.assertTrue(exam["certify"])
            examined = exam["head"]
            if examined != head:
                self.assertEqual(git("rev-parse", f"{head}^", cwd=self.repo.work), examined)
                self.assertTrue(git("log", "-1", "--format=%s", head, cwd=self.repo.work)
                                .startswith(f"Lock the tests for #{n} and adopt the examiner's probes"))
            verified = [e for e in mine if e["kind"] == "verified" and e["ok"] is True and e["seq"] > barrier]
            self.assertTrue([e for e in verified if e["head"] == examined and e["seq"] < exam["seq"]],
                            f"{examined} was examined before it was verified: {events}")
            self.assertTrue([e for e in verified if e["head"] == head and e["seq"] > exam["seq"]],
                            f"{head} was not verified again before it landed: {events}")
            earlier = [e["head"] for e in mine if e["kind"] == "examined" and e["seq"] < barrier]
            self.assertNotIn(examined, earlier)
            st = engine.store.issue(n)
            self.assertEqual((st.verified_sha, st.certified_sha), (head, head))
            self.assertIn((n, examined), engine.agents.exam_heads)

    def test_same_line_conflict_goes_back_to_build_and_merges(self):
        agents = self.conflict_scenario()
        self.assert_success()
        found = land_conflicts(self.events())
        self.assertEqual(len(found), 1)
        self.assertIn("shared/suites.txt", found[0]["files"])
        self.assertFalse(self.events("round_failed"), "a conflict charges no round")
        self.assertEqual(self.engine.store.issue(3).unproductive, 0)
        entries = [e for e in agents.entries if e["issue"] == 3]
        self.assertEqual(len(entries), 2)
        self.assertIn("shared/suites.txt", "\n".join(entries[1]["feedback"]))
        self.assertIn("MERGE_HEAD", entries[1]["operations"])
        self.assertTrue(has_markers(entries[1]["contents"]["shared/suites.txt"]))
        examined = self.events("examined")
        self.assertNotEqual(examined[0]["head"], examined[-1]["head"])
        self.assertLess(examined[0]["seq"], found[0]["seq"])
        self.assertLess(found[0]["seq"], examined[-1]["seq"])
        self.assertTrue(examined[-1]["seq"] > found[0]["seq"] and not examined[-1]["adopted"],
                        "the certificate after the conflict comes from a focused delta examination")

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
        found = land_conflicts(self.events())
        self.assertEqual(len(found), 1)
        self.assertEqual(set(found[0]["files"]), set(self.shared_paths))
        repair = [e for e in agents.entries if e["issue"] == 3][-1]
        for path in self.shared_paths:
            self.assertIn(path, "\n".join(repair["feedback"]))
        self.assertFalse(self.events("round_failed"))

    def test_main_moves_again_before_land(self):
        self.conflict_scenario(move_again=True)
        self.assert_success()
        self.assertEqual(self.repo.main_file("docs/later-main.txt"), "another main change")
        self.assertEqual(len(land_conflicts(self.events())), 1)
        updates = self.events("updated_from_main")
        self.assertTrue(any(e.get("phase") == "land" for e in updates))
        self.assertGreaterEqual(len(self.events("examined")), 3)
        self.assertFalse(self.events("round_failed"))

    def test_merged_head_is_the_exact_verified_and_certified_head(self):
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

        def stop_with_markers(req, plan, wt, entry):
            if entry["operations"] and not interrupted:
                interrupted.append(True)
                self.assertIn("MERGE_HEAD", entry["operations"])
                self.assertTrue(has_markers(entry["contents"][self.shared_paths[0]]))
                (self.engine.store.dir / "STOP").write_text("stop during conflict repair\n")
                raise type("AgentStopped", (RuntimeError,), {})("interrupted repair")

        agents.before_build = stop_with_markers
        self.run_engine(agents)
        self.assertTrue(interrupted)
        self.assertTrue(self.events("step_interrupted"))
        self.assertFalse(self.events("step_crashed"))
        st = self.engine.store.issue(3)
        self.assertEqual(st.phase, Phase.BUILD)
        self.assert_no_operation(Path(st.worktree), clean=True)
        self.run_engine(agents)
        self.assert_success()
        self.assertFalse(self.events("round_failed"))

    def test_same_line_conflict_unresolved_markers_are_bounded_and_aborted(self):
        self.setup_pair()
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)

        def leave_markers(req, plan, wt, entry):
            if "MERGE_HEAD" in entry["operations"]:
                # A builder claiming done is insufficient: keep its original
                # conflict markers and require the engine to reject the result.
                (wt / self.shared_paths[0]).write_text(entry["contents"][self.shared_paths[0]])

        agents.after_build = leave_markers
        self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertTrue(self.events("conflict_unresolved"))
        # Conflicts spend no round; the issue's call ceiling bounds them (ADR 0012).
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "ceiling"), self.events())
        self.assertFalse(self.events("step_crashed"))
        self.assertFalse(self.events("merged"))
        self.assert_no_operation(Path(st.worktree), clean=True)
        self.assertLessEqual(len([e for e in agents.entries if e["issue"] == 3]), CEILINGS["M"])

    def test_a_conflict_charges_no_round_and_is_never_an_engine_fault(self):
        self.conflict_scenario()
        st = self.engine.store.issue(3)
        self.assertEqual(st.phase, Phase.DONE, self.events())
        self.assertTrue(self.events("conflict"))
        self.assertFalse(self.events("step_crashed"))
        self.assertFalse(self.events("round_failed"))
        self.assertFalse([e for e in self.events("waiting") if e["wait"] == "engine"])
        self.assertEqual((st.unproductive, st.replans), (0, 0))
        self.assert_no_operation(self.engine.ws.coord_path(), clean=True)

    def test_locked_test_conflict_is_resolved_by_the_other_vendor(self):
        agents = self.conflict_scenario(locked=True)
        self.assert_success()
        lane = "checks/shared.sh"
        resolutions = [e for e in agents.lanes if e["issue"] == 3 and lane in e["conflicted"]]
        self.assertTrue(resolutions, agents.lanes)
        self.assertTrue(all(e["vendor"] == agents.other for e in resolutions))
        self.assertTrue(all(e["files"] == [lane] for e in resolutions))
        self.assertTrue(all(lane in "\n".join(e["feedback"]) for e in resolutions))
        builds = [c for c in agents.calls if c[0] == "build" and c[2] == 3]
        self.assertTrue(all(c[1] == agents.operator for c in builds), "the builder never resolves its locked test")
        reverted = self.events("locked_changes_reverted")
        self.assertTrue(any(lane in e["files"] for e in reverted))
        relocked = self.events("checks_relocked")
        self.assertTrue(any(lane in e["files"] and e["source"] == "other-vendor" for e in relocked))
        self.assertFalse(self.events("locked_tests_changed"), "no test change request was needed")
        final = self.repo.main_file(lane)
        self.assertFalse(has_markers(final))
        for n in (2, 3):
            self.assertIn(f"docs/issue-{n}.txt", final)
        # Retaining main's test requirements is observable, not just a relock event.
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

    def test_locked_test_conflict_restores_resolver_edits_outside_its_lane(self):
        self.setup_pair(locked=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_resolve = agents.resolve_locked
        attempted = []
        before_resolver = []
        restored = []

        def stray_edit(vendor, req, wt, files, feedback):
            was_conflicted = "checks/shared.sh" in git(
                "diff", "--name-only", "--diff-filter=U", cwd=wt).splitlines()
            if was_conflicted:
                before_resolver.append((wt / self.shared_paths[0]).read_bytes())
            result = real_resolve(vendor, req, wt, files, feedback)
            if was_conflicted:
                attempted.append(True)
                # This is outside the resolver's lane, and restoring HEAD
                # here would lose the conflict's main-side registration.
                (wt / self.shared_paths[0]).write_text("out-of-lane replacement\n")
            return result

        def observe_restoration(req, plan, wt, entry):
            if before_resolver and "MERGE_HEAD" in entry["operations"]:
                self.assertEqual((wt / self.shared_paths[0]).read_bytes(), before_resolver[-1])
                restored.append(True)

        agents.resolve_locked = stray_edit
        agents.before_build = observe_restoration
        self.run_engine(agents)
        self.assertTrue(attempted)
        self.assertTrue(restored)
        self.assertTrue(any(self.shared_paths[0] in e["discarded"] for e in self.events("resolver_out_of_lane")))
        self.assert_success()

    def test_locked_test_conflict_unresolved_markers_never_reach_the_builder(self):
        self.setup_pair(locked=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        real_resolve = agents.resolve_locked

        def leave_locked_markers(vendor, req, wt, files, feedback):
            lane = wt / "checks/shared.sh"
            if lane.exists() and has_markers(lane.read_text()):
                # An unsuccessful resolver answers, but leaves the merge unresolvable.
                return agents._metered(req.issue.number, "resolve_locked", vendor, lambda: None)
            return real_resolve(vendor, req, wt, files, feedback)

        def observe_build(req, plan, wt, entry):
            lane = wt / "checks/shared.sh"
            self.assertFalse(lane.exists() and has_markers(lane.read_text()))

        agents.resolve_locked = leave_locked_markers
        agents.before_build = observe_build
        self.run_engine(agents)
        st = self.engine.store.issue(3)
        self.assertTrue(self.events("check_conflict_unresolved"))
        # Conflicts spend no round; the issue's call ceiling bounds them (ADR 0012).
        self.assertEqual((st.phase, st.fail["cause"]), (Phase.FAILED, "ceiling"), self.events())
        self.assertFalse(self.events("step_crashed"))
        self.assertFalse(self.events("merged"))
        self.assert_no_operation(Path(st.worktree), clean=True)

    def test_conflict_scope_allows_a_conflicted_path_outside_the_plan(self):
        # A differently named shared file prevents a suites.txt-only workaround.
        path = "shared/alternate-registry.txt"
        self.seed_main({path: "other-base\n"})
        self.shared_paths = [path]
        self.setup_pair()
        self.scripts[2].lines[path] = "different-first-registration"
        self.scripts[3].lines[path] = "different-second-registration"
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        # The branch was verified and certified with its original zones. Model a narrowed plan
        # as it lands, before main's merge introduces the conflict; otherwise the original
        # edit would fail the zone check before reaching land.
        real_land = Engine._step_land
        narrowed = []

        def narrow_then_land(engine, n):
            if n == 3 and not narrowed:
                narrowed.append(True)
                st = engine.store.issue(3)
                st.plan["zones"].remove(path)
                st.grants = [g for g in st.grants if g["path"] != path]
                engine.store.put(st)
                engine.plan.specs[3].declared_paths.remove(path)
            return real_land(engine, n)

        real_build = Engine._step_build
        stopped = []

        def stop_after_conflict(engine, n):
            if n == 3 and engine.store.issue(n).conflict_pending and not stopped:
                stopped.append(True)
                (engine.store.dir / "STOP").write_text("stop after conflict scope was persisted\n")
                raise type("AgentStopped", (RuntimeError,), {})("pause repair fixture")
            return real_build(engine, n)

        with mock.patch.object(Engine, "_step_land", narrow_then_land), \
                mock.patch.object(Engine, "_step_build", stop_after_conflict):
            self.run_engine(agents)
        self.assertTrue(narrowed)
        self.assertTrue(stopped)
        self.assertEqual(self.engine.store.issue(3).phase, Phase.BUILD)
        self.assert_no_operation(Path(self.engine.store.issue(3).worktree), clean=True)
        # A fresh plan must recover the conflict permission from persisted state,
        # not merely retain a mutation of the first run's in-memory declared paths.
        self.run_engine(agents)
        self.assert_success(path=path)
        st = self.engine.store.issue(3)
        self.assertNotIn(path, st.plan["zones"])
        self.assertIn({"path": path, "source": "conflict", "protected": False}, st.grants)
        self.assertIn(path, st.conflict_paths)
        self.assertIn(path, self.engine.plan.specs[3].declared_paths)
        self.assertFalse(st.conflict_pending)
        self.assertTrue(any(path in e["files"] for e in self.events("conflict")))

    def test_each_build_round_starts_from_current_main(self):
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

                def move_main(req, plan, wt, entry):
                    if req.issue.number == 3 and not moved:
                        moved.append(True)
                        if conflicting:
                            self.peer = self.make_engine(root=10)
                            self.peer.run()
                            self.assertEqual(self.peer.store.issue(2).phase, Phase.DONE)
                        else:
                            self.seed_main({"docs/main-round-one.txt": "arrived during round one\n"})

                agents.after_build = move_main
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
                    self.assertEqual(conflicts[0]["phase"], "build")
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
        # A blocking finding at the first examination (where the test locks) brings a second round.
        self.add_issue(3, lines={}, test_file=lane, findings=1)
        self.gh.add_issue(1, "Epic", "Epic.\n", subs=(3,))
        agents = ObservedAgents(self)
        agents.preserve_test = lane
        moved = []

        def update_check(req, wt, head):
            if not moved:
                moved.append(True)
                self.seed_main({lane: original_check.replace("baseline metadata", "metadata from main")})

        agents.on_examine = update_check
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
        self.assertEqual(st.phase, Phase.WAITING)
        self.assertEqual((st.wait["kind"], st.wait["version"], st.wait["resume"]), ("engine", "0.2.0", "land"))
        wt = Path(st.worktree)
        self.assertIn("rebase-merge", operation_paths(wt))
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt), "HEAD")
        return st, wt

    def test_resume_recovers_a_worktree_left_mid_rebase(self):
        old, wt = self.legacy_fault()
        branch_head = git("rev-parse", old.branch, cwd=wt)
        self.assertEqual(branch_head, old.certified_sha)
        previous_seq = max(e["seq"] for e in self.engine.store.events())
        self.run_engine()
        self.assert_success(after_seq=previous_seq)
        recovered = [e for e in self.events("worktree_recovered") if e["seq"] > previous_seq]
        self.assertEqual(len(recovered), 1)
        self.assertEqual((recovered[0]["operation"], recovered[0]["head"]), ("rebase", branch_head))
        resumed = [e for e in self.events("resumed") if e["seq"] > previous_seq]
        self.assertEqual(len(resumed), 1)
        self.assertEqual((resumed[0]["wait"], resumed[0]["phase"]), ("engine", "land"))
        st = self.engine.store.issue(3)
        self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor", old.certified_sha,
                                    st.certified_sha).returncode, 0, "recovery must retain committed work")
        # Successful acceptance removes the worktree; its branch still names the merged head.
        self.assertEqual(git("rev-parse", st.branch, cwd=self.repo.work), st.certified_sha)
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
        st.phase = Phase.WAITING
        st.wait = {"kind": "github", "resume": "land", "detail": "interrupted while updating main", "since": 0}
        self.engine.store.put(st)
        self.run_engine()
        self.assert_success()
        recovery = self.events("worktree_recovered")
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0]["operation"], recovery[0]["head"]), ("merge", before))
        self.assertTrue(self.events("resumed"))
        self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor", before,
                                    self.engine.store.issue(3).certified_sha).returncode, 0)

    def test_engine_version_is_bumped_past_the_faulty_release(self):
        self.assertGreater(tuple(int(part) for part in implement_loop.VERSION.split(".")), (0, 2, 0))


if __name__ == "__main__":
    unittest.main()

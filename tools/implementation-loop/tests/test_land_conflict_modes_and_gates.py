"""Additional #74 acceptance checks: git file modes and independent HEAD evidence.

Real temporary repositories, ship.sh, checks and merges exercise the engine. Only
agents and GitHub are scripted. File/index observations deliberately use git and
lstat directly rather than the production restoration helpers under test.
"""

import os
from pathlib import Path
import shlex
import stat
import subprocess
import threading
import unittest
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body
from test_land_conflicts import ObservedAgents, has_markers, operation_paths
from implement_loop.agents import Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.model import Phase
from implement_loop.state import RunStore
from implement_loop.workspace import Workspace


def disk_state(path):
    """Only the kind, content and permission bit that git tracks."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return ("symlink", os.readlink(path))
    if stat.S_ISDIR(info.st_mode):
        return ("directory",)
    return ("file", path.read_bytes(), bool(info.st_mode & stat.S_IXUSR))


def index_state(wt, rel):
    return subprocess.check_output(
        ["git", "ls-files", "--stage", "-z", "--", rel], cwd=wt)


def executable(path, enabled):
    mode = path.stat().st_mode
    path.chmod((mode | 0o111) if enabled else (mode & ~0o111))


class LandConflictModesAndGatesTests(unittest.TestCase):
    # Compose a small fixture; inheriting LandConflictTests would collect its
    # entire acceptance suite twice under unittest discover.
    def setUp(self):
        self.new_fixture()

    def new_fixture(self):
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        for key, value in (("core.filemode", "true"), ("core.autocrlf", "false"),
                           ("merge.conflictStyle", "merge"), ("rerere.enabled", "false"),
                           ("rebase.backend", "merge")):
            git("config", key, value, cwd=self.repo.work)
        self.scripts = {}
        self.shared_paths = ["registry/widget-list.txt"]
        self.gh = FakeGitHub(on_merge=self.merge_published_head)
        self.engine = None
        self.peer = None
        self.boundary_errors = []
        self.seed_main({self.shared_paths[0]: "initial-entry\n"})

    def seed_main(self, files, *, executables=()):
        # All fixture publication is confined to TempRepo's local bare remote.
        git("fetch", "-q", "origin", cwd=self.repo.merger)
        git("checkout", "-q", "-B", "main", "origin/main", cwd=self.repo.merger)
        for rel, text in files.items():
            path = self.repo.merger / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            executable(path, rel in executables)
        git("add", "-A", cwd=self.repo.merger)
        git("commit", "-qm", "fixture: update main", cwd=self.repo.merger)
        git("push", "-q", "origin", "HEAD:main", cwd=self.repo.merger)
        return git("rev-parse", "HEAD", cwd=self.repo.merger)

    def add_issue(self, n, *, locked=False, **options):
        self.scripts[n] = Script(files={f"docs/issue-{n}.txt": f"content-{n}"},
                                 lines={self.shared_paths[0]: f"registration-{n}"},
                                 test_file="checks/combined.sh" if locked else "", **options)
        self.gh.add_issue(n, f"Widget {n}", issue_body(f"feat/issue-{n}",
                          ["Keep the widget and its registration."], ["The checks pass."]),
                          labels=("size:M",))

    def setup_issues(self, *, pair=False, locked=False, **options):
        self.add_issue(3, locked=locked, **options)
        self.gh.add_issue(1, "Second widget", "Epic.\n", subs=(3,))
        if pair:
            self.add_issue(2, locked=locked)
            self.gh.add_issue(10, "First widget", "Epic.\n", subs=(2,))

    def make_engine(self, root=1, agents=None):
        return Engine(build_plan(self.gh, root, self.repo.work),
                      RunStore.for_root(self.repo.work, root), self.gh,
                      Workspace(self.repo.work, root, SHIP,
                                base_dir=self.repo.loop_dir / f"run-{root}"),
                      agents or ObservedAgents(self),
                      Config(repo="test/test", caps=Caps(ci_poll_s=0)),
                      repo_root=self.repo.work, log=lambda m: None, sleep=lambda s: None)

    def run_engine(self, agents):
        self.engine = self.make_engine(agents=agents)
        original = Engine._set_phase

        def boundary(engine, n, phase, **kwargs):
            result = original(engine, n, phase, **kwargs)
            wt = engine.store.issue(n).worktree
            if wt and Path(wt).exists():
                try:
                    self.assert_no_operation(Path(wt), clean=True)
                except AssertionError as error:
                    self.boundary_errors.append(str(error))
            return result

        with mock.patch.object(Engine, "_set_phase", boundary):
            self.engine.run()
        return self.engine

    def events(self, kind=None):
        return [e for e in self.engine.store.events() if e.get("issue") == 3
                and (kind is None or e["kind"] == kind)]

    def assert_no_operation(self, wt, *, clean=False):
        self.assertEqual(operation_paths(wt), [])
        if clean:
            self.assertEqual(git("status", "--porcelain", cwd=wt), "")

    def merge_published_head(self, branch, head):
        self.assertEqual(git("rev-parse", f"refs/heads/{branch}", cwd=self.repo.remote), head)
        return self.repo.merge(branch, head)

    def install_peer_hook(self, agents, *, after_peer=None):
        moved = []

        def peer_lands(req, wt, head):
            if req.issue.number == 3 and not moved:
                moved.append(head)
                self.peer = self.make_engine(root=10)
                self.peer.run()
                self.assertEqual(self.peer.store.issue(2).phase, Phase.DONE,
                                 self.peer.store.events())
                if after_peer:
                    after_peer()

        agents.on_examine = peer_lands

    def assert_done(self, *, pair=False):
        self.assertEqual(self.engine.store.issue(3).phase, Phase.DONE, self.events())
        self.assertFalse([e for e in self.events() if e["kind"] in ("waiting", "failed")])
        self.assertFalse(self.events("step_crashed"))
        self.assertEqual(self.boundary_errors, [])
        text = self.repo.main_file(self.shared_paths[0])
        self.assertFalse(has_markers(text))
        for n in ((2, 3) if pair else (3,)):
            self.assertIn(self.scripts[n].lines[self.shared_paths[0]], text.splitlines())
        merged = self.events("merged")
        self.assertEqual(len(merged), 1)
        head = merged[0]["head"]
        st = self.engine.store.issue(3)
        self.assertEqual((st.verified_sha, st.certified_sha), (head, head))
        self.assertIn(("merge_pr", st.pr, head), self.gh.calls)

    def assert_main_state(self, rel, expected):
        mode = git("ls-tree", "origin/main", "--", rel, cwd=self.repo.merger).split()[0]
        self.assertEqual(mode, "100755" if expected[2] else "100644", rel)
        data = subprocess.check_output(["git", "show", f"origin/main:{rel}"], cwd=self.repo.merger)
        self.assertEqual(data, expected[1], rel)

    def mode_targets(self):
        plain = "assets/plain with spaces-λ.txt"
        runner = "bin/runner.sh"
        alike = "assets/identical.txt"
        copy = "assets/identical-copy.txt"
        self.seed_main({plain: "plain bytes\n", runner: "#!/bin/sh\nexit 0\n",
                        alike: "identical bytes\n", copy: "identical bytes\n"},
                       executables=(runner,))
        return plain, runner, alike, copy

    def stray_modes(self, wt, targets):
        plain, runner, alike, copy = targets
        executable(wt / plain, True)
        executable(wt / runner, False)
        git("add", "--", runner, cwd=wt)  # one mode change is staged
        (wt / alike).unlink()
        (wt / alike).symlink_to(Path(copy).name)  # dereferences to identical bytes
        self.assertEqual((wt / alike).read_bytes(), (wt / copy).read_bytes())

    def test_locked_test_conflict_restores_file_modes_outside_its_lane(self):
        targets = self.mode_targets()
        late = "bin/tool introduced by main.sh"
        self.setup_issues(pair=True, locked=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents, after_peer=lambda: self.seed_main(
            {late: "#!/bin/sh\necho introduced-on-main\n"}, executables=(late,)))
        real_resolve = agents.resolve_locked
        snapshots, restored = [], []
        watched = [*targets[:3], late, self.shared_paths[0]]

        def outside_lane(vendor, req, wt, files, feedback):
            resolving = req.issue.number == 3 and "checks/combined.sh" in git(
                "diff", "--name-only", "--diff-filter=U", cwd=wt).splitlines()
            if resolving:
                snapshots.append({f: (disk_state(wt / f), index_state(wt, f)) for f in watched})
                self.assertIn(b" 1\t", snapshots[-1][self.shared_paths[0]][1],
                              "the out-of-lane shared conflict must still have index stages")
                self.assertEqual(git("ls-tree", "HEAD", "--", late, cwd=wt), "",
                                 "the executable must come from main, not the issue's HEAD")
            result = real_resolve(vendor, req, wt, files, feedback)
            if resolving:
                self.stray_modes(wt, targets)
                content = (wt / late).read_bytes()
                (wt / late).unlink()
                (wt / late).write_bytes(content)
                executable(wt / late, False)
                git("add", "--", late, cwd=wt)
            return result

        def before_builder(req, plan, wt, entry):
            if snapshots:
                for f, (state, index) in snapshots[-1].items():
                    self.assertEqual(disk_state(wt / f), state, f)
                    self.assertEqual(index_state(wt, f), index, f)
                restored.append(True)

        agents.resolve_locked = outside_lane
        agents.before_build = before_builder
        self.run_engine(agents)
        self.assert_done(pair=True)
        self.assertEqual((len(snapshots), len(restored)), (1, 1))
        for f in watched[:-1]:
            self.assert_main_state(f, snapshots[0][f][0])
        discarded = set().union(*(set(e["discarded"]) for e in self.events("resolver_out_of_lane")))
        self.assertTrue(set(watched[:-1]) <= discarded)
        self.assertFalse(self.events("round_failed"), "a conflict charges no round")

    def test_examiner_mode_changes_never_reach_the_branch(self):
        # The examiner works in a disposable copy of the exact head; whatever it changes there,
        # modes included, is discarded with the copy (ADR 0012).
        targets = self.mode_targets()
        self.setup_issues()
        agents = ObservedAgents(self)
        real_examine = agents.examine
        observed = []

        def outside_lane(vendor, req, plan, wt, *args, **kwargs):
            result = real_examine(vendor, req, plan, wt, *args, **kwargs)
            self.stray_modes(wt, targets)
            observed.append(wt)
            return result

        agents.examine = outside_lane
        self.run_engine(agents)
        self.assert_done()
        self.assertTrue(observed)
        issue_worktree = Path(self.engine.store.issue(3).worktree)
        self.assertTrue(all(Path(wt) != issue_worktree for wt in observed))
        self.assertTrue(all(not Path(wt).exists() for wt in observed), "each copy is removed")
        for f in targets[:3]:
            self.assert_main_state(f, disk_state(self.repo.merger / f))
        self.assertEqual(git("ls-tree", "origin/main", "--", targets[1], cwd=self.repo.merger).split()[0], "100755")

    def test_builder_mode_change_to_a_locked_test_is_reverted(self):
        for mid_merge in (False, True):
            for change in ("chmod", "symlink"):
                with self.subTest(mid_merge=mid_merge, change=change):
                    if mid_merge or change != "chmod":
                        self.repo.cleanup()
                        self.new_fixture()
                    # Without a conflict, a blocking finding at the first examination (where the
                    # test locks) brings the second build that tampers.
                    self.setup_issues(pair=mid_merge, locked=True, **({} if mid_merge else {"findings": 1}))
                    lane = "checks/combined.sh"
                    agents = ObservedAgents(self)
                    intended, tampered = [], []

                    def tamper(req, plan, wt, entry):
                        if req.issue.number != 3:
                            return
                        if lane not in self.engine.store.issue(3).locked:
                            executable(wt / lane, mid_merge)   # the builder's own test, as it wants it
                            return
                        if tampered or (mid_merge and not self.events("conflict")):
                            return
                        intended.append(disk_state(wt / lane))
                        if change == "chmod":
                            executable(wt / lane, not intended[-1][2])
                        else:
                            copy = self.repo.tmp / "identical-check.sh"
                            copy.write_bytes(intended[-1][1])
                            (wt / lane).unlink()
                            (wt / lane).symlink_to(copy)
                        if mid_merge:
                            git("add", "--", lane, cwd=wt)
                        self.assertEqual((wt / lane).read_bytes(), intended[-1][1])
                        self.assertNotEqual(disk_state(wt / lane), intended[-1])
                        tampered.append(True)

                    agents.after_build = tamper
                    if mid_merge:
                        self.install_peer_hook(agents)
                    self.run_engine(agents)
                    self.assert_done(pair=mid_merge)
                    self.assertEqual(len(tampered), 1)
                    self.assert_main_state(lane, intended[0])
                    self.assertTrue(any(lane in e["files"] for e in self.events("locked_changes_reverted")))
                    if mid_merge:
                        self.assertEqual(len([e for e in self.events("conflict") if e["phase"] == "land"]), 1)
                        for n in (2, 3):
                            self.assertIn(f"docs/issue-{n}.txt", self.repo.main_file(lane))

    def logged_checks(self, agents):
        """A test logs real HEAD only after its assertions pass, outside all worktrees.

        Observe log offsets at sync events and snapshots before each examination. This
        avoids trusting the engine's own verified_sha or Evidence.head_sha labels.
        """
        log = self.repo.tmp / "passed heads with spaces.log"
        real_build, real_examine = agents.build, agents.examine
        exams, barriers = [], []
        observe_lock = threading.Lock()
        line = f"printf '%s\\n' \"$(git rev-parse HEAD)\" >> {shlex.quote(str(log))}\n"

        def heads():
            return log.read_text().splitlines() if log.exists() else []

        def build(vendor, req, plan, wt, feedback):
            result = real_build(vendor, req, plan, wt, feedback)
            if req.issue.number == 3:
                lane = wt / (self.scripts[3].test_file or "checks/issue_3.sh")
                if line not in lane.read_text():   # the builder rewrites its test each round
                    with lane.open("a") as stream:
                        stream.write(line)
            return result

        def examine(vendor, req, plan, wt, base, head, *args, **kwargs):
            if req.issue.number == 3:
                with observe_lock:
                    logged = heads()
                    self.assertIn(head, logged, "the examination started without the real test passing on this HEAD")
                    seq = max((e["seq"] for e in self.engine.store.events()), default=0)
                    exams.append({"head": head, "heads": logged, "seq": seq})
            return real_examine(vendor, req, plan, wt, base, head, *args, **kwargs)

        real_event = RunStore.event

        def event(store, kind, **data):
            result = real_event(store, kind, **data)
            if self.engine is not None and store is self.engine.store and data.get("issue") == 3:
                if kind in ("conflict", "updated_from_main", "head_changed_after_certificate"):
                    barriers.append({"seq": max(e["seq"] for e in store.events()), "offset": len(heads())})
            return result

        agents.build, agents.examine = build, examine
        return log, exams, barriers, mock.patch.object(RunStore, "event", event)

    def assert_independent_gates(self, log, exams, barriers):
        self.assertTrue(exams)
        merged = self.events("merged")[0]
        head = merged["head"]
        final_exams = [r for r in exams if r["head"] == head]
        self.assertTrue(final_exams, "the merged head itself was examined")
        self.assertIn(head, log.read_text().splitlines())
        last_barrier = max((b for b in barriers if b["seq"] < merged["seq"]),
                           key=lambda b: b["seq"], default={"seq": 0, "offset": 0})
        for exam in exams:
            self.assertIn(exam["head"], exam["heads"])
            self.assertLess(exam["seq"], merged["seq"])
            earlier = [b for b in barriers if b["seq"] <= exam["seq"]]
            barrier = max(earlier, key=lambda b: b["seq"], default={"seq": 0, "offset": 0})
            self.assertIn(exam["head"], exam["heads"][barrier["offset"]:],
                          "the real test must pass again after the last update/conflict barrier")
        for exam in final_exams:
            self.assertGreater(exam["seq"], last_barrier["seq"])
            self.assertIn(head, exam["heads"][last_barrier["offset"]:])

    def test_exact_head_is_independently_verified_before_merge(self):
        self.setup_issues(pair=True)
        agents = ObservedAgents(self)
        self.install_peer_hook(agents)
        log, exams, barriers, recording = self.logged_checks(agents)
        with recording:
            self.run_engine(agents)
        self.assert_done(pair=True)
        self.assertEqual(len([e for e in self.events("conflict") if e["phase"] == "land"]), 1)
        self.assertFalse(self.events("round_failed"))
        self.assertGreaterEqual(len({r["head"] for r in exams}), 2)
        self.assert_independent_gates(log, exams, barriers)

    def test_exact_head_after_main_moves_between_land_sync_and_ship(self):
        for conflicting in (False, True):
            with self.subTest(conflicting=conflicting):
                if conflicting:
                    self.repo.cleanup()
                    self.new_fixture()
                self.setup_issues()
                agents = ObservedAgents(self)
                log, exams, barriers, recording = self.logged_checks(agents)
                real_update, real_push = Workspace.update, Workspace.push
                syncs, moved = {}, []
                before_push = []

                def update(ws, wt):
                    result = real_update(ws, wt)
                    syncs[wt] = result.status
                    return result

                def push(ws, wt):
                    if not moved:
                        self.assertEqual(syncs[wt], "current")
                        st = self.engine.store.issue(3)
                        before_push.append(git("rev-parse", "HEAD", cwd=wt))
                        self.assertEqual((st.verified_sha, st.certified_sha), (before_push[0], before_push[0]))
                        moved.append(self.seed_main({
                            self.shared_paths[0] if conflicting else "docs/race-from-main.txt":
                            "registration-from-concurrent-main\n" if conflicting else "clean concurrent update\n"}))
                    try:
                        return real_push(ws, wt)
                    finally:
                        self.assert_no_operation(wt, clean=True)

                with recording, mock.patch.object(Workspace, "update", update), \
                        mock.patch.object(Workspace, "push", push):
                    self.run_engine(agents)
                self.assert_done()
                self.assertEqual(len(moved), 1)
                merged_head = self.events("merged")[0]["head"]
                self.assertNotEqual(merged_head, before_push[0])
                self.assertEqual(subprocess.run(
                    ["git", "merge-base", "--is-ancestor", moved[0], merged_head],
                    cwd=self.repo.work, capture_output=True).returncode, 0)
                if conflicting:
                    conflicts = [e for e in self.events("conflict") if e["phase"] == "land"]
                    self.assertEqual(len(conflicts), 1)
                    self.assertIn(self.shared_paths[0], conflicts[0]["files"])
                    self.assertFalse(self.events("round_failed"))
                    self.assertEqual(len(agents.entries), 2)
                    self.assertIn(self.shared_paths[0], "\n".join(agents.entries[-1]["feedback"]))
                    self.assertIn("registration-from-concurrent-main",
                                  self.repo.main_file(self.shared_paths[0]).splitlines())
                else:
                    changed = self.events("head_changed_after_certificate")
                    self.assertEqual(len(changed), 1)
                    self.assertEqual((changed[0]["certified"], changed[0]["head"]),
                                     (before_push[0], merged_head))
                    self.assertEqual(self.repo.main_file("docs/race-from-main.txt"), "clean concurrent update")
                    self.assertFalse(self.events("conflict"))
                    self.assertFalse(self.events("round_failed"))
                self.assert_independent_gates(log, exams, barriers)


if __name__ == "__main__":
    unittest.main()

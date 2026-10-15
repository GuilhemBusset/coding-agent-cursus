"""Acceptance checks for #78: ref ownership, concurrent runs and missing-branch resume.

Only agents and GitHub are scripted. Git, verification, shipping and squash merges are
real, local operations. The two-run test uses disjoint plans, as agreed in the design.
"""

import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body

import implement_loop
from implement_loop.agents import FakeAgents, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.model import Phase
from implement_loop.state import RunStore
from implement_loop.workspace import Workspace


WAIT = 60


def git_result(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True)


def snapshot(path):
    """Use bytes: whitespace in porcelain output and index stage numbers matter."""
    records = []
    for args in (("status", "--porcelain=v1", "-z", "--untracked-files=all"),
                 ("ls-files", "--stage", "-z")):
        result = git_result(path, *args)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        records.append(result.stdout)
    return tuple(records)


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)

    def run_fixture(self, n=2, root=1, files=None, **script_options):
        files = files or {f"docs/issue-{n}.txt": f"content for issue {n}"}
        gh = FakeGitHub(on_merge=self.repo.merge)
        gh.add_issue(n, f"Issue {n}", issue_body(
            f"feat/issue-{n}", [f"`{p}` contains `{v}`." for p, v in files.items()],
            ["The check passes."]), labels=("size:M",))
        if root != n:
            gh.add_issue(root, f"Epic {root}", "Disjoint test epic.\n", subs=(n,))
        agents = FakeAgents({n: Script(files=files, **script_options)})
        store = RunStore.for_root(self.repo.work, root)
        ws = Workspace(self.repo.work, root, SHIP, base_dir=self.repo.loop_dir / f"run-{root}")
        run = SimpleNamespace(n=n, root=root, gh=gh, agents=agents, store=store, ws=ws, files=files)
        run.engine = self.new_engine(run)
        return run

    def new_engine(self, run):
        return Engine(build_plan(run.gh, run.root, self.repo.work), run.store, run.gh,
                      run.ws, run.agents, Config(repo="test/test", caps=Caps(ci_poll_s=0)),
                      repo_root=self.repo.work, log=lambda _: None, sleep=lambda _: None)

    def events(self, run, kind=None, after=0):
        return [e for e in run.store.events() if e["seq"] > after
                and (kind is None or e["kind"] == kind)]

    def assert_done(self, run, after=0):
        self.assertEqual(self.events(run, "step_crashed", after), [])
        self.assertEqual(run.store.issue(run.n).phase, Phase.DONE,
                         json.dumps(self.events(run), indent=1))
        for path, content in run.files.items():
            self.assertEqual(self.repo.main_file(path), content)

    def commit_object(self, message, parent=None):
        tree = git("rev-parse", "HEAD^{tree}", cwd=self.repo.work)
        args = ["commit-tree", tree, "-m", message]
        if parent is not None:
            args += ["-p", parent]
        return git(*args, cwd=self.repo.work)

    def assert_registered_gitfile(self, path):
        entry = (path / ".git").read_text().strip()
        self.assertTrue(entry.startswith("gitdir: "), entry)
        admin = Path(entry.removeprefix("gitdir: "))
        if not admin.is_absolute():
            admin = path / admin
        self.assertEqual(Path((admin / "gitdir").read_text().strip()).resolve(),
                         (path / ".git").resolve())
        self.assertEqual(admin.resolve().parent, (self.repo.work / ".git/worktrees").resolve())


class RefOwnershipTests(LoopCase):
    def test_a_branch_and_a_tag_an_agent_creates_are_deleted(self):
        run = self.run_fixture(tags=True, branches=True)
        observed = []
        review = run.agents.review

        def observe_cleanup(vendor, role, req, design, worktree, *args, **kwargs):
            self.assert_registered_gitfile(worktree)
            observed.append(worktree)
            return review(vendor, role, req, design, worktree, *args, **kwargs)

        run.agents.review = observe_cleanup
        run.engine.run()
        self.assert_done(run)
        self.assertTrue(observed, "the config must be inspected before the worktree is removed")
        expected = ["refs/heads/agent-branch-2", "refs/tags/agent-probe-2"]
        for ref in expected:
            self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", ref).returncode, 0)
        self.assertEqual([e["refs"] for e in self.events(run, "agent_refs_deleted")], [expected])

    def test_only_this_worktrees_ref_changes_are_undone(self):
        run = self.run_fixture(n=7)
        base = git("rev-parse", "HEAD", cwd=self.repo.work)
        first = self.commit_object("first independent commit", base)
        second = self.commit_object("second independent commit", first)
        third = self.commit_object("third independent commit", second)
        moved = "refs/heads/existing/topic"
        deleted = "refs/tags/existing/release"
        raced = "refs/heads/shared/topic"
        human_moved = "refs/heads/person/existing"
        for ref in (moved, deleted, raced, human_moved):
            git("update-ref", ref, base, cwd=self.repo.work)
        created = ["refs/heads/worker/scratch-seven", "refs/tags/worker/scratch-seven"]
        human_created = ["refs/heads/person/during-call", "refs/tags/person/during-call"]
        implement = run.agents.implement
        observations = []

        def manipulate(vendor, req, design, worktree, feedback):
            # No env marker or wrapper: these are ordinary Git subprocesses in each cwd.
            for ref in human_created:
                git("update-ref", ref, second, cwd=self.repo.work)
            git("update-ref", human_moved, third, cwd=self.repo.work)
            for ref in created:
                git("update-ref", ref, first, cwd=worktree)
                git("update-ref", ref, second, cwd=worktree)
            git("update-ref", moved, first, cwd=worktree)
            git("update-ref", moved, second, cwd=worktree)
            git("update-ref", "-d", deleted, cwd=worktree)
            git("update-ref", raced, first, cwd=worktree)
            git("update-ref", raced, third, cwd=self.repo.work)
            # Inspect during the call: cleanup must never have to undo an agent
            # mutation in the shared repository.
            for ref in (moved, deleted):
                self.assertEqual(git("rev-parse", ref, cwd=self.repo.work), base)
            self.assertEqual(git("rev-parse", raced, cwd=self.repo.work), third)
            for ref in created:
                self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", ref).returncode, 0)
            observations.append(True)
            return implement(vendor, req, design, worktree, feedback)

        run.agents.implement = manipulate
        review = run.agents.review

        def inspect(vendor, role, req, design, worktree, *args, **kwargs):
            self.assert_registered_gitfile(worktree)
            return review(vendor, role, req, design, worktree, *args, **kwargs)

        run.agents.review = inspect
        run.engine.run()
        self.assert_done(run)
        self.assertEqual(len(observations), 1)
        expected = {moved: base, deleted: base, raced: third, human_moved: third,
                    **{ref: second for ref in human_created}}
        for ref, sha in expected.items():
            with self.subTest(ref=ref):
                self.assertEqual(git("rev-parse", ref, cwd=self.repo.work), sha)
        for ref in created:
            self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", ref).returncode, 0)
        self.assertEqual([e["refs"] for e in self.events(run, "agent_refs_deleted")], [created])
        discarded = {ref for e in self.events(run, "agent_ref_changes_discarded") for ref in e["refs"]}
        self.assertEqual(discarded, {moved, deleted, raced})

    def test_check_author_refs_are_also_attributed_and_person_refs_survive(self):
        run = self.run_fixture(n=19)
        write_checks = run.agents.write_checks
        agent_refs = ["refs/heads/check-author/topic", "refs/tags/check-author/probe"]
        person_refs = ["refs/heads/person/check-window", "refs/tags/person/check-window"]
        oid = git("rev-parse", "HEAD", cwd=self.repo.work)

        def write(vendor, req, design, worktree, feedback=None):
            for ref in agent_refs:
                git("update-ref", ref, oid, cwd=worktree)
            for ref in person_refs:
                git("update-ref", ref, oid, cwd=self.repo.work)
            return write_checks(vendor, req, design, worktree, feedback)

        run.agents.write_checks = write
        run.engine.run()
        self.assert_done(run)
        for ref in person_refs:
            self.assertEqual(git("rev-parse", ref, cwd=self.repo.work), oid)
        for ref in agent_refs:
            self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", ref).returncode, 0)
        self.assertEqual([e["refs"] for e in self.events(run, "agent_refs_deleted")], [agent_refs])


class ConcurrentRunsTests(LoopCase):
    def test_a_branch_another_run_creates_during_an_agent_call_survives(self):
        a = self.run_fixture(n=30, root=13)
        b = self.run_fixture(n=34, root=34)
        a_inside, b_inside, a_absorbed, b_done = (threading.Event() for _ in range(4))
        release_a, release_b = threading.Event(), threading.Event()
        errors = []
        threads = []

        def wait(event, description):
            self.assertTrue(event.wait(WAIT), f"timed out waiting for {description}")

        def refs(run):
            return [f"refs/heads/agent-during-checks-{run.n}", f"refs/tags/agent-during-checks-{run.n}"]

        def block_checks(run, inside, release):
            original = run.agents.write_checks

            def call(vendor, req, design, worktree, feedback=None):
                result = original(vendor, req, design, worktree, feedback)
                for ref in refs(run):
                    git("update-ref", ref, git("rev-parse", "HEAD", cwd=worktree), cwd=worktree)
                git("add", "checks", cwd=worktree)
                inside.set()
                wait(release, f"release run {run.root}'s check author")
                return result

            run.agents.write_checks = call

        block_checks(a, a_inside, release_a)
        block_checks(b, b_inside, release_b)
        implement_a = a.agents.implement

        def hold_a_after_absorb(*args, **kwargs):
            a_absorbed.set()
            wait(b_done, "run B to land before run A")
            return implement_a(*args, **kwargs)

        a.agents.implement = hold_a_after_absorb

        def start(run, finished=None):
            def target():
                try:
                    run.engine.run()
                except BaseException as error:
                    errors.append(error)
                finally:
                    if finished is not None:
                        finished.set()
            thread = threading.Thread(target=target, daemon=True)
            threads.append(thread)
            thread.start()

        try:
            start(a)
            wait(a_inside, "run A's in-flight agent call")
            # B's branch does not exist when A starts; it is created in A's call window.
            self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", "feat/issue-34").returncode, 0)
            start(b, b_done)
            wait(b_inside, "run B's worktree and in-flight agent call")
            b_path = b.ws.dir / "issue-34"
            ref = "refs/heads/feat/issue-34"
            before_oid = git("rev-parse", ref, cwd=self.repo.work)
            before_tree = snapshot(b_path)
            b_index = Path(git("rev-parse", "--git-path", "index", cwd=b_path))
            if not b_index.is_absolute():
                b_index = b_path / b_index
            before_index = b_index.read_bytes()
            before_state = (b.store.dir / "state.json").read_bytes()
            before_git_file = (b_path / ".git").read_bytes()
            before_checks = (b_path / "checks/issue_34.sh").read_bytes()
            before_refs = {r: git("rev-parse", r, cwd=b_path) for r in refs(b)}
            release_a.set()
            wait(a_absorbed, "run A to finish absorbing its check author")
            self.assertEqual(git("rev-parse", ref, cwd=self.repo.work), before_oid)
            self.assertEqual(snapshot(b_path), before_tree)
            self.assertEqual(b_index.read_bytes(), before_index)
            self.assertEqual((b.store.dir / "state.json").read_bytes(), before_state)
            self.assertEqual((b_path / ".git").read_bytes(), before_git_file)
            self.assertEqual((b_path / "checks/issue_34.sh").read_bytes(), before_checks)
            for other_ref, oid in before_refs.items():
                self.assertEqual(git("rev-parse", other_ref, cwd=b_path), oid)
            self.assertEqual([e["refs"] for e in self.events(a, "agent_refs_deleted")], [refs(a)])
            release_b.set()
            wait(b_done, "run B to finish")
        finally:
            release_a.set()
            release_b.set()
            for thread in threads:
                thread.join(WAIT)
            self.assertTrue(all(not t.is_alive() for t in threads), "engine threads must terminate")
        self.assertEqual(errors, [])
        for run in (a, b):
            self.assert_done(run)
            self.assertEqual([e["refs"] for e in self.events(run, "agent_refs_deleted")], [refs(run)])
            for ref in refs(run):
                self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", ref).returncode, 0)
        self.assertNotIn("refs/heads/feat/issue-34",
                         [ref for e in self.events(a, "agent_refs_deleted") for ref in e["refs"]])

    def test_two_workspace_instances_exclude_each_others_shared_git_writes(self):
        a = Workspace(self.repo.work, 13, SHIP, base_dir=self.repo.loop_dir / "a")
        b = Workspace(self.repo.work, 34, SHIP, base_dir=self.repo.loop_dir / "b")
        attempting, entered, finished = (threading.Event() for _ in range(3))
        errors = []
        real_git = b.git

        def observe(*args, **kwargs):
            if args[0] == "fetch":
                entered.set()
            return real_git(*args, **kwargs)

        def contender():
            attempting.set()
            try:
                b.fetch()
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        b.git = observe
        thread = threading.Thread(target=contender, daemon=True)
        try:
            with a._mutex:
                with a._mutex:  # existing nested Workspace calls require reentrancy
                    thread.start()
                    self.assertTrue(attempting.wait(WAIT))
                    self.assertFalse(entered.wait(0.3), "a separate Workspace fetched while the lock was held")
                self.assertFalse(entered.is_set(), "leaving an inner acquisition must keep the outer lock")
            self.assertTrue(finished.wait(WAIT))
        finally:
            thread.join(WAIT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(entered.is_set())

    def test_shared_git_lock_also_excludes_an_independent_process(self):
        ws = Workspace(self.repo.work, 13, SHIP, base_dir=self.repo.loop_dir / "parent")
        # A process-local or class-level RLock cannot satisfy this probe.
        code = "\n".join([
            "import sys", "from pathlib import Path",
            "sys.path.insert(0, sys.argv[1])",
            "from implement_loop.workspace import Workspace",
            "ws = Workspace(Path(sys.argv[2]), 34, Path(sys.argv[3]), base_dir=Path(sys.argv[4]))",
            "print('ready', flush=True)", "ws.fetch()", "print('fetched', flush=True)",
        ])
        ready, output = threading.Event(), []
        proc = None

        def read_ready():
            output.append(proc.stdout.readline())
            ready.set()

        try:
            with ws._mutex:
                proc = subprocess.Popen([sys.executable, "-c", code,
                                         str(Path(__file__).resolve().parents[1]),
                                         str(self.repo.work), str(SHIP), str(self.repo.loop_dir / "child")],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                reader = threading.Thread(target=read_ready, daemon=True)
                reader.start()
                self.assertTrue(ready.wait(WAIT), "child must reach the fetch probe")
                reader.join(WAIT)
                self.assertEqual(output, ["ready\n"])
                with self.assertRaises(subprocess.TimeoutExpired,
                                       msg="the child fetched while another process held the shared lock"):
                    proc.wait(timeout=0.3)
            stdout, stderr = proc.communicate(timeout=WAIT)
            self.assertEqual(proc.returncode, 0, stderr)
            self.assertEqual(stdout, "fetched\n")
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=WAIT)


class MissingBranchRecoveryTests(LoopCase):
    def prepared_resume(self, *, checks=False, dirty=False, candidate=None, anchor_field=None):
        files = {"docs/task.txt": "implemented task", "docs/recovered.txt": "newer committed work",
                 "docs/untracked.txt": "untracked work"}
        run = self.run_fixture(files=files)
        step = run.engine._step_checks

        def stop_after_checks(n):
            step(n)
            (run.store.dir / "STOP").write_text("stop at a safe phase boundary\n")

        with mock.patch.object(run.engine, "_step_checks", stop_after_checks):
            run.engine.run()
        st = run.store.issue(run.n)
        self.assertEqual(st.phase, Phase.IMPLEMENT)
        wt = Path(st.worktree)
        recorded = st.checks_sha
        (wt / "docs").mkdir(exist_ok=True)
        (wt / "docs/recovered.txt").write_text("newer committed work\n")
        git("add", "docs/recovered.txt", cwd=wt)
        git("commit", "-qm", "work committed after the engine saved state", cwd=wt)
        latest = git("rev-parse", "HEAD", cwd=wt)
        self.assertNotEqual(latest, recorded)
        if dirty:
            (wt / "docs/task.txt").write_text("staged work\n")
            git("add", "docs/task.txt", cwd=wt)
            (wt / "docs/task.txt").write_text("unstaged work\n")
            (wt / "docs/untracked.txt").write_text("untracked work\n")
        tree_snapshot = snapshot(wt)
        file_snapshot = {p: (wt / p).read_bytes() for p in files if (wt / p).exists()}
        if candidate == "unrelated":
            bad = self.commit_object("parentless entry newer than the recoverable work")
            git("update-ref", "HEAD", bad, cwd=wt)
        elif candidate == "behind-anchor":
            # This shares main's history, but lacks the checks commit recorded in state.
            bad = self.commit_object("sibling entry that lacks the engine anchor", st.base_sha)
            git("update-ref", "HEAD", bad, cwd=wt)
        elif candidate == "behind-later-anchor":
            # The latest entry descends from checks_sha, but a later recorded engine sha
            # proves additional work must survive. Check each such field independently.
            setattr(st, anchor_field, latest)
            bad = self.commit_object("sibling after checks but before a later anchor", recorded)
            git("update-ref", "HEAD", bad, cwd=wt)
        ref = git("symbolic-ref", "HEAD", cwd=wt)
        git("update-ref", "-d", ref, cwd=self.repo.work)
        self.assertNotEqual(git_result(wt, "rev-parse", "--verify", "HEAD").returncode, 0)
        self.assertEqual(git("symbolic-ref", "HEAD", cwd=wt), ref)
        if candidate == "none":
            log = Path(git("rev-parse", "--git-path", "logs/HEAD", cwd=wt))
            if not log.is_absolute():
                log = wt / log
            log.write_text("")
        st.phase, st.park_kind, st.parked_version = Phase.PARKED, "engine_error", "0.3.0"
        st.resume_phase = "checks" if checks else "implement"
        st.retry, st.reason = False, "historical cross-run ref deletion"
        if checks:
            st.worktree = None  # #34 crashed before _step_checks persisted this field.
        run.store.put(st)
        run.after = max(e["seq"] for e in self.events(run))
        run.wt, run.ref, run.latest = wt, ref, latest
        run.tree_snapshot, run.file_snapshot = tree_snapshot, file_snapshot
        run.engine = self.new_engine(run)
        return run

    def assert_recovered(self, run):
        self.assert_done(run, after=run.after)
        restored = self.events(run, "branch_restored", run.after)
        self.assertEqual(len(restored), 1)
        event = restored[0]
        self.assertEqual(event["sha"], run.latest)
        self.assertEqual(event["issue"], run.n)
        self.assertIn(event["branch"], (run.ref, run.ref.removeprefix("refs/heads/")))
        later_phases = self.events(run, "phase", run.after)
        self.assertTrue(later_phases)
        self.assertLess(event["seq"], min(e["seq"] for e in later_phases))
        self.assertEqual(self.events(run, "branch_restore_failed", run.after), [])
        self.assertEqual(git_result(self.repo.work, "merge-base", "--is-ancestor", run.latest,
                                    run.store.issue(run.n).reviewed_sha).returncode, 0)
        self.assertEqual(self.repo.main_file("docs/recovered.txt"), "newer committed work")

    def test_resume_restores_a_missing_branch_with_its_latest_commit(self):
        run = self.prepared_resume(dirty=True)
        implement = run.agents.implement
        observed = []

        def inspect(vendor, req, design, worktree, feedback):
            self.assertEqual(git("rev-parse", "HEAD", cwd=worktree), run.latest)
            self.assertEqual(snapshot(worktree), run.tree_snapshot,
                             "recreating a ref must preserve staged and unstaged changes")
            for path, content in run.file_snapshot.items():
                self.assertEqual((worktree / path).read_bytes(), content)
            self.assertTrue(self.events(run, "branch_restored", run.after))
            observed.append(True)
            return implement(vendor, req, design, worktree, feedback)

        run.agents.implement = inspect
        run.engine.run()
        self.assertEqual(observed, [True])
        self.assert_recovered(run)

    def test_checks_resume_finds_the_worktree_when_state_has_no_worktree_path(self):
        run = self.prepared_resume(checks=True)
        self.assertIsNone(run.store.issue(run.n).worktree)
        run.engine.run()
        self.assert_recovered(run)

    def test_newest_parentless_reflog_entry_is_rejected(self):
        run = self.prepared_resume(candidate="unrelated")
        run.engine.run()
        self.assert_recovered(run)

    def test_newest_entry_sharing_main_but_missing_a_recorded_anchor_is_rejected(self):
        run = self.prepared_resume(candidate="behind-anchor")
        run.engine.run()
        self.assert_recovered(run)

    def test_all_recorded_commit_anchors_constrain_recovery(self):
        for field in ("head_sha", "verified_sha", "reviewed_sha"):
            with self.subTest(anchor=field):
                # A fresh repository keeps each resumed issue and its reflog independent.
                previous_repo = self.repo
                self.repo = TempRepo()
                try:
                    run = self.prepared_resume(candidate="behind-later-anchor", anchor_field=field)
                    run.engine.run()
                    self.assert_recovered(run)
                finally:
                    self.repo.cleanup()
                    self.repo = previous_repo

    def test_a_recorded_sha_that_no_longer_exists_is_not_a_recovery_anchor(self):
        run = self.prepared_resume()
        st = run.store.issue(run.n)
        st.head_sha = "0" * len(run.latest)
        run.store.put(st)
        run.engine.run()
        self.assert_recovered(run)

    def test_no_usable_reflog_parks_without_guessing_or_resetting(self):
        run = self.prepared_resume(dirty=True, candidate="none")
        before = snapshot(run.wt)
        git_file = (run.wt / ".git").read_bytes()
        run.engine.run()
        self.assertEqual(run.store.issue(run.n).phase, Phase.PARKED)
        self.assertEqual(self.events(run, "step_crashed", run.after), [])
        self.assertEqual(self.events(run, "branch_restored", run.after), [])
        failed = self.events(run, "branch_restore_failed", run.after)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["issue"], run.n)
        self.assertIn(run.ref.removeprefix("refs/heads/"), run.store.issue(run.n).reason)
        self.assertNotEqual(git_result(self.repo.work, "rev-parse", "--verify", run.ref).returncode, 0)
        self.assertEqual(snapshot(run.wt), before)
        self.assertEqual((run.wt / ".git").read_bytes(), git_file)
        for path, content in run.file_snapshot.items():
            self.assertEqual((run.wt / path).read_bytes(), content)
        self.assertEqual(self.events(run, "implemented", run.after), [])


class VersionTests(LoopCase):
    def test_version_is_newer_than_the_release_that_parked_this_fault(self):
        self.assertGreater(tuple(int(p) for p in implement_loop.VERSION.split(".")), (0, 3, 0))

    def test_old_version_engine_error_resumes_without_retry_or_requirements_changes(self):
        run = self.run_fixture(n=23, root=23)
        run.engine._reconcile()
        st = run.store.issue(run.n)
        body_hash = st.body_hash
        st.phase, st.park_kind, st.parked_version = Phase.PARKED, "engine_error", "0.3.0"
        st.resume_phase, st.retry, st.reason = "design", False, "historical ref fault"
        run.store.put(st)
        run.engine = self.new_engine(run)
        run.engine.run()
        self.assert_done(run)
        resumed = self.events(run, "resumed")
        self.assertEqual(len(resumed), 1)
        self.assertEqual((resumed[0]["phase"], resumed[0]["retry"]), ("design", False))
        self.assertEqual(run.store.issue(run.n).body_hash, body_hash)
        self.assertEqual(self.events(run, "requirements_changed"), [])


if __name__ == "__main__":
    unittest.main()

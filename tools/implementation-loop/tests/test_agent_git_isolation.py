"""#78 acceptance checks for the private git-directory agent boundary.

Real Git and the engine run against a local bare remote. Scripted workers deliberately
interleave their own ref writes with writes from the original checkout. No external
services, timing-dependent races, or implementation recorder helpers are used.
"""

import json
import shlex
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from helpers import SHIP, TempRepo, git, issue_body
from implement_loop.agents import FakeAgents, Script
from implement_loop.config import Caps, Config
from implement_loop.engine import Engine
from implement_loop.github import FakeGitHub
from implement_loop.graph import build_plan
from implement_loop.live import LiveAgents
from implement_loop.model import Finding, Phase
from implement_loop.state import RunStore
from implement_loop.workspace import GitError, Workspace


WAIT = 60


def result(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True)


def git_path(path, name):
    p = Path(git("rev-parse", "--git-path", name, cwd=path))
    return p if p.is_absolute() else path / p


def git_dir(path):
    p = Path(git("rev-parse", "--absolute-git-dir", cwd=path))
    return p.resolve()


def ref_files(common):
    """Byte-level snapshot, including packed refs, to catch transient shared writes."""
    paths = list((common / "refs").rglob("*"))
    if (common / "packed-refs").exists():
        paths.append(common / "packed-refs")
    return {str(p.relative_to(common)): p.read_bytes() for p in paths if p.is_file()}


class IsolationCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.addCleanup(self.repo.cleanup)
        self.n = 17
        self.files = {"docs/result.txt": "the requested result"}
        self.script = Script(files=self.files)
        self.gh = FakeGitHub(on_merge=self.repo.merge)
        self.gh.add_issue(self.n, "Isolated worker", issue_body(
            "feat/isolated-worker", ["Keep the requested result."], ["The check passes."]),
            labels=("size:M",))
        self.agents = FakeAgents({self.n: self.script})
        self.store = RunStore.for_root(self.repo.work, self.n)
        self.ws = Workspace(self.repo.work, self.n, SHIP, base_dir=self.repo.loop_dir / "this-run")
        self.engine = self.new_engine()

    def new_engine(self):
        return Engine(build_plan(self.gh, self.n, self.repo.work), self.store, self.gh,
                      self.ws, self.agents, Config(repo="test/test", caps=Caps(ci_poll_s=0)),
                      repo_root=self.repo.work, log=lambda _: None, sleep=lambda _: None)

    def events(self, kind):
        return [e for e in self.store.events() if e["kind"] == kind]

    def assert_done(self):
        self.assertEqual(self.events("step_crashed"), [])
        self.assertEqual(self.store.issue(self.n).phase, Phase.DONE,
                         json.dumps(self.store.events(), indent=1))
        for path, content in self.files.items():
            self.assertEqual(self.repo.main_file(path), content)

    def commit_object(self, message, parent=None):
        tree = git("rev-parse", "HEAD^{tree}", cwd=self.repo.work)
        args = ["commit-tree", tree, "-m", message]
        if parent:
            args += ["-p", parent]
        return git(*args, cwd=self.repo.work)

    def assert_ref(self, path, ref, oid):
        if oid is None:
            self.assertNotEqual(result(path, "rev-parse", "--verify", ref).returncode, 0, ref)
        else:
            self.assertEqual(git("rev-parse", "--verify", ref, cwd=path), oid, ref)

    def worktree(self):
        return self.ws.issue_worktree(self.n, "feat/isolated-worker")

    def assert_registered(self, wt, original):
        self.assertEqual((wt / ".git").read_bytes(), original)
        admin = git_dir(wt)
        self.assertEqual(Path((admin / "gitdir").read_text().strip()).resolve(),
                         (wt / ".git").resolve())
        self.assertEqual(admin.parent, (self.ws.common_dir() / "worktrees").resolve())


class InterleavedRefUpdateTests(IsolationCase):
    def interleave(self, suffix, initial, operations):
        base = git("rev-parse", "HEAD", cwd=self.repo.work)
        values = {"A": base, "B": self.commit_object("outside value B", base)}
        values["C"] = self.commit_object("outside value C", values["B"])
        ref = f"refs/{suffix}"
        if initial:
            git("update-ref", ref, values[initial], cwd=self.repo.work)
        implement = self.agents.implement
        observed = []
        expected = [values[initial] if initial else None]

        def worker(vendor, req, design, wt, feedback):
            shared = expected[0]
            for actor, value in operations:
                where = wt if actor == "agent" else self.repo.work
                if value is None:
                    git("update-ref", "-d", ref, cwd=where)
                else:
                    git("update-ref", ref, values[value], cwd=where)
                if actor == "external":
                    shared = values[value] if value else None
                # Assert during the window, after each operation. Value-based undo at
                # the end cannot meet this contract, even for ABA or same-OID reuse.
                self.assert_ref(self.repo.work, ref, shared)
            expected[0] = shared
            observed.append(True)
            return implement(vendor, req, design, wt, feedback)

        self.agents.implement = worker
        self.engine.run()
        self.assert_done()
        self.assertEqual(observed, [True])
        self.assert_ref(self.repo.work, ref, expected[0])

    def test_existing_branch_agent_external_agent(self):
        self.interleave("heads/shared/alternating", "A",
                        [("agent", "B"), ("external", "C"), ("agent", "B")])

    def test_agent_created_tag_moved_externally_then_by_agent(self):
        self.interleave("tags/shared/new-tag", None,
                        [("agent", "B"), ("external", "C"), ("agent", "A")])

    def test_agent_created_branch_deleted_externally_and_recreated_by_agent(self):
        self.interleave("heads/shared/deleted", None,
                        [("agent", "B"), ("external", None), ("agent", "C")])

    def test_existing_tag_deleted_by_agent_and_recreated_externally(self):
        self.interleave("tags/shared/old-tag", "A",
                        [("agent", None), ("external", None), ("external", "C")])

    def test_same_oid_delete_recreate_is_still_external_ownership(self):
        self.interleave("heads/shared/same-oid", None,
                        [("agent", "B"), ("external", "B"), ("external", None),
                         ("external", "B"), ("agent", "B")])

    def test_external_aba_cycle_between_agent_updates(self):
        self.interleave("tags/shared/aba-cycle", "A",
                        [("agent", "C"), ("external", "B"), ("external", "A"),
                         ("agent", "B")])

    def test_external_deletion_of_existing_ref_stays_deleted(self):
        self.interleave("heads/shared/remove-old", "A",
                        [("agent", "B"), ("external", None), ("agent", "C")])

    def test_outside_commit_on_the_issue_branch_survives_absorption(self):
        implement = self.agents.implement
        observed = []

        def worker(vendor, req, design, wt, feedback):
            before = git("rev-parse", "HEAD", cwd=wt)
            own = git("symbolic-ref", "HEAD", cwd=wt)
            external = self.commit_object("person advanced active issue branch", before)
            git("update-ref", own, external, before, cwd=self.repo.work)
            answer = implement(vendor, req, design, wt, feedback)
            git("add", "--all", cwd=wt)
            git("commit", "-qm", "private worker commit", cwd=wt)
            agent_head = git("rev-parse", "HEAD", cwd=wt)
            self.assertNotEqual(agent_head, external)
            self.assert_ref(self.repo.work, own, external)
            observed.append((before, external, agent_head))
            return answer

        self.agents.implement = worker
        self.engine.run()
        self.assert_done()
        self.assertEqual(len(observed), 1)
        before, external, agent_head = observed[0]
        head = self.store.issue(self.n).reviewed_sha
        self.assertEqual(result(self.repo.work, "merge-base", "--is-ancestor", external, head).returncode, 0)
        events = self.events("issue_branch_moved_externally")
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["from"], events[0]["to"]), (before, external))
        absorbed = self.events("agent_commits_absorbed")
        self.assertTrue(any(e["from_head"] == agent_head and e["to"] == before for e in absorbed))

    def test_finding_verifier_refs_never_reach_the_shared_repository(self):
        wt = self.worktree()
        original = (wt / ".git").read_bytes()
        live = LiveAgents("claude", self.store.dir, self.ws)
        refs = ["refs/heads/verifier/temporary", "refs/tags/verifier/temporary"]
        observed = []

        def verifier(vendor, role, scratch, prompt, number):
            self.assertEqual(role, "verify_finding")
            self.assertNotEqual(scratch, wt)
            for ref in refs:
                git("update-ref", ref, "HEAD", cwd=scratch)
                self.assert_ref(self.repo.work, ref, None)
            observed.append(scratch)
            return {"reproduced": False}

        self.engine._reconcile()
        finding = Finding(id="isolation-probe", reviewer="cross", priority=1,
                          confidence=1.0, title="Probe scratch isolation", file="README.md", line=1)
        with mock.patch.object(live, "call", verifier):
            self.assertFalse(live.verify_finding("claude", self.engine._req(self.n), wt, finding))
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0].exists())
        self.assert_registered(wt, original)
        for ref in refs:
            self.assert_ref(self.repo.work, ref, None)


class AgentGitDirTests(IsolationCase):
    def test_switching_or_detaching_private_head_keeps_the_source_branch_and_files(self):
        for detach in (False, True):
            with self.subTest(detached=detach):
                wt = self.worktree()
                before = git("rev-parse", "HEAD", cwd=wt)
                own = git("symbolic-ref", "HEAD", cwd=wt)
                original = (wt / ".git").read_bytes()
                with self.ws.agent_call(wt):
                    if detach:
                        git("checkout", "-q", "--detach", "HEAD", cwd=wt)
                    else:
                        git("checkout", "-q", "-b", "worker-branch", cwd=wt)
                    (wt / "head-probe.txt").write_text("working tree survives head changes\n")
                    git("add", "head-probe.txt", cwd=wt)
                    git("commit", "-qm", "private changed head", cwd=wt)
                    self.assert_ref(self.repo.work, own, before)
                self.assert_registered(wt, original)
                self.assertEqual(git("symbolic-ref", "HEAD", cwd=wt), own)
                self.assert_ref(wt, "HEAD", before)
                self.assert_ref(self.repo.work, "refs/heads/worker-branch", None)
                self.assertEqual((wt / "head-probe.txt").read_text(),
                                 "working tree survives head changes\n")
                # The first call intentionally left a working-tree file behind; the
                # next call still sees the source index, with that file untracked.


    def test_private_git_directory_never_changes_shared_refs_config_or_index(self):
        wt = self.worktree()
        common = self.ws.common_dir()
        base = git("rev-parse", "HEAD", cwd=wt)
        refs = ["refs/heads/person/topic", "refs/tags/person/version",
                "refs/remotes/person/topic", "refs/notes/person"]
        for ref in refs:
            git("update-ref", ref, base, cwd=self.repo.work)
        git("tag", "-a", "annotated-probe", "-m", "annotated tag", cwd=self.repo.work)
        git("pack-refs", "--all", cwd=self.repo.work)
        (wt / "staged.txt").write_text("staged version\n")
        git("add", "staged.txt", cwd=wt)
        (wt / "staged.txt").write_text("unstaged version\n")
        (wt / "untracked.txt").write_text("untracked version\n")
        index_path = git_path(wt, "index")
        index_before = index_path.read_bytes()
        status_before = result(wt, "status", "--porcelain=v1", "-z").stdout
        original = (wt / ".git").read_bytes()
        config_before = (common / "config").read_bytes()
        refs_before = ref_files(common)
        all_refs = git("for-each-ref", "--format=%(refname) %(objectname)", cwd=self.repo.work)
        with self.ws.agent_call(wt):
            private = git_dir(wt)
            self.assertTrue(private.is_relative_to(self.ws.dir.resolve()))
            self.assertFalse(private.is_relative_to(common.resolve()))
            self.assertEqual(git("rev-parse", "--show-toplevel", cwd=wt), str(wt))
            self.assertEqual(git("rev-parse", "--show-object-format", cwd=wt),
                             git("rev-parse", "--show-object-format", cwd=self.repo.work))
            self.assertEqual(git("for-each-ref", "--format=%(refname) %(objectname)", cwd=wt), all_refs)
            self.assertEqual(result(wt, "status", "--porcelain=v1", "-z").stdout, status_before)
            for ref in refs:
                git("update-ref", "-d", ref, cwd=wt)
                self.assertEqual(ref_files(common), refs_before)
            git("tag", "private-only", cwd=wt)
            (wt / "from-agent.txt").write_text("keep this working tree\n")
            git("add", "--all", cwd=wt)
            git("commit", "-qm", "private commit", cwd=wt)
            private_head = git("rev-parse", "HEAD", cwd=wt)
            self.assertNotEqual(private_head, base)
            self.assertNotEqual(result(self.repo.work, "cat-file", "-e", private_head).returncode, 0,
                                "new objects must go to the private object store")
            self.assertEqual(ref_files(common), refs_before)
            self.assertEqual((common / "config").read_bytes(), config_before)
            self.assertEqual(index_path.read_bytes(), index_before)
        self.assert_registered(wt, original)
        self.assertFalse(private.exists())
        self.assertEqual(ref_files(common), refs_before)
        self.assertEqual((common / "config").read_bytes(), config_before)
        self.assertEqual(index_path.read_bytes(), index_before)
        self.assertEqual((wt / "from-agent.txt").read_text(), "keep this working tree\n")
        self.assert_ref(wt, "HEAD", base)

    def test_split_index_and_worktree_config_are_readable_in_the_private_repository(self):
        wt = self.worktree()
        common = self.ws.common_dir()
        git("config", "extensions.worktreeConfig", "true", cwd=self.repo.work)
        git("config", "isolation.shared", "common value", cwd=self.repo.work)
        git("config", "--worktree", "isolation.shared", "worktree override", cwd=wt)
        git("config", "--worktree", "user.name", "Worktree Worker", cwd=wt)
        git("config", "--worktree", "user.email", "worktree@example.invalid", cwd=wt)
        (wt / "split-index.txt").write_text("staged split index content\n")
        git("add", "split-index.txt", cwd=wt)
        git("update-index", "--split-index", cwd=wt)
        shared_index = Path(git("rev-parse", "--shared-index-path", cwd=wt))
        if not shared_index.is_absolute():
            shared_index = wt / shared_index
        self.assertTrue(shared_index.is_file(), "the fixture must really use a split index")
        entries = result(wt, "ls-files", "--stage", "-z").stdout
        index = git_path(wt, "index")
        before = index.read_bytes()
        config = (common / "config").read_bytes()
        worktree_config = git_path(wt, "config.worktree")
        local_config = worktree_config.read_bytes()
        with self.ws.agent_call(wt):
            self.assertEqual(result(wt, "ls-files", "--stage", "-z").stdout, entries)
            self.assertEqual(git("config", "--get", "isolation.shared", cwd=wt), "worktree override")
            self.assertEqual(git("config", "--get", "user.name", cwd=wt), "Worktree Worker")
            git("commit", "-qm", "commit from copied split index", cwd=wt)
            self.assertEqual(git("show", "-s", "--format=%an <%ae>", "HEAD", cwd=wt),
                             "Worktree Worker <worktree@example.invalid>")
            self.assertEqual(index.read_bytes(), before)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual((common / "config").read_bytes(), config)
        self.assertEqual(worktree_config.read_bytes(), local_config)

    def test_info_excludes_attributes_and_operation_anchors_are_available(self):
        wt = self.worktree()
        common = self.ws.common_dir()
        info = common / "info"
        (info / "exclude").write_text("ignored-by-info.txt\n")
        (info / "attributes").write_text("README.md isolation=from-info\n")
        (wt / "ignored-by-info.txt").write_text("ignored local file\n")
        anchor = self.commit_object("operation anchor", git("rev-parse", "HEAD", cwd=wt))
        anchors = {}
        for name in ("ORIG_HEAD", "AUTO_MERGE", "MERGE_MSG", "MERGE_MODE"):
            value = (anchor + "\n") if name in ("ORIG_HEAD", "AUTO_MERGE") else "copied operation metadata\n"
            path = git_path(wt, name)
            path.write_text(value)
            anchors[name] = (path, path.read_bytes())
        with self.ws.agent_call(wt):
            self.assertEqual(git("check-ignore", "ignored-by-info.txt", cwd=wt), "ignored-by-info.txt")
            self.assertEqual(git("check-attr", "isolation", "--", "README.md", cwd=wt),
                             "README.md: isolation: from-info")
            for name, (_, content) in anchors.items():
                self.assertEqual(git_path(wt, name).read_bytes(), content)
        for path, content in anchors.values():
            self.assertEqual(path.read_bytes(), content)

    def hook_probe(self, mode):
        wt = self.worktree()
        if mode == "relative":
            hooks = wt / ".githooks"
            git("config", "core.hooksPath", ".githooks", cwd=self.repo.work)
        elif mode == "default":
            hooks = self.ws.common_dir() / "hooks"
            git("config", "--unset-all", "core.hooksPath", cwd=self.repo.work)
        else:
            hooks = self.repo.tmp / "original-hooks"
            git("config", "core.hooksPath", str(hooks), cwd=self.repo.work)
        hooks.mkdir(exist_ok=True)
        transcript = self.repo.tmp / "hook-transcript"
        for name in ("reference-transaction", "pre-commit"):
            hook = hooks / name
            hook.write_text("#!/bin/sh\n" +
                            f"printf '%s\\n' {shlex.quote(name)} \"$1\" >> {shlex.quote(str(transcript))}\n" +
                            (f"cat >> {shlex.quote(str(transcript))}\n" if name == "reference-transaction" else ""))
            hook.chmod(0o755)
        original = (wt / ".git").read_bytes()
        config_before = (self.ws.common_dir() / "config").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "intentional interruption"):
            with self.ws.agent_call(wt):
                private = git_dir(wt)
                git("tag", "hook-probe", cwd=wt)
                (wt / "hook-file.txt").write_text("hook content\n")
                git("add", "hook-file.txt", cwd=wt)
                git("commit", "-qm", "exercise original pre-commit", cwd=wt)
                self.assertEqual((self.ws.common_dir() / "config").read_bytes(), config_before)
                raise RuntimeError("intentional interruption")
        self.assert_registered(wt, original)
        self.assertFalse(private.exists(), "an exceptional call must remove its private git dir")
        self.assertEqual((self.ws.common_dir() / "config").read_bytes(), config_before)
        self.assert_ref(self.repo.work, "refs/tags/hook-probe", None)
        self.assertEqual((wt / "hook-file.txt").read_text(), "hook content\n")
        text = transcript.read_text()
        self.assertIn("pre-commit", text)
        self.assertIn("reference-transaction\nprepared\n", text)
        self.assertIn("reference-transaction\ncommitted\n", text)
        self.assertIn("refs/tags/hook-probe", text)

    def test_absolute_hooks_fire_and_gitfile_is_restored_after_an_exception(self):
        self.hook_probe("absolute")

    def test_relative_hooks_still_fire(self):
        self.hook_probe("relative")

    def test_default_hooks_still_fire(self):
        self.hook_probe("default")

    def killed_call(self):
        wt = self.worktree()
        original = (wt / ".git").read_bytes()
        base = git("rev-parse", "HEAD", cwd=wt)
        code = "\n".join([
            "import sys", "from pathlib import Path", "sys.path.insert(0, sys.argv[1])",
            "from implement_loop.workspace import Workspace",
            "ws = Workspace(Path(sys.argv[2]), 17, Path(sys.argv[3]), base_dir=Path(sys.argv[4]))",
            "with ws.agent_call(Path(sys.argv[5])):",
            "    print('attached', flush=True)", "    sys.stdin.read()",
        ])
        proc = subprocess.Popen([sys.executable, "-c", code,
                                 str(Path(__file__).resolve().parents[1]), str(self.repo.work),
                                 str(SHIP), str(self.ws.dir), str(wt)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        ready, lines = threading.Event(), []

        def reader():
            lines.append(proc.stdout.readline())
            ready.set()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(WAIT), "child did not attach its private git directory")
            self.assertEqual(lines, ["attached\n"])
            private = git_dir(wt)
            self.assertTrue(private.is_relative_to(self.ws.dir.resolve()))
            self.assertNotEqual((wt / ".git").read_bytes(), original)
        finally:
            proc.kill()
            proc.communicate(timeout=WAIT)
            thread.join(WAIT)
        self.assertTrue(private.exists(), "SIGKILL leaves a stale attachment for recovery")
        return wt, original, base, private

    def test_reusing_a_worktree_reattaches_after_a_killed_call(self):
        wt, original, base, private = self.killed_call()
        self.assertEqual(self.worktree(), wt)
        self.assert_registered(wt, original)
        self.assert_ref(wt, "HEAD", base)
        self.assertFalse(private.exists())

    def test_restore_branch_first_reattaches_a_killed_call(self):
        wt, original, base, private = self.killed_call()
        ref = "refs/heads/feat/isolated-worker"
        git("update-ref", "-d", ref, cwd=self.repo.work)
        self.ws.restore_branch(wt, [base])
        self.assert_registered(wt, original)
        self.assert_ref(self.repo.work, ref, base)
        self.assertFalse(private.exists())

    def test_engine_worktree_recovery_reattaches_a_killed_call(self):
        wt, original, base, private = self.killed_call()
        self.engine._reconcile()
        self.engine._recover_worktree(self.n, wt)
        self.assert_registered(wt, original)
        self.assert_ref(wt, "HEAD", base)
        self.assertFalse(private.exists())
        self.assertEqual(self.events("worktree_recovery_failed"), [])

    def test_remove_reattaches_a_killed_call_before_removing_the_worktree(self):
        wt, original, base, private = self.killed_call()
        self.ws.remove(wt)
        self.assertFalse(wt.exists())
        self.assertFalse(private.exists())
        self.assertNotIn(str(wt), git("worktree", "list", "--porcelain", cwd=self.repo.work))
        self.assert_ref(self.repo.work, "refs/heads/feat/isolated-worker", base)

    def test_agent_call_rejects_a_checkout_with_a_git_directory(self):
        before = (self.ws.common_dir() / "config").read_bytes()
        with self.assertRaises(GitError):
            with self.ws.agent_call(self.repo.work):
                self.fail("a primary checkout must not be attached by replacing its .git directory")
        self.assertTrue((self.repo.work / ".git").is_dir())
        self.assertEqual((self.ws.common_dir() / "config").read_bytes(), before)


class MergeStateTests(IsolationCase):
    def prepare_conflict(self, *, locked=False):
        self.script.lines = {"README.md": "issue-side"}
        # Stop after the first honest implementation; it has committed an append to
        # README. Main then independently appends, yielding a real same-hunk conflict.
        step = self.engine._step_implement

        def stop(n):
            step(n)
            (self.store.dir / "STOP").write_text("stop after implementing\n")

        with mock.patch.object(self.engine, "_step_implement", stop):
            self.engine.run()
        self.assertEqual(self.store.issue(self.n).phase, Phase.VERIFY)
        wt = Path(self.store.issue(self.n).worktree)
        git("checkout", "-q", "main", cwd=self.repo.merger)
        (self.repo.merger / "README.md").write_text("test repo\nmain-side\n")
        (self.repo.merger / "main-only.txt").write_text("retain main's new file\n")
        if locked:
            check = f"checks/issue_{self.n}.sh"
            target = self.repo.merger / check
            target.parent.mkdir(exist_ok=True)
            target.write_text((wt / check).read_text() + "test -e main-only.txt\n")
        git("add", "--all", cwd=self.repo.merger)
        git("commit", "-qm", "person advances main independently", cwd=self.repo.merger)
        git("push", "-q", "origin", "HEAD:main", cwd=self.repo.merger)
        main = git("rev-parse", "HEAD", cwd=self.repo.merger)
        st = self.store.issue(self.n)
        st.phase = Phase.IMPLEMENT
        self.store.put(st)
        (self.store.dir / "STOP").unlink()
        self.engine = self.new_engine()
        return wt, main

    def drop_merge(self, action):
        wt, main = self.prepare_conflict()
        implement = self.agents.implement
        seen = []

        def worker(vendor, req, design, path, feedback):
            self.assertEqual(git("rev-parse", "MERGE_HEAD", cwd=path), main)
            if action == "abort":
                git("merge", "--abort", cwd=path)
            elif action == "quit":
                git("merge", "--quit", cwd=path)
            else:
                git("reset", "--hard", "HEAD", cwd=path)
            # Resolve marker text too: lack of markers alone must not convince the
            # engine to conclude a merge the private worker explicitly dropped.
            answer = implement(vendor, req, design, path, feedback)
            self.assertNotEqual(result(path, "rev-parse", "--verify", "MERGE_HEAD").returncode, 0)
            seen.append(True)
            return answer

        self.agents.implement = worker
        step = self.engine._step_implement

        def stop(n):
            step(n)
            (self.store.dir / "STOP").write_text("inspect dropped merge\n")

        with mock.patch.object(self.engine, "_step_implement", stop):
            self.engine.run()
        self.assertEqual(seen, [True])
        self.assertEqual(self.events("step_crashed"), [])
        self.assertEqual(self.store.issue(self.n).phase, Phase.IMPLEMENT)
        self.assertEqual(len(self.events("agent_merge_dropped")), 1)
        self.assertEqual(len(self.events("conflict_unresolved")), 1)
        self.assertNotEqual(result(wt, "rev-parse", "--verify", "MERGE_HEAD").returncode, 0)
        self.assertEqual([c for c in self.gh.calls if c[0] == "merge_pr"], [])
        self.agents.implement = implement
        (self.store.dir / "STOP").unlink()
        self.engine = self.new_engine()
        self.engine.run()
        self.assert_done()
        self.assert_main_preserved(main)

    def assert_main_preserved(self, main):
        self.assertEqual(self.repo.main_file("main-only.txt"), "retain main's new file")
        content = self.repo.main_file("README.md")
        self.assertIn("main-side", content.splitlines())
        self.assertIn("issue-side", content.splitlines())
        self.assertNotIn("<<<<<<<", content)
        self.assertEqual(result(self.repo.work, "merge-base", "--is-ancestor", main,
                                self.store.issue(self.n).reviewed_sha).returncode, 0)

    def test_an_implementer_aborting_the_private_merge_returns_to_conflict_resolution(self):
        self.drop_merge("abort")

    def test_an_implementer_quitting_the_private_merge_returns_to_conflict_resolution(self):
        self.drop_merge("quit")

    def test_an_implementer_resetting_the_private_merge_returns_to_conflict_resolution(self):
        self.drop_merge("reset")

    def test_a_check_author_aborting_the_private_merge_returns_to_check_resolution(self):
        wt, main = self.prepare_conflict(locked=True)
        write_checks = self.agents.write_checks
        observed = []

        def worker(vendor, req, design, path, feedback=None):
            self.assertEqual(git("rev-parse", "MERGE_HEAD", cwd=path), main)
            self.assertEqual(design.check_files, [f"checks/issue_{self.n}.sh"])
            git("merge", "--abort", cwd=path)
            answer = write_checks(vendor, req, design, path, feedback)
            observed.append(True)
            return answer

        self.agents.write_checks = worker
        step = self.engine._step_implement

        def stop(n):
            step(n)
            (self.store.dir / "STOP").write_text("inspect dropped check repair\n")

        with mock.patch.object(self.engine, "_step_implement", stop):
            self.engine.run()
        self.assertEqual(observed, [True])
        self.assertEqual(self.events("step_crashed"), [])
        self.assertEqual(self.store.issue(self.n).phase, Phase.IMPLEMENT)
        self.assertEqual(len(self.events("agent_merge_dropped")), 1)
        self.assertEqual(len(self.events("check_conflict_unresolved")), 1)
        self.assertEqual([c for c in self.gh.calls if c[0] == "merge_pr"], [])
        self.assertNotEqual(result(wt, "rev-parse", "--verify", "MERGE_HEAD").returncode, 0)
        self.agents.write_checks = write_checks
        (self.store.dir / "STOP").unlink()
        self.engine = self.new_engine()
        self.engine.run()
        self.assert_done()
        self.assert_main_preserved(main)
        self.assertIn("test -e main-only.txt", self.repo.main_file(f"checks/issue_{self.n}.sh"))

    def test_an_implementer_committing_the_private_merge_is_absorbed_and_lands(self):
        wt, main = self.prepare_conflict()
        implement = self.agents.implement
        observed = []

        def worker(vendor, req, design, path, feedback):
            self.assertEqual(git("rev-parse", "MERGE_HEAD", cwd=path), main)
            before = git("rev-parse", "HEAD", cwd=path)
            own = git("symbolic-ref", "HEAD", cwd=path)
            answer = implement(vendor, req, design, path, feedback)
            git("add", "--all", cwd=path)
            git("commit", "-qm", "worker commits main's resolved merge", cwd=path)
            agent_head = git("rev-parse", "HEAD", cwd=path)
            self.assert_ref(self.repo.work, own, before)
            self.assertEqual(result(path, "merge-base", "--is-ancestor", main, agent_head).returncode, 0)
            observed.append(agent_head)
            return answer

        self.agents.implement = worker
        self.engine.run()
        self.assert_done()
        self.assertEqual(len(observed), 1)
        self.assertTrue(any(e["from_head"] == observed[0] for e in self.events("agent_commits_absorbed")))
        self.assertEqual(self.events("agent_merge_dropped"), [])
        self.assert_main_preserved(main)


if __name__ == "__main__":
    unittest.main()

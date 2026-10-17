"""#78: private Git metadata must retain index-only executable intent.

These checks use real repositories and compare Git's public index/tree records.
With fileMode=false, the index is Git's only record of an executable bit that
differs from the file on disk. With fileMode=true, only the immediate handoff of
the index is guaranteed; subsequent staging follows Git's usual disk semantics.
"""

import signal
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import SHIP, git
from test_agent_git_isolation import IsolationCase


class AgentIndexModeTests(IsolationCase):
    def prepare(self, *, executable=False, filemode=False, name="tools/local task.py"):
        wt = self.worktree()
        path = wt / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print('original task')\n")
        path.chmod(0o755 if executable else 0o644)
        # Establish a real committed baseline before disabling filesystem mode
        # detection. All configuration is local to this temporary repository.
        git("config", "core.fileMode", "true", cwd=wt)
        self.assertIsNotNone(self.ws.commit_all(wt, "Seed mode fixture", "implement", self.n))
        git("config", "core.fileMode", str(filemode).lower(), cwd=wt)
        self.assert_index_mode(wt, name, "100755" if executable else "100644")
        return wt, name

    def index_record(self, wt, name):
        record = git("ls-files", "--stage", "--", name, cwd=wt)
        self.assertEqual(len(record.splitlines()), 1, record)
        metadata, actual_name = record.split("\t", 1)
        self.assertEqual(actual_name, name)
        mode, oid, stage = metadata.split()
        self.assertEqual(stage, "0")
        return record

    def assert_index_mode(self, wt, name, mode):
        record = self.index_record(wt, name)
        self.assertEqual(record.split(" ", 1)[0], mode)
        return record

    def assert_committed_record(self, wt, name, record):
        mode, oid, _ = record.split("\t", 1)[0].split()
        self.assertEqual(git("ls-tree", "HEAD", "--", name, cwd=wt),
                         f"{mode} blob {oid}\t{name}")

    def commit_and_assert(self, wt, name, record):
        self.assertIsNotNone(self.ws.commit_all(wt, "Keep executable intent", "implement", self.n))
        self.assertEqual(self.index_record(wt, name), record)
        self.assert_committed_record(wt, name, record)

    def test_staged_only_executable_bit_survives_handoff_and_commit_all(self):
        wt, name = self.prepare()
        original = (wt / ".git").read_bytes()
        with self.ws.agent_call(wt):
            git("update-index", "--chmod=+x", "--", name, cwd=wt)
            expected = self.assert_index_mode(wt, name, "100755")
        self.assert_registered(wt, original)
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o644)
        self.commit_and_assert(wt, name, expected)
        self.assertEqual(git("config", "--get", "core.fileMode", cwd=wt), "false")

    def test_privately_committed_executable_bit_and_new_blob_survive_commit_all(self):
        wt, name = self.prepare(name="scripts/another task.py")
        shared_head = git("rev-parse", "HEAD", cwd=wt)
        with self.ws.agent_call(wt):
            # The new content forces the mode handoff to carry a blob that did
            # not exist in the shared object store before this call.
            (wt / name).write_text("print('changed inside private repository')\n")
            git("add", "--", name, cwd=wt)
            git("update-index", "--chmod=+x", "--", name, cwd=wt)
            expected = self.assert_index_mode(wt, name, "100755")
            git("commit", "-qm", "Agent's private executable commit", cwd=wt)
            self.assert_committed_record(wt, name, expected)
            self.assertNotEqual(git("rev-parse", "HEAD", cwd=wt), shared_head)
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt), shared_head)
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o644)
        self.commit_and_assert(wt, name, expected)

    def test_removing_executable_bit_survives_handoff_and_commit_all(self):
        wt, name = self.prepare(executable=True, name="bin/previously-executable")
        with self.ws.agent_call(wt):
            git("update-index", "--chmod=-x", "--", name, cwd=wt)
            expected = self.assert_index_mode(wt, name, "100644")
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o755)
        self.commit_and_assert(wt, name, expected)

    def test_filemode_true_hands_back_index_only_executable_bit(self):
        wt, name = self.prepare(filemode=True)
        with self.ws.agent_call(wt):
            git("update-index", "--chmod=+x", "--", name, cwd=wt)
            expected = self.assert_index_mode(wt, name, "100755")
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o644)
        self.assertEqual(git("config", "--get", "core.fileMode", cwd=wt), "true")

    def test_reattach_after_sigkill_keeps_the_index_only_executable_bit(self):
        wt, name = self.prepare()
        original = (wt / ".git").read_bytes()
        code = "\n".join([
            "import os, signal, subprocess, sys",
            "from pathlib import Path",
            "sys.path.insert(0, sys.argv[1])",
            "from implement_loop.workspace import Workspace",
            "ws = Workspace(Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), base_dir=Path(sys.argv[5]))",
            "wt, name = Path(sys.argv[6]), sys.argv[7]",
            "with ws.agent_call(wt):",
            "    (wt / name).write_text('new content before abrupt death\\n')",
            "    subprocess.run(['git', 'add', '--', name], cwd=wt, check=True)",
            "    subprocess.run(['git', 'update-index', '--chmod=+x', '--', name], cwd=wt, check=True)",
            "    os.kill(os.getpid(), signal.SIGKILL)",
        ])
        proc = subprocess.run(
            [sys.executable, "-c", code, str(Path(__file__).resolve().parents[1]),
             str(self.repo.work), str(self.n), str(SHIP), str(self.ws.dir), str(wt), name],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, -signal.SIGKILL, proc.stderr)
        self.assertNotEqual((wt / ".git").read_bytes(), original)
        expected = self.assert_index_mode(wt, name, "100755")
        self.ws.reattach(wt)
        self.assert_registered(wt, original)
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(git("show", f":{name}", cwd=wt), "new content before abrupt death")
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o644)

    def test_exception_still_hands_back_the_executable_bit(self):
        wt, name = self.prepare()
        original = (wt / ".git").read_bytes()

        class WorkerFailed(Exception):
            pass

        with self.assertRaises(WorkerFailed):
            with self.ws.agent_call(wt):
                git("update-index", "--chmod=+x", "--", name, cwd=wt)
                expected = self.assert_index_mode(wt, name, "100755")
                raise WorkerFailed()
        self.assert_registered(wt, original)
        self.assertEqual(self.index_record(wt, name), expected)
        self.commit_and_assert(wt, name, expected)

    def test_disk_chmod_with_unchanged_private_index_does_not_override_shared_index(self):
        wt, name = self.prepare(filemode=True)
        before = self.index_record(wt, name)
        with self.ws.agent_call(wt):
            (wt / name).chmod(0o755)
            self.assertEqual(self.index_record(wt, name), before)
        self.assertEqual(self.index_record(wt, name), before)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o755)

    def test_untouched_preexisting_index_only_mode_is_preserved(self):
        wt, name = self.prepare()
        git("update-index", "--chmod=+x", "--", name, cwd=wt)
        before = self.assert_index_mode(wt, name, "100755")
        with self.ws.agent_call(wt):
            self.assertEqual(self.index_record(wt, name), before)
        self.assertEqual(self.index_record(wt, name), before)
        self.assertEqual(stat.S_IMODE((wt / name).stat().st_mode), 0o644)

    def test_unrelated_staged_and_unstaged_work_is_unchanged(self):
        wt, name = self.prepare()
        other = "docs/unrelated notes.txt"
        (wt / other).parent.mkdir(parents=True, exist_ok=True)
        (wt / other).write_text("staged notes\n")
        git("add", "--", other, cwd=wt)
        (wt / other).write_text("unstaged notes\n")
        before = self.index_record(wt, other)
        status_before = git("status", "--porcelain=v1", "--", other, cwd=wt)
        self.assertTrue(status_before)
        with self.ws.agent_call(wt):
            git("update-index", "--chmod=+x", "--", name, cwd=wt)
            expected = self.assert_index_mode(wt, name, "100755")
            # Even a private change to the unrelated index must not replace
            # its staged/unstaged split in the shared index.
            git("add", "--", other, cwd=wt)
        self.assertEqual(self.index_record(wt, name), expected)
        self.assertEqual(self.index_record(wt, other), before)
        self.assertEqual(git("status", "--porcelain=v1", "--", other, cwd=wt), status_before)
        self.assertEqual((wt / other).read_text(), "unstaged notes\n")


if __name__ == "__main__":
    unittest.main()

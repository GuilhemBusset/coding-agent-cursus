"""Git worktrees for a run, and the only code that commits or pushes.

Layout: `<repo parent>/<repo name>.loop/issue-<root>/` holds a detached coordination worktree
(`coord/`, at the remote base branch) and one worktree per active issue (`issue-<n>/`, on the
issue's branch). The engine creates and removes them itself.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


# A path as git records it: None (absent), ("link", target), ("dir",) or ("file", bytes, executable).
FileState = tuple | None


class GitError(RuntimeError):
    pass


class MergeConflict(GitError):
    """Bringing a branch up to date with the base branch hit conflicts in `files`. The failed
    operation was aborted: the worktree is clean, on its branch, at its previous head."""

    def __init__(self, message: str, files: list[str]):
        super().__init__(message)
        self.files = files


@dataclass
class UpdateResult:
    status: str               # "current" | "merged" | "conflict" (the merge is left in progress)
    files: list[str]          # the conflicted files
    before: str               # HEAD before the update
    main: str                 # the base branch's head that was merged


class Workspace:
    def __init__(self, repo_root: Path, root: int, ship_script: Path, base_dir: Path | None = None,
                 remote: str = "origin", base_branch: str = "main"):
        self.repo = repo_root
        self.remote = remote
        self.base = base_branch
        self.ship_script = ship_script
        self.dir = base_dir or repo_root.parent / f"{repo_root.name}.loop" / f"issue-{root}"
        # Worktrees share one repository: concurrent fetches, ref updates and worktree changes
        # contend for the same lock files, so every operation that writes shared state is serialized.
        self._mutex = threading.RLock()

    def git(self, *args: str, cwd: Path | None = None, check: bool = True, strip: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
        return proc.stdout.strip() if strip else proc.stdout

    def uncommitted(self, path: Path) -> list[str]:
        """Paths changed in the working tree, staged or not, including untracked files.

        Read NUL-delimited and unstripped: porcelain lines start with a two-letter status that
        may begin with a space (" M setup/package.json"), and stripping the output once cut the
        first path to "etup/package.json"."""
        out = self.git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=path, strip=False)
        paths, records = [], out.split("\0")
        i = 0
        while i < len(records):
            record = records[i]
            if len(record) > 3:
                paths.append(record[3:])
                if record[0] in "RC":   # a rename or copy is followed by its source path
                    i += 1
            i += 1
        return paths

    def index_entries(self, path: Path) -> dict[str, list[str]]:
        """The index, path by path: `ls-files --stage` records, one per stage (a conflicted
        path has up to three), in the form `git update-index --index-info` reads back."""
        entries: dict[str, list[str]] = {}
        for record in self.git("ls-files", "--stage", "-z", cwd=path, strip=False).split("\0"):
            if "\t" in record:
                entries.setdefault(record.split("\t", 1)[1], []).append(record)
        return entries

    def restore_index_entry(self, path: Path, name: str, entries: list[str]) -> None:
        """Put `name` back in the index exactly as `entries` (from `index_entries`) recorded it,
        conflict stages included; no entries removes it from the index."""
        removal = f"0 {'0' * len(self.head(path))}\t{name}"
        info = "".join(f"{record}\0" for record in [removal, *entries])
        proc = subprocess.run(["git", "update-index", "-z", "--index-info"], cwd=path, input=info,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitError(f"git update-index --index-info failed for {name}: {proc.stderr.strip()[:400]}")

    def fetch(self) -> None:
        with self._mutex:
            self.git("fetch", "--quiet", self.remote, self.base)

    def base_ref(self) -> str:
        return f"{self.remote}/{self.base}"

    # worktrees ---------------------------------------------------------------
    def coord(self) -> Path:
        with self._mutex:
            return self._coord()

    def _coord(self) -> Path:
        path = self.dir / "coord"
        self.fetch()
        if not (path / ".git").exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            self.git("worktree", "add", "--detach", "--quiet", str(path), self.base_ref())
        else:
            self.git("checkout", "--detach", "--quiet", self.base_ref(), cwd=path)
        self.provision(path)
        return path

    def coord_path(self) -> Path:
        """The coordination worktree for read-only agents, created if missing but not refreshed:
        refreshing is the engine's job, between verifications."""
        path = self.dir / "coord"
        if not (path / ".git").exists():
            return self.coord()
        return path

    def provision(self, path: Path) -> None:
        """Give a fresh worktree its own copy of ignored, machine-local tooling: the locked
        browser tooling in setup/node_modules (about 20 MB). A copy, not a link, so an agent that
        edits it changes only its own worktree; post-merge verification uses the coord copy."""
        source = self.repo / "setup" / "node_modules"
        target = path / "setup" / "node_modules"
        if source.is_dir() and (path / "setup").is_dir() and not target.exists():
            shutil.copytree(source, target, symlinks=True)

    @contextmanager
    def disposable(self, from_worktree: Path):
        """A throwaway detached worktree at another worktree's HEAD; removed on exit."""
        with self._mutex:
            scratch = self.dir / f"scratch-{uuid.uuid4().hex[:8]}"
            self.git("worktree", "add", "--detach", "--quiet", str(scratch), self.head(from_worktree))
        self.provision(scratch)
        try:
            yield scratch
        finally:
            self.remove(scratch)

    def remote_branch_exists(self, branch: str) -> bool:
        return bool(self.git("ls-remote", "--heads", self.remote, branch))

    def issue_worktree(self, n: int, branch: str) -> Path:
        with self._mutex:
            return self._issue_worktree(n, branch)

    def _issue_worktree(self, n: int, branch: str) -> Path:
        path = self.dir / f"issue-{n}"
        if (path / ".git").exists():
            return path
        self.dir.mkdir(parents=True, exist_ok=True)
        local = bool(self.git("branch", "--list", branch))
        if local:
            self.git("worktree", "add", "--quiet", str(path), branch)
        elif self.remote_branch_exists(branch):
            self.git("fetch", "--quiet", self.remote, branch)
            self.git("worktree", "add", "--quiet", "-b", branch, str(path), f"{self.remote}/{branch}")
        else:
            self.fetch()
            self.git("worktree", "add", "--quiet", "-b", branch, str(path), self.base_ref())
        self.provision(path)
        return path

    def refs(self) -> dict[str, str]:
        out = self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags")
        return dict(line.split(" ", 1) for line in out.splitlines() if line)

    def remove(self, path: Path) -> None:
        with self._mutex:
            if path.exists():
                self.git("worktree", "remove", "--force", str(path), check=False)

    # inspection ---------------------------------------------------------------
    def head(self, path: Path) -> str:
        return self.git("rev-parse", "HEAD", cwd=path)

    def changed_files(self, path: Path, since: str) -> list[str]:
        committed = self.git("diff", "--name-only", f"{since}..HEAD", cwd=path).splitlines()
        return sorted(set(f for f in committed + self.uncommitted(path) if f))

    def has_commit(self, path: Path, sha: str) -> bool:
        return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=path, capture_output=True).returncode == 0

    def is_ancestor(self, path: Path, ancestor: str, descendant: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=path,
                              capture_output=True).returncode == 0

    def exists_at(self, path: Path, ref: str, file: str) -> bool:
        return bool(self.git("ls-tree", "--name-only", ref, "--", file, cwd=path, check=False))

    def show_bytes(self, path: Path, ref: str, file: str) -> bytes | None:
        """The bytes of `file` at `ref`, or None when it is not a file there."""
        proc = subprocess.run(["git", "cat-file", "blob", f"{ref}:{file}"], cwd=path, capture_output=True)
        return proc.stdout if proc.returncode == 0 else None

    def file_state(self, path: Path, rel: str) -> FileState:
        """What git records of `rel` in the working tree: its kind, content and executable bit."""
        target = path / rel
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return ("link", os.readlink(target))
        if stat.S_ISDIR(info.st_mode):
            return ("dir",)
        return ("file", target.read_bytes(), bool(info.st_mode & 0o100))

    def file_state_at(self, path: Path, ref: str, rel: str) -> FileState:
        """`file_state` of `rel` as it is at `ref`, from the tree's recorded mode."""
        out = self.git("ls-tree", "-z", ref, "--", rel, cwd=path, check=False, strip=False)
        record = next((r for r in out.split("\0") if "\t" in r and r.split("\t", 1)[1] == rel), None)
        if record is None:
            return None
        mode, kind, sha = record.split("\t", 1)[0].split()
        if kind != "blob":
            return ("dir",)
        data = subprocess.run(["git", "cat-file", "blob", sha], cwd=path, capture_output=True, check=True).stdout
        if mode == "120000":
            return ("link", os.fsdecode(data))
        return ("file", data, mode == "100755")

    def write_file_state(self, path: Path, rel: str, state: FileState) -> None:
        """Put `rel` back in the working tree as `state` (from `file_state`) recorded it."""
        target = path / rel
        current = self.file_state(path, rel)
        if current is not None and (state is None or current[0] != state[0] or current[0] == "link"):
            if current[0] == "dir":
                shutil.rmtree(target)
            else:
                target.unlink()
        if state is None or state[0] == "dir":
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if state[0] == "link":
            os.symlink(state[1], target)
            return
        target.write_bytes(state[1])
        mode = os.stat(target).st_mode
        os.chmod(target, (mode | 0o111) if state[2] else (mode & ~0o111))

    def _git_path(self, path: Path, name: str) -> Path:
        """A path in this worktree's own git directory (each worktree has its own MERGE_HEAD)."""
        p = Path(self.git("rev-parse", "--git-path", name, cwd=path))
        return p if p.is_absolute() else path / p

    def in_progress(self, path: Path) -> str | None:
        """"rebase" or "merge" when one stopped half-way in this worktree, else None."""
        if self._git_path(path, "rebase-merge").exists() or self._git_path(path, "rebase-apply").exists():
            return "rebase"
        if self._git_path(path, "MERGE_HEAD").exists():
            return "merge"
        return None

    def conflicted_files(self, path: Path) -> list[str]:
        """Unmerged paths, read NUL-delimited so spaces and non-ASCII names survive."""
        out = self.git("diff", "--name-only", "--diff-filter=U", "-z", cwd=path, strip=False)
        return list(dict.fromkeys(f for f in out.split("\0") if f))

    # in-progress operations ------------------------------------------------------
    def _ok(self, path: Path, *args: str) -> bool:
        return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True).returncode == 0

    def abort_in_progress(self, path: Path) -> str | None:
        """Abort a rebase or merge left half-way, returning which it was. Committed work is never
        lost: an unfinished rebase never moved the branch ref, and a merge only adds a commit
        once it is concluded. Never `reset --hard` or `clean`."""
        with self._mutex:
            op = self.in_progress(path)
            if op == "rebase":
                head_name = next((self._git_path(path, d) / "head-name" for d in ("rebase-merge", "rebase-apply")
                                  if (self._git_path(path, d) / "head-name").is_file()), None)
                branch = head_name.read_text().strip().removeprefix("refs/heads/") if head_name else ""
                if not self._ok(path, "rebase", "--abort"):
                    self._ok(path, "rebase", "--quit")
                    if branch and branch != "detached HEAD":
                        self.git("checkout", "--force", "--quiet", branch, cwd=path)
            elif op == "merge":
                if not self._ok(path, "merge", "--abort"):
                    self._ok(path, "merge", "--quit")
                    self.git("checkout", "--force", "--quiet",
                             self.git("symbolic-ref", "--short", "-q", "HEAD", cwd=path, check=False) or "HEAD", cwd=path)
            if op and self.in_progress(path):
                raise GitError(f"could not abort the {op} in progress in {path}")
            return op

    def update(self, path: Path) -> UpdateResult:
        """Bring the branch up to date with the base branch by merging it in (never a rebase:
        it would rewrite commits that were verified, reviewed or published). On conflicts the
        merge is left in progress for the caller, who resolves or aborts it."""
        self.abort_in_progress(path)
        self.fetch()
        with self._mutex:
            before = self.head(path)
            main = self.git("rev-parse", self.base_ref(), cwd=path)
            if self.is_ancestor(path, main, before):
                return UpdateResult("current", [], before, main)
            proc = subprocess.run(["git", "merge", "--no-edit", "-m", f"Merge {self.base_ref()} into the issue branch",
                                   main], cwd=path, capture_output=True, text=True)
            if proc.returncode == 0:
                return UpdateResult("merged", [], before, main)
            files = self.conflicted_files(path)
            if files and self.in_progress(path) == "merge":
                return UpdateResult("conflict", files, before, main)
            self.abort_in_progress(path)
            raise GitError(f"git merge {self.base_ref()} failed: {(proc.stderr or proc.stdout).strip()[:400]}")

    # writes ---------------------------------------------------------------------
    def commit_all(self, path: Path, subject: str, phase: str, issue: int, unlocks: list[str] | None = None) -> str | None:
        """Commit everything in the worktree. Returns the new SHA, or None if nothing changed.
        `unlocks` names check files an earlier acceptance-checks commit locked that a new design
        no longer uses; the CI guard stops protecting them from this commit on. A merge in
        progress is concluded even when its resolution leaves the tree as it was."""
        with self._mutex:
            self.git("add", "--all", cwd=path)
            if not self.git("status", "--porcelain", cwd=path) and not unlocks and self.in_progress(path) != "merge":
                return None
            trailers = f"Loop-Phase: {phase}\n" + "".join(f"Loop-Unlocks: {f}\n" for f in unlocks or [])
            message = f"{subject}\n\nRefs #{issue}\n\n{trailers}"
            self.git("commit", "--quiet", "--allow-empty", "-m", message, cwd=path)
            return self.head(path)

    def commit_paths(self, path: Path, paths: list[str], subject: str, phase: str, issue: int) -> str | None:
        """Commit only `paths` (changed, added or deleted), leaving every other change uncommitted."""
        with self._mutex:
            self.git("reset", "-q", cwd=path)
            self.git("add", "--all", "--", *paths, cwd=path)
            if not self.git("diff", "--cached", "--name-only", cwd=path):
                return None
            self.git("commit", "--quiet", "-m", f"{subject}\n\nRefs #{issue}\n\nLoop-Phase: {phase}\n", cwd=path)
            return self.head(path)

    def nothing_to_land(self, path: Path) -> bool:
        """The branch changes nothing on the base branch (for example a re-run that found the
        work already merged)."""
        return not self.git("diff", "--name-only", f"{self.base_ref()}...HEAD", cwd=path)

    def push(self, path: Path) -> str:
        """Publish through the trusted ship script (rebase before first push, merge-forward after).
        A conflict while it brings the branch up to date is aborted and raised as `MergeConflict`,
        with the worktree back on its branch, at its previous head, clean."""
        with self._mutex:
            before = self.head(path)
            branch = self.git("symbolic-ref", "--short", "-q", "HEAD", cwd=path, check=False)
            proc = subprocess.run(["bash", str(self.ship_script)], cwd=path, capture_output=True, text=True)
            if proc.returncode == 0:
                return self.head(path)
            message = f"ship.sh failed: {(proc.stderr or proc.stdout).strip()[-600:]}"
            files = self.conflicted_files(path)
            if not files and not self.in_progress(path):
                raise GitError(message)
            self.abort_in_progress(path)
            now = self.git("symbolic-ref", "--short", "-q", "HEAD", cwd=path, check=False)
            if now != branch or self.head(path) != before or self.git("status", "--porcelain", cwd=path):
                raise GitError(f"{message}\n(the worktree did not return to {branch} at {before[:12]} after the abort)")
            raise MergeConflict(message, files)

"""Git worktrees for a run, and the only code that commits or pushes.

Layout: `<repo parent>/<repo name>.loop/issue-<root>/` holds a detached coordination worktree
(`coord/`, at the remote base branch) and one worktree per active issue (`issue-<n>/`, on the
issue's branch). The engine creates and removes them itself.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path


class GitError(RuntimeError):
    pass


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

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
        return proc.stdout.strip()

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
        working = [line[3:] for line in self.git("status", "--porcelain", "--untracked-files=all", cwd=path).splitlines()]
        return sorted(set(f for f in committed + working if f))

    # writes ---------------------------------------------------------------------
    def commit_all(self, path: Path, subject: str, phase: str, issue: int) -> str | None:
        """Commit everything in the worktree. Returns the new SHA, or None if nothing changed."""
        with self._mutex:
            self.git("add", "--all", cwd=path)
            if not self.git("status", "--porcelain", cwd=path):
                return None
            message = f"{subject}\n\nRefs #{issue}\n\nLoop-Phase: {phase}\n"
            self.git("commit", "--quiet", "-m", message, cwd=path)
            return self.head(path)

    def push(self, path: Path) -> str:
        """Publish through the trusted ship script (rebase before first push, merge-forward after)."""
        with self._mutex:
            proc = subprocess.run(["bash", str(self.ship_script)], cwd=path, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitError(f"ship.sh failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
        return self.head(path)

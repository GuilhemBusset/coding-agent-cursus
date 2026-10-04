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

    # writes ---------------------------------------------------------------------
    def commit_all(self, path: Path, subject: str, phase: str, issue: int, unlocks: list[str] | None = None) -> str | None:
        """Commit everything in the worktree. Returns the new SHA, or None if nothing changed.
        `unlocks` names check files an earlier acceptance-checks commit locked that a new design
        no longer uses; the CI guard stops protecting them from this commit on."""
        with self._mutex:
            self.git("add", "--all", cwd=path)
            if not self.git("status", "--porcelain", cwd=path) and not unlocks:
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
        """Publish through the trusted ship script (rebase before first push, merge-forward after)."""
        with self._mutex:
            proc = subprocess.run(["bash", str(self.ship_script)], cwd=path, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitError(f"ship.sh failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
        return self.head(path)

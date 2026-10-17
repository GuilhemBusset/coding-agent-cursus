"""Git worktrees for a run, and the only code that commits or pushes.

Layout: `<repo parent>/<repo name>.loop/issue-<root>/` holds a detached coordination worktree
(`coord/`, at the remote base branch) and one worktree per active issue (`issue-<n>/`, on the
issue's branch). The engine creates and removes them itself.

Several runs may share one repository. Shared git writes are serialized across them by an flock
on `<git common dir>/implementation-loop/git.lock`, and an agent works against a private git
directory of its run's own (`agent_call`), so it never changes a shared ref: not another run's,
not a person's.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import stat
import subprocess
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


# A path as git records it: None (absent), ("link", target), ("dir",) or ("file", bytes, executable).
FileState = tuple | None

OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

# What an agent call copies from the worktree's own git directory into its private one.
OPERATION_FILES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "AUTO_MERGE", "ORIG_HEAD")
# The worktree's original gitfile, kept in the private directory so a killed call can be undone.
SAVED_GITFILE = "implement-loop-gitfile"


class GitError(RuntimeError):
    pass


class BranchNotRestored(GitError):
    """A worktree's branch ref is gone and nothing in the worktree's own history can safely
    restore it."""

    def __init__(self, message: str, branch: str):
        super().__init__(message)
        self.branch = branch


class RepoLock:
    """Reentrant for one thread, exclusive across threads, Workspaces and processes: an
    `threading.RLock` plus an flock on a file in the repository's common git directory, taken
    on the outermost acquisition and released with it. Each instance opens its own file
    description, so two Workspaces in one process exclude each other too."""

    def __init__(self, path):
        self._path = path          # a callable: the lock file, resolved on first use
        self._rlock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def __enter__(self) -> "RepoLock":
        self._rlock.acquire()
        try:
            if self._depth == 0:
                path = self._path()
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_CREAT | os.O_RDWR)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except BaseException:
                    os.close(fd)
                    raise
                self._fd = fd
            self._depth += 1
        except BaseException:
            self._rlock.release()
            raise
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._depth -= 1
            if self._depth == 0 and self._fd is not None:
                fd, self._fd = self._fd, None
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            self._rlock.release()


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


@dataclass
class AgentCall:
    """One agent call (`Workspace.agent_call`): the worktree before it, and what the agent left in
    its private git directory, read before that directory was deleted. Nothing in it was ever
    written to the shared repository."""
    head: str                                  # HEAD before the call
    branch: str | None                         # the branch HEAD was on, None when detached
    merge_head: str | None                     # MERGE_HEAD before the call
    after_head: str | None = None              # the private HEAD after the call
    after_branch: str | None = None            # the branch it was on, None when detached
    after_merge_head: str | None = None        # the private MERGE_HEAD after the call
    merge_committed: bool = False              # `merge_head` is in the private HEAD's history
    created: list[str] = field(default_factory=list)     # refs the agent created
    discarded: list[str] = field(default_factory=list)   # refs it moved or deleted, the branch aside


class Workspace:
    def __init__(self, repo_root: Path, root: int, ship_script: Path, base_dir: Path | None = None,
                 remote: str = "origin", base_branch: str = "main"):
        self.repo = repo_root
        self.remote = remote
        self.base = base_branch
        self.ship_script = ship_script
        self.dir = base_dir or repo_root.parent / f"{repo_root.name}.loop" / f"issue-{root}"
        # Worktrees share one repository, with other runs too: concurrent fetches, ref updates and
        # worktree changes contend for the same lock files, so every operation that writes shared
        # state is serialized, across threads and processes. Never held across an agent call.
        self._common: Path | None = None
        self._mutex = RepoLock(lambda: self.common_dir() / "implementation-loop" / "git.lock")

    def common_dir(self) -> Path:
        """The repository's git directory shared by all its worktrees."""
        if self._common is None:
            proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=self.repo,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                raise GitError(f"git rev-parse --git-common-dir failed: {proc.stderr.strip()[:400]}")
            path = Path(proc.stdout.strip())
            self._common = path if path.is_absolute() else (self.repo / path).resolve()
        return self._common

    def git(self, *args: str, cwd: Path | None = None, check: bool = True, strip: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
        return proc.stdout.strip() if strip else proc.stdout

    def uncommitted(self, path: Path) -> list[str]:
        """Paths changed in the working tree, staged or not, including untracked files, and both
        ends of a rename (a merge that brings main's rename stages one): its source changed too.

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
                if "R" in record[:2] and i + 1 < len(records):   # followed by its source path
                    paths.append(records[i + 1])
                if "R" in record[:2] or "C" in record[:2]:   # a copy's source is unchanged
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
        conflict stages included; no entries removes it from the index. Needs no HEAD: a
        worktree whose branch was deleted (#34's) still gets its entries back."""
        fmt = self.git("rev-parse", "--show-object-format", cwd=path)
        removal = f"0 {'0' * (64 if fmt == 'sha256' else 40)}\t{name}"
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
        """A throwaway detached worktree at another worktree's HEAD, on a private git directory
        for its whole life (`agent_call`); removed on exit."""
        with self._mutex:
            scratch = self.dir / f"scratch-{uuid.uuid4().hex[:8]}"
            self.git("worktree", "add", "--detach", "--quiet", str(scratch), self.head(from_worktree))
        try:
            self.provision(scratch)
            with self.agent_call(scratch):
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
            self.reattach(path)
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

    def remove(self, path: Path) -> None:
        with self._mutex:
            if path.exists():
                try:
                    self.reattach(path, carry=False)   # nothing to carry: the worktree goes
                except GitError:
                    pass   # removed anyway: `worktree remove --force` does not need it
                self.git("worktree", "remove", "--force", str(path), check=False)

    # agent calls ----------------------------------------------------------------
    def _gitfile_target(self, path: Path) -> Path | None:
        """The git directory `<path>/.git` names, None when it is not a gitfile."""
        entry = path / ".git"
        if not entry.is_file():
            return None
        text = entry.read_text(errors="replace").strip()
        if not text.startswith("gitdir: "):
            return None
        target = Path(text.removeprefix("gitdir: "))
        return target if target.is_absolute() else path / target

    def _write_gitfile(self, path: Path, data: bytes) -> None:
        """Replace `<path>/.git` in one step: a git process sees the old gitfile or the new one."""
        tmp = path / f".git.implement-loop-{uuid.uuid4().hex[:8]}"
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path / ".git")
        finally:
            tmp.unlink(missing_ok=True)

    def _admin_dir(self, path: Path) -> Path | None:
        """The directory git registered for linked worktree `path`: the one under
        `<common>/worktrees/` whose `gitdir` file names `<path>/.git`."""
        entry = (path / ".git").resolve()
        for gitdir in sorted((self.common_dir() / "worktrees").glob("*/gitdir")):
            named = Path(gitdir.read_text(errors="replace").strip())
            if (named if named.is_absolute() else gitdir.parent / named).resolve() == entry:
                return gitdir.parent
        return None

    def reattach(self, path: Path, carry: bool = True) -> None:
        """Put back the worktree's own git directory when a killed agent call left `path` on its
        private one (only this run's: another run's attachment is never touched), keep the staged
        work its agent left that the files cannot rebuild (`_keep_carried_entries`: ignored paths,
        index-only executable bits; skipped when `carry` is false), then delete the private
        directory (`_detach`)."""
        with self._mutex:
            target = self._gitfile_target(path)
            root = (self.dir / "agent-git").resolve()
            if target is None or root not in target.resolve().parents:
                return
            private = target.resolve()
            admin = self._admin_dir(path)
            saved = private / SAVED_GITFILE
            original = saved.read_bytes() if saved.is_file() else b""
            if not original.startswith(b"gitdir: ") or (
                    admin is not None and Path(os.fsdecode(original[8:].strip())).resolve() != admin.resolve()):
                if admin is None:
                    raise GitError(f"{path} is attached to the agent git directory {private}, and git has no "
                                   "worktree registered for it")
                original = f"gitdir: {admin}\n".encode()
            staged = names = None
            if carry:
                try:
                    staged = self.index_entries(path)
                    names = self._carried_names(path, staged)
                except GitError:
                    names = None   # a private index the kill left unreadable: the files are kept anyway
            self._detach(path, original, private, staged, names)

    def _detach(self, path: Path, original: bytes, private: Path, staged: dict[str, list[str]] | None,
                names: set[str] | None) -> None:
        """Put `original` back as the worktree's gitfile, carry the entries `names` picks from the
        agent's index (`staged`) into the worktree's own, then delete the private directory. When
        carrying fails, the worktree is left on its private directory, kept whole, so the next
        `reattach` tries again instead of losing the agent's staged work."""
        self._write_gitfile(path, original)
        if names is not None:
            try:
                self._keep_carried_entries(path, private, staged, names)
            except BaseException:
                self._write_gitfile(path, f"gitdir: {private}\n".encode())
                raise
        shutil.rmtree(private, ignore_errors=True)

    def _ref_values(self, git_dir: Path | None = None, cwd: Path | None = None) -> dict[str, str]:
        """Every ref and its object, of a git directory or of the worktree at `cwd`."""
        args = [f"--git-dir={git_dir}"] if git_dir else []
        out = self.git(*args, "for-each-ref", "--format=%(refname) %(objectname)", cwd=cwd or git_dir)
        return dict(line.split(" ", 1) for line in out.splitlines() if " " in line)

    def _config_entries(self, file: Path) -> list[tuple[str, str | None]]:
        """A config file's settings in order, includes expanded; None for a bare boolean key."""
        if not file.is_file():
            return []
        out = self.git("config", "--file", str(file), "--list", "--includes", "-z", strip=False)
        entries = []
        for record in out.split("\0"):
            if record:
                key, _, value = record.partition("\n")
                entries.append((key, value if "\n" in record else None))
        return entries

    @staticmethod
    def _config_text(entries: list[tuple[str, str | None]]) -> str:
        def quote(text: str) -> str:
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'

        lines, header = [], None
        for key, value in entries:
            section, _, rest = key.partition(".")
            sub, _, name = rest.rpartition(".")
            line = f"[{section}{' ' + quote(sub) if sub else ''}]"
            if line != header:
                lines.append(line)
                header = line
            lines.append(f"\t{name}" if value is None else f"\t{name} = {quote(value)}")
        return "\n".join(lines) + "\n"

    def _private_git_dir(self, path: Path, admin: Path, refs: dict[str, str]) -> Path:
        """A git directory of this run's own for worktree `path`: the shared objects through an
        alternate (new objects stay private), a copy of every ref, of the worktree's HEAD, index and
        operation state, and the shared and per-worktree config. Writes nothing shared."""
        common = self.common_dir()
        root = self.dir / "agent-git"
        root.mkdir(parents=True, exist_ok=True)
        private = (root / uuid.uuid4().hex).resolve()
        fmt = self.git("rev-parse", "--show-object-format", cwd=path)
        self.git("init", "--bare", "--quiet", "--template=", f"--object-format={fmt}", str(private), cwd=root)
        try:
            (private / "objects" / "info").mkdir(parents=True, exist_ok=True)
            (private / "objects" / "info" / "alternates").write_text(f"{common / 'objects'}\n")
            if refs:   # no hooks run for the copy: it is not an update anyone made
                updates = "".join(f"create {ref} {oid}\n" for ref, oid in sorted(refs.items()))
                proc = subprocess.run(["git", f"--git-dir={private}", "-c", f"core.hooksPath={private / 'no-hooks'}",
                                       "update-ref", "--stdin"], cwd=private, input=updates,
                                      capture_output=True, text=True)
                if proc.returncode != 0:
                    raise GitError(f"copying the refs into {private} failed: {proc.stderr.strip()[:400]}")
            shutil.copyfile(admin / "HEAD", private / "HEAD")
            shared_index = self.git("rev-parse", "--shared-index-path", cwd=path)
            for source in [admin / "index", *([Path(shared_index)] if shared_index else []),
                           *(admin / name for name in OPERATION_FILES), common / "shallow"]:
                source = source if source.is_absolute() else path / source
                if source.is_file():
                    shutil.copy2(source, private / source.name)
            for info in (common / "info", admin / "info"):
                if info.is_dir():
                    shutil.copytree(info, private / "info", dirs_exist_ok=True)
            fixed = ("core.bare", "core.worktree", "core.repositoryformatversion")
            entries = [e for e in self._config_entries(private / "config")
                       if e[0] == "core.repositoryformatversion" or e[0].startswith("extensions.")]
            shared = self._config_entries(common / "config")
            if self.git("config", "--file", str(common / "config"), "--type=bool", "--get",
                        "extensions.worktreeConfig", check=False) == "true":
                shared += self._config_entries(admin / "config.worktree")
            entries += [(k, v) for k, v in shared
                        if k not in fixed and not k.startswith(("extensions.", "include.", "includeif."))]
            entries += [("core.bare", "false"), ("core.worktree", str(path.resolve()))]
            (private / "config").write_text(self._config_text(entries))
            hooks = private / "hooks"
            if hooks.is_dir() and not hooks.is_symlink():
                shutil.rmtree(hooks)
            os.symlink(common / "hooks", hooks)   # default hooks; a relative core.hooksPath is per worktree
        except BaseException:
            shutil.rmtree(private, ignore_errors=True)
            raise
        return private

    def _read_private(self, private: Path, call: AgentCall, refs: dict[str, str]) -> None:
        """Fill `call` from what the agent left in its private git directory."""
        head = (private / "HEAD").read_text(errors="replace").strip() if (private / "HEAD").is_file() else ""
        call.after_branch = head.removeprefix("ref: ") if head.startswith("ref: ") else None
        call.after_head = self.git(f"--git-dir={private}", "rev-parse", "-q", "--verify", "HEAD",
                                   cwd=private, check=False) or None
        merge = private / "MERGE_HEAD"
        call.after_merge_head = (merge.read_text(errors="replace").split() or [None])[0] if merge.is_file() else None
        if call.merge_head and call.after_merge_head is None and call.after_head:
            call.merge_committed = self._ok(private, f"--git-dir={private}", "merge-base", "--is-ancestor",
                                            call.merge_head, call.after_head)
        after = self._ref_values(git_dir=private)
        call.created = sorted(r for r in after if r not in refs)
        call.discarded = sorted(r for r, oid in refs.items() if after.get(r) != oid and r != call.branch)

    def _carried_names(self, path: Path, index: dict[str, list[str]]) -> set[str]:
        """The paths of `index` (`index_entries` of whichever git directory `path` is attached to)
        whose staged state `git add --all` cannot rebuild from the files: ignored paths, and
        regular files whose single stage-0 entry records an executable bit the file on disk does
        not have, or the reverse (`update-index --chmod`; under `core.fileMode=false` the index is
        git's only record of it)."""
        out = self.git("ls-files", "--cached", "--ignored", "--exclude-standard", "-z", cwd=path, strip=False)
        names = {name for name in out.split("\0") if name}
        for name, entries in index.items():
            if len(entries) != 1:
                continue
            mode, _, stage = entries[0].split("\t", 1)[0].split()
            if stage != "0" or mode not in ("100644", "100755"):
                continue
            try:
                info = os.lstat(path / name)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and bool(info.st_mode & stat.S_IXUSR) != (mode == "100755"):
                names.add(name)
        return names

    def _keep_carried_entries(self, path: Path, private: Path, private_index: dict[str, list[str]],
                              names: set[str]) -> None:
        """Carry the agent's index entries (`private_index`, read from its private index) for the
        paths `_carried_names` picks, there (`names`) or in the worktree's own index, into that
        index, with the blobs they name copied into the shared object store, where nothing refers to
        them until the engine commits. Only entries the agent's index records differently are
        written, so a mode the agent left alone is never overridden. Every other path is rebuilt
        from the working tree by `commit_all`, so the shared index is otherwise left as it was."""
        shared_index = self.index_entries(path)
        for name in sorted(names | self._carried_names(path, shared_index)):
            entries = private_index.get(name, [])
            if entries == shared_index.get(name, []):
                continue
            for record in entries:
                mode, oid = record.split(" ", 2)[:2]
                if mode != "160000" and not self._ok(path, "cat-file", "-e", oid):   # a gitlink names no blob here
                    blob = subprocess.run(["git", f"--git-dir={private}", "cat-file", "blob", oid], cwd=private,
                                          capture_output=True)
                    if blob.returncode != 0:
                        raise GitError(f"the agent staged {name}, and its blob {oid} cannot be read: "
                                       f"{blob.stderr.decode(errors='replace').strip()[:400]}")
                    proc = subprocess.run(["git", "hash-object", "-w", "--no-filters", "--stdin"], cwd=path,
                                          input=blob.stdout, capture_output=True)
                    if proc.returncode != 0:
                        raise GitError(f"copying the blob of {name} failed: "
                                       f"{proc.stderr.decode(errors='replace').strip()[:400]}")
            self.restore_index_entry(path, name, entries)

    @contextmanager
    def agent_call(self, path: Path):
        """Run an agent in worktree `path` against a private git directory under this run's own
        directory (`<run dir>/agent-git/<id>/`): `<path>/.git` names it for the call. Every git
        process run in the worktree, whatever its environment, then reads and writes refs, HEAD,
        the index and operation state there, never in the shared repository, so nothing the agent
        does to git can reach another run's or a person's refs, and nothing has to be undone. The
        working tree is the real one, and the agent's index entries `commit_all` could not rebuild
        from it are carried into the worktree's index: ignored paths it staged (`git add -f`) and
        executable bits recorded only in the index (`update-index --chmod`). Yields an
        `AgentCall` that is filled in once the block exits; the gitfile is put back and the private
        directory deleted whatever happens, unless carrying those entries fails (`_detach`)."""
        with self._mutex:
            self.reattach(path)
            admin = self._gitfile_target(path)
            if admin is None:
                raise GitError(f"{path} is not a linked worktree: its .git is not a gitfile")
            original = (path / ".git").read_bytes()
            merge = admin / "MERGE_HEAD"
            call = AgentCall(head=self.head(path), branch=self.branch(path),
                             merge_head=(merge.read_text().split() or [None])[0] if merge.is_file() else None)
            refs = self._ref_values(cwd=path)
            private = self._private_git_dir(path, admin, refs)
            try:
                (private / SAVED_GITFILE).write_bytes(original)
                self._write_gitfile(path, f"gitdir: {private}\n".encode())
            except BaseException:
                shutil.rmtree(private, ignore_errors=True)
                raise
        try:
            yield call
        finally:
            with self._mutex:
                staged = names = None
                try:
                    staged = self.index_entries(path)   # still attached: the agent's index
                    names = self._carried_names(path, staged)
                    self._read_private(private, call, refs)
                finally:
                    self._detach(path, original, private, staged, names)

    def restore_branch(self, path: Path, anchors: list[str]) -> tuple[str, str] | None:
        """Recreate the branch worktree `path` is on when its ref is gone (another run deleted
        #34's), at the newest commit of the worktree's own HEAD reflog that shares history with
        the base branch and contains every commit in `anchors` that still exists. An anchor a
        later-recorded anchor rewrote (shipping rebases an unpublished branch, so the checks commit
        and the reviewed head are no longer in the verified head's history) no longer binds. Only
        the ref is written, create-only: the working tree and index are never touched. Returns
        (ref, sha), None when nothing is missing, and raises BranchNotRestored when no entry
        qualifies."""
        with self._mutex:
            self.reattach(path)
            ref = self.git("symbolic-ref", "-q", "HEAD", cwd=path, check=False)
            if not ref or self._ok(path, "rev-parse", "-q", "--verify", ref):
                return None
            branch = ref.removeprefix("refs/heads/")
            log = self._git_path(path, "logs/HEAD")
            entries = log.read_text(errors="replace").splitlines() if log.is_file() else []
            shas = [parts[1] if len(parts) > 2 else "" for parts in (line.split(" ", 2) for line in entries)]
            anchors = self._current_anchors(path, anchors, shas)
            seen = set()
            for sha in reversed(shas):
                if sha in seen or not OID.match(sha) or set(sha) == {"0"}:
                    continue
                seen.add(sha)
                if (self.has_commit(path, sha) and self._ok(path, "merge-base", sha, self.base_ref())
                        and all(self.is_ancestor(path, a, sha) for a in anchors)):
                    self.git("update-ref", ref, sha, "", cwd=self.repo)
                    return ref, sha
            raise BranchNotRestored(f"the branch {branch} of {path} is gone, and no commit in its worktree's HEAD "
                                    f"reflog shares history with {self.base_ref()} and contains the recorded commits",
                                    branch)

    def _current_anchors(self, path: Path, anchors: list[str], reflog: list[str]) -> list[str]:
        """The anchors that still exist and that no later one superseded. Two anchors where
        neither contains the other mean history was rewritten between them; the one HEAD reached
        later in the worktree's reflog is the current line, and the other is dropped. Anchors
        that are not in the reflog cannot be ordered, so they are kept (and failing to restore
        parks the issue rather than guessing)."""
        anchors = [a for a in dict.fromkeys(anchors) if a and self.has_commit(path, a)]
        last = {sha: i for i, sha in enumerate(reflog)}
        return [a for a in anchors
                if not any(a in last and b in last and last[b] > last[a]
                           and not self.is_ancestor(path, a, b) and not self.is_ancestor(path, b, a)
                           for b in anchors)]

    # inspection ---------------------------------------------------------------
    def head(self, path: Path) -> str:
        return self.git("rev-parse", "HEAD", cwd=path)

    def branch(self, path: Path) -> str | None:
        """The full ref of the branch checked out in `path`, None when HEAD is detached."""
        return self.git("symbolic-ref", "-q", "HEAD", cwd=path, check=False) or None

    def changed_files(self, path: Path, since: str) -> list[str]:
        committed = self.git("diff", "--name-only", "-z", f"{since}..HEAD", cwd=path, strip=False).split("\0")
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
    def commit_all(self, path: Path, subject: str, phase: str, issue: int, unlocks: list[str] | None = None,
                   locks: list[str] | None = None, trailers: dict[str, str] | None = None) -> str | None:
        """Commit everything in the worktree. Returns the new SHA, or None if nothing changed.
        `unlocks` names test files an earlier acceptance-checks commit locked that are released
        (an approved change, or an earlier engine's checks taken over by the builder); `locks`
        names files already on the branch that are locked from this commit on, unchanged. The CI
        guard reads both trailers. A merge in progress is concluded even when its resolution
        leaves the tree as it was."""
        with self._mutex:
            self.git("add", "--all", cwd=path)
            if (not self.git("status", "--porcelain", cwd=path) and not unlocks and not locks
                    and self.in_progress(path) != "merge"):
                return None
            trailers = (f"Loop-Phase: {phase}\n" + "".join(f"Loop-Unlocks: {f}\n" for f in unlocks or [])
                        + "".join(f"Loop-Locks: {f}\n" for f in locks or [])
                        + "".join(f"{k}: {v}\n" for k, v in (trailers or {}).items()))
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

"""Run state: a directory under the git common dir, outside every worktree.

`state.json` is rewritten atomically after each transition; `events.jsonl` is append-only.
A run is keyed by its root issue, so re-running `implement <n>` resumes it. A `STOP` file in
the run directory asks the engine to stop at the next safe point.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from .model import IssueState

STATE_VERSION = 1


class LockHeld(RuntimeError):
    pass


def git_common_dir(repo_root: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo_root,
                         capture_output=True, text=True, check=True).stdout.strip()
    path = Path(out)
    return path if path.is_absolute() else (repo_root / path).resolve()


def runs_root(repo_root: Path) -> Path:
    return git_common_dir(repo_root) / "implementation-loop"


class RunStore:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seq = 0
        path = self.dir / "state.json"
        if path.exists():
            self.state = json.loads(path.read_text())
            events = self.dir / "events.jsonl"
            if events.exists():
                with events.open() as f:
                    self._seq = sum(1 for _ in f)
        else:
            self.state = {"version": STATE_VERSION, "issues": {}, "context": None, "meta": {}}

    @classmethod
    def for_root(cls, repo_root: Path, root: int, fresh: bool = False) -> "RunStore":
        run_dir = runs_root(repo_root) / f"issue-{root}"
        if fresh and run_dir.exists():
            run_dir.rename(run_dir.with_name(f"issue-{root}.archived-{int(time.time())}"))
        store = cls(run_dir)
        store.state["meta"].setdefault("root", root)
        return store

    # persistence -------------------------------------------------------------
    def save(self) -> None:
        with self._lock:
            tmp = self.dir / "state.json.tmp"
            tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True))
            os.replace(tmp, self.dir / "state.json")

    def event(self, kind: str, **data) -> None:
        with self._lock:
            self._seq += 1
            record = {"seq": self._seq, "ts": round(time.time(), 3), "kind": kind, **data}
            with (self.dir / "events.jsonl").open("a") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")

    def events(self) -> list[dict]:
        path = self.dir / "events.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    # issue state -------------------------------------------------------------
    def issue(self, n: int) -> IssueState:
        with self._lock:
            raw = self.state["issues"].get(str(n))
            return IssueState.from_dict(raw) if raw else IssueState(number=n)

    def put(self, st: IssueState) -> None:
        with self._lock:
            self.state["issues"][str(st.number)] = st.to_dict()
            self.save()

    def known(self) -> list[int]:
        return sorted(int(k) for k in self.state["issues"])

    def issue_dir(self, n: int) -> Path:
        d = self.dir / "issues" / str(n)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # control -----------------------------------------------------------------
    def stop_requested(self) -> bool:
        return (self.dir / "STOP").exists()

    def lock(self) -> "RunLock":
        return RunLock(self.dir / "lock")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLock:
    """One engine per run. A lock left by a dead process on this host is taken over."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self) -> "RunLock":
        me = {"pid": os.getpid(), "host": socket.gethostname(), "started": time.time()}
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump(me, f)
                return self
            except FileExistsError:
                try:
                    holder = json.loads(self.path.read_text())
                except (OSError, ValueError):
                    holder = {}
                if holder.get("host") == me["host"] and not _pid_alive(int(holder.get("pid", 0))):
                    self.path.unlink(missing_ok=True)
                    continue
                raise LockHeld(f"run is locked by pid {holder.get('pid')} on {holder.get('host')}")
        raise LockHeld("could not acquire the run lock")

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


class RepoClaims:
    """Repo-wide claims shared by every run: the merge queue and shared files.

    A claim is a file under `<git common dir>/implementation-loop/claims/`, created atomically.
    """

    def __init__(self, repo_root: Path):
        self.dir = runs_root(repo_root) / "claims"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, resource: str) -> Path:
        return self.dir / (resource.replace("/", "__") + ".claim")

    def acquire(self, resource: str, owner: str) -> bool:
        path = self._path(resource)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = json.loads(path.read_text())
            except (OSError, ValueError):
                return False
            if holder.get("owner") == owner:
                return True
            if holder.get("host") == socket.gethostname() and not _pid_alive(int(holder.get("pid", 0))):
                path.unlink(missing_ok=True)
                return self.acquire(resource, owner)
            return False
        with os.fdopen(fd, "w") as f:
            json.dump({"owner": owner, "pid": os.getpid(), "host": socket.gethostname()}, f)
        return True

    def release(self, resource: str, owner: str) -> None:
        path = self._path(resource)
        try:
            if json.loads(path.read_text()).get("owner") == owner:
                path.unlink()
        except (OSError, ValueError):
            pass

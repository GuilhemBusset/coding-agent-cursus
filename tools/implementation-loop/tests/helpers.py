"""Shared test scaffolding: a throwaway repo with a bare remote, and a merge that really
happens in that remote, so the engine's git, ship and verify code runs for real."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

REPO_ROOT = HERE.parents[2]
SHIP = REPO_ROOT / "scripts" / "ship.sh"
HOOKS = REPO_ROOT / ".githooks"
FIXTURE = HERE / "fixtures" / "epic10.json"

HAS_PYTEST = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True).returncode == 0


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


def identify(path: Path) -> None:
    git("config", "user.name", "Loop Test", cwd=path)
    git("config", "user.email", "loop-test@example.invalid", cwd=path)
    git("config", "commit.gpgsign", "false", cwd=path)


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


class TempRepo:
    """remote.git (bare) <- work (the engine's repo) ; merger (performs squash merges)."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-loop-"))
        self.remote = self.tmp / "remote.git"
        git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=self.tmp)
        seed = self.tmp / "seed"
        git("clone", "-q", str(self.remote), str(seed), cwd=self.tmp)
        identify(seed)
        (seed / "README.md").write_text("test repo\n")
        git("add", "README.md", cwd=seed)
        git("commit", "-q", "-m", "seed", cwd=seed)
        git("push", "-q", "origin", "HEAD:main", cwd=seed)
        self.work = self.tmp / "work"
        git("clone", "-q", str(self.remote), str(self.work), cwd=self.tmp)
        identify(self.work)
        git("config", "core.hooksPath", str(HOOKS), cwd=self.work)
        self.merger = self.tmp / "merger"
        git("clone", "-q", str(self.remote), str(self.merger), cwd=self.tmp)
        identify(self.merger)
        self.loop_dir = self.tmp / "loop"

    def merge(self, branch: str, sha: str) -> str:
        git("fetch", "-q", "origin", cwd=self.merger)
        git("checkout", "-q", "main", cwd=self.merger)
        git("reset", "-q", "--hard", "origin/main", cwd=self.merger)
        git("merge", "-q", "--squash", sha, cwd=self.merger)
        git("commit", "-q", "-m", f"Squash {branch}", cwd=self.merger)
        git("push", "-q", "origin", "HEAD:main", cwd=self.merger)
        return git("rev-parse", "HEAD", cwd=self.merger)

    def main_file(self, path: str) -> str | None:
        try:
            return git("show", f"origin/main:{path}", cwd=self.merger)
        except RuntimeError:
            return None

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def issue_body(branch: str, deliverables: list[str], acceptance: list[str]) -> str:
    lines = [f"Suggested branch: `{branch}`", "", "## Context", "Test issue.", "", "## Deliverables"]
    lines += [f"- [ ] {d}" for d in deliverables] + ["", "## Acceptance criteria"]
    lines += [f"- [ ] {a}" for a in acceptance]
    return "\n".join(lines) + "\n"


class Case(unittest.TestCase):
    pass

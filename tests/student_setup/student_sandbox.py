"""Sandboxes for the student setup tests: a PATH of stub tools, a fake HOME and system root.

Stubs log every call to $STUB_LOG as `<name> <args>` (mise adds `@<cwd>`), print a version for
--version, and do nothing else. `uv run ... python ARGS` runs this interpreter on ARGS, so
prepare.py runs for real. A few real programs (bash, coreutils, git when asked) are linked in.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STUDENT = REPO / "setup/student"
# What install.sh itself calls besides the tools it looks for.
REAL = ["bash", "sh", "cat", "dirname", "sed", "cksum", "mktemp", "rm", "tail", "ls", "mkdir", "mv", "ln",
        "chmod", "cut", "tr", "env", "head", "id", "tar", "gzip", "awk", "grep", "tee"]

LOGGING = """#!/bin/sh
echo "{name} $*" >> "$STUB_LOG"
if [ "$1" = --version ]; then echo "{version}"; fi
exit 0
"""
MISE = """#!/bin/sh
echo "mise $* @$(pwd)" >> "$STUB_LOG"
if [ "$1" = --version ]; then echo "{version}"; exit 0; fi
if [ -n "$MISE_FAIL" ]; then
  case "$* @$(pwd)" in *"$MISE_FAIL"*) echo "stub mise failed"; exit 3 ;; esac
fi
exit 0
"""
UV = """#!/bin/sh
echo "uv $*" >> "$STUB_LOG"
if [ "$1" = --version ]; then echo "{version}"; exit 0; fi
if [ "$1" = run ]; then
  while [ "$#" -gt 0 ] && [ "$1" != python ]; do shift; done
  shift
  exec "$STUB_PYTHON" "$@"
fi
exit 0
"""
UNAME = """#!/bin/sh
echo "uname $*" >> "$STUB_LOG"
case "$1" in -s) echo "$FAKE_OS" ;; -m) echo "$FAKE_ARCH" ;; *) echo "$FAKE_OS" ;; esac
"""
VERSIONS = {"git": "git version 2.43.0", "gh": "gh version 2.65.1 (2025-01-06)", "uv": "uv 0.11.28",
            "mise": "2026.10.12 linux-x64", "claude": "2.1.7 (Claude Code)", "codex": "codex-cli 0.98.3",
            "curl": "curl 8.5.0", "wget": "GNU Wget 1.21"}


def powershell() -> str:
    """A PowerShell to run install.ps1 with, found as Session 1's pre-work tests find theirs."""
    for candidate in (os.environ.get("CURSUS_PWSH"), shutil.which("pwsh"), shutil.which("powershell"),
                      str(Path.home() / ".local/bin/pwsh")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).absolute())
    raise AssertionError("PowerShell is required (no skips): run bash setup/pwsh.sh, or set CURSUS_PWSH")


class Box:
    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.home = root / "home"
        self.sysroot = root / "sysroot"
        self.tmp = root / "tmp"
        self.log = root / "calls.log"
        for d in (self.bin, self.home, self.sysroot, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        self.log.write_text("")
        for name in REAL:
            if found := shutil.which(name):
                (self.bin / name).symlink_to(found)
        self.stub("uname", UNAME)
        self.env = {"PATH": str(self.bin), "HOME": str(self.home), "TMPDIR": str(self.tmp), "LANG": "C.UTF-8",
                    "STUB_LOG": str(self.log), "STUB_PYTHON": sys.executable, "CURSUS_SYSROOT": str(self.sysroot),
                    "FAKE_OS": "Linux", "FAKE_ARCH": "x86_64", "MISE_FAIL": ""}

    def stub(self, name: str, body: str | None = None, version: str | None = None) -> None:
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        if body is None:
            template = {"mise": MISE, "uv": UV}.get(name, LOGGING)
            body = template.replace("{name}", name).replace("{version}", version or VERSIONS.get(name, "1.0.0"))
        path.write_text(body)
        path.chmod(0o755)

    def real(self, name: str) -> None:
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        found = shutil.which(name)
        assert found, f"{name} is needed on PATH for this test"
        path.symlink_to(found)

    def os_release(self, text: str, wsl: bool = False) -> None:
        (self.sysroot / "etc").mkdir(exist_ok=True)
        (self.sysroot / "etc/os-release").write_text(text)
        (self.sysroot / "proc").mkdir(exist_ok=True)
        kernel = "6.6.87.2-microsoft-standard-WSL2" if wsl else "6.12.1-generic"
        (self.sysroot / "proc/version").write_text(f"Linux version {kernel} (builder@host) #1 SMP\n")

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def run(self, argv: list[str], cwd: Path | None = None, input: str | None = None, **env: str):
        # A new session has no controlling terminal, as in CI: /dev/tty cannot be opened.
        return subprocess.run(argv, cwd=cwd or self.root, env={**self.env, **env}, input=input,
                              stdin=None if input is not None else subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120, start_new_session=True, check=False)


def tree(root: Path, skip: tuple[str, ...] = ()) -> dict[str, tuple[int, bytes]]:
    """Every file and link under root: its mode and content (a link's target)."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        if path.is_symlink():
            out[rel] = (0, os.readlink(path).encode())
        elif path.is_file():
            out[rel] = (path.stat().st_mode, path.read_bytes())
    return out


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def course(root: Path, sessions: dict[str, tuple[str, ...]]) -> Path:
    """A course repository: the student setup, the hooks, and sessions holding the given files."""
    repo = root / "course"
    (repo / "setup/student").mkdir(parents=True)
    for name in ("install.sh", "install.ps1", "prepare.py", "versions.env"):
        shutil.copy2(STUDENT / name, repo / "setup/student" / name)
    for name in ("editor.py", "editor.json"):
        shutil.copy2(REPO / "setup" / name, repo / "setup" / name)
    (repo / "setup").joinpath("session-01-fundamentals.sh").write_bytes((REPO / "setup/session-01-fundamentals.sh").read_bytes())
    shutil.copytree(REPO / ".githooks", repo / ".githooks")
    for session, files in sessions.items():
        folder = repo / "sessions" / session
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(f"# {name} of {session}\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "course")
    return repo

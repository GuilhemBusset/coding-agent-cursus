"""Steps 8 and 9 of the student setup: prepare a course clone, then run the setup check.

install.sh and install.ps1 run this after the clone and uv exist, the same way on every platform:

    uv run --no-project --python 3.12 python setup/student/prepare.py [--repo DIR] [--no-check]

1. Activate the clone's git hooks, as setup/git-hooks.sh does (core.hooksPath -> .githooks). A
   hook that is not executable is reported, not changed: the clone's files stay as they are.
2. Sync every session that follows the session contract .github/workflows/session-tests.yml
   enforces: each sessions/*/ folder with a mise.toml, a pyproject.toml and a uv.lock. In each one:
   `mise trust`, `mise install` (the Python and uv the session pins), then
   `mise exec -- uv sync --locked` (its packages from uv.lock). A new session that follows the
   contract needs no change here.
3. Unless --no-check: run the latest session's setup check (exercises/check_setup.py), which
   proves the logins, the push and the agent, and shows its summary block; then the next steps.

It never pulls, resets, switches or commits anything: a clone's branches, HEAD, index and files
are left as they are. Standard library only, so it needs nothing but the Python uv provides.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

CONTRACT = ("mise.toml", "pyproject.toml", "uv.lock")
HOOKS = ".githooks"


def say(text: str) -> None:
    print(f"[setup] {text}", flush=True)


def fail(step: str, why: str, command: str) -> int:
    say(f"FAILED at {step}: {why}")
    say(f"Next: {command}")
    say("Then rerun the same setup command; it continues from there.")
    return 1


def sessions(repo: Path) -> list[Path]:
    """Every sessions/*/ folder that holds all of CONTRACT, in name order."""
    folder = repo / "sessions"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and all((p / name).is_file() for name in CONTRACT))


def latest_check(found: list[Path]) -> Path | None:
    """The setup check of the latest session that has one."""
    checks = [s / "exercises" / "check_setup.py" for s in found if (s / "exercises" / "check_setup.py").is_file()]
    return checks[-1] if checks else None


def activate_hooks(repo: Path) -> None:
    current = subprocess.run(["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True).stdout.strip()
    if current != HOOKS:
        subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", HOOKS], check=True)
    say("hooks: core.hooksPath is .githooks" + (" (already set)" if current == HOOKS else " (set now)"))
    if os.name != "nt":
        # git checks the hooks out executable. One that is not is a change in this clone (or a
        # filesystem without modes): report it, never rewrite it, since files are left as they are.
        for hook in sorted((repo / HOOKS).iterdir()):
            if hook.is_file() and not hook.stat().st_mode & stat.S_IXUSR:
                rel = hook.relative_to(repo).as_posix()
                say(f"hooks: {rel} is not executable, so git skips it; left as it is. To fix: chmod +x {rel}")


def run_quiet(argv: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found on PATH"
    return result.returncode, result.stdout


def sync(repo: Path, session: Path) -> int:
    name = session.relative_to(repo).as_posix()
    say(f"{name}: syncing (the first run downloads its Python and packages)")
    for argv in (["mise", "trust", "mise.toml"], ["mise", "install"], ["mise", "exec", "--", "uv", "sync", "--locked"]):
        code, output = run_quiet(argv, session)
        if code != 0:
            tail = "\n".join(output.strip().splitlines()[-15:])
            if tail:
                print(tail, flush=True)
            return fail(f"session sync ({name})", f"`{' '.join(argv)}` exited {code}",
                        f"cd {name} && {' '.join(argv)}")
    say(f"{name}: synced (mise trust, mise install, mise exec -- uv sync --locked)")
    return 0


def check_command(check: Path, repo: Path) -> str:
    rel = check.parent.relative_to(repo)
    if os.name == "nt":
        return "powershell -NoProfile -ExecutionPolicy Bypass -File .\\" + "\\".join([*rel.parts, "check-setup.ps1"])
    return f"bash {rel.as_posix()}/check-setup.sh"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                        help="the course clone (default: the one this file is in)")
    parser.add_argument("--no-check", action="store_true", help="do not run the setup check")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    if not (repo / HOOKS).is_dir():
        return fail("prepare", f"{repo} is not a course clone (no {HOOKS}/ folder)", "pass --repo <your course clone>")
    activate_hooks(repo)
    found = sessions(repo)
    if not found:
        return fail("session sync", f"no session under {repo / 'sessions'} has " + ", ".join(CONTRACT),
                    "check that the clone is complete (git status)")
    for session in found:
        if sync(repo, session):
            return 1
    check = latest_check(found)
    if check is None:
        say("setup check: no session has exercises/check_setup.py, so nothing was checked")
        return 0
    command = check_command(check, repo)
    if args.no_check:
        say(f"setup check: not run, so nothing is verified yet. Once you are logged in, run it from the clone: {command}")
        return 0
    say(f"setup check: {check.relative_to(repo).as_posix()} (the agent smoke test can take a minute or two)")
    code = subprocess.run([sys.executable, str(check)], cwd=repo, stdin=subprocess.DEVNULL).returncode
    # The latest session's pre-work page, or else the first one any session has.
    pages = [check.parent / "00-prework.html", *sorted(repo.glob("sessions/*/exercises/00-prework.html"))]
    page = next((p for p in pages if p.is_file()), pages[0]).relative_to(repo).as_posix()
    say("Next steps:")
    print("  1. Copy the whole summary block above, both marker lines included, into the form your instructor gives you.")
    if code != 0:
        print(f"     Some lines FAIL: fix them with 'If a line is FAIL' on {page}, then rerun the setup.")
    print(f"  2. Open {page} in your browser and do the pre-reading.")
    print("  3. Open a new terminal window, so that PATH includes the tools installed now.")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

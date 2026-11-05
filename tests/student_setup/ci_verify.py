"""What .github/workflows/student-setup.yml checks after running the student setup twice.

    python ci_verify.py --clone DIR --record STATE.txt          after the first run
    python ci_verify.py --clone DIR --first FIRST.log --second SECOND.log --before STATE.txt
                        [--agents claude,codex] [--preinstalled git,gh]

- git, gh, uv, mise and each agent run with --version, at or above the floors in the clone's
  setup/student/versions.env;
- the clone's core.hooksPath is .githooks;
- the first run synced every session, and `mise exec -- uv sync --locked` exits 0 in each now;
- the first run said it skipped the setup check (--no-login), and never that it passed;
- --preinstalled tools were reported present and left alone by the first run;
- the second run reported every tool present and left alone, and installed nothing;
- `git status --porcelain` and HEAD in the clone are what they were after the first run (STATE.txt).

Standard library only; it runs with `uv run --no-project --python 3.12 python`. Exits 1 with
the list of what failed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def refresh_windows_path() -> None:
    """A new process does not see Path changes the installers wrote to the registry."""
    if sys.platform == "win32":
        import winreg

        parts = []
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(root, key) as handle:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]))
            except OSError:
                continue
        os.environ["PATH"] = os.pathsep.join([*parts, os.environ.get("PATH", "")])
    else:
        os.environ["PATH"] = os.pathsep.join([str(Path.home() / ".local/bin"), os.environ.get("PATH", "")])


def version(tool: str) -> tuple[int, int, int] | None:
    path = shutil.which(tool)
    if not path:
        return None
    out = subprocess.run([path, "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False).stdout
    match = VERSION.search(out.splitlines()[0] if out else "")
    return (int(match[1]), int(match[2]), int(match[3] or 0)) if match else None


def floors(clone: Path) -> dict[str, tuple[int, ...]]:
    values = {}
    for line in (clone / "setup/student/versions.env").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.endswith("_FLOOR"):
            values[key[:-len("_FLOOR")].lower()] = tuple(int(x) for x in value.split("."))
    return values


def state(clone: Path) -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, check=True).stdout

    return git("status", "--porcelain") + git("rev-parse", "HEAD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--clone", type=Path, required=True)
    parser.add_argument("--record", type=Path, help="write git status --porcelain and HEAD to this file, and stop")
    parser.add_argument("--first", type=Path)
    parser.add_argument("--second", type=Path)
    parser.add_argument("--before", type=Path, help="what --record wrote after the first run")
    parser.add_argument("--agents", default="claude,codex")
    parser.add_argument("--preinstalled", default="", help="tools the runner already had, which must be left alone")
    args = parser.parse_args(argv)
    if args.record:
        args.record.write_text(state(args.clone), encoding="utf-8")
        return 0
    if not (args.first and args.second and args.before):
        parser.error("--first, --second and --before are required without --record")
    refresh_windows_path()
    sys.path.insert(0, str(args.clone / "setup/student"))
    import prepare  # the clone's copy, put first on sys.path just above

    failed: list[str] = []
    first = args.first.read_text(encoding="utf-8-sig", errors="replace")
    second = args.second.read_text(encoding="utf-8-sig", errors="replace")
    tools = ["git", "gh", "uv", "mise", *[a for a in args.agents.split(",") if a]]
    minimum = floors(args.clone)
    for tool in tools:
        found = version(tool)
        floor = minimum.get(tool, (0,))
        print(f"{tool}: {'.'.join(map(str, found)) if found else 'not found'} (floor {'.'.join(map(str, floor))})")
        if found is None or found < floor:
            failed.append(f"{tool} --version is missing or below its floor")
    hooks = subprocess.run(["git", "-C", str(args.clone), "config", "--get", "core.hooksPath"],
                           capture_output=True, text=True, check=False).stdout.strip()
    print(f"core.hooksPath: {hooks}")
    if hooks != ".githooks":
        failed.append("core.hooksPath is not .githooks")
    sessions = prepare.sessions(args.clone.resolve())
    if not sessions:
        failed.append("no session follows the session contract")
    for session in sessions:
        name = session.relative_to(args.clone.resolve()).as_posix()
        if f"[setup] {name}: synced" not in first:
            failed.append(f"the first run did not sync {name}")
        code = subprocess.run(["mise", "exec", "--", "uv", "sync", "--locked"], cwd=session,
                              stdin=subprocess.DEVNULL, check=False).returncode
        print(f"{name}: mise exec -- uv sync --locked exited {code}")
        if code:
            failed.append(f"mise exec -- uv sync --locked failed in {name}")
    if "setup check: skipped (--no-login)" not in first and "setup check: skipped (-NoLogin)" not in first:
        failed.append("the first run did not say it skipped the setup check")
    if re.search(r"result: PASS", first + second):
        failed.append("a run without logins reported the setup check as passed")
    for tool in [t for t in args.preinstalled.split(",") if t]:
        if not re.search(rf"^\[setup\] {tool}: present \S+.*left alone", first, re.MULTILINE):
            failed.append(f"the first run did not leave the preinstalled {tool} alone")
    for tool in tools:
        if not re.search(rf"^\[setup\] {tool}: present \S+.*left alone", second, re.MULTILINE):
            failed.append(f"the second run did not report {tool} present and left alone")
    installs = [line for line in second.splitlines() if re.match(r"\[setup\] .*\b(installing|installed|upgrad)", line)]
    if installs:
        failed.append("the second run installed something: " + "; ".join(installs))
    if state(args.clone) != args.before.read_text(encoding="utf-8"):
        failed.append("git status --porcelain or HEAD changed in the clone during the second run")
    print("\n".join(["FAILED:", *failed]) if failed else "Every check passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

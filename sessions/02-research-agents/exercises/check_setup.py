"""Offline readiness only. Run: uv run --locked python exercises/check_setup.py.

Uses only this session's configuration and Pi import probe. Never reads credentials or
calls a provider; live adapter compatibility is a separate, explicitly authorized smoke test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

SESSION = Path(__file__).resolve().parents[1]


def run(argv: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                errors="replace", timeout=60, check=False)
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def check(session: Path = SESSION) -> int:
    failures = []

    def report(name: str, ready: bool, remedy: str) -> None:
        print(f"{name}: {'OK' if ready else 'FAIL — ' + remedy}")
        if not ready:
            failures.append(name)

    report("Python", sys.version_info[:2] == (3, 12), "use Python 3.12 (mise install)")
    try:
        package = json.loads((session / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((session / "package-lock.json").read_text(encoding="utf-8"))
        pins = tomllib.loads((session / "mise.toml").read_text(encoding="utf-8"))["tools"]
        types = json.loads((session / "tsconfig.json").read_text(encoding="utf-8"))
        root = lock["packages"][""]
        configured = (
            pins["node"] == package["engines"]["node"]
            and package["packageManager"] == "npm@" + package["engines"]["npm"]
            and all(root.get(group) == package.get(group) for group in ("dependencies", "devDependencies", "engines"))
            and types["compilerOptions"]["noEmit"] is True
            and (session / "pyproject.toml").is_file() and (session / "uv.lock").is_file()
        )
        expected = package["engines"]
    except (OSError, ValueError, KeyError, TypeError):
        configured, expected = False, {}
    report("Local configuration", configured, "restore the session manifests and locks")
    tools_ready = True
    for tool in ("node", "npm"):
        executable = shutil.which(tool)
        code, out = run([executable, "--version"], session) if executable else (1, "")
        ready = code == 0 and out.removeprefix("v") == expected.get(tool)
        report(tool, ready, "run mise install, then use mise exec -- for this command")
        tools_ready = tools_ready and ready
    if configured and tools_ready:
        node = shutil.which("node")
        assert node is not None
        code, _ = run([node, str(session / "exercises/fixed/check_setup.ts")], session)
        # Do not echo subprocess diagnostics: third-party failures may contain environment data.
        report("Pi imports", code == 0, "run npm ci in this session and retry")
    else:
        report("Pi imports", False, "fix configuration and Node/npm first")
    print("Offline readiness: " + ("FAIL" if failures else "PASS (no API call; live adapter unverified)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(check())

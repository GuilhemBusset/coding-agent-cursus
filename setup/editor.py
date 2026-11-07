"""Install and verify the repository's pinned VS Code extensions, when VS Code is available.

Run through the student setup, or directly with `python setup/editor.py`. The manifest and
checked-in workspace settings carry the configuration; this installer never edits user settings.
It also works when copied alongside editor.json into a standalone exercise's setup/ directory.
VS Code's supported `code` command handles native and Remote-WSL extension installation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

MANIFEST = Path(__file__).with_suffix(".json")


def say(message: str) -> None:
    print(f"[setup] editor: {message}", flush=True)


def extensions(path: Path) -> dict[str, str]:
    """Read exact Marketplace extension versions from the checked-in manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    pins = data.get("extensions") if isinstance(data, dict) else None
    if not isinstance(pins, dict) or not pins:
        raise ValueError(f"{path}: expected a non-empty extensions object")
    for name, version in pins.items():
        if not re.fullmatch(r"[A-Za-z0-9-]+\.[A-Za-z0-9-]+", name):
            raise ValueError(f"{path}: invalid extension ID {name!r}")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
            raise ValueError(f"{path}: {name} needs an exact extension version")
    return pins


def installed(output: str) -> dict[str, str]:
    """Ignore CLI notices and parse `code --list-extensions --show-versions`."""
    found = {}
    for line in output.splitlines():
        name, separator, version = line.strip().rpartition("@")
        if separator and re.fullmatch(r"[A-Za-z0-9-]+\.[A-Za-z0-9-]+", name):
            found[name.lower()] = version
    return found


def display(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def run(command: list[str], repo: Path, timeout: int = 60) -> tuple[int, str]:
    try:
        result = subprocess.run(command, cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return result.returncode, result.stdout


def failed(command: list[str], output: str) -> int:
    say(f"FAILED: {display(command)}")
    tail = "\n".join(output.strip().splitlines()[-15:])
    if tail:
        print(tail, flush=True)
    say("Check VS Code's network access and CLI. In WSL, install/enable Microsoft's WSL extension in Windows VS Code.")
    say("Then rerun the setup command; installed extensions are kept and verified.")
    return 1


def check_wsl_cli(executable: str, repo: Path) -> int:
    """A Windows CLI shim must route extensions into WSL, rather than its Windows host.

    The supported shim uses Microsoft's WSL extension when present and otherwise falls back
    to Windows. Use public CLI operations to verify this prerequisite; Linux/remote CLIs need
    no Windows extension, and no version-specific VS Code server path is constructed here.
    """
    if not os.environ.get("WSL_DISTRO_NAME"):
        return 0
    converter = shutil.which("wslpath")
    if not converter:
        return failed([executable], "WSL integration is unavailable: wslpath was not found on PATH.")
    command = [converter, "-w", str(Path(executable).resolve())]
    status, output = run(command, repo)
    if status:
        return failed(command, output)
    # Linux paths convert to a \\wsl.localhost\... UNC path. A drive-letter path identifies
    # the Windows command shim, including systems with a custom WSL automount directory.
    converted = output.strip()
    if re.match(r"^\\\\wsl(?:\.localhost|\$)\\", converted, re.IGNORECASE):
        return 0
    if not re.match(r"^[A-Za-z]:[/\\]", converted) and not converted.startswith("\\\\"):
        return failed(command, "wslpath did not report a Windows or WSL path for the VS Code CLI.\n" + output)
    command = [executable, "--locate-extension", "ms-vscode-remote.remote-wsl"]
    status, output = run(command, repo)
    located = any(re.match(r"^[A-Za-z]:[/\\]", line.strip()) for line in output.splitlines())
    if status or not located:
        return failed(command, "Microsoft's WSL extension is missing from Windows VS Code; "
                      "Windows-only Python extensions cannot configure this WSL workspace.\n" + output)
    return 0


def configure(repo: Path, manifest: Path = MANIFEST, code: str | None = None) -> int:
    try:
        pins = extensions(manifest)
    except (OSError, ValueError) as error:
        say(f"FAILED: {error}")
        return 1
    executable = (shutil.which(code) or code) if code else shutil.which("code") or shutil.which("code-insiders")
    if not executable:
        say("no VS Code CLI found; extension installation was not run (command-line setup is ready).")
        say("To use VS Code, enable its 'code' command and rerun setup; workspace settings are already checked in.")
        return 0
    if check_wsl_cli(executable, repo):
        return 1

    listing = [executable, "--list-extensions", "--show-versions"]
    status, output = run(listing, repo)
    if status:
        return failed(listing, output)
    current = installed(output)
    for name, version in pins.items():
        if current.get(name.lower()) == version:
            say(f"{name}@{version}: already installed")
            continue
        say(f"installing {name}@{version}")
        command = [executable, "--install-extension", f"{name}@{version}", "--force"]
        status, output = run(command, repo, timeout=300)
        if status:
            return failed(command, output)

    status, output = run(listing, repo)
    if status:
        return failed(listing, output)
    actual = installed(output)
    missing = [f"{name}@{version}" for name, version in pins.items() if actual.get(name.lower()) != version]
    if missing:
        return failed(listing, "VS Code did not report the required installed versions: " + ", ".join(missing))
    say("verified all pinned VS Code extensions; reopen the checked-in workspace if VS Code is already open.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="workspace root (default: the parent of setup/)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="the pinned extension manifest")
    parser.add_argument("--code", help="VS Code CLI executable (default: code, then code-insiders, on PATH)")
    args = parser.parse_args(argv)
    return configure(args.repo.resolve(), args.manifest, args.code)


if __name__ == "__main__":
    raise SystemExit(main())

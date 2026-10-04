"""The host environment a run depends on: probe it, and heal it from checked-in recipes.

ADR 0011, decision 5. `probe` checks what a run will actually use: Node with every package
`setup/package-lock.json` pins, at its locked version; a Chromium that launches and renders
offline HTML (`setup/doctor.mjs`); and the pinned Python test runner. `heal` repairs in stages,
each one checked before it replaces what works:

- npm packages missing or not as locked: `npm ci --include=dev --ignore-scripts` in a staging
  directory under the state directory, checked, then swapped in for `setup/node_modules`. The
  previous one is kept until the re-probe passes, and put back if it does not.
- a missing browser binary: Playwright's own CLI from `setup/node_modules`
  (`install --no-remove chromium`), which leaves `node_modules` alone.
- missing shared libraries: `setup/browser-libs.py`, which unpacks them in user space under
  the state directory. A copy Chromium still cannot start with is rolled back.

It never runs `setup/html-pages.mjs` (the human setup path, whose plain `npm ci` replaces
`node_modules` in place), sudo, or `--with-deps`.

Nothing here touches shell profiles or global configuration. The unpacked libraries reach only
browser processes: `browser_env` names them in CURSUS_BROWSER_LIBS, and
`tools/html-pages/browser.mjs` adds them to the browser's own environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]

MIN_NODE = 22
# The pytest CI pins (.github/workflows/checks.yml), run through uv: the host may have no
# `python` on PATH and no pytest in its system Python.
PYTEST_PIN = "pytest==8.3.5"
PYTEST = ["uv", "run", "--no-project", "--with", PYTEST_PIN, "python", "-m", "pytest"]
LIBS_DIR = "browser-libs"  # under the state directory: setup/browser-libs.py --dest
NPM_DIR = "npm"  # under the state directory: staged npm installs, and the node_modules they replace
NPM_CI = ["npm", "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"]

LIBRARY_ERRORS = ("error while loading shared libraries", "host system is missing dependencies",
                  "missing shared libraries")
BROWSER_MISSING = ("executable doesn't exist", "download new browsers")


@dataclass(frozen=True)
class Probe:
    name: str
    ok: bool
    detail: str
    kind: str  # "node", "browser" or "python-tests": the deliverables a failure blocks


def _run(runner: Runner, cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    """(exit code, stdout then stderr). A missing command or a timeout is a failure, not an error."""
    try:
        proc = runner(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd[:3])} timed out after {timeout}s"
    except OSError as e:
        return 126, f"{cmd[0]}: {e}"
    return proc.returncode, ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()


def _tail(out: str, lines: int = 3) -> str:
    return " | ".join(out.splitlines()[-lines:])


def _libs_copy(state_dir: Path) -> Path | None:
    """The copy setup/browser-libs.py activated under the state directory, if any."""
    dest = state_dir / LIBS_DIR
    try:
        name = (dest / "current").read_text().strip()
    except OSError:
        return None
    copy = dest / name
    if not name.startswith("libs-") or "/" in name or not (copy / "manifest.json").is_file():
        return None
    return copy


def browser_env(state_dir: Path) -> dict[str, str]:
    """What a browser-using subprocess needs in its environment: the active unpacked library
    copy, if there is one. Merge it into the environment of the doctor, verify commands and
    agents; only browser.mjs turns it into LD_LIBRARY_PATH, for the browser alone."""
    copy = _libs_copy(state_dir)
    return {"CURSUS_BROWSER_LIBS": str(copy)} if copy else {}


def _node_major(root: Path, runner: Runner) -> tuple[int | None, str]:
    code, out = _run(runner, ["node", "--version"], root, 30)
    match = re.search(r"v(\d+)\.", out) if code == 0 else None
    return (int(match.group(1)), out.splitlines()[0]) if match else (None, out or "node --version failed")


def _probe_node(root: Path, runner: Runner) -> Probe:
    major, version = _node_major(root, runner)
    if major is None:
        return Probe("node", False, version, "node")
    if major < MIN_NODE:
        return Probe("node", False, f"Node {version} is older than {MIN_NODE}", "node")
    if not (root / "setup" / "node_modules").is_dir():
        return Probe("node", False, f"Node {version}; setup/node_modules missing", "node")
    if problems := _package_problems(root / "setup"):
        return Probe("node", False, f"Node {version}; npm packages not as locked: {', '.join(problems)}", "node")
    return Probe("node", True, f"Node {version}; the locked npm packages are installed", "node")


def _package_problems(setup_dir: Path) -> list[str]:
    """Packages `package-lock.json` pins that `node_modules` beside it lacks or holds at another
    version. Optional packages (platform-specific) are not required."""
    try:
        lock = json.loads((setup_dir / "package-lock.json").read_text())
    except (OSError, ValueError):
        return ["package-lock.json unreadable"]
    problems = []
    for key, meta in sorted(lock.get("packages", {}).items()):
        if not key.startswith("node_modules/") or meta.get("optional"):
            continue
        name = key.rsplit("node_modules/", 1)[1]
        try:
            found = json.loads((setup_dir / key / "package.json").read_text()).get("version")
        except (OSError, ValueError):
            problems.append(f"{name} missing")
            continue
        if found != meta.get("version"):
            problems.append(f"{name} {found} (locked {meta.get('version')})")
    return problems


def _failure(detail: str) -> str | None:
    """Why the browser probe failed, as far as a recipe can act on it: "libraries", "browser"
    or None."""
    text = detail.lower()
    if any(marker in text for marker in LIBRARY_ERRORS):
        return "libraries"
    if any(marker in text for marker in BROWSER_MISSING):
        return "browser"
    return None


def _missing_libraries(executable: Path, state_dir: Path, root: Path, runner: Runner) -> list[str]:
    """`ldd` on the browser, with the active unpacked copy (if any) first on the library path:
    the same check Playwright makes, for failures the doctor's one-line message does not name."""
    env = None
    copy = _libs_copy(state_dir)
    if copy:
        try:
            dirs = json.loads((copy / "manifest.json").read_text())["lib_dirs"]
        except (OSError, ValueError, KeyError):
            dirs = []
        env = {**os.environ, "LD_LIBRARY_PATH": os.pathsep.join(str(copy / d) for d in dirs)}
    code, out = _run(runner, ["ldd", str(executable)], root, 60, env)
    return sorted({line.split("=>")[0].strip() for line in out.splitlines() if "not found" in line})


def _probe_browser(root: Path, state_dir: Path, runner: Runner, node: Probe) -> Probe:
    if not node.ok:
        return Probe("chromium", False, f"not checked: needs Node {MIN_NODE}+ and setup/node_modules", "browser")
    code, out = _run(runner, ["node", "setup/doctor.mjs"], root, 180, {**os.environ, **browser_env(state_dir)})
    lines = out.splitlines()
    detail = next((line for line in lines if line.startswith(("Ready:", "Not ready:"))), _tail(out) or "no output")
    if code == 0:
        return Probe("chromium", True, detail, "browser")
    exe = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("Chromium executable:")), "")
    if _failure(detail) is None and exe and sys.platform.startswith("linux"):
        if not Path(exe).is_file():
            detail += f" (executable doesn't exist at {exe})"
        elif missing := _missing_libraries(Path(exe), state_dir, root, runner):
            detail += f" (ldd: missing shared libraries {', '.join(missing)})"
    return Probe("chromium", False, detail, "browser")


def _probe_pytest(root: Path, runner: Runner) -> Probe:
    code, out = _run(runner, [*PYTEST, "--version"], root, 600)
    version = PYTEST_PIN.replace("==", " ")
    if code == 0 and version in out:
        return Probe("pytest", True, f"{version} via uv run --no-project", "python-tests")
    return Probe("pytest", False, _tail(out) or f"{' '.join(PYTEST)} --version failed", "python-tests")


def probe(root: Path, state_dir: Path, runner: Runner = subprocess.run) -> list[Probe]:
    """Node and the locked npm packages, a real Chromium launch, and the pinned test runner."""
    node = _probe_node(root, runner)
    return [node, _probe_browser(root, state_dir, runner, node), _probe_pytest(root, runner)]


def _by_name(probes: list[Probe]) -> dict[str, Probe]:
    return {p.name: p for p in probes}


def _stage_npm(root: Path, state_dir: Path, runner: Runner) -> tuple[bool, str]:
    """Install the locked packages in a staging directory with lifecycle scripts off (no locked
    package declares one), check them, and swap them in for `setup/node_modules`. The one they
    replace is kept in the state directory until `_settle_npm`. Nothing changes on failure."""
    work = state_dir / NPM_DIR
    staging = work / f"staging-{os.getpid()}-{time.time_ns()}"
    backup, target = work / "node_modules.previous", root / "setup" / "node_modules"
    try:
        staging.mkdir(parents=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copy2(root / "setup" / name, staging / name)
        code, out = _run(runner, NPM_CI, staging, 1800)
        if code != 0:
            return False, f"npm ci failed in a staging directory, setup/node_modules is unchanged: {_tail(out, 2)}"
        if problems := _package_problems(staging):
            return False, f"the staged npm install is incomplete ({', '.join(problems)}); setup/node_modules is unchanged"
        shutil.rmtree(backup, ignore_errors=True)
        if target.exists() or target.is_symlink():
            os.rename(target, backup)
        try:
            os.rename(staging / "node_modules", target)
        except OSError:
            if backup.exists() or backup.is_symlink():
                os.rename(backup, target)
            raise
        return True, "swapped in"
    except OSError as e:
        return False, f"could not stage the npm install, setup/node_modules is unchanged: {e}"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _settle_npm(root: Path, state_dir: Path, keep: bool) -> None:
    """After the re-probe: drop the replaced node_modules, or put it back."""
    backup, target = state_dir / NPM_DIR / "node_modules.previous", root / "setup" / "node_modules"
    if not keep:
        shutil.rmtree(target, ignore_errors=True)
        if backup.exists() or backup.is_symlink():
            os.rename(backup, target)
    shutil.rmtree(backup, ignore_errors=True)


def heal(root: Path, state_dir: Path, runner: Runner = subprocess.run) -> list[str]:
    """Repair what the checked-in recipes can, re-probing after each repair, and say what was
    done. Each repair runs at most once per call. Never sudo, never --with-deps."""
    actions: list[str] = []
    probes = _by_name(probe(root, state_dir, runner))
    major, version = _node_major(root, runner)
    if major is None or major < MIN_NODE:
        actions.append(f"no recipe installs Node.js {MIN_NODE}+ ({version}); browser checks stay unavailable")
    else:
        if not probes["node"].ok:  # Node is fine, so the packages are missing or not as locked
            ok, note = _stage_npm(root, state_dir, runner)
            if ok:
                probes = _by_name(probe(root, state_dir, runner))
                _settle_npm(root, state_dir, keep=probes["node"].ok)
                if probes["node"].ok:
                    note = "installed the locked npm packages in a staging directory (npm ci --ignore-scripts) and swapped them in"
                else:
                    note = (f"the staged npm install did not pass the re-probe ({probes['node'].detail}); "
                            "restored the previous setup/node_modules")
                    probes = _by_name(probe(root, state_dir, runner))
            actions.append(note)
        chromium = probes["chromium"]
        if probes["node"].ok and not chromium.ok and _failure(chromium.detail) == "browser":
            cli = root / "setup" / "node_modules" / "playwright" / "cli.js"
            code, out = _run(runner, ["node", str(cli), "install", "--no-remove", "chromium"], root / "setup", 1800)
            actions.append("installed the Chromium binary with Playwright's CLI (install --no-remove chromium)"
                           if code == 0 else f"Playwright's CLI could not install Chromium: {_tail(out, 2)}")
            probes = _by_name(probe(root, state_dir, runner))
        chromium = probes["chromium"]
        if not chromium.ok and _failure(chromium.detail) == "libraries":
            if not sys.platform.startswith("linux"):
                actions.append(f"no recipe unpacks browser libraries on {sys.platform}")
            else:
                actions.append(_heal_libraries(root, state_dir, runner))
                probes = _by_name(probe(root, state_dir, runner))
    if not probes["pytest"].ok and "uv not found" in probes["pytest"].detail:
        actions.append("no recipe installs uv; Python test checks stay unavailable")
    return actions


def _heal_libraries(root: Path, state_dir: Path, runner: Runner) -> str:
    """Run the library recipe, then launch Chromium for real; a new copy it still cannot start
    with is rolled back to the copy active before (or deactivated, if there was none)."""
    dest = state_dir / LIBS_DIR
    recipe = [sys.executable, str(root / "setup" / "browser-libs.py"), "--dest", str(dest)]
    before = _libs_copy(state_dir)
    code, out = _run(runner, recipe, root, 1800)
    if code != 0:
        return f"setup/browser-libs.py could not unpack the libraries: {_tail(out, 2)}"
    done = f"unpacked Chromium's shared libraries into {dest} with setup/browser-libs.py"
    chromium = _by_name(probe(root, state_dir, runner))["chromium"]
    if chromium.ok or _libs_copy(state_dir) == before:
        return done if chromium.ok else f"{done}, but the active copy did not change and Chromium still fails"
    code, out = _run(runner, [*recipe, "--rollback"], root, 120)
    if code != 0:
        return f"{done}, but Chromium still fails with it ({chromium.detail}) and the rollback failed: {_tail(out, 2)}"
    back = f"rolled back to {before.name}" if before else "deactivated it (no copy was active before)"
    return f"{done}, but Chromium still fails with it ({chromium.detail}); {back}"


def fingerprint(probes: list[Probe]) -> str:
    """A short hash of which probes pass, independent of their order and details, so the engine
    can tell whether the environment changed since a failure."""
    text = "\n".join(sorted(f"{p.kind}/{p.name}={'pass' if p.ok else 'fail'}" for p in probes))
    return hashlib.sha256(text.encode()).hexdigest()[:12]

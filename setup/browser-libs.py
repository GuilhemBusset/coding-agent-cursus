#!/usr/bin/env python3
"""Unpack the shared libraries Playwright's Chromium needs into a directory you own, without root.

The pinned, allowlisted recipe of ADR 0011 (decision 5), for a Debian or Ubuntu host where
Chromium cannot start because system libraries are missing and nobody can run
`sudo apt-get install`:

1. resolve PACKAGES (below), plus what apt's own solver says they need and the host lacks;
2. `apt-get download` them into a staging directory (no root; apt checks each file's hash
   against its signed package indexes);
3. unpack each `.deb` with `dpkg -x`;
4. smoke-test: `ldd` on Playwright's Chromium executables, with LD_LIBRARY_PATH set to the
   unpacked library directories, must report no missing library; then `setup/doctor.mjs`,
   given the staged copy, must launch Chromium and render offline HTML;
5. activate atomically: the staging directory is renamed `libs-<content hash>` and the
   `current` pointer file names it. The copy it replaces stays, named by `previous`.

Any failure leaves the active copy as it was and exits 1. `--rollback` undoes the last
activation: `current` goes back to the copy `previous` names (or to no copy, if none was
active) and the rolled-back copy is deleted. Nothing outside --dest is written: no shell
profile, no ld.so configuration. Only `tools/html-pages/browser.mjs` uses the copy, when
CURSUS_BROWSER_LIBS names it, and only in the environment of the browser process.

    python3 setup/browser-libs.py --dest DIR [--packages a,b] [--browser PATH ...] [--dry-run]
    python3 setup/browser-libs.py --dest DIR --rollback
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

# Playwright 1.63.0's Chromium dependencies for Ubuntu 24.04 and 26.04 (the two lists are
# identical, with the t64 names): `deps["ubuntu24.04-x64"].chromium` and
# `deps["ubuntu26.04-x64"].chromium` in setup/node_modules/playwright-core/lib/coreBundle.js.
# Re-check them when the Playwright pin in setup/package.json changes.
PACKAGES = [
    "libasound2t64",
    "libatk-bridge2.0-0t64",
    "libatk1.0-0t64",
    "libatspi2.0-0t64",
    "libcairo2",
    "libcups2t64",
    "libdbus-1-3",
    "libdrm2",
    "libgbm1",
    "libglib2.0-0t64",
    "libnspr4",
    "libnss3",
    "libpango-1.0-0",
    "libx11-6",
    "libxcb1",
    "libxcomposite1",
    "libxdamage1",
    "libxext6",
    "libxfixes3",
    "libxkbcommon0",
    "libxrandr2",
]
# The C runtime must match the host's dynamic loader, so it is never shadowed.
NEVER = {"libc6", "libc-bin", "libgcc-s1"}
ROOT = Path(__file__).resolve().parent.parent
CORE_BUNDLE = ROOT / "setup" / "node_modules" / "playwright-core" / "lib" / "coreBundle.js"
DOCTOR = ROOT / "setup" / "doctor.mjs"
NONE_ACTIVE = "none"  # `previous` when the last activation replaced no copy
SHARED_LIB = re.compile(r"^lib.+\.so(\.[0-9]+)*$")

Runner = Callable[..., subprocess.CompletedProcess]


class RecipeError(RuntimeError):
    pass


def say(message: str) -> None:
    print(f"browser-libs: {message}", flush=True)


def call(run: Runner, cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
         timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RecipeError(f"{cmd[0]} not found; this recipe needs a Debian or Ubuntu host") from None
    except subprocess.TimeoutExpired:
        raise RecipeError(f"{' '.join(cmd[:2])} timed out after {timeout}s") from None


def tail(proc: subprocess.CompletedProcess, lines: int = 6) -> str:
    text = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return " | ".join(text[-lines:]) or f"exit {proc.returncode}"


def resolve(packages: list[str], run: Runner) -> list[str]:
    """The requested packages plus every package apt's solver would install with them that the
    host lacks (a simulation, which needs no root). Already-installed dependencies are skipped."""
    proc = call(run, ["apt-get", "-s", "--no-install-recommends", "install", *packages])
    if proc.returncode != 0:
        raise RecipeError(f"apt cannot resolve {' '.join(packages)}: {tail(proc)}")
    extra = re.findall(r"^Inst (\S+)", proc.stdout or "", re.M)
    return sorted((set(packages) | set(extra)) - NEVER)


def download(packages: list[str], debs: Path, run: Runner) -> dict[str, Path]:
    proc = call(run, ["apt-get", "download", *packages], cwd=debs, timeout=1200)
    if proc.returncode != 0:
        stale = re.search(r"404|Failed to fetch|Unable to fetch", (proc.stdout or "") + (proc.stderr or ""))
        hint = " (the package indexes look stale; ask the owner for `sudo apt-get update`)" if stale else ""
        raise RecipeError(f"apt-get download failed{hint}: {tail(proc)}")
    files = {}
    for pkg in packages:
        found = sorted(debs.glob(f"{pkg}_*.deb"))
        if not found:
            raise RecipeError(f"apt-get download produced no .deb for {pkg}")
        files[pkg] = found[0]
    return files


def unpack(files: dict[str, Path], root: Path, run: Runner) -> None:
    for pkg, deb in files.items():
        proc = call(run, ["dpkg", "-x", str(deb), str(root)])
        if proc.returncode != 0:
            raise RecipeError(f"dpkg -x {deb.name} failed: {tail(proc)}")


def library_dirs(copy: Path) -> list[str]:
    """Directories under the copy that hold shared libraries, relative to the copy."""
    dirs = {p.parent.relative_to(copy).as_posix() for p in (copy / "root").rglob("lib*.so*")
            if SHARED_LIB.match(p.name) and (p.is_file() or p.is_symlink())}
    return sorted(dirs)


def find_browsers(run: Runner) -> list[Path]:
    """The Chromium executables the locked Playwright launches (headed, and the headless shell),
    from Playwright's own registry, keeping those that are installed."""
    script = ("const { registry } = require(process.argv[1]).registry;"
              "console.log(JSON.stringify(['chromium', 'chromium-headless-shell']"
              ".map(n => registry.findExecutable(n)?.executablePath()).filter(Boolean)));")
    proc = call(run, ["node", "-e", script, str(CORE_BUNDLE)], timeout=60)
    if proc.returncode != 0:
        raise RecipeError(f"cannot locate Playwright's Chromium (run node setup/html-pages.mjs): {tail(proc)}")
    try:
        paths = [Path(p) for p in json.loads((proc.stdout or "").strip().splitlines()[-1])]
    except (ValueError, IndexError):
        raise RecipeError(f"unexpected output locating Chromium: {tail(proc)}") from None
    return [p for p in paths if p.is_file()]


def smoke(executables: list[Path], copy: Path, dirs: list[str], run: Runner) -> int:
    """`ldd` each executable with the unpacked directories first on LD_LIBRARY_PATH. Any
    "not found" fails. Returns how many libraries resolved from the unpacked copy."""
    if not executables:
        raise RecipeError("no Playwright Chromium executable is installed; run node setup/html-pages.mjs first")
    env = {**os.environ, "LD_LIBRARY_PATH": os.pathsep.join(str(copy / d) for d in dirs)}
    from_copy: set[str] = set()
    for exe in executables:
        proc = call(run, ["ldd", str(exe)], env=env, timeout=120)
        out = proc.stdout or ""
        missing = sorted({line.split("=>")[0].strip() for line in out.splitlines() if "not found" in line})
        if missing:
            raise RecipeError(f"{exe.name} still misses {', '.join(missing)}; no allowlisted package provides it")
        if proc.returncode != 0:
            raise RecipeError(f"ldd {exe.name} failed: {tail(proc)}")
        from_copy |= {m.group(1) for m in re.finditer(r"^\s*(\S+) => (\S+)", out, re.M)
                      if m.group(2).startswith(str(copy))}
    return len(from_copy)


def launch(copy: Path, run: Runner) -> None:
    """The real thing: setup/doctor.mjs, given the staged copy, launches Chromium and renders
    offline HTML (ldd alone does not show that the libraries work together)."""
    proc = call(run, ["node", str(DOCTOR)], env={**os.environ, "CURSUS_BROWSER_LIBS": str(copy)}, timeout=180)
    if proc.returncode != 0:
        lines = ((proc.stdout or "") + (proc.stderr or "")).splitlines()
        reason = next((line for line in lines if line.startswith("Not ready:")), tail(proc))
        raise RecipeError(f"Chromium does not start with the staged copy: {reason}")


def content_hash(sums: dict[str, str]) -> str:
    """Names the copy by the exact .deb files it was unpacked from."""
    return hashlib.sha256("\n".join(f"{deb} {sha}" for deb, sha in sorted(sums.items())).encode()).hexdigest()[:16]


def read_pointer(dest: Path, name: str) -> str | None:
    try:
        value = (dest / name).read_text().strip()
    except OSError:
        return None
    return value if value.startswith("libs-") and "/" not in value and (dest / value).is_dir() else None


def write_pointer(dest: Path, name: str, value: str) -> None:
    tmp = dest / f".{name}.tmp"
    tmp.write_text(value + "\n")
    os.replace(tmp, dest / name)


def activate(dest: Path, staging: Path, digest: str) -> str:
    """Rename the staging copy into place and point `current` at it; the copy it replaces
    becomes `previous`. Older copies and leftover staging directories are removed."""
    name = f"libs-{digest}"
    active = read_pointer(dest, "current")
    if (dest / name).is_dir():
        shutil.rmtree(staging)  # the same content is already unpacked there
    else:
        os.rename(staging, dest / name)
    if active != name:
        write_pointer(dest, "previous", active or NONE_ACTIVE)
        write_pointer(dest, "current", name)
    keep = {name, read_pointer(dest, "previous")}
    for entry in dest.iterdir():
        if entry.is_dir() and entry.name.startswith(("libs-", "staging-")) and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)
    return name


def rollback(dest: Path) -> str:
    """Undo the last activation, once. Returns the copy now active, or "" for none."""
    with lock(dest):
        try:
            previous = (dest / "previous").read_text().strip()
        except OSError:
            raise RecipeError("nothing to roll back: no activation is recorded since the last rollback") from None
        restored = read_pointer(dest, "previous")
        if previous != NONE_ACTIVE and not restored:
            raise RecipeError(f"the previous copy {previous!r} is gone; the active copy is unchanged")
        bad = read_pointer(dest, "current")
        if restored:
            write_pointer(dest, "current", restored)
        else:
            (dest / "current").unlink(missing_ok=True)
        (dest / "previous").unlink()
        if bad and bad != restored:
            shutil.rmtree(dest / bad, ignore_errors=True)
        return restored or ""


def lock(dest: Path):
    """One recipe at a time per destination (Linux only, like the recipe)."""
    import fcntl
    handle = (dest / ".lock").open("w")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def install(dest: Path, packages: list[str], browsers: list[Path] | None, run: Runner) -> str:
    dest.mkdir(parents=True, exist_ok=True)
    with lock(dest):
        wanted = resolve(packages, run)
        say(f"{len(wanted)} package(s): {' '.join(wanted)}")
        staging = dest / f"staging-{os.getpid()}-{time.time_ns()}"
        (staging / "debs").mkdir(parents=True)
        try:
            files = download(wanted, staging / "debs", run)
            unpack(files, staging / "root", run)
            dirs = library_dirs(staging)
            if not dirs:
                raise RecipeError("the unpacked packages contain no shared library")
            executables = browsers if browsers is not None else find_browsers(run)
            resolved = smoke(executables, staging, dirs, run)
            say(f"ldd finds every library of {', '.join(e.name for e in executables)}; "
                f"{resolved} resolve from the unpacked copy")
            sums = {deb.name: hashlib.sha256(deb.read_bytes()).hexdigest() for deb in files.values()}
            manifest = {
                "recipe": "setup/browser-libs.py",
                "requested": packages,
                "packages": [{"name": pkg, "deb": deb.name, "sha256": sums[deb.name]} for pkg, deb in sorted(files.items())],
                "lib_dirs": dirs,
                "checked": [str(e) for e in executables],
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            shutil.rmtree(staging / "debs")
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
            launch(staging, run)
            say("Chromium launched and rendered offline HTML with the staged copy")
            return activate(dest, staging, content_hash(sums))
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def main(argv: list[str] | None = None, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="browser-libs.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", required=True, type=Path, help="directory that holds the unpacked copies")
    parser.add_argument("--packages", help="comma-separated package names instead of the pinned list (tests)")
    parser.add_argument("--browser", action="append", type=Path,
                        help="executable to smoke-test instead of Playwright's Chromium (repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve and print what would be downloaded; write nothing")
    parser.add_argument("--rollback", action="store_true",
                        help="undo the last activation (back to the copy it replaced) and exit")
    args = parser.parse_args(argv)
    packages = [p.strip() for p in args.packages.split(",") if p.strip()] if args.packages else PACKAGES
    dest = args.dest.resolve()
    try:
        if not sys.platform.startswith("linux"):
            raise RecipeError("this recipe is for Linux hosts only")
        if args.rollback:
            restored = rollback(dest)
            say(f"rolled back: active copy {dest / restored}" if restored else "rolled back: no copy is active")
            return 0
        if args.dry_run:
            wanted = resolve(packages, run)
            proc = call(run, ["apt-get", "download", "--print-uris", *wanted])
            if proc.returncode != 0:
                raise RecipeError(f"apt-get download --print-uris failed: {tail(proc)}")
            say(f"dry run: would download {len(wanted)} package(s) into {dest}:")
            print((proc.stdout or "").strip())
            executables = args.browser if args.browser is not None else find_browsers(run)
            say(f"would check with ldd: {', '.join(map(str, executables)) or 'nothing installed yet'}, "
                "then launch Chromium through setup/doctor.mjs")
            return 0
        name = install(dest, packages, args.browser, run)
        say(f"active copy: {dest / name}")
        say(f"use it with CURSUS_BROWSER_LIBS={dest}")
        return 0
    except (RecipeError, OSError) as e:
        active = read_pointer(dest, "current") if dest.is_dir() else None
        say(f"failed: {e}")
        say(f"the active copy is unchanged: {dest / active}" if active else "no copy is active")
        return 1


if __name__ == "__main__":
    sys.exit(main())

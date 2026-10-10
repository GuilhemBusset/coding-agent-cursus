"""Session 1 setup check: the logic behind check-setup.sh and check-setup.ps1.

Students run one of the two wrappers next to this file (see 00-prework.html, section
"Check your setup"). Each wrapper starts this script with Python 3.12 through
``uv run --no-project --python 3.12 python check_setup.py``. It uses only the standard
library.

It prints one line per check, ``<name>: PASS <detail>``, ``<name>: FAIL <hint>`` or
``<agent>: not installed (fine)``, then a summary block between BEGIN and END markers
that students paste into the form their instructor gives them. The checks:

- git, gh, uv, mise: installed, with a version at or above the floor in FLOORS.
- git-identity: user.name and user.email are set (only whether, never the values).
- network <host>: an HTTPS request gets any HTTP response within 10 seconds.
- gh-auth: ``gh auth status`` exits 0 (its output is never shown).
- push: a real push of an empty-tree commit to ``setup-check/<handle>`` on the course
  repo, or on your fork when you cannot push to the course repo (the same rule turn-in
  uses), then a check that it arrived, then its deletion. HEAD, the index, the working
  tree and every existing branch are left alone.
- claude, codex: the version of each agent that is installed, and a smoke test that
  asks it to "Reply with exactly: OK". An agent that is not installed is fine; the
  ``agent`` line FAILs only when neither is.

Environment:
  CHECK_SETUP_URLS  Space-separated URLs that replace the default network probes
                    (https://github.com/, https://api.github.com/, https://pypi.org/,
                    plus https://api.anthropic.com/ when claude is installed and
                    https://api.openai.com/ when codex is installed). Use it to probe a
                    campus mirror or to test a proxy. Standard proxy variables
                    (HTTPS_PROXY, NO_PROXY) are honoured.

Exit status: 0 when no line FAILs, 1 otherwise, and never anything else, so a wrapper
can tell a verdict from a checker that could not start.

Nothing secret is printed: no environment variable value, no remote URL (only its
owner/name), no output of gh, git or the agents beyond the version numbers parsed here.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import ssl
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
BEGIN = "----- BEGIN SETUP SUMMARY -----"
END = "----- END SETUP SUMMARY -----"
PAGE = "the pre-work page (sessions/01-fundamentals/exercises/00-prework.html)"
INSTALL_HINT = f"see 'Install the tools' on {PAGE}"
LOGIN_HINT = f"see 'Login troubleshooting' on {PAGE}"
PROMPT = "Reply with exactly: OK"
SMOKE_TIMEOUT = 180
NETWORK_TIMEOUT = 10
# Minimum versions: git 2.23 has `git switch`, which turn-in uses.
FLOORS = {"git": (2, 23, 0), "gh": (2, 0, 0), "uv": (0, 5, 0), "mise": (2024, 1, 0)}
DEFAULT_URLS = ["https://github.com/", "https://api.github.com/", "https://pypi.org/"]
AGENT_URLS = {"claude": "https://api.anthropic.com/", "codex": "https://api.openai.com/"}
AGENT_NAMES = {"claude": "Claude Code", "codex": "Codex"}
VERSION = re.compile(r"(?<![\w.])(\d+)\.(\d+)(?:\.(\d+))?")
# The same origin rules as scripts/turn-in.sh.
ORIGIN = re.compile(r"^(https://(?:[^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)"
                    r"([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)$")
REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
HANDLE = re.compile(r"^[A-Za-z0-9-]+$")
PUSH_PERMISSIONS = {"ADMIN", "MAINTAIN", "WRITE"}
PROBE_IDENTITY = {"GIT_AUTHOR_NAME": "Cursus setup check",
                  "GIT_AUTHOR_EMAIL": "setup-check@example.invalid",
                  "GIT_COMMITTER_NAME": "Cursus setup check",
                  "GIT_COMMITTER_EMAIL": "setup-check@example.invalid"}


def ascii_only(text):
    return text.encode("ascii", "replace").decode("ascii")


class Report:
    def __init__(self):
        self.lines = []
        self.notes = []
        self.names = set()
        self.handle = None

    def add(self, name, status, detail=""):
        line = ascii_only(f"{name}: {status}" + (f" {detail}" if detail else ""))
        self.names.add(name)
        self.lines.append(line)
        print(line, flush=True)

    def ok(self, name, detail=""):
        self.add(name, "PASS", detail)

    def fail(self, name, detail):
        self.add(name, "FAIL", detail)

    def note(self, text):
        line = ascii_only("note: " + text)
        self.notes.append(line)
        print(line, flush=True)

    def failures(self):
        return sum(": FAIL" in line for line in self.lines)


def run(argv, cwd=None, env=None, timeout=60, input=None):
    """Run a command quietly. Returns (exit code, stdout); the code is None if it
    could not start or timed out. Its stderr is discarded, never shown."""
    try:
        result = subprocess.run(
            argv, cwd=cwd, env=env, input=input,
            stdin=subprocess.DEVNULL if input is None else None,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, ""
    return result.returncode, result.stdout


def kill_tree(process):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def run_agent(argv, cwd):
    """Run an agent in its own process group with stdin closed. Returns
    (exit code, stdout, timed out)."""
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **options)
    except (OSError, ValueError):
        return None, "", False
    try:
        stdout, _ = process.communicate(timeout=SMOKE_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            process.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return None, "", True
    return process.returncode, stdout, False


def parse_version(text):
    match = VERSION.search(text)
    if not match:
        return None
    numbers = tuple(int(part or 0) for part in match.groups())
    return numbers, match.group(0)


def dotted(numbers):
    return ".".join(str(n) for n in numbers)


def check_version(report, name, floor=None):
    """Report the tool's version line. Returns its path when it is on PATH."""
    path = shutil.which(name)
    if not path:
        report.fail(name, f"not found on PATH; {INSTALL_HINT}")
        return None
    code, out = run([path, "--version"])
    if code is None:
        report.fail(name, f"'{name} --version' did not run; reinstall it ({INSTALL_HINT})")
        return path
    if code != 0:
        report.fail(name, f"'{name} --version' exited with {code}; reinstall it ({INSTALL_HINT})")
        return path
    version = parse_version(out)
    if version is None:
        report.fail(name, f"could not read a version from '{name} --version'; reinstall it ({INSTALL_HINT})")
    elif floor and version[0] < floor:
        report.fail(name, f"{version[1]} is older than {dotted(floor)}; update it ({INSTALL_HINT})")
    else:
        report.ok(name, version[1] + (f" (>= {dotted(floor)})" if floor else ""))
    return path


def check_identity(report, git):
    if not git:
        report.fail("git-identity", "needs git")
        return
    missing = [key for key in ("user.name", "user.email")
               if not run([git, "config", "--get", key], cwd=HERE)[1].strip()]
    if missing:
        commands = " and ".join(f"git config --global {key} \"...\"" for key in missing)
        report.fail("git-identity", f"{' and '.join(missing)} not set; run {commands}")
    else:
        report.ok("git-identity", "user.name and user.email are set")


def network_label(url, index):
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        host, port = None, None
    if not host:
        return f"url-{index}"
    return f"{host}:{port}" if port else host


def network_failure(error):
    reason = getattr(error, "reason", error)
    if isinstance(reason, socket.gaierror):
        return "DNS lookup failed"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return f"no response within {NETWORK_TIMEOUT} s"
    if isinstance(reason, ssl.SSLError):
        return "TLS handshake failed (a proxy or firewall may intercept HTTPS)"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, ValueError):
        return "not a usable URL"
    return "could not connect"


def check_network(report, agents):
    raw = os.environ.get("CHECK_SETUP_URLS", "")
    urls = raw.split() if raw.strip() else DEFAULT_URLS + [AGENT_URLS[a] for a in agents]
    seen = set()
    for index, url in enumerate(urls, 1):
        label = network_label(url, index)
        if label in seen:
            continue
        seen.add(label)
        name = f"network {label}"
        request = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "cursus-check-setup"})
        try:
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:  # Any other failure means the host is not reachable.
            report.fail(name, network_failure(error) + "; check your connection, proxy or firewall")
            continue
        report.ok(name, f"reachable (HTTP {status})")


def check_auth(report, gh):
    if not gh:
        report.fail("gh-auth", "needs gh")
        return False
    code, _ = run([gh, "auth", "status"])
    if code == 0:
        report.ok("gh-auth", "logged in to GitHub")
        return True
    report.fail("gh-auth", "not logged in; run 'gh auth login'" + (f" (exit {code})" if code else ""))
    return False


def github_handle(gh):
    code, out = run([gh, "api", "user", "--jq", ".login"])
    handle = out.strip()
    if code == 0 and HANDLE.match(handle):
        return handle
    return None


def parent_name(parent):
    if not isinstance(parent, dict):
        return ""
    if parent.get("nameWithOwner"):
        return str(parent["nameWithOwner"])
    owner = parent.get("owner") or {}
    if parent.get("name") and isinstance(owner, dict) and owner.get("login"):
        return f"{owner['login']}/{parent['name']}"
    return ""


def push_destination(gh, origin_repo, handle):
    """Turn-in's routing. Returns (repo, uses origin url, via fork) or an error string."""
    code, out = run([gh, "repo", "view", origin_repo, "--json", "nameWithOwner,parent,viewerPermission"])
    if code != 0:
        return f"could not look up {origin_repo} and your permission on it with gh"
    try:
        info = json.loads(out)
        if not isinstance(info, dict):
            raise ValueError
    except ValueError:
        return f"unexpected reply from 'gh repo view {origin_repo}'"
    name = str(info.get("nameWithOwner") or "")
    if not REPO.match(name):
        name = origin_repo
    parent = parent_name(info.get("parent"))
    permission = str(info.get("viewerPermission") or "")
    if parent:
        return name, True, True  # A clone of your fork: push to it.
    if permission in PUSH_PERMISSIONS:
        return name, True, False
    if not permission:
        return f"could not tell whether you can push to {name}"
    # No push access: use your fork, created if needed, found through the API.
    code, _ = run([gh, "repo", "fork", name, "--clone=false"], timeout=120)
    if code != 0:
        return f"could not create or find your fork of {name} with 'gh repo fork'"
    lowered = handle.lower()
    query = f'.[] | select((.owner.login | ascii_downcase) == "{lowered}") | .full_name'
    delay = 2
    for attempt in range(1, 5):
        code, out = run([gh, "api", "--paginate", f"repos/{name}/forks", "--jq", query], timeout=120)
        if code != 0:
            return f"could not list the forks of {name}"
        forks = [line.strip() for line in out.splitlines() if line.strip()]
        if forks or attempt == 4:
            break
        time.sleep(delay)  # GitHub creates forks asynchronously.
        delay *= 2
    if len(forks) != 1 or not REPO.match(forks[0]):
        return f"expected exactly one fork of {name} owned by {handle}, found {len(forks)}"
    return forks[0], False, True


def check_push(report, git, gh, authenticated):
    if not authenticated:
        report.fail("push", "needs gh-auth")
        return
    if not git:
        report.fail("push", "needs git")
        return
    handle = github_handle(gh)
    if not handle:
        report.fail("push", "could not read your GitHub handle with 'gh api user'")
        return
    report.handle = handle
    code, top = run([git, "rev-parse", "--show-toplevel"], cwd=HERE)
    top = top.strip()
    if code != 0 or not top:
        report.fail("push", "run the check from your clone of the course repository")
        return
    code, origin = run([git, "config", "--get", "remote.origin.url"], cwd=top)
    origin = origin.strip()
    trimmed = origin.rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    match = ORIGIN.match(trimmed)
    if code != 0 or not match:
        report.fail("push", "this clone's 'origin' is not a GitHub repository; clone the course repository from GitHub")
        return
    destination = push_destination(gh, match.group(2), handle)
    if isinstance(destination, str):
        report.fail("push", destination)
        return
    repo, use_origin, via_fork = destination
    # Address every repository by an explicit URL in origin's own scheme, as turn-in does.
    url = origin if use_origin else f"{match.group(1)}{repo}.git"
    branch = f"setup-check/{handle}"
    ref = f"refs/heads/{branch}"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", **PROBE_IDENTITY)
    where = f"to {repo} " + ("(your fork; turn-in will use it)" if via_fork else "(course repo)")
    access_hint = "check 'gh auth setup-git' (HTTPS) or your SSH key"

    def remote_tip():
        code, out = run([git, "ls-remote", url, ref], cwd=top, env=env, timeout=120)
        if code != 0:
            return None
        fields = out.split()
        return fields[0] if fields else ""

    existing = remote_tip()
    if existing is None:
        report.fail("push", f"git could not reach {repo}; {access_hint}")
        return
    if existing:
        report.fail("push", f"{branch} already exists on {repo}; delete that branch on GitHub, then rerun")
        return
    code, tree = run([git, "mktree"], cwd=top, env=env, input="")
    tree = tree.strip()
    if code != 0 or not tree:
        report.fail("push", "git could not create the probe commit")
        return
    code, commit = run([git, "commit-tree", tree, "-m", f"Setup check for {handle}: safe to delete"],
                       cwd=top, env=env)
    commit = commit.strip()
    if code != 0 or not commit:
        report.fail("push", "git could not create the probe commit")
        return
    code, _ = run([git, "push", "--quiet", url, f"{commit}:{ref}"], cwd=top, env=env, timeout=180)
    if code != 0:
        report.fail("push", f"git could not push {where}; {access_hint}")
        return
    arrived = remote_tip() == commit
    run([git, "push", "--quiet", url, "--delete", ref], cwd=top, env=env, timeout=180)
    gone = remote_tip() == ""
    if arrived:
        report.ok("push", where)
    else:
        report.fail("push", f"pushed {where} but could not confirm the branch arrived; {access_hint}")
    if not gone:
        report.note(f"the temporary branch {branch} may still be on {repo}; delete it on GitHub "
                    f"or run gh api -X DELETE repos/{repo}/git/{ref}")


def check_agent(report, name):
    """Version and smoke test for one agent, or 'not installed (fine)'."""
    if not shutil.which(name):
        report.add(name, "not installed (fine)")
        return
    path = check_version(report, name)
    smoke = f"{name}-smoke"
    with tempfile.TemporaryDirectory(prefix="cursus-smoke-", ignore_cleanup_errors=True) as work, \
            tempfile.TemporaryDirectory(prefix="cursus-reply-", ignore_cleanup_errors=True) as replies:
        reply_file = Path(replies) / "last-message.txt"
        if name == "codex":
            argv = [path, "exec", "--skip-git-repo-check", "--output-last-message", str(reply_file), PROMPT]
        else:
            argv = [path, "-p", PROMPT]
        code, stdout, timed_out = run_agent(argv, work)
        if timed_out:
            report.fail(smoke, f"no reply within {SMOKE_TIMEOUT} s; {LOGIN_HINT}")
            return
        if code is None:
            report.fail(smoke, f"could not start {name}; reinstall it ({INSTALL_HINT})")
            return
        if code != 0:
            report.fail(smoke, f"exited with {code}; {LOGIN_HINT}")
            return
        if name == "codex":
            try:
                stdout = reply_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stdout = None
        if stdout is not None and stdout.strip() == "OK":
            report.ok(smoke, "replied OK")
        else:
            report.fail(smoke, f"unexpected reply; {LOGIN_HINT}")


def os_name():
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    if system == "Linux":
        wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in platform.release().lower()
        return "Linux (WSL)" if wsl else "Linux"
    return ascii_only(system or "unknown")


def script_hash():
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def summary(report):
    failures = report.failures()
    lines = [BEGIN,
             f"date: {datetime.datetime.now(datetime.timezone.utc).date().isoformat()} (UTC)",
             f"os: {os_name()}",
             ascii_only(f"kernel: {platform.release() or 'unknown'}"),
             f"python: {platform.python_version()}",
             f"script: check_setup.py sha256 {script_hash()}",
             f"github: {report.handle or 'unknown'}",
             *report.lines, *report.notes,
             "result: PASS" if failures == 0 else f"result: FAIL ({failures} FAIL)",
             END]
    print("\n".join(lines), flush=True)


def guarded(report, name, check, *args):
    """Run one check; an unexpected error becomes a FAIL, and later checks still run."""
    try:
        return check(*args)
    except Exception as error:
        detail = f"internal error ({type(error).__name__}); please report it to your instructor"
        report.fail(name if name not in report.names else "checker", detail)
        return None


def main():
    report = Report()
    try:
        git = guarded(report, "git", check_version, report, "git", FLOORS["git"])
        guarded(report, "git-identity", check_identity, report, git)
        gh = guarded(report, "gh", check_version, report, "gh", FLOORS["gh"])
        guarded(report, "uv", check_version, report, "uv", FLOORS["uv"])
        guarded(report, "mise", check_version, report, "mise", FLOORS["mise"])
        agents = [name for name in ("claude", "codex") if shutil.which(name)]
        guarded(report, "network", check_network, report, agents)
        authenticated = guarded(report, "gh-auth", check_auth, report, gh)
        guarded(report, "push", check_push, report, git, gh, authenticated)
        for name in ("claude", "codex"):
            guarded(report, f"{name}-smoke", check_agent, report, name)
        installed = [AGENT_NAMES[name] for name in agents]
        if "ANTHROPIC_API_KEY" in os.environ:
            report.note(f"ANTHROPIC_API_KEY is set (value hidden); if Claude Code login fails, {LOGIN_HINT}")
        if installed:
            report.ok("agent", " and ".join(installed))
        else:
            report.fail("agent", f"neither Claude Code nor Codex is installed; install one ({INSTALL_HINT})")
    except BaseException as error:  # Including Ctrl-C: still print the summary.
        reason = "interrupted" if isinstance(error, KeyboardInterrupt) else f"internal error ({type(error).__name__})"
        report.fail("checker", reason)
    try:
        summary(report)
    except BaseException:
        return 1
    return 0 if report.failures() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

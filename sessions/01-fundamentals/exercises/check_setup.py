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
  uses), then a check that it arrived, then its deletion if the branch still holds that
  commit. HEAD, the index, the working tree and every existing branch are left alone.
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
  CHECK_SETUP_SMOKE_TIMEOUT
                    Seconds to wait for each agent's smoke-test reply (default 180). A
                    value that is not a positive whole number keeps the default.

Independent checks run at the same time, so the whole run takes about as long as the
slowest one (usually the agent smoke test). Lines are still printed in a fixed order.

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
import secrets
import shutil
import signal
import ssl
import socket
import subprocess
import sys
import tempfile
import threading
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
_override = os.environ.get("CHECK_SETUP_SMOKE_TIMEOUT", "")
if _override.isdigit() and int(_override) > 0:
    SMOKE_TIMEOUT = int(_override)
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
    """The lines of one group of checks, or (after merge) of the whole run. A group
    records its lines quietly; main() prints each group once it is done, in order."""

    def __init__(self, echo=False):
        self.echo = echo
        self.entries = []  # ("line" | "note", text), in the order they were reported
        self.names = set()
        self.handle = None

    def _record(self, kind, text):
        text = ascii_only(text)
        self.entries.append((kind, text))
        if self.echo:
            print(text, flush=True)

    def add(self, name, status, detail=""):
        self.names.add(name)
        self._record("line", f"{name}: {status}" + (f" {detail}" if detail else ""))

    def ok(self, name, detail=""):
        self.add(name, "PASS", detail)

    def fail(self, name, detail):
        self.add(name, "FAIL", detail)

    def note(self, text):
        self._record("note", "note: " + text)

    def merge(self, part):
        for kind, text in part.entries:
            self._record(kind, text)
        self.names |= part.names
        self.handle = self.handle or part.handle

    @property
    def lines(self):
        return [text for kind, text in self.entries if kind == "line"]

    @property
    def notes(self):
        return [text for kind, text in self.entries if kind == "note"]

    def failures(self):
        return sum(": FAIL" in line for line in self.lines)


class Background:
    """Run fn(*args) on a daemon thread, so an interrupted run can still exit at once.
    result() waits for it and re-raises its error."""

    def __init__(self, fn, *args):
        self.value, self.error = None, None
        self.thread = threading.Thread(target=self._run, args=(fn, args), daemon=True)
        self.thread.start()

    def _run(self, fn, args):
        try:
            self.value = fn(*args)
        except BaseException as error:
            self.error = error

    def result(self):
        while self.thread.is_alive():
            self.thread.join(0.2)  # A short wait keeps Ctrl-C responsive on Windows.
        if self.error is not None:
            raise self.error
        return self.value


RUNNING_AGENTS = set()
RUNNING_LOCK = threading.Lock()


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
    with RUNNING_LOCK:
        RUNNING_AGENTS.add(process)
    try:
        stdout, _ = process.communicate(timeout=SMOKE_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            process.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return None, "", True
    finally:
        with RUNNING_LOCK:
            RUNNING_AGENTS.discard(process)
    return process.returncode, stdout, False


def stop_agents():
    with RUNNING_LOCK:
        processes = list(RUNNING_AGENTS)
    for process in processes:
        kill_tree(process)


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
    # One call for both keys; only which keys have a value is kept, never the values.
    _, out = run([git, "config", "--get-regexp", r"^user\.(name|email)$"], cwd=HERE)
    present = {key.lower() for key, _, value in (line.partition(" ") for line in out.splitlines())
               if value.strip()}
    missing = [key for key in ("user.name", "user.email") if key not in present]
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


def probe(url):
    """Returns (True, HTTP status) or (False, reason)."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "cursus-check-setup"})
    try:
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            return True, response.status
    except urllib.error.HTTPError as error:
        return True, error.code
    except Exception as error:  # Any other failure means the host is not reachable.
        return False, network_failure(error)


def check_network(report, agents):
    raw = os.environ.get("CHECK_SETUP_URLS", "")
    urls = raw.split() if raw.strip() else DEFAULT_URLS + [AGENT_URLS[a] for a in agents]
    probes, seen = [], set()
    for index, url in enumerate(urls, 1):
        label = network_label(url, index)
        if label not in seen:
            seen.add(label)
            probes.append((label, Background(probe, url)))  # All hosts at once.
    for label, job in probes:
        reachable, detail = job.result()
        if reachable:
            report.ok(f"network {label}", f"reachable (HTTP {detail})")
        else:
            report.fail(f"network {label}", detail + "; check your connection, proxy or firewall")


def check_auth(report, gh):
    """Returns (gh path, logged in)."""
    if not gh:
        report.fail("gh-auth", "needs gh")
        return gh, False
    code, _ = run([gh, "auth", "status"])
    if code == 0:
        report.ok("gh-auth", "logged in to GitHub")
        return gh, True
    report.fail("gh-auth", "not logged in; run 'gh auth login'" + (f" (exit {code})" if code else ""))
    return gh, False


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


def repo_view(gh, origin_repo):
    """The parsed 'gh repo view' reply, or an error string."""
    code, out = run([gh, "repo", "view", origin_repo, "--json", "nameWithOwner,parent,viewerPermission"])
    if code != 0:
        return f"could not look up {origin_repo} and your permission on it with gh"
    try:
        info = json.loads(out)
        if not isinstance(info, dict):
            raise ValueError
    except ValueError:
        return f"unexpected reply from 'gh repo view {origin_repo}'"
    return info


def push_destination(gh, origin_repo, info, handle):
    """Turn-in's routing. Returns (repo, uses origin url, via fork) or an error string."""
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
    # GitHub creates forks asynchronously: look again after 1, 2 and 4 seconds.
    for delay in (1, 2, 4, None):
        code, out = run([gh, "api", "--paginate", f"repos/{name}/forks", "--jq", query], timeout=120)
        if code != 0:
            return f"could not list the forks of {name}"
        forks = [line.strip() for line in out.splitlines() if line.strip()]
        if forks or delay is None:
            break
        time.sleep(delay)
    if not forks:
        return f"no fork of {name} owned by {handle} is visible yet; wait a minute, then rerun"
    if len(forks) != 1 or not REPO.match(forks[0]):
        return f"expected exactly one fork of {name} owned by {handle}, found {len(forks)}"
    return forks[0], False, True


def probe_commit(git, env):
    """A new commit with an empty tree and no parent, or None. Only adds an object.

    A random line in the message makes every run's commit unique, even two runs in the
    same second, so a run never mistakes another run's branch for its own."""
    code, tree = run([git, "mktree"], cwd=HERE, env=env, input="")
    tree = tree.strip()
    if code != 0 or not tree:
        return None
    message = f"Cursus setup check: safe to delete\n\nrun {secrets.token_hex(8)}\n"
    code, commit = run([git, "commit-tree", tree], cwd=HERE, env=env, input=message)
    commit = commit.strip()
    return commit if code == 0 and commit else None


def origin_url(git):
    """(origin URL, its ORIGIN match or None). Git finds the clone from this script's folder."""
    code, origin = run([git, "config", "--get", "remote.origin.url"], cwd=HERE)
    origin = origin.strip()
    trimmed = origin.rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    return origin, (ORIGIN.match(trimmed) if code == 0 else None)


def tracking_refs(git, branch):
    """The clone's remote-tracking refs for the probe branch, as {refname: tip}."""
    code, out = run([git, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes"], cwd=HERE)
    refs = {}
    if code == 0:
        for line in out.splitlines():
            name, _, tip = line.partition(" ")
            remote, _, rest = name.removeprefix("refs/remotes/").partition("/")
            if remote and rest == branch:
                refs[name] = tip
    return refs


def restore_tracking(git, branch, before, commit):
    """Undo any remote-tracking ref the probe pushes left at this run's commit. The old-value
    check makes each update atomic: a ref that has moved since is never touched."""
    for name, tip in tracking_refs(git, branch).items():
        if tip != commit:
            continue
        if name in before:
            run([git, "update-ref", name, before[name], commit], cwd=HERE)
        else:
            run([git, "update-ref", "-d", name, commit], cwd=HERE)


def check_push(report, auth_job):
    git, gh = shutil.which("git"), shutil.which("gh")
    origin, match, jobs = "", None, None
    if git:
        origin, match = origin_url(git)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", **PROBE_IDENTITY)
    if gh and match:
        # Look these up while gh-auth runs. Nothing is pushed unless gh-auth passes.
        jobs = (Background(github_handle, gh), Background(repo_view, gh, match.group(2)),
                Background(probe_commit, git, env))
    gh, authenticated = auth_job.result()
    if not authenticated:
        report.fail("push", "needs gh-auth")
        return
    if not git:
        report.fail("push", "needs git")
        return
    if not match:
        report.fail("push", "run the check from your clone of the course repository; its 'origin' "
                            "must be the course repository (or your fork) on GitHub")
        return
    handle, info, commit = (job.result() for job in jobs)
    if not handle:
        report.fail("push", "could not read your GitHub handle with 'gh api user'")
        return
    report.handle = handle
    if isinstance(info, str):
        report.fail("push", info)
        return
    destination = push_destination(gh, match.group(2), info, handle)
    if isinstance(destination, str):
        report.fail("push", destination)
        return
    repo, use_origin, via_fork = destination
    # Address every repository by an explicit URL in origin's own scheme, as turn-in does.
    url = origin if use_origin else f"{match.group(1)}{repo}.git"
    branch = f"setup-check/{handle}"
    ref = f"refs/heads/{branch}"
    where = f"to {repo} " + ("(your fork; turn-in will use it)" if via_fork else "(course repo)")
    access_hint = "check 'gh auth setup-git' (HTTPS) or your SSH key"

    def remote_tip():
        code, out = run([git, "ls-remote", url, ref], cwd=HERE, env=env, timeout=120)
        if code != 0:
            return None
        fields = out.split()
        return fields[0] if fields else ""

    if not commit:
        report.fail("push", "git could not create the probe commit")
        return
    # Git 2.56 and later also move the remote-tracking ref of a configured remote whose
    # URL matches the one pushed to; put the student's refs back however the probe ends.
    before = tracking_refs(git, branch)
    try:
        # Never forced: if the branch already exists, the push of this parentless commit is
        # refused and the branch is left as it was.
        code, _ = run([git, "push", "--quiet", url, f"{commit}:{ref}"], cwd=HERE, env=env, timeout=180)
        if code != 0:
            existing = remote_tip()
            if existing is None:
                report.fail("push", f"git could not reach {repo}; {access_hint}")
            elif existing:
                report.fail("push", f"{branch} already exists on {repo}; delete that branch on GitHub, then rerun")
            else:
                report.fail("push", f"git could not push {where}; {access_hint}")
            return
        tip = remote_tip()
        arrived = tip == commit
        if arrived:
            report.ok("push", where)
        else:
            report.fail("push", f"pushed {where} but could not confirm the branch arrived; {access_hint}")
        not_ours = (f"the branch {branch} on {repo} holds a different commit, one this check did "
                    "not push, so the check left it alone")
        if tip and not arrived:
            report.note(not_ours)
        elif arrived or tip is None:
            # The lease makes the deletion atomic: git deletes the branch only while it still
            # holds this run's commit, so a branch someone else moved is never deleted.
            run([git, "push", "--quiet", f"--force-with-lease={ref}:{commit}", url, f":{ref}"],
                cwd=HERE, env=env, timeout=180)
            left = remote_tip()
            if left == commit:
                report.note(f"the temporary branch {branch} is still on {repo}; delete it on GitHub "
                            f"or run gh api -X DELETE repos/{repo}/git/{ref}")
            elif left is None:
                report.note(f"the temporary branch {branch} may still be on {repo}; delete it only if "
                            f"it still points at commit {commit[:12]}")
            elif left:
                report.note(not_ours)

    finally:
        restore_tracking(git, branch, before, commit)

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


def step(part, name, check, *args):
    return guarded(part, name, check, part, *args)


def git_checks(part):
    git = step(part, "git", check_version, "git", FLOORS["git"])
    step(part, "git-identity", check_identity, git)
    return git


def auth_checks(part):
    return step(part, "gh-auth", check_auth, shutil.which("gh")) or (None, False)


def group(fn, *args):
    """Start a group of checks in the background. Returns (its report, its job)."""
    part = Report()
    return part, Background(fn, part, *args)


def main():
    report = Report(echo=True)
    try:
        agents = [name for name in ("claude", "codex") if shutil.which(name)]
        auth = group(auth_checks)
        groups = [group(git_checks),
                  group(step, "gh", check_version, "gh", FLOORS["gh"]),
                  auth,
                  group(step, "uv", check_version, "uv", FLOORS["uv"]),
                  group(step, "mise", check_version, "mise", FLOORS["mise"]),
                  group(step, "network", check_network, agents),
                  group(step, "push", check_push, auth[1]),
                  *[group(step, f"{name}-smoke", check_agent, name) for name in ("claude", "codex")]]
        for part, job in groups:  # Print in this fixed order, each as soon as it is done.
            job.result()
            report.merge(part)
        installed = [AGENT_NAMES[name] for name in agents]
        if "ANTHROPIC_API_KEY" in os.environ:
            report.note(f"ANTHROPIC_API_KEY is set (value hidden); if Claude Code login fails, {LOGIN_HINT}")
        if installed:
            report.ok("agent", " and ".join(installed))
        else:
            report.fail("agent", f"neither Claude Code nor Codex is installed; install one ({INSTALL_HINT})")
    except BaseException as error:  # Including Ctrl-C: still print the summary.
        stop_agents()
        reason = "interrupted" if isinstance(error, KeyboardInterrupt) else f"internal error ({type(error).__name__})"
        report.fail("checker", reason)
    try:
        summary(report)
    except BaseException:
        return 1
    return 0 if report.failures() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

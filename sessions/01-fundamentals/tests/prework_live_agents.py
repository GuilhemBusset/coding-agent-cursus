"""Issue 24 fixtures and opt-in live A1 proof (not collected by pytest).

Run with ``uv run --locked python tests/prework_live_agents.py``. Only the two
agent calls per wrapper use live services. GitHub, push and network probes use
local fixtures; this is NOT the full-platform A3 proof. Missing prerequisites
fail, never skip. All git mutations are confined to disposable repositories.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time


SESSION = Path(__file__).resolve().parents[1]
BEGIN = "----- BEGIN SETUP SUMMARY -----"
END = "----- END SETUP SUMMARY -----"
WRAPPERS = ("bash", "powershell")


def require_program(name):
    path = shutil.which(name)
    assert path, f"Required test prerequisite missing: {name}"
    return str(Path(path).absolute())


def powershell():
    candidates = [os.environ.get("CURSUS_PWSH"), shutil.which("pwsh"),
                  shutil.which("powershell"), str(Path.home() / ".local/bin/pwsh")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).absolute())
    raise AssertionError("PowerShell is required (no skips): run bash setup/pwsh.sh, "
                         "or set CURSUS_PWSH to its executable")


def checked_run(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, **kwargs)
    assert result.returncode == 0, f"Fixture command failed: {argv[0]} ({result.returncode})"
    return result.stdout.strip()


@contextmanager
def local_http(status=200, delay=0):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            self.send_response(status)
            self.end_headers()
            try:
                self.wfile.write(b"local setup probe")
            except (BrokenPipeError, ConnectionResetError):
                pass  # Timeout tests deliberately disconnect before the reply.

        def do_HEAD(self):
            time.sleep(delay)
            self.send_response(status)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/probe"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# Executables emulate external protocols, never import or patch the checker.
# Configuration lives outside the disposable checkout and is private to tests.
STUB = r'''
import json, os, pathlib, subprocess, sys, time
name = pathlib.Path(sys.argv[0]).name
a = sys.argv[1:]
c = json.loads(pathlib.Path(os.environ["PREWORK_FIXTURE_CONFIG"]).read_text())
event = {"tool": name, "args": a, "cwd": os.getcwd()}
if name in ("claude", "codex") and "--version" not in a:
    event["files"] = sorted(os.listdir("."))
    event["stdin"] = os.readlink("/proc/self/fd/0") if pathlib.Path("/proc/self/fd/0").exists() else "unknown"
with open(os.environ["PREWORK_FIXTURE_LOG"], "a") as f:
    f.write(json.dumps(event) + "\n")
if a == ["--version"]:
    versions = {"git": "git version 2.47.3", "gh": "gh version 2.65.1 (2025-01-01)",
                "mise": "2025.3.2 linux-x64", "claude": "2.1.7 (Claude Code)",
                "codex": "codex-cli 0.98.3", "uv": "uv 0.7.8"}
    print(c.get("versions", {}).get(name, versions[name]))
    sys.exit(c.get("version_exit", {}).get(name, 0))
if name == "git":
    if "ls-remote" in a and c.get("ls_remote_fail"):
        print("PRIVATE_GIT_STDERR", file=sys.stderr); sys.exit(17)
    os.execv(c["git"], [c["git"], *a])
if name == "uv":
    if "bootstrap_exit" in c:
        print("PRIVATE_BOOTSTRAP_STDERR", file=sys.stderr)
        sys.exit(c["bootstrap_exit"])
    os.execv(c["uv"], [c["uv"], *a])
if name == "gh":
    if a[:2] == ["auth", "status"]:
        print("PRIVATE_AUTH_STDOUT"); print("PRIVATE_AUTH_STDERR", file=sys.stderr)
        print(os.environ.get("GH_TOKEN", ""), file=sys.stderr)
        sys.exit(c.get("auth_exit", 0))
    if a[:2] == ["repo", "view"]:
        if c.get("bad_repo_json"):
            print("PRIVATE_MALFORMED_JSON"); sys.exit(0)
        data = {"nameWithOwner": c["origin_slug"], "parent": c.get("parent"),
                "viewerPermission": c.get("permission", "WRITE")}
        if "--jq" in a or "-q" in a:
            parent = (data["parent"] or {}).get("nameWithOwner", "")
            print(data["nameWithOwner"] + "|" + parent + "|" + data["viewerPermission"])
        else:
            print(json.dumps(data))
        sys.exit(0)
    if a[:2] == ["repo", "fork"]:
        print("PRIVATE_FORK_OUTPUT")
        sys.exit(c.get("fork_exit", 0))
    if a and a[0] == "api" and any(x.strip("/") == "user" for x in a):
        print(c["handle"] if ("--jq" in a or "-q" in a) else json.dumps({"login": c["handle"]}))
        sys.exit(0)
    if a and a[0] == "api" and any(x.split("?")[0].rstrip("/").endswith("/forks") for x in a):
        forks = c.get("forks", [{"owner": {"login": c["handle"]}, "full_name": c["fork_slug"]}])
        calls = [json.loads(line) for line in pathlib.Path(os.environ["PREWORK_FIXTURE_LOG"]).read_text().splitlines()]
        attempts = sum(e["tool"] == "gh" and any(x.split("?")[0].rstrip("/").endswith("/forks") for x in e["args"]) for e in calls)
        if attempts <= c.get("fork_empty_attempts", 0):
            forks = []
        if "--jq" in a or "-q" in a:
            print("\n".join(x["full_name"] for x in forks if x["owner"]["login"].lower() == c["handle"].lower()))
        else:
            print(json.dumps(forks))
        sys.exit(c.get("fork_lookup_exit", 0))
    sys.exit(42)
if name in ("claude", "codex"):
    mode = c.get("smoke", {}).get(name, "ok")
    if mode == "timeout":
        time.sleep(190)
    reply = {"ok": " \nOK\n ", "mixed": "OK\nActually, no", "empty": "", "wrong": "NOT OK",
             "secret": os.environ.get("ANTHROPIC_API_KEY", "PRIVATE_AGENT_REPLY"),
             "nonzero": "OK", "timeout": "OK", "unreadable": "OK"}[mode]
    print("PRIVATE_AGENT_STDERR", file=sys.stderr)
    if mode == "secret":
        print(" ".join(os.environ.get(k, "") for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GH_TOKEN")), file=sys.stderr)
    if name == "codex":
        assert "exec" in a and "--skip-git-repo-check" in a
        output = next((x.split("=", 1)[1] for x in a if x.startswith("--output-last-message=")), None)
        if output is None:
            assert "--output-last-message" in a
            output = a[a.index("--output-last-message") + 1]
        target = pathlib.Path(output)
        if mode == "unreadable":
            if target.exists(): target.unlink()
            target.mkdir()
        else:
            target.write_text(reply)
        print("PRIVATE_CODEX_PROGRESS (not the final message)")
    else:
        assert a == ["-p", "Reply with exactly: OK"]
        print(reply)
    sys.exit(23 if mode == "nonzero" else 0)
sys.exit(42)
'''


class Sandbox:
    """A dirty student checkout, local GitHub-shaped remotes and isolated PATH."""

    def __init__(self, root, url, agents=("claude", "codex"), live=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = self.root / "student checkout"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.git = require_program("git")
        self.uv = require_program("uv")
        self.bash = require_program("bash")
        self.log = self.root / "commands.jsonl"
        self.config_path = self.root / "fixture.json"
        self.push_log = self.root / "pushes.jsonl"
        self.config = {"git": self.git, "uv": self.uv, "handle": "student-47",
                       "origin_slug": "teaching-lab/course-24", "fork_slug": "student-47/course-renamed"}
        # No inherited git config, credentials, Python startup injection or proxy.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GIT_", "GH_", "GITHUB_", "UV_", "PYTHON"))
                    and k not in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDECODE"}
                    and "proxy" not in k.lower()}
        if live:
            # Live proof uses the operator's existing login mechanism, including
            # API-key based logins. No values are ever printed by this harness.
            for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
                if key in os.environ:
                    self.env[key] = os.environ[key]
        self.env.update({"PATH": str(self.bin), "GIT_CONFIG_NOSYSTEM": "1",
                         "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
                         "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
                         "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                         "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                         "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never",
                         "UV_CACHE_DIR": str(self.root / "uv-cache"),
                         "UV_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1",
                         "CHECK_SETUP_URLS": url, "NO_PROXY": "127.0.0.1,localhost",
                         "PREWORK_FIXTURE_CONFIG": str(self.config_path),
                         "PREWORK_FIXTURE_LOG": str(self.log)})
        if not live:
            self.env["HOME"] = str(self.root / "home")
            Path(self.env["HOME"]).mkdir()
            # Preserve discovery of preinstalled managed Python, without allowing downloads.
            self.env["UV_PYTHON_INSTALL_DIR"] = os.environ.get(
                "UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local/share/uv/python"))
        for program in ("bash", "sh", "env", "dirname", "basename", "date", "uname", "cat",
                        "readlink", "sed", "grep", "awk", "tr", "mktemp", "rm", "sleep"):
            found = shutil.which(program)
            if found:
                (self.bin / program).symlink_to(found)
        for name in ("python", "python3"):
            (self.bin / name).symlink_to(sys.executable)
        for name in ("git", "gh", "mise", *agents):
            self.stub(name)
        (self.bin / "uv").symlink_to(self.uv)
        self.save()
        self.git_run("init", "--quiet", "--initial-branch=student-work", str(self.repo), cwd=self.root)
        self.git_run("config", "user.name", "Student Fixture")
        self.git_run("config", "user.email", "student@example.invalid")
        self.exercise = self.repo / "sessions/01-fundamentals/exercises"
        self.exercise.mkdir(parents=True)
        for name in ("check_setup.py", "check-setup.sh", "check-setup.ps1"):
            source = SESSION / "exercises" / name
            assert source.is_file(), f"Missing implementation: {source}"
            shutil.copy2(source, self.exercise / name)
        (self.repo / "student.txt").write_text("baseline\n")
        self.git_run("add", ".")
        tree = self.git_run("write-tree")
        commit = self.git_run("commit-tree", tree, input="fixture baseline\n")
        self.git_run("update-ref", "refs/heads/student-work", commit)
        self.git_run("update-ref", "refs/heads/homework/s01/old-student", commit)
        (self.repo / "student.txt").write_text("staged edit\n")
        self.git_run("add", "student.txt")
        (self.repo / "student.txt").write_text("unstaged edit\n")
        (self.repo / "untracked.txt").write_text("student notes\n")
        self.course = self.make_remote("course.git", self.config["origin_slug"], commit)
        self.fork = self.make_remote("fork.git", self.config["fork_slug"], commit)
        self.git_run("remote", "add", "origin", "https://github.com/" + self.config["origin_slug"] + ".git")

    def save(self):
        self.config_path.write_text(json.dumps(self.config))

    def stub(self, name):
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_text(f"#!{sys.executable}\n" + STUB)
        path.chmod(0o755)

    def git_run(self, *args, cwd=None, input=None):
        return checked_run([self.git, *args], cwd=cwd or self.repo, env=self.env, input=input)

    def make_remote(self, filename, slug, commit):
        remote = self.root / filename
        self.git_run("init", "--bare", "--quiet", str(remote))
        self.git_run("push", "--quiet", str(remote), f"{commit}:refs/heads/main")
        for prefix in ("https://github.com/", "ssh://git@github.com/", "git@github.com:"):
            for suffix in ("", ".git"):
                self.git_run("config", "--global", "--add", f"url.{remote}.insteadOf", prefix + slug + suffix)
        self.hook(remote)
        return remote

    def hook(self, remote, reject=""):
        # pre-receive observes the actual object, not the checker's claimed result.
        script = f'''#!{sys.executable}
import json, subprocess, sys
for line in sys.stdin:
    old, new, ref = line.split()
    tree = subprocess.check_output([{self.git!r}, "ls-tree", "-r", new], text=True) if set(new) != {{"0"}} else ""
    with open({str(self.push_log)!r}, "a") as f:
        f.write(json.dumps({{"remote": {str(remote)!r}, "old": old, "new": new, "ref": ref, "tree": tree}}) + "\\n")
    if {reject!r} == "all" or ({reject!r} == "delete" and set(new) == {{"0"}}):
        print("PRIVATE_PUSH_STDERR", file=sys.stderr)
        sys.exit(1)
'''
        path = remote / "hooks/pre-receive"
        path.write_text(script)
        path.chmod(0o755)

    def snapshot(self):
        return {"head": self.git_run("rev-parse", "HEAD"),
                "refs": self.git_run("for-each-ref", "--format=%(refname) %(objectname)"),
                "index": (self.repo / ".git/index").read_bytes(),
                "files": {str(p.relative_to(self.repo)): p.read_bytes()
                          for p in self.repo.rglob("*") if p.is_file()
                          and ".git" not in p.relative_to(self.repo).parts}}

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def pushes(self):
        return [json.loads(line) for line in self.push_log.read_text().splitlines()] if self.push_log.exists() else []

    def run(self, wrapper, timeout=45):
        self.save()
        if wrapper == "bash":
            argv = [self.bash, str(self.exercise / "check-setup.sh")]
        else:
            argv = [powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(self.exercise / "check-setup.ps1")]
        # Different CWD proves wrappers locate their own script/repository.
        return subprocess.run(argv, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)


def report(result, success):
    """Check the public report interface, including failure count and exit code."""
    assert result.returncode == (0 if success else 1), (
        f"Expected {'PASS' if success else 'FAIL'} exit; got {result.returncode}\n"
        f"{result.stdout}\n{result.stderr}")
    output = result.stdout
    assert output.isascii(), "Setup output must be ASCII"
    assert output.count(BEGIN) == output.count(END) == 1, output
    before, rest = output.split(BEGIN)
    summary, after = rest.split(END)
    assert not after.strip(), "Summary must be last"
    lines = [line for line in before.splitlines()
             if re.match(r".+: (?:PASS\b|FAIL\b|not installed \(fine\))", line)]
    assert lines, "No check lines"
    for line in lines:
        assert summary.splitlines().count(line) == 1, f"Summary omitted/duplicated: {line}"
    summary_checks = [line for line in summary.splitlines()
                      if re.match(r".+: (?:PASS\b|FAIL\b|not installed \(fine\))", line)
                      and not line.startswith("result:")]
    assert sorted(summary_checks) == sorted(lines), "Summary must repeat the actual checks"
    assert not any(line.startswith("note: FAIL") for line in lines), "Notes are not failing probes"
    assert re.search(r"\b\d{4}-\d{2}-\d{2}\b", summary), "Missing UTC date"
    assert re.search(r"(?im)^os:\s*(Linux(?: \(WSL\))?|macOS|Windows)\s*$", summary)
    failures = sum(bool(re.match(r".+: FAIL\b", line)) for line in lines)
    expected = "result: PASS" if success else f"result: FAIL ({failures} FAIL)"
    assert [line for line in summary.splitlines() if line.startswith("result:")] == [expected], summary
    assert (failures == 0) == success
    assert "Traceback" not in output + result.stderr
    return before, summary


def link_interpreter(binary, bindir, seen=None):
    """Follow env shebangs, preserving symlink resolution for npm launchers."""
    seen = set() if seen is None else seen
    resolved = Path(binary).resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    with resolved.open("rb") as stream:
        first = stream.readline(4096)
    if not first.startswith(b"#!"):
        return
    words = shlex.split(first[2:].decode().strip())
    interpreter = words[0]
    if Path(interpreter).name == "env":
        words = [word for word in words[1:] if not word.startswith("-")]
        assert words, "Cannot determine agent shebang interpreter"
        interpreter = require_program(words[0])
    else:
        assert Path(interpreter).is_file(), "Agent interpreter is unavailable"
    link = bindir / Path(interpreter).name
    if not link.exists():
        link.symlink_to(interpreter)
    link_interpreter(interpreter, bindir, seen)


def main():
    powershell()
    real = {agent: require_program(agent) for agent in ("claude", "codex")}
    for kept, other in (("claude", "codex"), ("codex", "claude")):
        with tempfile.TemporaryDirectory(prefix="prework-live-") as tmp, local_http() as url:
            box = Sandbox(Path(tmp), url, agents=(), live=True)
            (box.bin / kept).symlink_to(real[kept])
            link_interpreter(real[kept], box.bin)
            assert box.env["PATH"] == str(box.bin)
            assert shutil.which(other, path=box.env["PATH"]) is None
            assert shutil.which(kept, path=box.env["PATH"])
            # The versions/probes use real git and uv. Only gh and mise are fixtures.
            (box.bin / "git").unlink()
            (box.bin / "git").symlink_to(box.git)
            for wrapper in WRAPPERS:
                before = box.snapshot()
                result = box.run(wrapper, timeout=220)
                # Do not echo a failed live process: it might contain a secret.
                assert result.returncode == 0, f"Live {kept} via {wrapper} failed; inspect login privately"
                assert f"{kept}-smoke: PASS" in result.stdout
                assert f"{other}: not installed (fine)" in result.stdout
                for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
                    value = os.environ.get(key)
                    assert not value or value not in result.stdout + result.stderr, "Live checker leaked a credential"
                _, summary = report(result, True)
                assert before == box.snapshot(), "Live proof changed the student checkout"
                assert box.pushes(), "Live proof did not exercise the local push fixture"
                print(f"A1 live agent only: {kept}; entry point: {wrapper}; network/gh/push: fixtures")
                print(BEGIN + summary + END)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, subprocess.SubprocessError):
        print("A1 live proof FAILED: both authenticated agents, uv/Python 3.12, git and PowerShell "
              "are required. Run bash setup/pwsh.sh if needed. No live transcript printed.", file=sys.stderr)
        raise SystemExit(1)

"""The pre-work setup check (check-setup.sh, check-setup.ps1 and check_setup.py), offline.

Scenarios run a public entry point against external CLI fixtures and real local git pushes
(prework_live_agents.Sandbox). Both wrappers start the same check_setup.py, so what the
wrappers themselves do (pass the checker's verdict through, fall back to a presence-only
report when uv cannot start it) runs through bash and PowerShell, and the checker's own
checks run through bash only.

Two waits are tested in process on check_setup.py with shorter delays, since nothing outside
the checker can shorten them: the 10-second network timeout and the 1, 2 and 4-second looks
for a fork GitHub is still creating. The agent smoke timeout is shortened through the
documented CHECK_SETUP_SMOKE_TIMEOUT override.
"""

import re
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from prework_live_agents import SESSION, Sandbox, local_http, powershell, report

TOOLS = {"git", "gh", "uv", "mise", "claude", "codex"}
VERSIONS = {"git": "2.47.3", "gh": "2.65.1", "mise": "2025.3.2",
            "claude": "2.1.7", "codex": "0.98.3"}
PRIVATE = ("PRIVATE_AUTH_STDOUT", "PRIVATE_AUTH_STDERR", "PRIVATE_FORK_OUTPUT",
           "PRIVATE_AGENT_STDERR", "PRIVATE_CODEX_PROGRESS", "PRIVATE_GIT_STDERR",
           "PRIVATE_PUSH_STDERR", "PRIVATE_BOOTSTRAP_STDERR", "PRIVATE_MALFORMED_JSON")


@pytest.fixture(params=("bash", "powershell"))
def entrypoint(request):
    """Both wrappers, for the scenarios where the wrapper itself decides the outcome."""
    if request.param == "powershell":
        powershell()  # Fails, never skips, when PowerShell is missing.
    return request.param


@pytest.fixture
def box(tmp_path):
    with local_http() as url:
        yield Sandbox(tmp_path / "sandbox", url)


def check(box, entrypoint, success, **kwargs):
    state = box.snapshot()
    result = box.run(entrypoint, **kwargs)
    before, summary = report(result, success)
    assert box.snapshot() == state, "Checker changed HEAD, refs, index or student files"
    for secret in PRIVATE:
        assert secret not in result.stdout + result.stderr, f"Leaked subprocess output: {secret}"
    assert datetime.now(UTC).date().isoformat() in summary
    return before, summary, result


def status(output, name, expected):
    matches = [line for line in output.splitlines() if line.startswith(name + ": ")]
    assert len(matches) == 1, f"Expected one {name} check, got {matches}\n{output}"
    assert matches[0].startswith(f"{name}: {expected}"), matches[0]
    return matches[0]


def load_checker():
    """check_setup.py as a module, for the waits a test cannot sit through."""
    path = SESSION / "exercises/check_setup.py"
    module = ModuleType("check_setup")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def test_single_agent_matrix(box, entrypoint):
    before, summary, _ = check(box, entrypoint, True)
    for name in TOOLS | {"git-identity", "gh-auth", "push", "agent", "claude-smoke", "codex-smoke"}:
        line = status(before, name, "PASS")
        if name in VERSIONS:
            assert VERSIONS[name] in line
        if name == "uv":
            assert re.search(r"\b\d+\.\d+(?:\.\d+)?\b", line)
    assert box.config["handle"] in summary
    assert re.search(r"(?m)^network .+: PASS", before)
    for agent in ("claude", "codex"):
        calls = [e for e in box.events() if e["tool"] == agent and "--version" not in e["args"]]
        assert len(calls) == 1
        assert "Reply with exactly: OK" in calls[0]["args"]
        assert not Path(calls[0]["cwd"]).is_relative_to(box.repo)
        # A pre-created last-message file is permitted, but no repository context.
        allowed_files = set()
        if agent == "codex":
            args = calls[0]["args"]
            output = next((x.split("=", 1)[1] for x in args if x.startswith("--output-last-message=")), None)
            if output is None:
                output = args[args.index("--output-last-message") + 1]
            allowed_files.add(Path(output).name)
        assert set(calls[0]["files"]) <= allowed_files
        assert calls[0]["stdin"] == "/dev/null"


def test_one_agent_is_enough(box):
    (box.bin / "codex").unlink()
    before, _, _ = check(box, "bash", True)
    status(before, "agent", "PASS")
    status(before, "claude-smoke", "PASS")
    status(before, "codex", "not installed (fine)")
    assert not any(e["tool"] == "codex" for e in box.events())


def test_no_agent_fails(box, entrypoint):
    # Also each wrapper passing a FAIL verdict (exit 1, summary printed) through.
    for agent in ("claude", "codex"):
        (box.bin / agent).unlink()
    before, _, _ = check(box, entrypoint, False)
    status(before, "agent", "FAIL")
    for agent in ("claude", "codex"):
        status(before, agent, "not installed (fine)")


@pytest.mark.parametrize("agent,mode", [("claude", "mixed"), ("codex", "wrong"), ("codex", "nonzero")])
def test_single_agent_exit_code_exact_reply(box, agent, mode):
    other = "codex" if agent == "claude" else "claude"
    (box.bin / other).unlink()
    box.config["smoke"] = {agent: mode}
    before, _, _ = check(box, "bash", False)
    line = status(before, agent + "-smoke", "FAIL")
    assert "login" in line.lower(), "Smoke failure should point to login troubleshooting"
    status(before, "push", "PASS")  # A failed probe does not abort later checks.


def test_smoke_timeout_exit_code(box):
    (box.bin / "codex").unlink()
    box.config["smoke"] = {"claude": "timeout"}  # The fixture agent sleeps 190 s.
    box.env["CHECK_SETUP_SMOKE_TIMEOUT"] = "1"
    start = time.monotonic()
    before, _, _ = check(box, "bash", False, timeout=60)
    elapsed = time.monotonic() - start
    line = status(before, "claude-smoke", "FAIL")
    assert "within 1 s" in line
    # An agent left running would hold the checker another 10 s.
    assert elapsed < 8, f"The agent must be stopped at the 1 s timeout; took {elapsed:.1f} s"
    status(before, "push", "PASS")


@pytest.mark.parametrize("tool,version", [("git", "git version 2.22.9"), ("claude", "PRIVATE_UNPARSEABLE_VERSION")])
def test_version_exit_code(box, tool, version):
    box.config["versions"] = {tool: version}
    before, _, result = check(box, "bash", False)
    status(before, tool, "FAIL")
    assert "PRIVATE_UNPARSEABLE_VERSION" not in result.stdout + result.stderr


@pytest.mark.parametrize("tool,version", [
    ("git", "git version 2.23.0"), ("git", "git version 3.0.0"), ("gh", "gh version 10.0.0"),
])
def test_version_floor_and_new_major(box, tool, version):
    box.config["versions"] = {tool: version}
    before, _, _ = check(box, "bash", True)
    line = status(before, tool, "PASS")
    number = re.search(r"\d+\.\d+\.\d+", version)
    assert number and number[0] in line


def test_missing_tool_exit_code(box):
    (box.bin / "git").unlink()
    before, _, _ = check(box, "bash", False)
    status(before, "git", "FAIL")
    assert re.search(r"(?m)^network .+: PASS", before), "Independent probes must still run"


def test_version_command_failure_exit_code(box):
    box.config["version_exit"] = {"gh": 19}
    before, _, _ = check(box, "bash", False)
    status(before, "gh", "FAIL")


def test_identity_exit_code(box):
    box.git_run("config", "--unset", "user.email")
    before, _, _ = check(box, "bash", False)
    status(before, "git-identity", "FAIL")
    status(before, "claude-smoke", "PASS")


def test_network_http_error_is_reachable(box):
    with local_http(404) as url:
        box.env["CHECK_SETUP_URLS"] = url
        before, _, _ = check(box, "bash", True)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: PASS", before)


def test_network_exit_code_and_multiple_urls(box):
    # Keep a bound socket without listening: deterministic ECONNREFUSED, no race
    # with another process claiming a released 'closed' port.
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        box.env["CHECK_SETUP_URLS"] += f" http://localhost:{port}/closed"
        before, _, _ = check(box, "bash", False)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: PASS", before)
    assert re.search(r"(?m)^network .*localhost.*: FAIL", before)
    status(before, "gh-auth", "PASS")


def test_network_timeout_is_a_failure(monkeypatch):
    # The checker waits NETWORK_TIMEOUT (10 s) for a host that accepts but never answers.
    checker = load_checker()
    monkeypatch.setattr(checker, "NETWORK_TIMEOUT", 0.5)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "*")
    with local_http(delay=5) as url:
        start = time.monotonic()
        result = checker.probe(url)
        elapsed = time.monotonic() - start
    assert result == (False, "no response within 0.5 s")
    assert elapsed < 4, f"The request must stop at the timeout; took {elapsed:.1f} s"


def test_network_tls_failure_exit_code(box):
    # A TLS handshake to a plain local HTTP listener must fail closed.
    box.env["CHECK_SETUP_URLS"] = box.env["CHECK_SETUP_URLS"].replace("http:", "https:")
    before, _, _ = check(box, "bash", False)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: FAIL", before)


# uv missing, and uv failing to start the checker with exit 1, which a wrapper must not take for
# the checker's own FAIL verdict.
@pytest.mark.parametrize("bootstrap", ["missing", 1])
def test_bootstrap_exit_code_fallback(box, entrypoint, bootstrap):
    if bootstrap == "missing":
        (box.bin / "uv").unlink()
    else:
        box.stub("uv")
        box.config["bootstrap_exit"] = bootstrap
    (box.bin / "codex").unlink()
    before, _, _ = check(box, entrypoint, False)
    status(before, "uv" if bootstrap == "missing" else "checker", "FAIL")
    for name in ("git", "gh", "mise", "claude"):
        status(before, name, "PASS")
    status(before, "codex", "not installed (fine)")
    assert not box.pushes()


def test_push_course_round_trip(box):
    box.config["permission"] = "WRITE"
    before, _, _ = check(box, "bash", True)
    line = status(before, "push", "PASS")
    assert box.config["origin_slug"] in line and "(course repo)" in line
    assert_round_trip(box, box.course)
    assert not any(e["args"][:2] == ["repo", "fork"] for e in box.events())


def assert_round_trip(box, remote, cleanup=True):
    events = box.pushes()
    assert events, "No real push was attempted"
    expected = "refs/heads/setup-check/" + box.config["handle"]
    assert all(e["ref"] == expected for e in events), "Touched a ref outside setup-check/<handle>"
    assert all(e["remote"] == str(remote) for e in events), "Push routed to the wrong repository"
    creations = [e for e in events if set(e["new"]) != {"0"}]
    assert len(creations) == 1, "Expected exactly one empty-tree commit push"
    assert creations[0]["tree"] == "", "Probe commit must have an empty tree"
    assert len([e for e in events if set(e["new"]) == {"0"}]) == 1, "Must attempt cleanup"
    refs = box.git_run("ls-remote", str(remote), expected)
    assert bool(refs) != cleanup
    # Require remote verification after the push and again after cleanup.
    calls = [e for e in box.events() if e["tool"] == "git"]
    pushes = [i for i, e in enumerate(calls) if "push" in e["args"]]
    verifications = [i for i, e in enumerate(calls) if "ls-remote" in e["args"]]
    assert len(pushes) >= 2
    assert any(pushes[0] < i < pushes[-1] for i in verifications), "Missing post-push verification"
    if cleanup:
        assert any(i > pushes[-1] for i in verifications), "Missing post-delete verification"


def test_push_read_permission_fork_fallback(box):
    box.config["permission"] = "READ"
    # Includes an unrelated fork and a case-insensitive owner match; the fork's
    # repo name differs from the course, so guessing '<handle>/<course>' fails.
    box.config["forks"] = [
        {"owner": {"login": "someone-else"}, "full_name": "someone-else/course"},
        {"owner": {"login": box.config["handle"].upper()}, "full_name": box.config["fork_slug"]},
    ]
    before, _, _ = check(box, "bash", True)
    line = status(before, "push", "PASS")
    assert box.config["fork_slug"] in line and "your fork" in line and "turn-in" in line
    assert "(course repo)" not in line
    assert any(e["args"][:3] == ["repo", "fork", box.config["origin_slug"]]
               and "--clone=false" in e["args"] for e in box.events())
    assert_round_trip(box, box.fork)


def test_push_clone_of_fork(box):
    course = box.config["origin_slug"]
    box.config["origin_slug"] = box.config["fork_slug"]
    box.config["parent"] = {"nameWithOwner": course, "name": "course-24", "owner": {"login": "teaching-lab"}}
    box.config["permission"] = "READ"
    box.git_run("remote", "set-url", "origin", "git@github.com:" + box.config["fork_slug"] + ".git")
    before, _, _ = check(box, "bash", True)
    line = status(before, "push", "PASS")
    assert box.config["fork_slug"] in line and "your fork" in line
    assert_round_trip(box, box.fork)
    assert not any(e["args"][:2] == ["repo", "fork"] for e in box.events())


def test_fork_lookup_waits_while_github_creates_the_fork(monkeypatch):
    # GitHub creates a fork asynchronously: the checker looks again after 1, 2 and 4 s.
    checker = load_checker()
    sleeps = []
    monkeypatch.setattr(checker, "time", SimpleNamespace(sleep=sleeps.append))
    course = "teaching-lab/course-24"
    info = {"nameWithOwner": course, "parent": None, "viewerPermission": "READ"}

    def fork_listings(*replies):
        pending = list(replies)
        return lambda argv, **_: (0, pending.pop(0) if argv[1] == "api" else "")

    monkeypatch.setattr(checker, "run", fork_listings("", "", "student-47/course-renamed\n"))
    assert checker.push_destination("gh", course, info, "student-47") == ("student-47/course-renamed", False, True)
    assert sleeps == [1, 2]

    sleeps.clear()
    monkeypatch.setattr(checker, "run", fork_listings("", "", "", ""))
    destination = checker.push_destination("gh", course, info, "student-47")
    assert isinstance(destination, str) and "no fork" in destination and "rerun" in destination
    assert sleeps == [1, 2, 4]


@pytest.mark.parametrize("failure", ["ambiguous", "malformed", "transport", "reject"])
def test_push_exit_code_failures(box, failure):
    if failure == "ambiguous":
        box.config["permission"] = "READ"
        box.config["forks"] = [{"owner": {"login": box.config["handle"]}, "full_name": slug}
                               for slug in (box.config["fork_slug"], box.config["handle"] + "/other")]
    if failure == "malformed":
        box.config["bad_repo_json"] = True
    if failure == "transport":
        box.course.rename(box.root / "unavailable.git")
    if failure == "reject":
        box.hook(box.course, reject="all")
    before, _, _ = check(box, "bash", False)
    status(before, "push", "FAIL")
    if failure in {"ambiguous", "malformed"}:
        assert not box.pushes(), "Must not guess a push destination"
    if failure == "reject":
        assert box.pushes(), "Must prove rejection with a real push"


def test_push_cleanup_failure_is_note(box):
    box.hook(box.course, reject="delete")
    before, summary, _ = check(box, "bash", True)
    status(before, "push", "PASS")
    assert re.search(r"(?m)^note:.*setup-check/" + re.escape(box.config["handle"]), before + summary)
    assert_round_trip(box, box.course, cleanup=False)


def test_push_preserves_preexisting_setup_branch(box):
    ref = "refs/heads/setup-check/" + box.config["handle"]
    original = box.git_run("rev-parse", "HEAD")
    box.git_run("--git-dir=" + str(box.course), "update-ref", ref, original)
    before, _, _ = check(box, "bash", False)
    status(before, "push", "FAIL")
    assert box.git_run("ls-remote", str(box.course), ref).split()[0] == original, (
        "Existing remote setup branch must not be overwritten or deleted")


def test_push_auth_exit_code(box):
    box.config["auth_exit"] = 4
    before, _, _ = check(box, "bash", False)
    status(before, "gh-auth", "FAIL")
    status(before, "push", "FAIL needs gh-auth")
    assert not box.pushes()


def test_push_secrets_credentials_and_agent_output(box):
    secrets = {"ANTHROPIC_API_KEY": "sk-ant-prework-a71b9", "OPENAI_API_KEY": "sk-prework-o913f",
               "GH_TOKEN": "ghp_prework_T0ken_9173"}
    box.env.update(secrets)
    credential = "ghp_prework_remote_529d"
    remote = "https://user:" + credential + "@github.com/" + box.config["origin_slug"] + ".git"
    box.git_run("config", "--global", "--add", f"url.{box.course}.insteadOf", remote)
    box.git_run("remote", "set-url", "origin", remote)
    box.config["smoke"] = {"claude": "secret", "codex": "secret"}
    box.config["versions"] = {"mise": "mise 2025.3.2 PRIVATE_VERSION_SUFFIX"}
    before, _, result = check(box, "bash", False)
    status(before, "push", "PASS")
    assert "ANTHROPIC_API_KEY" in before and "value hidden" in before
    for value in [*secrets.values(), credential, remote, "PRIVATE_VERSION_SUFFIX"]:
        assert value not in result.stdout + result.stderr
    assert "https://" not in status(before, "push", "PASS")


def test_ps1_runs_on_windows_powershell_51():
    """Windows students may only have PowerShell 5.1; the suite runs PowerShell 7."""
    path = SESSION / "exercises/check-setup.ps1"
    assert path.read_text(encoding="utf-8").isascii(), "PowerShell 5.1 reads a BOM-less script as ANSI"
    # Tokenize first so 7-only syntax in comments/help strings is not falsely
    # rejected. AST type names catch ternary/null-conditional expressions.
    command = r'''
$tokens = $null; $errors = $null
$tree = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$tokens, [ref]$errors)
$bad = @($tree.FindAll({param($n) $n.GetType().Name -match 'TernaryExpressionAst|PipelineChainAst' -or ($n.PSObject.Properties['NullConditional'] -and $n.NullConditional)}, $true))
$badTokens = @($tokens | Where-Object { $_.Kind.ToString() -in @('AndAnd','OrOr','QuestionQuestion','QuestionQuestionEquals','QuestionDot') -or ($_.Kind.ToString() -eq 'Variable' -and $_.Text -match '^\$IsWindows$') })
$parallel = @($tree.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -in @('ForEach-Object','%') -and @($n.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Parallel' }).Count -gt 0}, $true))
if (@($errors).Count -gt 0 -or $bad.Count -gt 0 -or $badTokens.Count -gt 0 -or $parallel.Count -gt 0) { exit 1 }
'''
    # -CommandWithArgs is not available on all PowerShell 7 hosts. Pass the
    # literal file path in a single-quoted PowerShell string instead.
    command = command.replace("$args[0]", "'" + str(path).replace("'", "''") + "'")
    result = subprocess.run([powershell(), "-NoProfile", "-Command", command],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, "PowerShell parser errors or 7-only syntax in wrapper"

"""Issue 24 acceptance checks, written before implementation.

Offline scenarios exercise BOTH public entry points with external CLI fixtures
and real local git pushes. No tests import checker functions or assume their
names. Smoke timeout scenarios deliberately take 180 seconds each: the timeout
is part of the agreed public behaviour, not a test-only checker setting.

Page tests establish structural coverage and source/evidence correspondence.
Review still establishes prose quality, that linked sources actually support
commands/chapters, screenshot quality, and authenticity of full-platform runs.
A3 remains manual; the separate prework_live_agents.py command establishes A1's
live-agent layer, not A3. No missing prerequisite or artifact is skipped.
"""

import ast
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

import prework_live_agents
from prework_live_agents import (
    BEGIN, END, SESSION, STUB, Sandbox, local_http, powershell, report,
)


TOOLS = {"git", "gh", "uv", "mise", "claude", "codex"}
PLATFORMS = {"macos", "linux", "wsl", "windows"}
VERSIONS = {"git": "2.47.3", "gh": "2.65.1", "mise": "2025.3.2",
            "claude": "2.1.7", "codex": "0.98.3"}
PRIVATE = ("PRIVATE_AUTH_STDOUT", "PRIVATE_AUTH_STDERR", "PRIVATE_FORK_OUTPUT",
           "PRIVATE_AGENT_STDERR", "PRIVATE_CODEX_PROGRESS", "PRIVATE_GIT_STDERR",
           "PRIVATE_PUSH_STDERR", "PRIVATE_BOOTSTRAP_STDERR", "PRIVATE_MALFORMED_JSON")


@pytest.fixture(params=("bash", "powershell"))
def entrypoint(request):
    if request.param == "powershell":
        powershell()  # Required even before any implementation exists.
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
    assert datetime.now(timezone.utc).date().isoformat() in summary
    return before, summary, result


def status(output, name, expected):
    matches = [line for line in output.splitlines() if line.startswith(name + ": ")]
    assert len(matches) == 1, f"Expected one {name} check, got {matches}\n{output}"
    assert matches[0].startswith(f"{name}: {expected}"), matches[0]
    return matches[0]


def test_single_agent_matrix(box, entrypoint):
    # The parametrized test below owns the matrix; this positive run separately
    # verifies all mandatory checks and the exact version values supplied.
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


@pytest.mark.parametrize("agents", [("claude",), ("codex",), ()], ids=["claude-only", "codex-only", "neither"])
def test_single_agent_availability(box, entrypoint, agents):
    for agent in {"claude", "codex"} - set(agents):
        (box.bin / agent).unlink()
    before, _, _ = check(box, entrypoint, bool(agents))
    status(before, "agent", "PASS" if agents else "FAIL")
    for agent in ("claude", "codex"):
        if agent in agents:
            status(before, agent + "-smoke", "PASS")
        else:
            status(before, agent, "not installed (fine)")
            assert not any(e["tool"] == agent for e in box.events())


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["mixed", "empty", "wrong", "nonzero"])
def test_single_agent_exit_code_exact_reply(box, entrypoint, agent, mode):
    other = "codex" if agent == "claude" else "claude"
    (box.bin / other).unlink()
    box.config["smoke"] = {agent: mode}
    before, _, _ = check(box, entrypoint, False)
    line = status(before, agent + "-smoke", "FAIL")
    assert "login" in line.lower(), "Smoke failure should point to login troubleshooting"
    status(before, "push", "PASS")  # A failed probe does not abort later checks.


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_smoke_timeout_exit_code(box, entrypoint, agent):
    box.config["smoke"] = {agent: "timeout"}
    start = time.monotonic()
    before, _, _ = check(box, entrypoint, False, timeout=215)
    elapsed = time.monotonic() - start
    status(before, agent + "-smoke", "FAIL")
    assert 175 <= elapsed < 210, f"Smoke timeout must be 180 seconds; elapsed {elapsed:.1f}"
    status(before, "push", "PASS")


@pytest.mark.parametrize("tool,version", [
    ("git", "git version 2.22.9"), ("gh", "gh version 1.99.9"),
    ("uv", "uv 0.4.99"), ("mise", "2023.12.99"),
    *[(tool, "PRIVATE_UNPARSEABLE_VERSION") for tool in sorted(TOOLS)],
])
def test_version_exit_code(box, entrypoint, tool, version):
    if tool == "uv":
        box.stub("uv")  # --version fixture, all other commands delegate to real uv.
    box.config["versions"] = {tool: version}
    before, _, result = check(box, entrypoint, False)
    status(before, tool, "FAIL")
    assert "PRIVATE_UNPARSEABLE_VERSION" not in result.stdout + result.stderr


@pytest.mark.parametrize("tool,version", [
    ("git", "git version 2.23.0"), ("gh", "gh version 2.0.0"),
    ("uv", "uv 0.5.0"), ("mise", "2024.1.0 linux-x64"),
    ("git", "git version 3.0.0"), ("gh", "gh version 10.0.0"),
    ("uv", "uv 1.0.0"), ("mise", "2026.10.0 linux-x64"),
])
def test_version_floor_and_new_major(box, entrypoint, tool, version):
    if tool == "uv":
        box.stub("uv")
    box.config["versions"] = {tool: version}
    before, _, _ = check(box, entrypoint, True)
    line = status(before, tool, "PASS")
    assert re.search(r"\d+\.\d+\.\d+", version)[0] in line


@pytest.mark.parametrize("tool", ["git", "gh", "mise"])
def test_missing_tool_exit_code(box, entrypoint, tool):
    (box.bin / tool).unlink()
    before, _, _ = check(box, entrypoint, False)
    status(before, tool, "FAIL")
    assert re.search(r"(?m)^network .+: PASS", before), "Independent probes must still run"


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_version_command_failure_exit_code(box, entrypoint, tool):
    if tool == "uv":
        box.stub("uv")
    box.config["version_exit"] = {tool: 19}
    before, _, _ = check(box, entrypoint, False)
    status(before, tool, "FAIL")


@pytest.mark.parametrize("setting", ["user.name", "user.email"])
def test_identity_exit_code(box, entrypoint, setting):
    box.git_run("config", "--unset", setting)
    before, _, _ = check(box, entrypoint, False)
    status(before, "git-identity", "FAIL")
    status(before, "claude-smoke", "PASS")


@pytest.mark.parametrize("code", [200, 401, 403, 404, 503])
def test_network_http_responses_are_reachable(box, entrypoint, code):
    with local_http(code) as url:
        box.env["CHECK_SETUP_URLS"] = url
        before, _, _ = check(box, entrypoint, True)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: PASS", before)


def test_network_exit_code_and_multiple_urls(box, entrypoint):
    # Keep a bound socket without listening: deterministic ECONNREFUSED, no race
    # with another process claiming a released 'closed' port.
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        box.env["CHECK_SETUP_URLS"] += f" http://localhost:{port}/closed"
        before, _, _ = check(box, entrypoint, False)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: PASS", before)
    assert re.search(r"(?m)^network .*localhost.*: FAIL", before)
    status(before, "gh-auth", "PASS")


def test_network_timeout_exit_code(box, entrypoint):
    with local_http(delay=12) as url:
        box.env["CHECK_SETUP_URLS"] = url
        start = time.monotonic()
        before, _, _ = check(box, entrypoint, False, timeout=30)
        elapsed = time.monotonic() - start
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: FAIL", before)
    assert 9 <= elapsed < 25, "Network request must time out after 10 seconds"


def test_network_tls_failure_exit_code(box, entrypoint):
    # A TLS handshake to a plain local HTTP listener must fail closed.
    box.env["CHECK_SETUP_URLS"] = box.env["CHECK_SETUP_URLS"].replace("http:", "https:")
    before, _, _ = check(box, entrypoint, False)
    assert re.search(r"(?m)^network .*127\.0\.0\.1.*: FAIL", before)


@pytest.mark.parametrize("bootstrap", ["missing", 2, 17, 127])
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


def test_internal_error_exit_code_no_traceback(box, entrypoint):
    box.config["smoke"] = {"codex": "unreadable"}
    before, _, _ = check(box, entrypoint, False)
    assert "codex-smoke: FAIL" in before or "checker: FAIL internal error" in before


@pytest.mark.parametrize("permission", ["WRITE", "ADMIN", "MAINTAIN"])
def test_push_course_round_trip(box, entrypoint, permission):
    box.config["permission"] = permission
    before, _, _ = check(box, entrypoint, True)
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


def test_push_read_permission_fork_fallback(box, entrypoint):
    box.config["permission"] = "READ"
    # Includes an unrelated fork and a case-insensitive owner match; the fork's
    # repo name differs from the course, so guessing '<handle>/<course>' fails.
    box.config["forks"] = [
        {"owner": {"login": "someone-else"}, "full_name": "someone-else/course"},
        {"owner": {"login": box.config["handle"].upper()}, "full_name": box.config["fork_slug"]},
    ]
    before, _, _ = check(box, entrypoint, True)
    line = status(before, "push", "PASS")
    assert box.config["fork_slug"] in line and "your fork" in line and "turn-in" in line
    assert "(course repo)" not in line
    assert any(e["args"][:3] == ["repo", "fork", box.config["origin_slug"]]
               and "--clone=false" in e["args"] for e in box.events())
    assert_round_trip(box, box.fork)


def test_push_clone_of_fork(box, entrypoint):
    course = box.config["origin_slug"]
    box.config["origin_slug"] = box.config["fork_slug"]
    box.config["parent"] = {"nameWithOwner": course, "name": "course-24", "owner": {"login": "teaching-lab"}}
    box.config["permission"] = "READ"
    box.git_run("remote", "set-url", "origin", "git@github.com:" + box.config["fork_slug"] + ".git")
    before, _, _ = check(box, entrypoint, True)
    line = status(before, "push", "PASS")
    assert box.config["fork_slug"] in line and "your fork" in line
    assert_round_trip(box, box.fork)
    assert not any(e["args"][:2] == ["repo", "fork"] for e in box.events())


def test_push_fork_creation_is_eventually_visible(box, entrypoint):
    box.config["permission"] = "READ"
    box.config["fork_empty_attempts"] = 2
    before, _, _ = check(box, entrypoint, True)
    status(before, "push", "PASS")
    assert_round_trip(box, box.fork)
    lookups = [e for e in box.events() if e["tool"] == "gh"
               and any(a.split("?")[0].rstrip("/").endswith("/forks") for a in e["args"])]
    assert len(lookups) >= 3, "Fork creation is asynchronous; retry empty lookup results"


def test_push_uses_authenticated_handle(box, entrypoint):
    box.config["handle"] = "Ada-902"
    before, summary, _ = check(box, entrypoint, True)
    status(before, "push", "PASS")
    assert "Ada-902" in summary
    assert_round_trip(box, box.course)


@pytest.mark.parametrize("failure", ["none", "ambiguous", "lookup", "fork", "malformed", "transport", "reject", "verify"])
def test_push_exit_code_failures(box, entrypoint, failure):
    if failure in {"none", "ambiguous", "lookup", "fork"}:
        box.config["permission"] = "READ"
        if failure == "none":
            box.config["forks"] = []
        if failure == "ambiguous":
            box.config["forks"] = [{"owner": {"login": box.config["handle"]}, "full_name": slug}
                                   for slug in (box.config["fork_slug"], box.config["handle"] + "/other")]
        if failure == "lookup":
            box.config["fork_lookup_exit"] = 9
        if failure == "fork":
            box.config["fork_exit"] = 9
    if failure == "malformed":
        box.config["bad_repo_json"] = True
    if failure == "transport":
        box.course.rename(box.root / "unavailable.git")
    if failure == "reject":
        box.hook(box.course, reject="all")
    if failure == "verify":
        box.config["ls_remote_fail"] = True
    before, _, _ = check(box, entrypoint, False)
    status(before, "push", "FAIL")
    if failure in {"none", "ambiguous", "lookup", "fork", "malformed"}:
        assert not box.pushes(), "Must not guess a push destination"
    if failure == "reject":
        assert box.pushes(), "Must prove rejection with a real push"


def test_push_cleanup_failure_is_note(box, entrypoint):
    box.hook(box.course, reject="delete")
    before, summary, _ = check(box, entrypoint, True)
    status(before, "push", "PASS")
    assert re.search(r"(?m)^note:.*setup-check/" + re.escape(box.config["handle"]), before + summary)
    assert_round_trip(box, box.course, cleanup=False)


def test_push_preserves_preexisting_setup_branch(box, entrypoint):
    ref = "refs/heads/setup-check/" + box.config["handle"]
    original = box.git_run("rev-parse", "HEAD")
    box.git_run("--git-dir=" + str(box.course), "update-ref", ref, original)
    before, _, _ = check(box, entrypoint, False)
    status(before, "push", "FAIL")
    assert box.git_run("ls-remote", str(box.course), ref).split()[0] == original, (
        "Existing remote setup branch must not be overwritten or deleted")


def test_push_auth_exit_code(box, entrypoint):
    box.config["auth_exit"] = 4
    before, _, _ = check(box, entrypoint, False)
    status(before, "gh-auth", "FAIL")
    status(before, "push", "FAIL needs gh-auth")
    assert not box.pushes()


def test_push_secrets_credentials_and_agent_output(box, entrypoint):
    secrets = {"ANTHROPIC_API_KEY": "sk-ant-prework-a71b9", "OPENAI_API_KEY": "sk-prework-o913f",
               "GH_TOKEN": "ghp_prework_T0ken_9173"}
    box.env.update(secrets)
    credential = "ghp_prework_remote_529d"
    remote = "https://user:" + credential + "@github.com/" + box.config["origin_slug"] + ".git"
    box.git_run("config", "--global", "--add", f"url.{box.course}.insteadOf", remote)
    box.git_run("remote", "set-url", "origin", remote)
    box.config["smoke"] = {"claude": "secret", "codex": "secret"}
    box.config["versions"] = {"mise": "mise 2025.3.2 PRIVATE_VERSION_SUFFIX"}
    before, _, result = check(box, entrypoint, False)
    status(before, "push", "PASS")
    assert "ANTHROPIC_API_KEY" in before and "value hidden" in before
    for value in [*secrets.values(), credential, remote, "PRIVATE_VERSION_SUFFIX"]:
        assert value not in result.stdout + result.stderr
    assert "https://" not in status(before, "push", "PASS")


def test_ps51_syntax_and_launch_contract():
    path = SESSION / "exercises/check-setup.ps1"
    source = read(path)
    assert source.isascii(), "PowerShell 5.1 wrapper must be ASCII"
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
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "PowerShell parser errors or 7-only syntax in wrapper"
    assert re.search(r"powershell\s+-NoProfile\s+-ExecutionPolicy\s+Bypass\s+-File\s+\.\\check-setup\.ps1", source, re.I)


class Element:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def text(self):
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def descendants(self, tag=None):
        for child in self.children:
            if isinstance(child, Element):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.descendants(tag)

    def ancestor(self, predicate):
        node = self
        while node is not None:
            if predicate(node):
                return node
            node = node.parent
        return None


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Element("document")
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current.ancestor(lambda node: node.tag == tag)
        if node and node.parent:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)

    def section(self, ident):
        nodes = [n for n in self.root.descendants() if n.attrs.get("id") == ident]
        assert len(nodes) == 1, f"Expected one #{ident} section"
        return nodes[0]


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def page():
    return Document(read(SESSION / "exercises/00-prework.html"))


def normalized(value):
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", unescape(value).replace("\\|", "|").replace("`", "")).strip()


def dates(node):
    values = [n.attrs.get("datetime", "") for n in node.descendants("time")]
    assert values, "Missing dated <time datetime=...> source check"
    for value in values:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), value
        assert date.fromisoformat(value) <= datetime.now(timezone.utc).date(), value
    return values


def links(node):
    return [n.attrs.get("href", "") for n in node.descendants("a")]


def blocks(page):
    return [n for n in page.root.descendants() if "data-install" in n.attrs]


def test_page_content_install_coverage(page):
    covered = set()
    for block in blocks(page):
        tool = block.attrs.get("data-tool")
        platforms = set(block.attrs.get("data-platform", "").split())
        assert tool in TOOLS and platforms and platforms <= PLATFORMS
        commands = [n for n in block.descendants("code") if n.parent.tag == "pre" and n.text().strip()]
        assert commands, f"{tool}/{platforms}: no pre>code installation command"
        covered.update((tool, platform) for platform in platforms)
        source = "\n".join(n.text() for n in commands).lower()
        if tool == "claude":
            assert "npm" not in source, "Claude Code must use its native installer"
            assert re.search(r"claude\.ai/install\.(?:sh|ps1|cmd)", source), source
        if tool == "codex":
            assert "@openai/codex" in source or ("codex" in source and re.search(r"brew|winget|github\.com/openai/codex", source))
    assert covered == {(tool, platform) for tool in TOOLS for platform in PLATFORMS}, covered
    for ident in ("reading", "install", "login", "check", "platforms"):
        page.section(ident)


def test_page_content_login_and_check_instructions(page):
    login = normalized(page.section("login").text())
    assert "unset ANTHROPIC_API_KEY" in login
    assert "Remove-Item Env:ANTHROPIC_API_KEY" in login
    # These are named operational hazards; the adequacy of the prose is reviewed.
    for pattern in (r"(?:copy|paste)", r"\bURL\b", r"(?:\.bashrc|\.zshrc|\brc\b|shell.*(?:profile|config))",
                    r"Windows", r"user.*environment|environment.*user"):
        assert re.search(pattern, login, re.I), pattern
    all_text = normalized(page.root.text())
    assert re.search(r"npm\s+(?:i|install)\s+-g\s+codex\b", all_text)
    assert "unrelated" in all_text.lower()
    check_text = normalized(page.section("check").text())
    assert re.search(r"bash\s+(?:\S*/)?check-setup\.sh", check_text)
    assert re.search(r"powershell\s+-NoProfile\s+-ExecutionPolicy\s+Bypass\s+-File", check_text, re.I)
    for token in ("check-setup.ps1", "setup-check/", "fork", "PASS", "FAIL", "paste"):
        assert token.lower() in check_text.lower()
    assert re.search(r"delet|remov|clean", check_text, re.I)
    assert re.search(r"instructor|teacher", check_text, re.I)
    assert "Git Bash" in all_text and "PATH" in all_text
    assert "../prework-verification.md" in links(page.root)


PLATFORM_NAMES = {
    "linux": r"(?:native\s+)?linux",
    "wsl": r"wsl(?:2)?",
    "macos": r"macos|mac os",
    "windows-powershell": r"(?:windows\s+)?powershell\s*5\.1",
    "windows-git-bash": r"(?:windows\s+)?git\s+bash",
}


def test_page_content_platform_evidence_matches(page):
    nodes = [n for n in page.section("platforms").descendants() if "data-status" in n.attrs]
    record = read(SESSION / "prework-verification.md")
    for platform, pattern in PLATFORM_NAMES.items():
        candidates = [n for n in nodes if re.search(pattern, n.text(), re.I)
                      or n.attrs.get("data-platform") == platform]
        # WSL entries sometimes mention Linux; the native entry must be separate.
        if platform == "linux":
            candidates = [n for n in candidates if not re.search(r"\bWSL", n.text(), re.I)
                          or n.attrs.get("data-platform") == "linux"]
        assert len(candidates) == 1, f"One status required for {platform}"
        state = candidates[0].attrs["data-status"]
        assert state in {"tested", "untested"}
        rows = [line for line in record.splitlines() if re.search(pattern, line, re.I)
                and re.search(r"\b" + state + r"\b", line, re.I)]
        assert rows, f"Verification record must explicitly agree: {platform}: {state}"
        if state == "tested":
            assert BEGIN in record and END in record and "result: PASS" in record
            assert re.search(r"kernel", record, re.I)
            assert re.search(r"\b[0-9a-f]{64}\b", record, re.I), "Tested platforms need script hashes"
    assert not re.search(r"data-status\s*=\s*['\"]fixture-tested", read(SESSION / "exercises/00-prework.html"))


OFFICIAL = {
    "git": [("git-scm.com", "/")],
    "gh": [("cli.github.com", "/"), ("github.com", "/cli/")],
    "uv": [("docs.astral.sh", "/")],
    "mise": [("mise.jdx.dev", "/")],
    "claude": [("code.claude.com", "/docs/en/setup")],
    "codex": [("developers.openai.com", "/codex"), ("github.com", "/openai/codex")],
}
INSTALL = re.compile(r"\b(?:curl|irm|iex|winget|brew|apt(?:-get)?|dnf)\b|\bnpm\s+(?:i|install)\b|\binstall\b|\|\s*(?:ba)?sh\b", re.I)


def official(tool, url):
    parts = urlsplit(url)
    return parts.scheme == "https" and any(parts.hostname == host and parts.path.startswith(prefix)
                                            for host, prefix in OFFICIAL[tool])


def test_page_sources_every_install_command_is_audited(page):
    record = read(SESSION / "prework-verification.md")
    match = re.search(r"(?im)^#{1,6}\s+Install sources\s*$", record)
    assert match, "Verification record needs an Install sources table"
    section = re.split(r"(?m)^#{1,6}\s", record[match.end():], maxsplit=1)[0]
    rows = [normalized(line) for line in section.splitlines() if line.lstrip().startswith("|")]
    assert rows, "Install sources must be a table"
    for node in page.root.descendants():
        if node.tag not in {"code", "pre"}:
            continue
        if INSTALL.search(node.text()):
            assert node.ancestor(lambda n: "data-install" in n.attrs), (
                "Every installation command (even outside #install) needs a data-install block: " + node.text())
    for block in blocks(page):
        tool = block.attrs["data-tool"]
        urls = [url for url in links(block) if official(tool, url)]
        assert urls, f"No official documentation for {tool}"
        checked_dates = dates(block)
        commands = [normalized(n.text()) for n in block.descendants("code") if n.parent.tag == "pre"]
        assert commands
        candidates = [row for row in rows if re.search(r"\b" + tool + r"\b", row, re.I)
                      and any(url in row for url in urls) and any(day in row for day in checked_dates)]
        assert candidates, f"No matching Install sources row for {tool}: {urls} / {checked_dates}"
        for command in commands:
            assert any(command in row for row in candidates), f"Exact command absent from audit: {command}"
        for platform in block.attrs["data-platform"].split():
            assert any(platform in row.lower() for row in candidates), f"Missing platform in audit: {tool}/{platform}"
        # At least six cells: tool, platform/shell, command, URL, source claim, date.
        assert any(len(re.split(r"(?<!\\)\|", row.strip("|"))) >= 6 for row in candidates)


def test_page_reading_links_chapters_dates_and_audit(page):
    reading = page.section("reading")
    all_links = [n for n in reading.descendants("a") if n.attrs.get("href", "").startswith("https://")]
    text = normalized(reading.text()).lower()
    assert "3blue1brown" in text and "karpathy" in text
    assert re.search(r"large language models|llms", text) and "briefly" in text
    assert "how i use llms" in text
    assert re.search(r"pick|choose|your agent", text)
    videos = [n for n in all_links if urlsplit(n.attrs["href"]).hostname in {"www.youtube.com", "youtube.com", "youtu.be", "3blue1brown.com", "www.3blue1brown.com"}]
    timed = [n for n in videos if parse_qs(urlsplit(n.attrs["href"]).query).get("t")]
    assert len({parse_qs(urlsplit(n.attrs["href"]).query)["t"][0] for n in timed}) >= 2, "Two distinct Karpathy chapter timestamps required"
    assert all(normalized(n.text()) for n in timed), "Chapters need names"
    video_ids = set()
    for link in timed:
        parsed = urlsplit(link.attrs["href"])
        assert parsed.hostname in {"www.youtube.com", "youtube.com", "youtu.be"}
        identity = parsed.path.strip("/") if parsed.hostname == "youtu.be" else parse_qs(parsed.query).get("v", [""])[0]
        assert identity, "Chapter URL must identify the video"
        video_ids.add(identity)
    assert len(video_ids) == 1, "Karpathy chapter selections must refer to the same video"
    assert any(n not in timed for n in videos), "Full-length 3Blue1Brown reading link required"
    anthology = [n for n in all_links if (urlsplit(n.attrs["href"]).hostname or "").endswith(".anthropic.com")
                 or urlsplit(n.attrs["href"]).hostname in {"anthropic.com", "anthropic.skilljar.com"}]
    academy = [n for n in all_links if urlsplit(n.attrs["href"]).hostname == "academy.openai.com"]
    assert anthology and academy and len(videos) >= 3
    record = read(SESSION / "prework-verification.md")
    # An item may wrap several chapter links. Find its nearest dated ancestor
    # below #reading, allowing list items, cards, table rows or plain paragraphs.
    for link in videos + anthology + academy:
        item = link.parent
        while item is not reading and item is not None and not list(item.descendants("time")):
            item = item.parent
        assert item is not None and item is not reading, "Each reading item needs its own as-of date"
        days = dates(item)
        assert re.search(r"\b\d+(?:\s*[-–]\s*\d+)?\s*(?:min|minute|h\b|hour)", item.text(), re.I), "Reading item needs approximate length"
        url = link.attrs["href"]
        assert any(url in line and any(day in line for day in days) for line in record.splitlines()), (
            "Reading source-check row missing URL and matching date: " + url)


def test_checker_is_stdlib_and_override_is_documented():
    source = read(SESSION / "exercises/check_setup.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert not node.level, "Core must be a standalone stdlib-only script"
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        assert all(root in sys.stdlib_module_names for root in roots), roots
    header = (ast.get_docstring(tree) or "") + "\n".join(line for line in source.splitlines() if line.startswith("#"))
    assert "CHECK_SETUP_URLS" in header


def test_acceptance_harness_syntax():
    # Catch errors in the generated fixture executables even when implementation
    # files are still absent. Does not substitute for running product scenarios.
    compile(STUB, "<external-tool-fixture>", "exec")


def test_acceptance_fixture_protocols(tmp_path, monkeypatch):
    """Validate real fixture transport/hooks without supplying an implementation."""
    source = tmp_path / "source"
    (source / "exercises").mkdir(parents=True)
    for name in ("check_setup.py", "check-setup.sh", "check-setup.ps1"):
        (source / "exercises" / name).write_text("# fixture payload, never executed\n")
    monkeypatch.setattr(prework_live_agents, "SESSION", source)
    sandbox = Sandbox(tmp_path / "protocols", "http://127.0.0.1:1/not-used")
    state = sandbox.snapshot()
    # These commands test the fixtures only, never the delivered checker.
    gh = subprocess.run([str(sandbox.bin / "gh"), "api", "user"],
                        env=sandbox.env, capture_output=True, text=True, check=True)
    assert json.loads(gh.stdout)["login"] == sandbox.config["handle"]
    bootstrap = subprocess.run([str(sandbox.bin / "uv"), "run", "--no-project", "--python", "3.12",
                                "python", "-c", "import sys; print(sys.version_info[:2])"],
                               env=sandbox.env, cwd=sandbox.root, capture_output=True, text=True, timeout=30)
    assert bootstrap.returncode == 0, "Fixture needs an offline, preinstalled uv-managed Python 3.12"
    assert "(3, 12)" in bootstrap.stdout
    tree = sandbox.git_run("mktree", input="")
    commit = sandbox.git_run("commit-tree", tree, input="fixture probe\n")
    remote = "https://github.com/" + sandbox.config["origin_slug"] + ".git"
    ref = "refs/heads/setup-check/fixture-protocol"
    sandbox.git_run("push", remote, f"{commit}:{ref}")
    assert sandbox.git_run("ls-remote", remote, ref).split()[0] == commit
    sandbox.git_run("push", remote, "--delete", ref)
    assert sandbox.git_run("ls-remote", remote, ref) == ""
    assert len(sandbox.pushes()) == 2 and sandbox.pushes()[0]["tree"] == ""
    assert state == sandbox.snapshot()

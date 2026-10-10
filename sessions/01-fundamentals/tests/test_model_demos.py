"""Issue 30 acceptance checks, authored before implementation (ADR 0011).

Run each ledger selection with ``uv run pytest -q tests/test_model_demos.py -k
test_d1`` etc. D1 must ALSO run tests/test_self_contained.py without that filter.
No real API or CLI is called. All mutations, including git commits for the reset
test, are confined to disposable copies. Missing deliverables fail, never skip.

The design fixes metadata fields but leaves JSON containers unspecified. Readers
accept answers/outputs (raw strings, integers, or objects containing raw/text/
answer/output), runs as a list or low/high mapping, and probe entries under
models/probes/results. Per-run prompt/model may inherit from top-level/meta;
explicit per-run values must agree. This is a data interface, not an import of
the implementation. No particular implementation functions are required.

Fallback fenced shell blocks are executed literally from BOTH starting folders;
an anchored cd prelude can make the specified short uv commands portable.
Temperature source accuracy, current model availability, authentic unedited
recordings, honest attempt counts, prose quality, observed-outcome descriptions,
and realistic timing still require the named agent review in the PR. Offline
checks cannot establish those facts and must not be cited as that review.
"""

import ast
from collections import Counter
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import Thread
from urllib.parse import unquote, urlsplit

import pytest


SESSION = Path(__file__).resolve().parents[1]
ROOT = SESSION.parents[1]
RELATIVE = Path("sessions/01-fundamentals/cursus/demos/model")
DEMO = ROOT / RELATIVE
PROVIDERS = ("anthropic", "openai")
CLIS = ("claude", "codex")
KEYS = {p: p.upper() + "_API_KEY" for p in PROVIDERS}
BASES = {p: p.upper() + "_BASE_URL" for p in PROVIDERS}
ENDPOINTS = {"anthropic": "/v1/messages", "openai": "/v1/chat/completions"}
PROMPT = "Invent a name for a new optimization solver. Reply with the name only."
JSON_FILES = ("strawberry-claude.json", "strawberry-codex.json", "sampling.json")
RECORDINGS = (*JSON_FILES, "claude-pivot.txt", "codex-pivot.txt",
              "claude_count_r.py", "codex_count_r.py")
SECTIONS = ("Before class", "Timing", "Predict", "Expected outcome", "Run",
            "Fallback", "Recorded runs", "Reset")
RESET = ('git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD '
         '--staged --worktree -- sessions/01-fundamentals/cursus/demos/model '
         '&& git -C "$(git rev-parse --show-toplevel)" clean -fdx -- '
         'sessions/01-fundamentals/cursus/demos/model')

# These hooks log attempted network access before raising, so catching an audit
# exception cannot make an offline check pass. Loopback tests allow only the
# test server's numeric host and ephemeral port, not arbitrary local services.
AUDIT = r'''
import os
import sys
def acceptance_audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
                 "socket.gethostbyaddr", "socket.sendto"}:
        allowed = False
        port = os.environ.get("DEMO_TEST_PORT")
        if port and event == "socket.connect":
            address = args[1]
            allowed = isinstance(address, tuple) and address[:2] == ("127.0.0.1", int(port))
        elif port and event == "socket.getaddrinfo":
            allowed = args[0] == "127.0.0.1" and str(args[1]) == port
        if not allowed:
            with open(os.environ["DEMO_TEST_AUDIT_LOG"], "a") as log:
                log.write(event + "\n")
            raise RuntimeError("acceptance check forbids network access")
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"}:
        if os.environ.get("DEMO_TEST_NO_CHILDREN") == "1":
            with open(os.environ["DEMO_TEST_AUDIT_LOG"], "a") as log:
                log.write(event + "\n")
            raise RuntimeError("offline replay must not launch a CLI or child process")
sys.addaudithook(acceptance_audit)
'''
RUNNER = AUDIT + r'''
from pathlib import Path
from types import ModuleType
path = Path(sys.argv[1]).resolve()
sys.argv = [str(path), *sys.argv[2:]]
# Match Python's normal script-directory import behavior, even from repo root.
sys.path.insert(0, str(path.parent))
main = ModuleType("__main__")
main.__file__ = str(path)
main.__package__ = None
sys.modules["__main__"] = main
exec(compile(path.read_bytes(), str(path), "exec"), main.__dict__)
'''


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    value = path.read_text(encoding="utf-8")
    assert value.strip(), f"Empty artifact: {path}"
    return value


def document(name):
    return read(DEMO / name)


def section(name, heading):
    source = document(name)
    match = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", source, re.M | re.S)
    assert match and match[1].strip(), f"{name} needs non-empty ## {heading}"
    return match[1]


def blocks(source):
    return re.findall(r"^```[^\n]*\n(.*?)^```\s*$", source, re.M | re.S)


def links(source):
    targets = re.findall(r"\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)", source)
    targets += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", source, re.M)
    found = set()
    for target in targets:
        parsed = urlsplit(target)
        if parsed.scheme:
            continue
        assert not parsed.netloc, f"Remote protocol-relative link: {target}"
        if not parsed.path:
            continue
        path = (DEMO / unquote(parsed.path)).resolve()
        assert not parsed.path.startswith("/") and path.is_relative_to(SESSION), target
        assert path.exists(), f"Broken relative link: {target}"
        found.add(path)
    return found


def recording(name, base=DEMO):
    value = json.loads(read(base / "recorded" / name))
    assert isinstance(value, dict) and isinstance(value.get("meta"), dict), name
    return value


def pick(mapping, *names):
    for name in names:
        if name in mapping:
            return mapping[name]
    raise AssertionError(f"Expected one of {names}, got {list(mapping)}")


def raw_output(value):
    if isinstance(value, dict):
        value = pick(value, "raw", "text", "answer", "output", "response")
    assert isinstance(value, (str, int)) and not isinstance(value, bool), value
    assert str(value).strip(), "Keep non-empty raw model answers"
    return str(value)


def answers(data):
    values = pick(data, "answers", "outputs", "responses")
    assert isinstance(values, list) and len(values) == 5, "Exactly five model responses required"
    return [raw_output(value) for value in values]


def inherited(data, run, name):
    return run.get(name, run.get("meta", {}).get(name,
                   data.get(name, data["meta"].get(name))))


def sampling_runs(data):
    runs = data.get("runs")
    if runs is None:
        runs = {key: data[key] for key in ("low", "high") if key in data}
    if isinstance(runs, dict):
        assert set(runs) == {"low", "high"}, "Need low and high sampling runs"
        runs = list(runs.values())
    assert isinstance(runs, list) and len(runs) == 2, "Need exactly two temperature runs"
    assert all(isinstance(run, dict) for run in runs)
    for run in runs:
        assert type(run.get("temperature")) in {int, float}
        assert inherited(data, run, "prompt") == data["meta"]["prompt"] == PROMPT
        assert inherited(data, run, "model") == data["meta"]["model"]
        answers(run)
    return sorted(runs, key=lambda run: run["temperature"])


def probe_entries(data):
    entries = pick(data, "models", "probes", "results", "entries")
    assert isinstance(entries, list) and entries
    return entries


def word_constant(base=DEMO):
    tree = ast.parse(read(base / "strawberry.py"))
    values = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "WORD" for target in targets):
                values.append(ast.literal_eval(node.value))
    assert len(values) == 1 and isinstance(values[0], str), "One literal WORD constant required"
    return values[0]


def valid_date(value):
    assert isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), value
    assert date.fromisoformat(value) <= date.today(), "Run dates cannot be in the future"


def valid_model(value):
    assert isinstance(value, str) and value.strip() == value and value
    assert value.lower() not in {"unknown", "default", "n/a", "none", "todo", "tbd", "model", "placeholder"}
    assert not re.search(r"[<>]|placeholder|example-model|your-model", value, re.I), value


def child_env(tmp_path):
    env = os.environ.copy()
    for name in list(env):
        if (name.startswith("GIT_") or name in {*KEYS.values(), *BASES.values(), "PYTHONPATH",
                "PYTHONHOME", "VIRTUAL_ENV", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                "DEMO_TEST_PORT", "DEMO_TEST_NO_CHILDREN"}
                or name.lower().endswith("_proxy")):
            env.pop(name, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never",
               UV_CACHE_DIR=str(tmp_path / "uv-cache"), UV_PYTHON=sys.executable,
               NO_PROXY="127.0.0.1,localhost", DEMO_TEST_AUDIT_LOG=str(tmp_path / "audit.log"))
    return env


def run(args, cwd, env):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=45, check=False)


def success(result):
    assert result.returncode == 0, f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def no_forbidden_io(env):
    path = Path(env["DEMO_TEST_AUDIT_LOG"])
    assert not path.exists() or not path.read_text().strip(), "Forbidden I/O attempted: " + path.read_text()


def script(base, name, args, env, cwd=None, children=False):
    read(base / name)
    env = dict(env)
    env["DEMO_TEST_NO_CHILDREN"] = "0" if children else "1"
    result = run([sys.executable, "-c", RUNNER, base / name, *args], cwd or base, env)
    no_forbidden_io(env)
    return result


@pytest.fixture
def sandbox(tmp_path):
    assert DEMO.is_dir(), f"Missing demo: {DEMO}"
    root = tmp_path / "disposable repo with spaces"
    base = root / RELATIVE
    shutil.copytree(DEMO, base, ignore=shutil.ignore_patterns("__pycache__", ".uv-cache", "work"))
    return root, base, child_env(tmp_path)


@contextmanager
def api_server(provider, rejected=()):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            index = len(calls) + 1
            denied = "*" in rejected or payload.get("model") in rejected
            # Unique markers prove that actual returned text is propagated.
            label = index if payload.get("temperature", 1) >= 0.9 else "shared"
            text = f"solver-{provider}-{label}-λ"
            error = f"temperature unavailable for {payload.get('model')}: test rejection"
            calls.append({"path": self.path, "headers": dict(self.headers), "body": payload,
                          "text": text, "status": 400 if denied else 200, "error": error})
            if denied:
                body = {"error": {"type": "invalid_request_error", "message": error}}
            elif provider == "openai":
                body = {"id": f"response-{index}", "object": "chat.completion",
                        "model": payload["model"], "choices": [{"index": 0,
                        "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}}
            else:
                body = {"id": f"response-{index}", "type": "message", "role": "assistant",
                        "model": payload["model"], "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn", "usage": {"input_tokens": 9, "output_tokens": 3}}
            encoded = json.dumps(body).encode()
            self.send_response(400 if denied else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def api_env(env, provider, port):
    result = dict(env)
    result.update({KEYS[provider]: f"dummy-env-only-{provider}-73",
                   BASES[provider]: f"http://127.0.0.1:{port}", "DEMO_TEST_PORT": str(port)})
    return result


def assert_request(call, provider, env):
    assert call["path"] == ENDPOINTS[provider]
    headers = {key.lower(): value for key, value in call["headers"].items()}
    assert headers.get("content-type", "").startswith("application/json")
    if provider == "openai":
        assert headers.get("authorization") == "Bearer " + env[KEYS[provider]]
        assert "max_completion_tokens" in call["body"] and "max_tokens" not in call["body"]
        assert type(call["body"]["max_completion_tokens"]) is int and call["body"]["max_completion_tokens"] > 0
    else:
        assert headers.get("x-api-key") == env[KEYS[provider]]
        assert headers.get("anthropic-version") == "2023-06-01"
        assert type(call["body"].get("max_tokens")) is int and call["body"]["max_tokens"] > 0


def user_prompt(body):
    messages = body.get("messages")
    assert isinstance(messages, list)
    users = [message["content"] for message in messages if message.get("role") == "user"]
    assert len(users) == 1
    if isinstance(users[0], str):
        return users[0]
    return "".join(part["text"] for part in users[0] if part.get("type") == "text")


def test_d1_layout_links_stdlib_and_help(tmp_path):
    names = ("README.md", "strawberry.md", "sampling.md", "llm_api.py", "strawberry.py",
             "sampling.py", "ask.txt", "pivot.txt")
    for name in names:
        read(DEMO / name)
    assert (DEMO / "recorded").is_dir()
    for name in ("README.md", "strawberry.md", "sampling.md"):
        found = links(document(name))
        if name == "README.md":
            assert {DEMO / "strawberry.md", DEMO / "sampling.md"} <= found
            assert DEMO / "recorded" in found or any(path.parent == DEMO / "recorded" for path in found)
    for name in ("strawberry", "sampling"):
        assert len(document(name + ".md").splitlines()) <= 120
        assert re.search(rf"\buv\s+run\b[^\n]*\b{name}\.py\b", section(name + ".md", "Run"))
        success(script(DEMO, name + ".py", ["--help"], child_env(tmp_path)))
    for path in DEMO.rglob("*.py"):
        if any(part.startswith(".") or part == "work" for part in path.relative_to(DEMO).parts):
            continue
        for node in ast.walk(ast.parse(read(path))):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for module in modules:
                root = module.split(".")[0]
                assert root in sys.stdlib_module_names or (DEMO / (root + ".py")).is_file(), module
    assert re.search(r"cursus/demos/model/?", read(SESSION / "README.md"))


CLI_STUB = r'''
import json
import os
from pathlib import Path
import sys
cli = Path(sys.argv[0]).name
args = sys.argv[1:]
if "--version" in args or "-V" in args:
    print(cli + " 1.2.3")
    raise SystemExit(0)
if "--help" in args:
    print("-p --tools --disallowedTools --output-format exec --sandbox")
    raise SystemExit(0)
stdin = ""
if "-" in args or not any(os.environ["STUB_WORD"] in arg for arg in args):
    stdin = sys.stdin.read()
with open(os.environ["STUB_CALLS"], "a") as handle:
    handle.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
index = len(Path(os.environ["STUB_CALLS"]).read_text().splitlines())
if os.environ.get("STUB_FAIL") == "1":
    print("login expired (test stub)", file=sys.stderr)
    raise SystemExit(7)
answer = ["2", "17", "not an integer", "31", "5"][index - 1]
if cli == "claude" and "--output-format" in args:
    fmt = args[args.index("--output-format") + 1]
    init = {"type": "system", "subtype": "init", "model": "stub-claude-model"}
    result = {"type": "result", "subtype": "success", "is_error": False,
              "result": answer, "model": "stub-claude-model",
              "modelUsage": {"stub-claude-model": {"inputTokens": 4, "outputTokens": 1}}}
    if fmt == "stream-json":
        print(json.dumps(init))
        print(json.dumps(result))
    elif fmt == "json":
        print(json.dumps(result))
    else:
        print(answer)
elif cli == "codex" and "--json" in args:
    print(json.dumps({"type": "thread.started", "thread_id": "stub-thread"}))
    print(json.dumps({"type": "item.completed", "item": {"id": "item_0",
          "type": "agent_message", "text": answer}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 1}}))
else:
    print(answer)
for flag in ("-o", "--output-last-message"):
    if flag in args:
        Path(args[args.index(flag) + 1]).write_text(answer)
print("model: stub-" + cli + "-model", file=sys.stderr)
'''


def stub_cli(tmp_path, env, cli, word, fail=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    executable = bin_dir / cli
    executable.write_text("#!" + sys.executable + "\n" + CLI_STUB, encoding="utf-8")
    executable.chmod(0o755)
    result = dict(env, PATH=str(bin_dir), STUB_WORD=word,
                  STUB_CALLS=str(tmp_path / "cli-calls.jsonl"), STUB_FAIL="1" if fail else "0")
    return result


def tool_withholding(cli, argv):
    if cli == "codex":
        assert "exec" in argv
        assert "--sandbox=read-only" in argv or ("--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only")
    else:
        assert "-p" in argv or "--print" in argv
        disabled = "--tools=" in argv or ("--tools" in argv and argv[argv.index("--tools") + 1] == "")
        for index, arg in enumerate(argv):
            if arg.startswith("--disallowedTools"):
                value = arg.partition("=")[2] if "=" in arg else argv[index + 1]
                # A partial list (e.g. just Bash) still leaves tools available.
                disabled |= value.strip() == "*"
        assert disabled, "Claude naive step must disable all tools"


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("override", [False, True])
def test_d2_headless_cli_five_answers_and_custom_word(sandbox, tmp_path, cli, override):
    root, base, env = sandbox
    word = "rurrquarrrenbrirrrmorrzerr" if override else word_constant(base)
    env = stub_cli(tmp_path, env, cli, word)
    args = ["--via", cli, "--record", "stub-run.json"]
    if override:
        args += ["--word", word]
    output = success(script(base, "strawberry.py", args, env, cwd=root, children=True))
    calls = [json.loads(line) for line in read(Path(env["STUB_CALLS"])).splitlines()]
    assert len(calls) == 5
    expected_prompt = read(base / "ask.txt").replace("{WORD}", word).strip()
    for call in calls:
        tool_withholding(cli, call["args"])
        assert expected_prompt in "\n".join([*call["args"], call["stdin"]])
    data = json.loads(read(base / "stub-run.json"))
    assert data["word"] == word and data["truth"] == word.count("r")
    expected = ["2", "17", "not an integer", "31", "5"]
    assert answers(data) == expected
    assert all(answer in output for answer in expected)
    assert not (root / "stub-run.json").exists(), "Relative --record belongs beside the script"


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("failure", ["missing", "nonzero"])
def test_d2_cli_failure_explains_replay(sandbox, tmp_path, cli, failure):
    _, base, env = sandbox
    if failure == "missing":
        bin_dir = tmp_path / "empty-bin"
        bin_dir.mkdir()
        env["PATH"] = str(bin_dir)
    else:
        env = stub_cli(tmp_path, env, cli, word_constant(base), fail=True)
    result = script(base, "strawberry.py", ["--via", cli], env, children=True)
    assert result.returncode == 1
    message = result.stdout + result.stderr
    assert cli in message.lower() and "--replay" in message and "Traceback" not in message


def rendered(source):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    result = []
    for line in source.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            result.append(line)
        else:
            result.extend(strings(value))
    return "\n".join(result)


def pivot_metadata(cli):
    source = read(DEMO / "recorded" / f"{cli}-pivot.txt")
    lines = source.splitlines()
    meta = {}
    for key, line in zip(("cli", "version", "model", "date"), lines[:4]):
        assert line.startswith(key + ":"), "Pivot transcript starts with cli/version/model/date headers"
        meta[key] = line.split(":", 1)[1].strip()
    assert len(meta) == 4 and cli in meta["cli"].lower()
    assert re.search(r"\d+\.\d+", meta["version"])
    return meta, rendered("\n".join(lines[4:]))


def test_d2_word_recordings_and_prompt_binding(tmp_path):
    word = word_constant()
    assert len(word) >= 20 and word.count("r") >= 6 and word.isalpha()
    for name in ("ask.txt", "pivot.txt"):
        assert "{WORD}" in document(name)
    wrong = 0
    for cli in CLIS:
        data = recording(f"strawberry-{cli}.json")
        assert data["word"] == word and data["truth"] == word.count("r")
        meta = data["meta"]
        valid_model(meta["model"])
        if cli == "claude":
            assert meta["model"].startswith("claude-"), "Record the resolved Claude model ID, not its alias"
            assert meta["requested_model"] == "haiku"
        assert meta["model"].lower() not in {"haiku", "sonnet", "opus", "default", "latest"}
        assert meta["params"].get("effort") == "low"
        outcome = section("strawberry.md", "Expected outcome")
        assert any(meta["model"] in line and re.search(r"\beffort\b.*\blow\b", line, re.I)
                   for line in outcome.splitlines()), "Name each naive model and its low effort setting"
        assert data["meta"]["prompt"].strip() == document("ask.txt").replace("{WORD}", word).strip()
        for answer in answers(data):
            try:
                wrong += int(answer.strip()) != data["truth"]
            except ValueError:
                wrong += 1
        _, transcript = pivot_metadata(cli)
        pivot = document("pivot.txt").replace("{WORD}", word).strip()
        assert re.sub(r"\s+", " ", pivot) in re.sub(r"\s+", " ", transcript)
        # Ignore occurrences inside the request itself. The remaining evidence
        # must include the agent's invocation, not merely the requested command.
        without_prompt = re.sub(re.escape(pivot), "", transcript)
        command = re.search(r"\buv\s+run\s+python\s+(?:\./)?work/count_r\.py\b", without_prompt)
        assert command
        # Require a tool invocation and creation evidence, not an assistant's
        # assertion that it ran the command. Authenticity still needs review.
        assert re.search(r"\b(?:Bash|exec_command|command_execution|tool_use|shell)\b", without_prompt, re.I)
        assert re.search(r"(?:Write|write|writing|wrote|create|created|add.file|apply_patch|cat\s*>|write_text)", without_prompt, re.I)
        assert re.search(rf"^\s*{data['truth']}\s*$", without_prompt[command.end():], re.M), "Need executed count after command"
        path = DEMO / "recorded" / f"{cli}_count_r.py"
        assert word in read(path)
        output = success(script(path.parent, path.name, [], child_env(tmp_path)))
        assert output.strip() == str(word.count("r"))
    assert wrong >= 1, "Keep real unreliable answers; if all are right, record a harder configuration"
    runbook = section("strawberry.md", "Run")
    assert re.search(r"\bclaude\s+-p\b", runbook)
    assert re.search(r"\bcodex\s+exec\b", runbook)
    assert "--permission-mode acceptEdits" in runbook and 'Bash(uv run:*)' in runbook
    assert "--sandbox workspace-write" in runbook


@pytest.mark.parametrize("cli", CLIS)
def test_d2_pivot_transcripts_show_agent_wrote_and_ran_code(cli):
    import shlex

    word = word_constant()
    expected = word.count("r")
    data = recording(f"strawberry-{cli}.json")
    assert data["word"] == word and data["truth"] == expected
    source = read(DEMO / "recorded" / f"{cli}-pivot.txt")
    pivot = document("pivot.txt").replace("{WORD}", word).strip()
    assert " ".join(pivot.split()) in " ".join(rendered(source).split())
    events = [json.loads(line) for line in source.splitlines() if line.lstrip().startswith("{")]
    assert events and all(isinstance(event, dict) for event in events), "Need raw JSON tool events"

    def count_path(value):
        return isinstance(value, str) and Path(value).parts[-2:] == ("work", "count_r.py")

    def shell_body(command):
        parts = shlex.split(command)
        if len(parts) == 3 and Path(parts[0]).name in {"bash", "sh", "zsh"} and parts[1] in {"-c", "-lc"}:
            return parts[2]
        return command

    def runs_counter(command):
        return re.fullmatch(r"\s*uv\s+run\s+python\s+(?:\./)?work/count_r\.py\s*", shell_body(command))

    def has_count(output):
        return re.search(rf"^\s*{expected}\s*$", output, re.M)

    def writes_counter(command):
        command = shell_body(command)
        if word not in command:
            return False
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&<>|")
        lexer.whitespace_split = True
        tokens = list(lexer)
        start = 0
        for index, token in enumerate(tokens[:-1]):
            if token in {";", "&&", "||", "|"}:
                start = index + 1
            if (token in {">", ">>"} and count_path(tokens[index + 1]) and start < index
                    and tokens[start] in {"cat", "printf", "echo"}):
                return True
        # Python -c is another common write shape. Inspect executable syntax,
        # not strings that merely mention Path(...).write_text(...).
        args = shlex.split(command)
        if len(args) == 3 and Path(args[0]).name in {"python", "python3"} and args[1] == "-c":
            for node in ast.parse(args[2]).body:
                if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                    continue
                call = node.value
                if not isinstance(call.func, ast.Attribute) or call.func.attr != "write_text" or not call.args:
                    continue
                target = call.func.value
                if (isinstance(target, ast.Call) and isinstance(target.func, ast.Name)
                        and target.func.id == "Path" and len(target.args) == 1
                        and isinstance(target.args[0], ast.Constant) and count_path(target.args[0].value)
                        and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
                        and word in call.args[0].value):
                    return True
        return False

    if cli == "claude":
        content = read(DEMO / "recorded" / "claude_count_r.py")
        assert word in content
        # Retain event/block order and message roles: prose about a tool call
        # cannot substitute for tool_use and its matching tool_result.
        blocks_in_order = []
        for event in events:
            message = event.get("message", {})
            parts = message.get("content", [])
            if isinstance(parts, list):
                blocks_in_order.extend((event.get("type"), part) for part in parts if isinstance(part, dict))
        writes = [index for index, (role, block) in enumerate(blocks_in_order)
                  if role == "assistant" and block.get("type") == "tool_use"
                  and block.get("name") in {"Write", "Edit", "MultiEdit"}
                  and count_path(block.get("input", {}).get("file_path"))
                  and " ".join(block["input"].get("content", "").split()) == " ".join(content.split())]
        assert writes, "Claude must write the recorded counting code to work/count_r.py"
        for index, (role, block) in enumerate(blocks_in_order):
            if (role != "assistant" or block.get("type") != "tool_use" or block.get("name") != "Bash"
                    or not any(write < index for write in writes)
                    or not runs_counter(block.get("input", {}).get("command", ""))):
                continue
            tool_id = block.get("id")
            assert tool_id, "Bash invocation needs its tool-use ID"
            for result_role, result in blocks_in_order[index + 1:]:
                if (result_role != "user" or result.get("type") != "tool_result"
                        or result.get("tool_use_id") != tool_id or result.get("is_error", False)):
                    continue
                output = result.get("content", "")
                if isinstance(output, list):
                    output = "\n".join(part.get("text", "") for part in output if part.get("type") == "text")
                if isinstance(output, str) and has_count(output):
                    return
        pytest.fail("Claude needs a later uv execution and a successful, ID-linked result containing the computed count")
    else:
        completed = [event["item"] for event in events
                     if event.get("type") == "item.completed" and isinstance(event.get("item"), dict)]
        writes = []
        for index, item in enumerate(completed):
            if (item.get("type") == "file_change" and item.get("status") == "completed"
                    and any(count_path(change.get("path")) and change.get("kind") in {"add", "update"}
                            for change in item.get("changes", []))):
                writes.append(index)
            elif item.get("type") == "command_execution" and item.get("exit_code") == 0:
                # A successful shell write is also valid creation evidence;
                # merely mentioning the path or reading it is insufficient.
                if writes_counter(item.get("command", "")):
                    writes.append(index)
        assert writes, "Codex must complete a file change or a successful command writing work/count_r.py"
        assert any(item.get("type") == "command_execution" and item.get("exit_code") == 0
                   and any(write < index for write in writes)
                   and runs_counter(item.get("command", "")) and has_count(item.get("aggregated_output", ""))
                   for index, item in enumerate(completed)), "Codex needs a later successful uv execution with the computed count"


def test_d2_print_prompts_substitutes_custom_word(sandbox):
    _, base, env = sandbox
    word = "quarrrbirrrtorrrmerx"
    output = success(script(base, "strawberry.py", ["--print-prompts", "--word", word], env))
    for name in ("ask.txt", "pivot.txt"):
        assert read(base / name).replace("{WORD}", word).strip() in output
    assert "{WORD}" not in output


@pytest.mark.parametrize("cli", CLIS)
def test_d2_recorded_code_really_counts_letters(sandbox, cli):
    _, base, env = sandbox
    word = word_constant(base)
    path = base / "recorded" / f"{cli}_count_r.py"
    source = read(path)
    assert word in source
    # Mutate only the input in a disposable copy. A canned print of the old
    # answer is not the pivot to executable counting the demo promises.
    alternate = "r" * (word.count("r") + 3) + "quux"
    path.write_text(source.replace(word, alternate), encoding="utf-8")
    assert success(script(path.parent, path.name, [], env)).strip() == str(alternate.count("r"))


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("temperatures", [(0.0, 1.0), (0.2, 0.95)])
def test_d3_http_sampling_request_shape_and_returned_text(sandbox, provider, temperatures):
    root, base, env = sandbox
    with api_server(provider) as (port, calls):
        env = api_env(env, provider, port)
        args = ["--provider", provider, "--model", "alternate-model-73", "--record", "http-run.json"]
        if temperatures != (0.0, 1.0):
            args += ["--low", str(temperatures[0]), "--high", str(temperatures[1])]
        output = success(script(base, "sampling.py", args, env, cwd=root))
    assert len(calls) == 10
    assert Counter(call["body"].get("temperature") for call in calls) == Counter({t: 5 for t in temperatures})
    for call in calls:
        assert_request(call, provider, env)
        body = call["body"]
        assert body["model"] == "alternate-model-73" and user_prompt(body) == PROMPT
        assert not {"top_p", "thinking", "reasoning", "reasoning_effort"} & body.keys()
        assert call["text"] in output
    low_texts = [call["text"] for call in calls if call["body"]["temperature"] == temperatures[0]]
    high_texts = [call["text"] for call in calls if call["body"]["temperature"] == temperatures[1]]
    for low_text, high_text in zip(low_texts, high_texts):
        assert any(low_text in line and high_text in line for line in output.splitlines()), "Show paired low/high columns"
    summaries = "\n".join(line for line in output.splitlines() if re.search(r"distinct|unique", line, re.I))
    assert summaries, "Display the spread, not only raw answers"
    # Permit a table with the counts in the next row, or prose on the same line.
    summary_index = next(i for i, line in enumerate(output.splitlines()) if re.search(r"distinct|unique", line, re.I))
    summaries += "\n" + "\n".join(output.splitlines()[summary_index:summary_index + 3])
    assert re.search(r"\b1\b", summaries) and re.search(r"\b5\b", summaries)
    saved = json.loads(read(base / "http-run.json"))
    runs = sampling_runs(saved)
    assert [item["temperature"] for item in runs] == list(temperatures)
    for item in runs:
        assert answers(item) == [call["text"] for call in calls if call["body"]["temperature"] == item["temperature"]]
    assert not (root / "http-run.json").exists()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_d3_vendor_400_is_clear_error(sandbox, provider):
    _, base, env = sandbox
    with api_server(provider, rejected={"*"}) as (port, calls):
        env = api_env(env, provider, port)
        result = script(base, "sampling.py", ["--provider", provider, "--model", "rejected-model"], env)
    assert result.returncode == 1 and calls
    assert calls[0]["error"] in result.stderr and "Traceback" not in result.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_d3_probe_records_success_and_rejection(sandbox, provider):
    root, base, env = sandbox
    models = ["candidate-a", "candidate-b", "candidate-c"]
    target = base / "recorded/temperature_probe.json"
    target.unlink(missing_ok=True)
    with api_server(provider, rejected={models[1]}) as (port, calls):
        env = api_env(env, provider, port)
        args = ["--probe", "--provider", provider]
        for model in models:
            args += ["--model", model]
        success(script(base, "sampling.py", args, env, cwd=root))
    assert Counter(call["body"]["model"] for call in calls) == Counter(models)
    data = recording("temperature_probe.json", base)
    entries = probe_entries(data)
    assert len(entries) == 3
    assert {entry["model"] for entry in entries} == set(models)
    valid_date(data["meta"]["date"])
    for entry in entries:
        call = next(call for call in calls if call["body"]["model"] == entry["model"])
        assert_request(call, provider, env)
        assert "temperature" in call["body"] and "top_p" not in call["body"]
        assert entry["provider"] == provider
        assert urlsplit(entry["endpoint"]).path == ENDPOINTS[provider]
        assert entry["temperature"] == call["body"]["temperature"]
        assert entry["accepted"] is (call["status"] == 200)
        assert entry["http_status"] == call["status"]
        if call["status"] == 400:
            assert call["error"] in str(entry["error"])
        else:
            assert entry["error"] in (None, "")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_d3_temperature_support_table_matches_script_defaults(sandbox, provider):
    _, base, env = sandbox
    with api_server(provider) as (port, calls):
        env = api_env(env, provider, port)
        success(script(base, "sampling.py", ["--provider", provider], env))
    assert len(calls) == 10
    models = {call["body"]["model"] for call in calls}
    assert len(models) == 1
    model = models.pop()
    valid_model(model)
    for call in calls:
        assert_request(call, provider, env)
        assert "temperature" in call["body"] and user_prompt(call["body"]) == PROMPT
    support = section("sampling.md", "Temperature support")
    as_of = re.search(r"as of\s+(\d{4}-\d\d-\d\d)", support, re.I)
    assert as_of, "Date the temperature-support documentation check"
    valid_date(as_of[1])
    urls = [urlsplit(url) for url in re.findall(r"https://[^\s)>|]+", support)]
    assert any(url.hostname == "platform.claude.com" and "/api/messages" in url.path for url in urls)
    assert any(url.hostname == "platform.claude.com" and "model-deprecations" in url.path for url in urls)
    openai_urls = [url for url in urls if url.hostname in {"platform.openai.com", "developers.openai.com"}]
    assert any("reference" in url.path and "chat" in url.path and "completions" in url.path for url in openai_urls)
    assert any("/models/gpt-4.1-mini" in url.path for url in openai_urls)
    assert "Models released after Claude Opus 4.6 do not support setting temperature" in " ".join(support.split())
    rows = [row for row in support.splitlines() if "|" in row
            and re.search(r"(?<![\w.-])" + re.escape(model) + r"(?![\w.-])", row)]
    assert any(re.search(r"\|\s*(?:\*\*)?(?:yes|accepts)\b", row, re.I) for row in rows), (
        f"Temperature support needs an accepting table row for the actual {provider} default {model}")


def test_d4_sampling_recording_is_vendor_api_run_with_spread():
    data = recording("sampling.json")
    meta = metadata(data, "sampling")
    low, high = sampling_runs(data)
    assert 0 <= low["temperature"] <= 0.3 and high["temperature"] >= 0.9
    assert len(set(answers(high))) >= max(2, len(set(answers(low))))
    support = section("sampling.md", "Temperature support")
    rows = [row for row in support.splitlines() if "|" in row
            and re.search(r"(?<![\w.-])" + re.escape(meta["model"]) + r"(?![\w.-])", row)]
    assert any(re.search(r"\|\s*(?:\*\*)?(?:yes|accepts)\b", row, re.I) for row in rows), (
        "The recorded vendor model needs an accepting Temperature support row")


@pytest.mark.parametrize("name,via", [("strawberry.py", "claude"), ("strawberry.py", "codex"), ("sampling.py", None)])
@pytest.mark.parametrize("start", ["demo", "root"])
def test_d4_replay_offline_and_independent_of_cwd(sandbox, name, via, start):
    root, base, env = sandbox
    args = ["--replay"] + (["--via", via] if via else [])
    data = recording(f"strawberry-{via}.json" if via else "sampling.json", base)
    output = success(script(base, name, args, env, cwd=base if start == "demo" else root))
    expected = answers(data) if via else [answer for item in sampling_runs(data) for answer in answers(item)]
    assert all(answer in output for answer in expected)
    assert data["meta"]["model"] in output and data["meta"]["date"] in output


@pytest.mark.parametrize("via", CLIS)
def test_d4_replay_reads_recorded_answers_instead_of_canned_output(sandbox, via):
    _, base, env = sandbox
    path = base / "recorded" / f"strawberry-{via}.json"
    data = recording(path.name, base)
    container = next(key for key in ("answers", "outputs", "responses") if key in data)
    values = data[container]
    for index, value in enumerate(values):
        marker = f"unparseable-offline-answer-{index}"
        if isinstance(value, dict):
            key = next(key for key in ("raw", "text", "answer", "output", "response") if key in value)
            value[key] = marker
        else:
            values[index] = marker
    path.write_text(json.dumps(data), encoding="utf-8")
    output = success(script(base, "strawberry.py", ["--replay", "--via", via], env))
    assert all(f"unparseable-offline-answer-{index}" in output for index in range(5))


def init_repository(root, env):
    for args in (["git", "init", "-b", "test-model-demos"],
                 ["git", "config", "user.email", "test@example.invalid"],
                 ["git", "config", "user.name", "Acceptance test"],
                 ["git", "add", "."], ["git", "commit", "-m", "Disposable test baseline"]):
        success(run(args, root, env))


@pytest.mark.parametrize("book", ["strawberry.md", "sampling.md"])
@pytest.mark.parametrize("start", ["demo", "root"])
def test_d4_documented_fallback_commands_run_literally(sandbox, tmp_path, book, start):
    root, base, env = sandbox
    init_repository(root, env)
    fallback = section(book, "Fallback")
    commands = [block for block in blocks(fallback) if re.search(r"\buv\s+run\b", block)]
    assert commands, "Put the runnable fallback in a fenced shell block"
    combined = "\n".join(commands).replace("\\\n", " ")
    script_name = book.replace(".md", ".py")
    assert re.search(r"uv run --no-project --offline python\b[^\n]*" + re.escape(script_name) + r"[^\n]*--replay", combined)
    if book == "strawberry.md":
        assert "--via codex" in combined, "Document both recorded CLI fallbacks"
    hook = tmp_path / "audit-hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(AUDIT, encoding="utf-8")
    env.update(PYTHONPATH=str(hook), DEMO_TEST_NO_CHILDREN="1")
    # uv is offline, and its selected Python gets the same fail-and-log hook.
    # No shell rewriting or cwd repair: execute exactly the documented block.
    outputs = []
    for command in commands:
        outputs.append(success(run(["bash", "-e", "-c", command], base if start == "demo" else root, env)))
        no_forbidden_io(env)
    output = "\n".join(outputs)
    expected_names = [f"strawberry-{cli}.json" for cli in CLIS] if book == "strawberry.md" else ["sampling.json"]
    linked = links(fallback)
    for name in expected_names:
        assert DEMO / "recorded" / name in linked
        data = recording(name)
        assert data["meta"]["model"] in output and data["meta"]["date"] in output
        values = answers(data) if name.startswith("strawberry") else [value for item in sampling_runs(data) for value in answers(item)]
        assert all(value in output for value in values)


def test_d4_strawberry_recordings_are_tracked_and_dated(tmp_path):
    tracked = success(run(["git", "ls-files", "--", RELATIVE / "recorded"], ROOT, child_env(tmp_path)))
    paths = set(tracked.splitlines())
    for name in RECORDINGS:
        if name == "sampling.json":
            continue
        read(DEMO / "recorded" / name)
        assert (RELATIVE / "recorded" / name).as_posix() in paths, f"Recording must be tracked: {name}"
    for cli in CLIS:
        valid_date(recording(f"strawberry-{cli}.json")["meta"]["date"])
        pivot, _ = pivot_metadata(cli)
        valid_date(pivot["date"])


def test_d4_sampling_recording_is_tracked_and_dated(tmp_path):
    data = recording("sampling.json")
    tracked = success(run(["git", "ls-files", "--", RELATIVE / "recorded"], ROOT, child_env(tmp_path)))
    assert (RELATIVE / "recorded/sampling.json").as_posix() in set(tracked.splitlines()), "Recording must be tracked: sampling.json"
    valid_date(data["meta"]["date"])


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("mode", ["sampling", "probe", "strawberry"])
@pytest.mark.parametrize("key_value", [None, "", "   \t"])
def test_a1_missing_or_blank_key_fails_before_network(sandbox, provider, mode, key_value):
    _, base, env = sandbox
    if key_value is not None:
        env[KEYS[provider]] = key_value
    if mode == "strawberry":
        name, args = "strawberry.py", ["--via", provider]
    else:
        name, args = "sampling.py", ["--provider", provider, "--model", "unavailable-model"]
        if mode == "probe":
            args += ["--probe"]
    result = script(base, name, args, env)
    assert result.returncode == 2
    assert KEYS[provider] in result.stderr and "--replay" in result.stderr
    assert re.search(r"not set|missing|blank|empty", result.stderr, re.I)
    assert "Traceback" not in result.stderr and len(result.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("name", ["strawberry.py", "sampling.py"])
def test_a1_environment_key_is_sent_to_provider(sandbox, provider, name):
    _, base, env = sandbox
    args = (["--via", provider, "--word", "birrrquerrr"] if name == "strawberry.py"
            else ["--provider", provider, "--model", "auth-test-model"])
    with api_server(provider) as (port, calls):
        env = api_env(env, provider, port)
        result = script(base, name, args, env)
        output = success(result)
    assert len(calls) == (5 if name == "strawberry.py" else 10)
    for call in calls:
        assert_request(call, provider, env)
        assert call["text"] in output
        if name == "strawberry.py":
            assert "birrrquerrr" in user_prompt(call["body"])
            assert not {"tools", "temperature"} & call["body"].keys(), "Use vendor default and no tools"
    assert env[KEYS[provider]] not in output + result.stderr


def test_a1_recordings_and_source_are_scrubbed():
    assert DEMO.is_dir()
    for path in DEMO.rglob("*"):
        if not path.is_file() or any(part.startswith(".") or part == "work" for part in path.relative_to(DEMO).parts):
            continue
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}", source), f"Key-like literal in {path}"
        assert not re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+", source), f"Unscrubbed home path in {path}"
        if path.suffix == ".txt" and path.parent.name == "recorded":
            assert not re.search(r'(?i)session[_ -]?id["\s:=]+["\s]*[a-f0-9]{8}[a-f0-9-]{12,}', source), path


def timing_total(source):
    """Accept min/sec or m:ss, including Markdown table column units."""
    lines = [line for line in source.splitlines() if "|" in line]
    assert len(lines) >= 3, "Timing needs a table of beats"
    total = [line for line in lines if re.search(r"\btotal\b", line, re.I)]
    assert len(total) == 1, "State a total in the timing table"
    value = total[0]
    minute_second = re.search(r"\b(\d+):(\d{2})\b", value)
    if minute_second:
        assert int(minute_second[2]) < 60
        return int(minute_second[1]) * 60 + int(minute_second[2])
    quantity = re.search(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|m|seconds?|secs?|s)\b", value, re.I)
    if quantity:
        return float(quantity[1]) * (60 if quantity[2].lower().startswith("m") else 1)
    header = lines[0].lower()
    numbers = re.findall(r"\b\d+(?:\.\d+)?\b", value)
    assert len(numbers) == 1 and re.search(r"min|sec|\(s\)|\(m\)", header), "Give timing units"
    return float(numbers[0]) * (60 if "min" in header or "(m)" in header else 1)


@pytest.mark.parametrize("book", ["strawberry.md", "sampling.md"])
def test_a2_runbook_sections_timing_and_reset(sandbox, book):
    root, base, env = sandbox
    for heading in SECTIONS:
        section(book, heading)
    assert 0 < timing_total(section(book, "Timing")) <= 300
    if book == "sampling.md":
        assert re.search(r"not (fully )?deterministic|not guaranteed|may (still )?differ",
                         section(book, "Expected outcome"), re.I), "Explain that low-temperature identity is not guaranteed"
    reset = blocks(section(book, "Reset"))
    assert len(reset) == 1 and reset[0].strip() == RESET
    (root / ".gitignore").write_text(".uv-cache/\n*.pyc\n", encoding="utf-8")
    init_repository(root, env)
    sentinel = root / "outside-the-demo.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    for name in ("work/count_r.py", "work/.uv-cache/cache.bin", "work/__pycache__/dirty.pyc", "stray.txt"):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dirty", encoding="utf-8")
    (base / book).write_text("staged edit", encoding="utf-8")
    success(run(["git", "add", str(RELATIVE / book)], root, env))
    (base / "README.md").write_text("unstaged edit", encoding="utf-8")
    success(run(["bash", "-c", reset[0].strip()], base, env))
    assert success(run(["git", "status", "--short", "--ignored", "--untracked-files=all", "--", RELATIVE], root, env)) == ""
    assert sentinel.read_text() == "preserve me"


def metadata(data, kind):
    meta = data["meta"]
    valid_date(meta["date"])
    assert type(meta.get("attempt")) is int and meta["attempt"] >= 1
    if kind == "probe":
        # Probe model IDs belong to individual entries, not one aggregate model.
        for entry in probe_entries(data):
            valid_model(entry["model"])
            if "date" in entry:
                valid_date(entry["date"])
        return meta
    valid_model(meta["model"])
    # A CLI-default request has no explicit requested model; record that fact
    # while requiring the actual model reported by the CLI above.
    assert "requested_model" in meta
    assert meta["requested_model"] is None or (isinstance(meta["requested_model"], str) and meta["requested_model"].strip())
    assert isinstance(meta["params"], dict) and meta["params"]
    assert isinstance(meta["prompt"], str) and meta["prompt"].strip()
    assert Path(meta["script"]).name == ("sampling.py" if kind == "sampling" else "strawberry.py")
    if kind in CLIS:
        assert meta["via"] == kind and kind in meta["cli"].lower()
        assert re.search(r"\d+\.\d+", meta["cli_version"])
        params = json.dumps(meta["params"])
        if kind == "claude":
            assert "--tools" in params or "--disallowedTools" in params
        else:
            assert "read-only" in params
    else:
        assert meta["provider"] in PROVIDERS
        assert urlsplit(meta["endpoint"]).path == ENDPOINTS[meta["provider"]]
    return meta


def table_mentions(table, filename, model, run_date):
    rows = [row for row in table.splitlines() if "|" in row and filename in row]
    assert rows, f"Recorded runs needs a row for {filename}"
    assert any(model in row and run_date in row for row in rows), f"Metadata mismatch for {filename}: {model}, {run_date}"


def test_a3_every_committed_recording_has_model_and_date():
    required = set(RECORDINGS) - {"sampling.json"}
    for name in required:
        read(DEMO / "recorded" / name)
    for cli in CLIS:
        name = f"strawberry-{cli}.json"
        meta = metadata(recording(name), cli)
        assert meta["model"].lower() not in {"haiku", "sonnet", "opus", "default", "latest"}
        if cli == "claude":
            assert meta["model"].startswith("claude-"), "Record the resolved Claude model ID"
        table = section("strawberry.md", "Recorded runs")
        linked = links(table)
        assert DEMO / "recorded" / name in linked
        table_mentions(table, name, meta["model"], meta["date"])
        pivot, _ = pivot_metadata(cli)
        valid_model(pivot["model"])
        valid_date(pivot["date"])
        for filename in (f"{cli}-pivot.txt", f"{cli}_count_r.py"):
            assert DEMO / "recorded" / filename in linked
            table_mentions(table, filename, pivot["model"], pivot["date"])
    # Optional recordings are not prerequisites, but none may escape metadata
    # and runbook checks when added. Unknown formats fail rather than vanish.
    for path in sorted((DEMO / "recorded").rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(DEMO / "recorded").as_posix()
        if name in required:
            continue
        assert name in {"sampling.json", "temperature_probe.json"}, f"No metadata contract for recording: {name}"
        data = recording(name)
        table = section("sampling.md", "Recorded runs")
        linked = links(table)
        assert path in linked
        if name == "sampling.json":
            meta = metadata(data, "sampling")
            table_mentions(table, name, meta["model"], meta["date"])
        else:
            metadata(data, "probe")
            for entry in probe_entries(data):
                table_mentions(table, name, entry["model"], entry.get("date", data["meta"]["date"]))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a3_sampling_record_writes_model_and_run_date(sandbox, tmp_path, provider):
    _, base, env = sandbox
    model = "alternate-record-model-73"
    target = tmp_path / "new recording.json"
    today = date.today().isoformat()
    with api_server(provider) as (port, calls):
        env = api_env(env, provider, port)
        success(script(base, "sampling.py", ["--provider", provider, "--model", model,
                                            "--record", str(target)], env))
    assert len(calls) == 10
    for call in calls:
        assert_request(call, provider, env)
        assert call["body"]["model"] == model
    data = json.loads(read(target))
    meta = metadata(data, "sampling")
    assert meta["model"] == model and meta["date"] == today
    assert meta["provider"] == provider and urlsplit(meta["endpoint"]).path == ENDPOINTS[provider]


def test_d3_harness_oracles_reject_bad_sampling_data():
    """Test our schema adapter without fabricating any deliverable recordings."""
    sample = {"meta": {"model": "test-model", "prompt": PROMPT}, "runs": [
        {"temperature": 0, "outputs": ["a"] * 5},
        {"temperature": 1, "outputs": ["b", "c", "d", "e", "f"]}]}
    assert len(sampling_runs(sample)) == 2
    for field, value in (("outputs", ["a"] * 4), ("outputs", [""] * 5),
                         ("model", "different-model"), ("prompt", "different prompt")):
        changed = json.loads(json.dumps(sample))
        changed["runs"][1][field] = value
        with pytest.raises(AssertionError):
            sampling_runs(changed)


def test_a1_harness_audit_logs_even_caught_network_attempts(tmp_path):
    env = child_env(tmp_path)
    code = AUDIT + '''
import socket
try:
    socket.getaddrinfo("example.invalid", 443)
except RuntimeError:
    pass
'''
    success(run([sys.executable, "-c", code], tmp_path, env))
    assert "socket.getaddrinfo" in Path(env["DEMO_TEST_AUDIT_LOG"]).read_text()


def test_d3_harness_loopback_server_and_audit_work(tmp_path):
    env = child_env(tmp_path)
    code = AUDIT + '''
import json
from urllib.request import Request, urlopen
request = Request(os.environ["OPENAI_BASE_URL"] + "/v1/chat/completions",
    data=json.dumps({"model": "harness-model", "temperature": 1}).encode(),
    headers={"Content-Type": "application/json"})
with urlopen(request, timeout=5) as response:
    print(response.read().decode())
'''
    with api_server("openai") as (port, calls):
        env = api_env(env, "openai", port)
        output = success(run([sys.executable, "-c", code], tmp_path, env))
    no_forbidden_io(env)
    assert len(calls) == 1
    assert json.loads(output)["choices"][0]["message"]["content"] == calls[0]["text"]

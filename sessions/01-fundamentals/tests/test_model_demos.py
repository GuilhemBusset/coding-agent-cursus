"""Issue 30 acceptance contract (checks authored independently of implementation).

Each ledger command is one pytest invocation. D4's machine-provable tests are
selected by A3; a real sampling recording remains an owner obligation. Missing
sampling.json is allowed, fabricated sampling data is not. Authenticity of CLI
recordings, temperature-document accuracy, and teaching quality require review.
No API credentials or real model CLIs are used here. Mutations are temporary.
"""

import ast
from collections import Counter
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from threading import Thread
import tomllib
from urllib.parse import unquote, urlsplit

import pytest

SESSION = Path(__file__).resolve().parents[1]
ROOT = SESSION.parents[1]
RELATIVE = Path("sessions/01-fundamentals/cursus/demos/model")
DEMO = ROOT / RELATIVE
CLIS = ("claude", "codex")
PROVIDERS = ("anthropic", "openai")
PROMPT = "Invent a name for a new optimization solver. Reply with the name only."
KEYS = {p: p.upper() + "_API_KEY" for p in PROVIDERS}
BASES = {p: p.upper() + "_BASE_URL" for p in PROVIDERS}
STRAWBERRY_FILES = tuple(f"{step}-{cli}.json" for cli in CLIS for step in ("strawberry", "pivot"))
COUNT_FILES = tuple(f"{cli}_count_r.py" for cli in CLIS)

# Logging BEFORE raising detects attempted I/O even when a script catches the
# exception. Only the current stub server's numeric address/port is allowed.
RUNNER = r'''
import os
import sys
def audit(event, args):
    blocked = False
    if event == "socket.__new__":
        blocked = not os.environ.get("DEMO_TEST_PORT")
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
                 "socket.gethostbyaddr", "socket.sendto"}:
        port = os.environ.get("DEMO_TEST_PORT")
        allowed = False
        if port and event == "socket.connect":
            address = args[1]
            allowed = isinstance(address, tuple) and address[:2] == ("127.0.0.1", int(port))
        elif port and event == "socket.getaddrinfo":
            allowed = args[0] == "127.0.0.1" and str(args[1]) == port
        blocked = not allowed
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty"}:
        blocked |= os.environ.get("DEMO_TEST_NO_CHILDREN") == "1"
    if blocked:
        with open(os.environ["DEMO_TEST_AUDIT_LOG"], "a", encoding="utf-8") as log:
            log.write(event + "\n")
        raise RuntimeError("acceptance harness forbids this I/O")
sys.addaudithook(audit)
from pathlib import Path
path = Path(sys.argv[1]).resolve()
sys.argv = [str(path), *sys.argv[2:]]
namespace = {"__name__": "__main__", "__file__": str(path), "__package__": None}
exec(compile(path.read_bytes(), str(path), "exec"), namespace)
'''


def read(path):
    assert path.is_file(), f"Missing artifact: {path}"
    return path.read_text(encoding="utf-8")


def constants(script):
    result = {}
    for node in ast.parse(read(script)).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    try:
                        result[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return result


def word(base=DEMO):
    value = constants(base / "strawberry.py").get("WORD")
    assert isinstance(value, str) and len(value) >= 30 and value.isalpha() and value.islower()
    assert value.count("r") >= 8
    return value


def section(name, heading, base=DEMO):
    source = read(base / name)
    matches = list(re.finditer(r"^##\s+([^\n]+)\n", source, re.M))
    selected = [i for i, match in enumerate(matches) if heading.lower() in match[1].lower()
                and not (heading.lower() == "run" and "recorded runs" in match[1].lower())]
    assert len(selected) == 1, f"{name}: need one ## heading containing {heading}"
    i = selected[0]
    value = source[matches[i].end():matches[i + 1].start() if i + 1 < len(matches) else len(source)]
    assert value.strip(), f"{name}: empty {heading} section"
    return value


def blocks(source):
    return re.findall(r"^```[^\n]*\n(.*?)^```\s*$", source, re.M | re.S)


def tables(source):
    rows = []
    previous = None
    active = False
    for line in source.splitlines():
        if "|" not in line:
            previous, active = None, False
            continue
        row = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        delimiter = len(row) >= 2 and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in row)
        if delimiter and previous is not None and len(previous) == len(row):
            rows.append(previous)
            active = True
        elif active and not delimiter:
            rows.append(row)
        previous = row
    return rows


def child_env(tmp_path):
    env = os.environ.copy()
    for name in list(env):
        if (name.startswith(("GIT_", "PYTEST_", "DEMO_TEST_", "STUB_"))
                or "API_KEY" in name or name in {*BASES.values(), "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
                or name.lower().endswith("_proxy")):
            env.pop(name, None)
    env.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", UV_PYTHON=sys.executable,
               UV_CACHE_DIR=str(tmp_path / "uv-cache"), PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               DEMO_TEST_AUDIT_LOG=str(tmp_path / "audit.log"))
    return env


def run(argv, cwd, env, input_text=None):
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=env, input=input_text,
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def success(result):
    assert result.returncode == 0, f"exit {result.returncode}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def no_forbidden_io(env):
    path = Path(env["DEMO_TEST_AUDIT_LOG"])
    assert not path.exists() or not path.read_text().strip(), f"Forbidden I/O: {read(path)}"


def script(base, name, args, env, cwd=None, children=False):
    read(base / name)
    scoped = dict(env, DEMO_TEST_NO_CHILDREN="0" if children else "1")
    result = run([sys.executable, "-I", "-c", RUNNER, base / name, *args],
                 cwd or base, scoped, "parent stdin must not reach the headless ask\n")
    no_forbidden_io(scoped)
    return result


def sandbox(tmp_path):
    assert DEMO.is_dir(), f"Missing {DEMO}"
    root = tmp_path / "disposable repo with spaces"
    base = root / RELATIVE
    shutil.copytree(DEMO, base, ignore=shutil.ignore_patterns("work", "__pycache__", ".uv-cache"))
    return root, base, child_env(tmp_path)


def recording(name, base=DEMO):
    value = json.loads(read(base / "recorded" / name))
    assert isinstance(value, dict) and isinstance(value.get("meta"), dict)
    return value


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def events(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(raw, dict):
        raw = [raw]
    assert isinstance(raw, list) and raw and all(isinstance(e, dict) for e in raw)
    return raw


def extracted(cli, raw):
    stream = events(raw)
    if cli == "claude":
        results = [e for e in stream if e.get("type") == "result"]
        assert len(results) == 1 and isinstance(results[0].get("result"), str)
        return results[0]["result"]
    messages = [e["item"]["text"] for e in stream
                if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
    assert messages and all(isinstance(m, str) for m in messages)
    return "\n".join(messages)


def used_tools(cli, raw):
    stream = events(raw)
    if cli == "claude":
        result = next(e for e in stream if e.get("type") == "result")
        assert type(result.get("num_turns")) is int
        return result["num_turns"] != 1
    return any(e.get("item", {}).get("type") not in {"agent_message", "reasoning"}
               for e in stream if isinstance(e.get("item"), dict))


def classify(text, truth):
    numbers = set(re.findall(r"\b\d+\b", text))
    # Distinct INTEGER values: 08 and 8 are the same answer.
    numbers = {int(n) for n in numbers}
    if len(numbers) != 1:
        return None, "unparseable"
    number = numbers.pop()
    return number, "correct" if number == truth else "incorrect"


def assert_ask_output(output, answers, tools, truth):
    counts = Counter(classify(answer, truth)[1] for answer in answers)
    expected = (f"wrong: {counts['incorrect']} of 5 (unparseable: {counts['unparseable']}, "
                f"tool-assisted: {sum(tools)}; true count: {truth})")
    assert expected in output.splitlines()
    for i, (answer, tool) in enumerate(zip(answers, tools), 1):
        number, kind = classify(answer, truth)
        symbol = {"correct": "✓", "incorrect": "✗", "unparseable": "?"}[kind]
        lines = [line for line in output.splitlines() if line.startswith(f"run {i}:")]
        assert len(lines) == 1 and lines[0].endswith("[tool used]" if tool else symbol)
        if number is not None:
            assert lines[0] == f"run {i}: {number}  {symbol}" + (" [tool used]" if tool else "")
        else:
            assert "  ?" in lines[0]
        assert ("[tool used]" in lines[0]) == tool


def valid_date(value):
    assert isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", value)
    assert date.fromisoformat(value) <= date.today()


def valid_model(value):
    assert isinstance(value, str) and value.strip() == value and re.search(r"\d", value)
    assert value.lower() not in {"opus", "sonnet", "haiku", "default", "latest"}
    assert not re.search(r"[<>]|placeholder|example|your.model|unknown|pending|tbd|todo", value, re.I)


def no_sensitive(source):
    assert not re.search(r"sk-ant-|\bsk-[\w-]+|Bearer\s+[A-Za-z0-9_-]{8,}", source)
    assert not re.search(r"/home/|/Users/|[A-Za-z]:[\\/]+Users[\\/]", source)
    assert not re.search(r'"(?:session_id|thread_id|uuid)"\s*:', source)
    assert not re.search(r'"type"\s*:\s*"system"', source)


def test_d1_layout_links_and_one_page_runbooks():
    for name in ("README.md", "strawberry.md", "sampling.md", "strawberry.py", "sampling.py", ".gitignore"):
        assert read(DEMO / name).strip()
    assert (DEMO / "recorded").is_dir()
    assert any(line.strip() in {"work/", "/work/"} for line in read(DEMO / ".gitignore").splitlines())
    assert not (DEMO / "llm_api.py").exists(), "Design specifies no shared helper module"
    found = set()
    for name in ("README.md", "strawberry.md", "sampling.md"):
        source = read(DEMO / name)
        targets = re.findall(r"\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)", source)
        targets += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", source, re.M)
        for target in targets:
            parsed = urlsplit(target)
            if parsed.scheme:
                continue
            assert not parsed.netloc and not parsed.path.startswith("/")
            if not parsed.path:
                continue
            path = (DEMO / unquote(parsed.path)).resolve()
            assert path.is_relative_to(SESSION) and path.exists(), target
            if name == "README.md":
                found.add(path)
    assert {DEMO / "strawberry.md", DEMO / "sampling.md", DEMO / "recorded"} <= found
    for name in ("strawberry", "sampling"):
        assert len(read(DEMO / (name + ".md")).splitlines()) <= 120
        assert re.search(rf"\buv\s+run\b[^\n]*\b{name}\.py\b", section(name + ".md", "Run"))
    assert "cursus/demos/model" in read(SESSION / "README.md")
    if not (DEMO / "recorded/sampling.json").exists():
        assert re.search(r"pending", read(DEMO / "README.md"), re.I)


def test_d1_pep723_stdlib_and_help(tmp_path):
    _, base, env = sandbox(tmp_path)
    for name in ("strawberry.py", "sampling.py"):
        source = read(base / name)
        match = re.search(r"^# /// script\n((?:#[^\n]*\n)+)# ///\s*$", source, re.M)
        assert match, f"{name} needs PEP 723 metadata"
        metadata = tomllib.loads("\n".join(line.removeprefix("# ").removeprefix("#") for line in match[1].splitlines()))
        assert metadata.get("requires-python") == ">=3.12" and metadata.get("dependencies") == []
        for node in ast.walk(ast.parse(source)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not isinstance(node, ast.ImportFrom) or not node.level
            assert all(n.split(".")[0] in sys.stdlib_module_names for n in names)
        success(script(base, name, ["--help"], env))
        assert shutil.which("uv"), "Engine prerequisite: real uv on PATH"
        success(run(["uv", "run", "--offline", name, "--help"], base, env))

# Executable stand-ins emit vendor-shaped JSON, not a substitute recording.
# They also verify cwd/stdin and put private fields in events to test redaction.
CLI_STUB = r'''
import json
import os
from pathlib import Path
import stat
import sys
cli = Path(sys.argv[0]).name
args = sys.argv[1:]
if "--version" in args or "-V" in args:
    print(cli + " 1.2.3")
    raise SystemExit(0)
if "--help" in args:
    print("-p --tools --disallowedTools --output-format --permission-mode --allowedTools --verbose exec --sandbox -c model_reasoning_effort")
    raise SystemExit(0)
pivot = "acceptEdits" in args or "workspace-write" in args or "--sandbox=workspace-write" in args
null = os.stat(os.devnull)
fd = os.fstat(0)
with open(os.environ["STUB_CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "cwd": os.getcwd(),
        "stdin_null": stat.S_ISCHR(fd.st_mode) and fd.st_rdev == null.st_rdev,
        "cache": os.environ.get("UV_CACHE_DIR"), "pivot": pivot}) + "\n")
index = len(Path(os.environ["STUB_CALLS"]).read_text().splitlines()) - 1
if os.environ.get("STUB_FAIL") == "1":
    print("test login expired", file=sys.stderr)
    raise SystemExit(7)
word = os.environ["STUB_WORD"]
truth = word.count("r")
reported = "claude-stub-20990101" if cli == "claude" else "gpt-stub-20990101"
if pivot:
    path = Path("work/count_r.py")
    path.parent.mkdir(exist_ok=True)
    code = "WORD = " + repr(word) + "\nprint(WORD.count('r'))\n"
    path.write_text(code, encoding="utf-8")
    command = "uv run --no-project python work/count_r.py"
    if cli == "claude":
        stream = [
            {"type": "system", "subtype": "init", "session_id": "private", "cwd": "/home/private-owner"},
            {"type": "assistant", "uuid": "private", "session_id": "private", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "write1", "name": "Write", "input": {"file_path": str(path.resolve()), "content": code}}]}},
            {"type": "user", "uuid": "private", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "write1", "content": "File written"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "bash1", "name": "Bash", "input": {"command": command}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "bash1", "content": str(truth) + "\n", "is_error": False}]}},
            {"type": "result", "subtype": "success", "result": str(truth), "num_turns": 3,
             "session_id": "private", "modelUsage": {reported: {"inputTokens": 12, "outputTokens": 4}}}]
    else:
        stream = [
            {"type": "thread.started", "thread_id": "private"},
            {"type": "item.completed", "item": {"id": "file1", "type": "file_change", "status": "completed", "changes": [{"path": str(path), "kind": "add"}]}},
            {"type": "item.started", "item": {"id": "cmd1", "type": "command_execution", "command": command, "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "cmd1", "type": "command_execution", "command": command, "status": "completed", "exit_code": 0, "aggregated_output": str(truth) + "\n"}},
            {"type": "item.completed", "item": {"id": "msg1", "type": "agent_message", "text": str(truth)}},
            {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}]
    for event in stream:
        print(json.dumps(event))
else:
    answer = json.loads(os.environ["STUB_ANSWERS"])[index]
    tool = index in json.loads(os.environ.get("STUB_TOOLS", "[]"))
    if cli == "claude":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "private",
            "num_turns": 2 if tool else 1, "result": answer,
            "modelUsage": {reported: {"inputTokens": 4, "outputTokens": 1}}}))
    else:
        print(json.dumps({"type": "thread.started", "thread_id": "private"}))
        print(json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "Counting mentally"}}))
        if tool:
            print(json.dumps({"type": "item.completed", "item": {"type": os.environ.get("STUB_TOOL_KIND", "command_execution"), "command": "echo tool", "aggregated_output": "tool"}}))
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 1}}))
'''


def cli_env(tmp_path, env, cli, base, answers=None, tools=(), fail=False, tool_kind="command_execution"):
    folder = tmp_path / "stub-bin"
    folder.mkdir(exist_ok=True)
    executable = folder / cli
    executable.write_text("#!" + sys.executable + "\n" + CLI_STUB, encoding="utf-8")
    executable.chmod(0o755)
    truth = word(base).count("r")
    return dict(env, PATH=str(folder), STUB_CALLS=str(tmp_path / "calls.jsonl"),
                STUB_WORD=word(base), STUB_ANSWERS=json.dumps(answers or [str(truth)] * 5),
                STUB_TOOLS=json.dumps(list(tools)), STUB_TOOL_KIND=tool_kind, STUB_FAIL="1" if fail else "0")


def cli_calls(env):
    return [json.loads(line) for line in read(Path(env["STUB_CALLS"])).splitlines()]


def option(argv, flag):
    if flag in argv:
        return argv[argv.index(flag) + 1]
    matches = [arg.split("=", 1)[1] for arg in argv if arg.startswith(flag + "=")]
    assert len(matches) == 1, f"Missing {flag} in {argv}"
    return matches[0]


def assert_ask_command(cli, argv, prompt, model):
    assert prompt in argv
    if cli == "codex":
        assert "--json" in argv
    assert option(argv, "-m" if cli == "codex" else "--model") == model
    if cli == "claude":
        assert "-p" in argv and option(argv, "--output-format") == "json"
        if any(a == "--tools" or a.startswith("--tools=") for a in argv):
            assert option(argv, "--tools") == ""
        else:
            excluded = option(argv, "--disallowedTools")
            assert excluded == "*" or {"Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task"} <= set(re.split(r"[\s,]+", excluded))
    else:
        assert "exec" in argv and option(argv, "--sandbox") == "read-only"
        assert any(re.search(r"model_reasoning_effort\s*=", arg) for arg in argv), "Set the lowest supported reasoning effort"


def compact_pivot(output, truth):
    assert f"true count: {truth}" in output.splitlines()
    assert re.search(r"^tool:.*(?:Write|file_change|apply_patch|command|Bash)", output, re.M | re.I)
    assert re.search(r"^tool:.*uv run.*work/count_r\.py", output, re.M)
    assert re.search(rf"^\s*{truth}\s*$", output, re.M), "Show the execution result"
    for line in output.splitlines():
        assert not line.lstrip().startswith(("{", "[")), "Projector output must be compact, not raw JSON"


def assert_ask_record(data, cli, base):
    literal = constants(base / "strawberry.py")
    truth = word(base).count("r")
    assert data["word"] == word(base) and data["truth"] == truth
    assert data["meta"]["demo"] == "strawberry" and data["meta"]["step"] == "ask"
    assert data["meta"]["cli"] == cli
    assert data["meta"]["prompt"] == literal["ASK"].replace("{WORD}", word(base))
    for field in ("answers", "classes", "tools_used", "raw"):
        assert isinstance(data[field], list) and len(data[field]) == 5
    assert all(type(t) is bool for t in data["tools_used"])
    for answer, kind, tool, raw in zip(data["answers"], data["classes"], data["tools_used"], data["raw"]):
        assert answer == extracted(cli, raw)
        assert kind == classify(answer, truth)[1]
        assert tool == used_tools(cli, raw)


def pivot_blocks(data):
    result = []
    for event in data["events"]:
        message = event.get("message", {})
        for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if isinstance(block, dict):
                result.append((event.get("type"), block))
    return result


def assert_pivot_record(data, cli, base):
    assert data["word"] == word(base) and data["truth"] == word(base).count("r")
    assert data["meta"]["demo"] == "strawberry" and data["meta"]["step"] == "pivot"
    assert data["meta"]["cli"] == cli and data["exit_code"] == 0
    assert data["meta"]["prompt"] == constants(base / "strawberry.py")["PIVOT"].replace("{WORD}", word(base))
    assert isinstance(data["events"], list) and data["events"]
    no_sensitive(json.dumps(data))
    command_pattern = r"\buv\s+run\b[^\n]*\bwork/count_r\.py\b"
    truth_pattern = rf"^\s*{data['truth']}\s*$"
    if cli == "claude":
        for event in data["events"]:
            assert event.get("type") in {"assistant", "user", "result"}
            if event["type"] != "result":
                content = event.get("message", {}).get("content")
                assert isinstance(content, list) and content
                expected = "tool_use" if event["type"] == "assistant" else "tool_result"
                assert all(block.get("type") == expected for block in content), "Only whitelisted tool blocks"
        ordered = pivot_blocks(data)
        writes = [i for i, (role, block) in enumerate(ordered)
                  if role == "assistant" and block.get("name") in {"Write", "Edit", "MultiEdit"}
                  and "count_r.py" in json.dumps(block.get("input", {}))]
        assert writes, "Need agent file creation evidence"
        matches = []
        for i, (role, block) in enumerate(ordered):
            command = block.get("input", {}).get("command", "")
            if role == "assistant" and block.get("name") == "Bash" and re.search(command_pattern, command):
                assert any(w < i for w in writes)
                for result_role, result in ordered[i + 1:]:
                    if result_role == "user" and result.get("tool_use_id") == block.get("id"):
                        text = "\n".join(strings(result.get("content", "")))
                        if not result.get("is_error", False) and re.search(truth_pattern, text, re.M):
                            matches.append(result)
        assert matches, "Need successful, ID-linked execution output from uv"
    else:
        for event in data["events"]:
            assert event.get("type") == "turn.completed" or (
                str(event.get("type", "")).startswith("item.")
                and event.get("item", {}).get("type") in {"command_execution", "file_change", "agent_message"})
        completed = [e["item"] for e in data["events"] if e.get("type") == "item.completed"]
        writes = [i for i, item in enumerate(completed)
                  if (item.get("type") == "file_change" and item.get("status") == "completed"
                      and any("count_r.py" in change.get("path", "") and change.get("kind") in {"add", "update"}
                              for change in item.get("changes", [])))
                  or (item.get("type") == "command_execution" and item.get("exit_code") == 0
                      and word(base) in item.get("command", "")
                      and re.search(r"(?:>|write_text|apply_patch)", item.get("command", "")))]
        assert writes, "Need completed agent write"
        assert any(item.get("type") == "command_execution" and item.get("exit_code") == 0
                   and re.search(command_pattern, item.get("command", ""))
                   and re.search(truth_pattern, item.get("aggregated_output", ""), re.M)
                   and any(w < i for w in writes) for i, item in enumerate(completed))


def test_d2_literal_word_and_prompts():
    literal = constants(DEMO / "strawberry.py")
    word()
    for key in ("ASK", "PIVOT"):
        assert isinstance(literal.get(key), str) and "{WORD}" in literal[key]
    ask = literal["ASK"].lower()
    assert "memory" in ask and re.search(r"without|do not|don't", ask)
    assert "code" in ask and "tools" in ask and re.search(r"number only|only (?:the )?number", ask)
    pivot = literal["PIVOT"]
    assert "work/count_r.py" in pivot and "WORD" in pivot
    assert "uv run --no-project python work/count_r.py" in pivot
    assert re.search(r"write", pivot, re.I) and re.search(r"run", pivot, re.I)
    assert re.search(r"print", pivot, re.I) and re.search(r"count", pivot, re.I)
    assert re.search(r"only|just", pivot, re.I)
    assert set(literal.get("MODELS", {})) == set(CLIS)
    for model in literal["MODELS"].values():
        valid_model(model)


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("alternate", [False, True])
def test_d2_five_headless_asks_classifier_and_tool_detection(tmp_path, cli, alternate):
    root, base, env = sandbox(tmp_path)
    if alternate:
        old = word(base)
        new = "r" * (old.count("r") + 7) + "quux" * 9
        path = base / "strawberry.py"
        path.write_text(read(path).replace(old, new), encoding="utf-8")
    truth = word(base).count("r")
    answers = [f"The count is {truth}.", str(truth + 3), "no numeric answer", "2 or 3", f"{truth}, yes {truth}"]
    tools = [False, True, False, False, True]
    env = cli_env(tmp_path, env, cli, base, answers, tools=(1, 4),
                  tool_kind="future_tool_fixture" if alternate else "file_change")
    output = success(script(base, "strawberry.py", ["--via", cli, "--record"], env, cwd=root, children=True))
    calls = cli_calls(env)
    assert len(calls) == 5
    for call in calls:
        assert call["cwd"] == str(base) and call["stdin_null"] is True
        assert_ask_command(cli, call["argv"], constants(base / "strawberry.py")["ASK"].replace("{WORD}", word(base)),
                           constants(base / "strawberry.py")["MODELS"][cli])
    assert_ask_output(output, answers, tools, truth)
    data = recording(f"strawberry-{cli}.json", base)
    assert_ask_record(data, cli, base)
    assert data["answers"] == answers and data["tools_used"] == tools
    assert data["classes"] == ["correct", "incorrect", "unparseable", "unparseable", "correct"]


@pytest.mark.parametrize("cli", CLIS)
def test_d2_pivot_cli_permissions_cwd_and_compact_projection(tmp_path, cli):
    root, base, env = sandbox(tmp_path)
    env = cli_env(tmp_path, env, cli, base)
    output = success(script(base, "strawberry.py", ["--pivot", "--via", cli, "--record"], env, cwd=root, children=True))
    calls = cli_calls(env)
    assert len(calls) == 1 and calls[0]["pivot"] and calls[0]["cwd"] == str(base)
    argv = calls[0]["argv"]
    assert constants(base / "strawberry.py")["PIVOT"].replace("{WORD}", word(base)) in argv
    assert option(argv, "-m" if cli == "codex" else "--model") == constants(base / "strawberry.py")["MODELS"][cli]
    if cli == "claude":
        assert "-p" in argv and option(argv, "--permission-mode") == "acceptEdits"
        assert option(argv, "--allowedTools") == "Bash(uv run:*)"
        assert option(argv, "--output-format") == "stream-json" and "--verbose" in argv
    else:
        assert "exec" in argv and "--json" in argv and option(argv, "--sandbox") == "workspace-write"
        assert Path(calls[0]["cache"]).resolve().is_relative_to(base / "work")
    compact_pivot(output, word(base).count("r"))
    assert_pivot_record(recording(f"pivot-{cli}.json", base), cli, base)
    assert (base / "recorded" / f"{cli}_count_r.py").read_bytes() == (base / "work/count_r.py").read_bytes()


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("pivot", [False, True])
@pytest.mark.parametrize("failure", ["missing", "nonzero"])
def test_d2_cli_failure_is_one_actionable_line(tmp_path, cli, pivot, failure):
    _, base, env = sandbox(tmp_path)
    if failure == "missing":
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        env["PATH"] = str(empty)
    else:
        env = cli_env(tmp_path, env, cli, base, fail=True)
    args = ["--via", cli] + (["--pivot"] if pivot else [])
    result = script(base, "strawberry.py", args, env, children=True)
    assert result.returncode == 1
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and cli in lines[0].lower() and "--replay" in lines[0]
    assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize("cli", CLIS)
def test_d2_real_recordings_bind_raw_answers_and_successful_pivot(tmp_path, cli):
    data = recording(f"strawberry-{cli}.json")
    assert_ask_record(data, cli, DEMO)
    assert "incorrect" in data["classes"], "Unparseable alone is not unreliable counting"
    assert data["tools_used"] == [False] * 5, "The recorded ask must be unaided"
    assert_pivot_record(recording(f"pivot-{cli}.json"), cli, DEMO)
    _, base, env = sandbox(tmp_path)
    path = base / "recorded" / f"{cli}_count_r.py"
    assert constants(path).get("WORD") == word(base)
    truth = word(base).count("r")
    assert success(script(path.parent, path.name, [], env)).strip() == str(truth)
    source = read(path)
    replacement = "quux" + "r" * (truth + 11)
    path.write_text(source.replace(word(base), replacement), encoding="utf-8")
    assert success(script(path.parent, path.name, [], env)).strip() == str(truth + 11)


@contextmanager
def api_server(provider, temperatures=(0.0, 1.0), reject=False, marker="fixture"):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        index = len(calls) + 1
        temperature = payload.get("temperature")
        position = sum(c["body"].get("temperature") == temperature for c in calls)
        # Deliberately greater spread at LOW temperature: the demo measures
        # observations, it must not invent a deterministic inequality.
        labels = ["A", "B", "C", "A", "B"] if temperature == temperatures[0] else ["X", "X", "Y", "X", "Y"]
        text = f"solver-{provider}-{marker}-{labels[position % 5]}-λ"
        error = "temperature unavailable: fixture rejection"
        if reject:
            body = {"error": {"type": "invalid_request_error", "message": error}}
        elif provider == "anthropic":
            body = {"id": f"response-{index}", "model": "claude-stub-20990101", "type": "message",
                    "role": "assistant", "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn", "usage": {"input_tokens": 9, "output_tokens": 3}}
        else:
            body = {"id": f"response-{index}", "model": "gpt-stub-20990101", "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}}
        calls.append({"path": self.path, "headers": dict(self.headers), "body": payload,
                      "text": text, "response": body, "error": error})
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(400 if reject else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    handler = type("VendorStubHandler", (BaseHTTPRequestHandler,), {"do_POST": do_POST, "log_message": log_message})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def api_env(env, provider, port, marker="73"):
    base = f"http://127.0.0.1:{port}" + ("/v1" if provider == "openai" else "")
    return dict(env, **{KEYS[provider]: f"test-env-only-{provider}-{marker}", BASES[provider]: base,
                       "DEMO_TEST_PORT": str(port)})


def user_prompt(body):
    messages = body.get("messages")
    assert isinstance(messages, list) and len(messages) == 1
    assert messages[0].get("role") == "user"
    content = messages[0].get("content")
    if isinstance(content, str):
        return content
    assert isinstance(content, list) and all(c.get("type") == "text" for c in content)
    return "".join(c["text"] for c in content)


def assert_requests(calls, provider, env, model, temperatures):
    assert len(calls) == 10
    assert Counter(c["body"].get("temperature") for c in calls) == Counter({t: 5 for t in temperatures})
    for call in calls:
        assert call["path"] == ("/v1/messages" if provider == "anthropic" else "/v1/chat/completions")
        headers = {key.lower(): value for key, value in call["headers"].items()}
        assert headers.get("content-type", "").startswith("application/json")
        if provider == "anthropic":
            assert headers.get("x-api-key") == env[KEYS[provider]]
            assert headers.get("anthropic-version") == "2023-06-01"
            assert call["body"].get("max_tokens") == 20 and "max_completion_tokens" not in call["body"]
        else:
            assert headers.get("authorization") == "Bearer " + env[KEYS[provider]]
            assert call["body"].get("max_completion_tokens") == 20 and "max_tokens" not in call["body"]
        body = call["body"]
        assert body["model"] == model and user_prompt(body) == PROMPT
        assert not {"top_p", "thinking", "reasoning", "reasoning_effort"} & body.keys()
        secret = env[KEYS[provider]]
        assert secret not in json.dumps(body) and secret not in call["path"]
        for key, value in headers.items():
            if key != ("x-api-key" if provider == "anthropic" else "authorization"):
                assert secret not in value


def assert_sampling_output(output, runs):
    assert len(runs) == 2
    low, high = runs
    paired = []
    for line in output.splitlines():
        if "|" in line and any(text in line for text in low["outputs"]):
            paired.append(line)
    assert len(paired) == 5, "Five paired low | high rows"
    for line, low_text, high_text in zip(paired, low["outputs"], high["outputs"]):
        assert low_text in line and high_text in line and line.index(low_text) < line.index(high_text)
    for item in runs:
        t, k = item["temperature"], len(set(item["outputs"]))
        candidates = [line for line in output.splitlines() if re.fullmatch(
            rf"distinct answers at temperature [-+\d.eE]+: {k} of 5", line)]
        assert any(float(re.search(r"temperature (.*):", line)[1]) == t for line in candidates)


def runs_from_calls(calls, temperatures):
    return [{"temperature": t, "outputs": [c["text"] for c in calls if c["body"]["temperature"] == t]} for t in temperatures]


def temperature_ranges(base=DEMO):
    source = section("sampling.md", "Temperature support", base)
    match = re.search(r"as of\s+(\d{4}-\d\d-\d\d)", source, re.I)
    assert match, "Temperature support needs an as-of date"
    valid_date(match[1])
    rows = tables(source)
    assert rows and len(rows[0]) >= 4
    header = [re.sub(r"[^a-z]", "", c.lower()) for c in rows[0]]
    assert "model" in header and "range" in header and "source" in header
    yes_col = next((i for i, h in enumerate(header) if "temperature" in h), None)
    assert yes_col is not None
    result = {}
    for row in rows[1:]:
        assert len(row) == len(header)
        if not re.search(r"\byes\b", row[yes_col], re.I):
            continue
        model_cell = row[header.index("model")]
        models = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*", model_cell)
        assert models, f"No concrete model ID in {model_cell}"
        numbers = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", row[header.index("range")])
        assert len(numbers) == 2, f"{model_cell}: numeric lower and upper range required"
        low, high = map(float, numbers)
        assert low < high
        urls = re.findall(r"https://[^\s)>\]]+", row[header.index("source")])
        references = dict((key.lower(), url) for key, url in re.findall(
            r"^\s*\[([^\]]+)\]:\s*<?(https://[^\s>]+)>?", read(base / "sampling.md"), re.M))
        urls.extend(references[key.lower()] for key in re.findall(r"\[([^\]]+)\]", row[header.index("source")])
                    if key.lower() in references)
        assert urls
        hosts = {urlsplit(url).hostname for url in urls}
        assert hosts <= {"docs.anthropic.com", "platform.claude.com", "docs.claude.com", "platform.openai.com", "developers.openai.com"}
        for model in models:
            assert model not in result or result[model] == (low, high), "Conflicting temperature ranges"
            result[model] = (low, high)
    return result


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("temperatures", [(0.0, 1.0), (0.2, 0.8)])
@pytest.mark.parametrize("override", [False, True])
def test_d3_vendor_http_contract_paired_answers_and_observed_spread(tmp_path, provider, temperatures, override):
    root, base, env = sandbox(tmp_path)
    defaults = constants(base / "sampling.py").get("DEFAULT_MODELS", {})
    assert set(defaults) == set(PROVIDERS)
    model = "fixture-requested-73" if override else defaults[provider]
    with api_server(provider, temperatures, marker=tmp_path.name) as (port, calls):
        env = api_env(env, provider, port, tmp_path.name)
        args = ["--provider", provider]
        if override:
            args += ["--model", model]
        if temperatures != (0.0, 1.0):
            args += ["--low", str(temperatures[0]), "--high", str(temperatures[1])]
        output = success(script(base, "sampling.py", args, env, cwd=root))
    assert_requests(calls, provider, env, model, temperatures)
    assert_sampling_output(output, runs_from_calls(calls, temperatures))


def test_d3_default_provider_is_anthropic(tmp_path):
    _, base, env = sandbox(tmp_path)
    with api_server("anthropic", marker=tmp_path.name) as (port, calls):
        env = api_env(env, "anthropic", port)
        output = success(script(base, "sampling.py", [], env))
    model = constants(base / "sampling.py")["DEFAULT_MODELS"]["anthropic"]
    assert_requests(calls, "anthropic", env, model, (0.0, 1.0))
    assert_sampling_output(output, runs_from_calls(calls, (0.0, 1.0)))


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("temperatures", [(1, 1), (1, 0)])
def test_d3_invalid_temperature_order_rejected_before_network(tmp_path, provider, temperatures):
    _, base, env = sandbox(tmp_path)
    env[KEYS[provider]] = "fixture-env-only"
    result = script(base, "sampling.py", ["--provider", provider, "--low", str(temperatures[0]), "--high", str(temperatures[1])], env)
    assert result.returncode != 0 and re.search(r"low|temperature", result.stderr, re.I)
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_d3_vendor_400_is_one_clean_error_line(tmp_path, provider):
    _, base, env = sandbox(tmp_path)
    with api_server(provider, reject=True) as (port, calls):
        env = api_env(env, provider, port)
        result = script(base, "sampling.py", ["--provider", provider], env)
    assert result.returncode == 1 and len(calls) == 1
    assert result.stderr.strip().splitlines() == [f"sampling.py: {provider} API error 400: {calls[0]['error']}"]
    assert "Traceback" not in result.stdout + result.stderr


def test_d3_temperature_documentation_covers_defaults():
    defaults = constants(DEMO / "sampling.py").get("DEFAULT_MODELS")
    assert isinstance(defaults, dict) and set(defaults) == set(PROVIDERS)
    assert constants(DEMO / "sampling.py").get("PROMPT") == PROMPT
    ranges = temperature_ranges()
    for model in defaults.values():
        valid_model(model)
        assert model in ranges
        assert ranges[model][0] <= 0.0 < 1.0 <= ranges[model][1]
    if (DEMO / "recorded/sampling.json").exists():
        model = recording("sampling.json")["meta"]["model"]
        assert model in ranges


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("key", [None, "", " \t\n"])
def test_a1_missing_key_is_one_line_and_never_connects(tmp_path, provider, key):
    _, base, env = sandbox(tmp_path)
    if key is not None:
        env[KEYS[provider]] = key
    result = script(base, "sampling.py", ["--provider", provider], env)
    assert result.returncode == 2
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and KEYS[provider] in lines[0] and "--replay" in lines[0]
    assert not result.stdout and "Traceback" not in result.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a1_key_only_reaches_authorization_header(tmp_path, provider):
    _, base, env = sandbox(tmp_path)
    with api_server(provider, marker=tmp_path.name) as (port, calls):
        env = api_env(env, provider, port, tmp_path.name)
        result = script(base, "sampling.py", ["--provider", provider, "--record"], env)
        output = success(result)
    assert_requests(calls, provider, env, constants(base / "sampling.py")["DEFAULT_MODELS"][provider], (0.0, 1.0))
    assert env[KEYS[provider]] not in output + result.stderr
    recorded = read(base / "recorded/sampling.json")
    assert env[KEYS[provider]] not in recorded
    data = json.loads(recorded)
    assert not {"headers", "key", "api_key", "authorization"} & data.keys()
    assert not re.search(r'"(?:headers|api_key|authorization|x-api-key)"\s*:', recorded, re.I)


def test_a1_public_demo_contains_no_credentials_or_private_trace_fields(tmp_path):
    assert DEMO.is_dir()
    result = run(["git", "ls-files", "-z", "--", str(RELATIVE)], ROOT, child_env(tmp_path))
    files = [ROOT / path for path in success(result).split("\0") if path]
    assert files
    for path in files:
        if path.suffix in {".py", ".json", ".md", ".txt"}:
            no_sensitive(read(path))


def test_a2_runbook_beats_prediction_and_expected_outcomes():
    truth = word().count("r")
    for name in ("strawberry.md", "sampling.md"):
        rows = tables(section(name, "Timing"))
        assert len(rows) >= 3, "Timing needs a header, per-beat rows, and Total"
        totals = [row for row in rows if any(re.search(r"\btotal\b", cell, re.I) for cell in row)]
        assert len(totals) == 1
        duration = re.search(r"\b(\d{1,2}):([0-5]\d)\b", " ".join(totals[0]))
        assert duration and 0 < int(duration[1]) * 60 + int(duration[2]) <= 600
        assert "?" in section(name, "Predict")
        section(name, "Run")
        section(name, "Fallback")
        section(name, "Recorded runs")
        assert len(blocks(section(name, "Reset"))) == 1
    expected = section("strawberry.md", "Expected outcome")
    assert re.search(rf"\b{truth}\b", expected)
    for cli in CLIS:
        assert recording(f"strawberry-{cli}.json")["meta"]["model"] in expected
    assert re.search(r"(?:all|every|five|5).*correct|correct.*(?:all|every|five|5)", expected, re.I | re.S)
    assert re.search(r"record(?:ing|ed)", expected, re.I) and re.search(r"wrong|incorrect", expected, re.I)
    assert re.search(r"pivot", expected, re.I)
    expected = section("sampling.md", "Expected outcome")
    assert re.search(r"not (?:fully )?(?:guaranteed|deterministic)|non[- ]deterministic", expected, re.I)
    if (DEMO / "recorded/sampling.json").exists():
        for item in recording("sampling.json")["runs"]:
            k = len(set(item["outputs"]))
            assert re.search(rf"\b{k}\s+(?:of|/)\s*5\b", expected)
    else:
        assert re.search(r"pending", expected, re.I)
        assert re.search(r"pending\s*:\s*record with a key", section("sampling.md", "Recorded runs"), re.I)


def git(argv, root, env):
    return success(run(["git", *argv], root, env))


@pytest.mark.parametrize("name", ["strawberry.md", "sampling.md"])
def test_a2_documented_reset_restores_demo_only_in_disposable_repo(tmp_path, name):
    root, base, env = sandbox(tmp_path)
    command_blocks = blocks(section(name, "Reset", base))
    assert len(command_blocks) == 1
    command = command_blocks[0]
    # This repository is a fixture; never mutate or commit the worker's repo.
    git(["init", "--initial-branch=fixture"], root, env)
    outside = root / "outside.txt"
    outside.write_text("outside baseline\n", encoding="utf-8")
    git(["add", "."], root, env)
    git(["-c", "user.name=Acceptance fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "fixture baseline"], root, env)
    baseline = {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    (base / "README.md").write_text("staged edit\n", encoding="utf-8")
    git(["add", str(RELATIVE / "README.md")], root, env)
    (base / "README.md").write_text("unstaged edit over staged edit\n", encoding="utf-8")
    (base / "sampling.md").unlink()
    staged_stray = base / "staged-stray.txt"
    staged_stray.write_text("new staged file\n", encoding="utf-8")
    git(["add", str(RELATIVE / "staged-stray.txt")], root, env)
    (base / "work").mkdir()
    (base / "work/ignored.txt").write_text("work debris\n", encoding="utf-8")
    (base / "stray-dir").mkdir()
    (base / "stray-dir/untracked.txt").write_text("untracked debris\n", encoding="utf-8")
    outside.write_text("outside staged edit\n", encoding="utf-8")
    git(["add", "outside.txt"], root, env)
    outside.write_text("outside unstaged edit\n", encoding="utf-8")
    outside_untracked = root / "outside-untracked.txt"
    outside_untracked.write_text("keep outside debris\n", encoding="utf-8")
    outside_index = git(["show", ":outside.txt"], root, env)
    # Fenced shell text is used exactly, without replacing it with a preferred
    # reset command. Global config and hooks cannot influence this fixture.
    success(run(["bash", "--noprofile", "--norc", "-c", command], base, env))
    assert not (base / "work").exists() and not (base / "stray-dir").exists()
    after = {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    assert after == baseline
    assert not git(["status", "--porcelain", "--", str(RELATIVE)], root, env).strip()
    assert outside.read_text() == "outside unstaged edit\n"
    assert git(["show", ":outside.txt"], root, env) == outside_index
    assert outside_untracked.read_text() == "keep outside debris\n"


def recorded_row(name, data, base=DEMO):
    rows = tables(section("sampling.md" if name == "sampling.json" else "strawberry.md", "Recorded runs", base))
    matches = [row for row in rows if name in " ".join(row)]
    assert len(matches) == 1, f"Recorded runs must list {name} once"
    line = " ".join(matches[0])
    assert data["meta"]["model"] in line and data["meta"]["date"] in line


def assert_cli_meta(data, cli, step, base, today=False):
    meta = data["meta"]
    assert meta["demo"] == "strawberry" and meta["cli"] == cli and meta["step"] == step
    valid_model(meta["model"])
    valid_date(meta["date"])
    if today:
        assert meta["date"] == date.today().isoformat()
        assert meta["model"] == constants(base / "strawberry.py")["MODELS"][cli]
    assert isinstance(meta["cli_version"], str) and re.search(r"\d", meta["cli_version"])
    assert isinstance(meta["command"], list) and meta["command"]
    assert all(isinstance(arg, str) for arg in meta["command"])
    assert Path(meta["command"][0]).name == cli and meta["command"].count("<prompt>") == 1
    assert word(base) not in " ".join(meta["command"])
    prompt = constants(base / "strawberry.py")["ASK" if step == "ask" else "PIVOT"].replace("{WORD}", word(base))
    assert meta["prompt"] == prompt
    # Reconstruct argv from the provenance placeholder and verify it too.
    argv = [prompt if arg == "<prompt>" else arg for arg in meta["command"][1:]]
    if step == "ask":
        assert_ask_command(cli, argv, prompt, meta["model"])
    elif cli == "claude":
        assert option(argv, "--permission-mode") == "acceptEdits"
        assert option(argv, "--allowedTools") == "Bash(uv run:*)"
        assert option(argv, "--output-format") == "stream-json" and "--verbose" in argv
    else:
        assert "exec" in argv and "--json" in argv and option(argv, "--sandbox") == "workspace-write"
    reported = meta.get("model_reported")
    assert isinstance(reported, (str, list)) and reported
    values = reported if isinstance(reported, list) else [reported]
    assert all(isinstance(v, str) and v.strip() for v in values)
    if cli == "claude":
        raw = data["raw"] if step == "ask" else [data["events"]]
        reported_raw = set()
        for stream in raw:
            for event in events(stream):
                reported_raw.update(event.get("modelUsage", {}).keys())
        assert reported_raw and set(values) == reported_raw
    elif today:
        # The fixture intentionally omits the reported Codex model; the requested
        # concrete ID must be used with an explicit provenance note.
        assert values == [meta["model"]]
        notes = " ".join(str(v) for k, v in meta.items() if k not in {"command", "prompt", "model", "model_reported"})
        assert re.search(r"requested|fallback|not report|unreported|does not report|did not report", notes, re.I)
    no_sensitive(json.dumps(data))


def assert_sampling_record(data, base, expected_calls=None, provider=None, env=None):
    meta = data["meta"]
    assert meta["demo"] == "sampling" and meta["provider"] in PROVIDERS
    valid_model(meta["model"])
    valid_date(meta["date"])
    assert meta["prompt"] == PROMPT and meta["max_tokens"] == 20
    parsed = urlsplit(meta["endpoint"])
    if expected_calls is None:
        assert parsed.scheme == "https"
        assert (parsed.hostname, parsed.path) == (("api.anthropic.com", "/v1/messages") if meta["provider"] == "anthropic"
                                                 else ("api.openai.com", "/v1/chat/completions"))
    else:
        assert meta["provider"] == provider and meta["date"] == date.today().isoformat()
        assert meta["endpoint"] == env[BASES[provider]] + ("/v1/messages" if provider == "anthropic" else "/chat/completions")
    runs = data.get("runs")
    assert isinstance(runs, list) and len(runs) == 2
    temperatures = [item.get("temperature") for item in runs]
    assert all(type(t) in {int, float} and math.isfinite(t) for t in temperatures)
    assert temperatures[0] < temperatures[1]
    if expected_calls is None:
        ranges = temperature_ranges(base)
        assert meta["model"] in ranges
        low, high = ranges[meta["model"]]
        assert all(low <= t <= high for t in temperatures)
    for item in runs:
        assert isinstance(item.get("outputs"), list) and len(item["outputs"]) == 5
        assert all(isinstance(s, str) and s.strip() for s in item["outputs"])
        assert isinstance(item.get("responses"), list) and len(item["responses"]) == 5
        if "prompt" in item:
            assert item["prompt"] == PROMPT
        if "model" in item:
            assert item["model"] == meta["model"]
        calls = ([c for c in expected_calls if c["body"]["temperature"] == item["temperature"]]
                 if expected_calls is not None else None)
        for i, response in enumerate(item["responses"]):
            assert isinstance(response, dict)
            assert isinstance(response.get("id"), str) and response["id"].strip()
            assert isinstance(response.get("model_reported"), str) and response["model_reported"].strip()
            reason = "stop_reason" if meta["provider"] == "anthropic" else "finish_reason"
            assert isinstance(response.get(reason), str) and response[reason]
            assert isinstance(response.get("usage"), dict) and response["usage"]
            assert not {"headers", "api_key", "authorization"} & response.keys()
            if calls is not None:
                raw = calls[i]["response"]
                assert item["outputs"][i] == calls[i]["text"]
                assert response["id"] == raw["id"] and response["model_reported"] == raw["model"]
                assert response["usage"] == raw["usage"]
                assert response[reason] == (raw[reason] if provider == "anthropic" else raw["choices"][0][reason])
    no_sensitive(json.dumps(data))


def test_a3_every_recording_metadata_and_runbook_rows():
    for name in STRAWBERRY_FILES:
        data = recording(name)
        cli = "claude" if "claude" in name else "codex"
        step = "ask" if name.startswith("strawberry-") else "pivot"
        assert_cli_meta(data, cli, step, DEMO)
        recorded_row(name, data)
        if step == "pivot":
            recorded_row(f"{cli}_count_r.py", data)
    names = list((DEMO / "recorded").glob("*.json"))
    assert names
    for path in names:
        data = recording(path.name)
        valid_model(data["meta"]["model"])
        valid_date(data["meta"]["date"])
        if path.name == "sampling.json":
            assert_sampling_record(data, DEMO)
        else:
            assert data["meta"].get("model_reported")
        recorded_row(path.name, data)


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("pivot", [False, True])
def test_a3_record_stamps_cli_model_version_date_and_safe_events(tmp_path, cli, pivot):
    _, base, env = sandbox(tmp_path)
    env = cli_env(tmp_path, env, cli, base)
    args = ["--via", cli, "--record"] + (["--pivot"] if pivot else [])
    success(script(base, "strawberry.py", args, env, children=True))
    name = f"{'pivot' if pivot else 'strawberry'}-{cli}.json"
    data = recording(name, base)
    assert_cli_meta(data, cli, "pivot" if pivot else "ask", base, today=True)
    assert re.search(r"\b1\.2\.3\b", data["meta"]["cli_version"])
    if pivot:
        assert_pivot_record(data, cli, base)
        assert (base / "recorded" / f"{cli}_count_r.py").read_bytes() == (base / "work/count_r.py").read_bytes()
    else:
        assert_ask_record(data, cli, base)
        if cli == "claude":
            value = data["meta"]["model_reported"]
            assert (value if isinstance(value, list) else [value]) == ["claude-stub-20990101"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a3_record_stamps_api_response_provenance_and_requested_model(tmp_path, provider):
    root, base, env = sandbox(tmp_path)
    with api_server(provider, (0.2, 0.8), marker=tmp_path.name) as (port, calls):
        env = api_env(env, provider, port)
        args = ["--provider", provider, "--model", "fixture-requested-73", "--low", "0.2", "--high", "0.8", "--record"]
        success(script(base, "sampling.py", args, env, cwd=root))
    data = recording("sampling.json", base)
    assert data["meta"]["model"] == "fixture-requested-73"
    assert_requests(calls, provider, env, "fixture-requested-73", (0.2, 0.8))
    assert_sampling_record(data, base, calls, provider, env)


def test_d4_strawberry_artifacts_are_git_tracked_and_dated(tmp_path):
    tracked = set(success(run(["git", "ls-files", "-z", "--", str(RELATIVE / "recorded")], ROOT,
                             child_env(tmp_path))).split("\0"))
    for name in (*STRAWBERRY_FILES, *COUNT_FILES):
        assert str(RELATIVE / "recorded" / name) in tracked, f"Uncommitted fallback: {name}"
        assert (DEMO / "recorded" / name).is_file()
    for name in STRAWBERRY_FILES:
        valid_date(recording(name)["meta"]["date"])
    if (DEMO / "recorded/sampling.json").exists():
        assert str(RELATIVE / "recorded/sampling.json") in tracked
        valid_date(recording("sampling.json")["meta"]["date"])


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("pivot", [False, True])
@pytest.mark.parametrize("start", ["demo", "repo"])
def test_d4_replay_reads_recording_offline_without_any_child(tmp_path, cli, pivot, start):
    root, base, env = sandbox(tmp_path)
    name = f"{'pivot' if pivot else 'strawberry'}-{cli}.json"
    data = recording(name, base)
    marker = "offline-pivot-proof-λ"
    if pivot:
        changed = False
        for event in data["events"]:
            if cli == "codex" and event.get("item", {}).get("type") == "command_execution" and event["item"].get("aggregated_output"):
                event["item"]["aggregated_output"] = marker + "\n" + str(data["truth"]) + "\n"
                changed = True
            elif cli == "claude":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_result" and re.search(rf"^\s*{data['truth']}\s*$", "\n".join(strings(block.get("content", ""))), re.M):
                        block["content"] = marker + "\n" + str(data["truth"]) + "\n"
                        changed = True
        assert changed, "Need a saved execution result to mutate"
    else:
        replacement = f"Replay-specific answer: {data['truth'] + 41}"
        data["answers"][0] = replacement
        data["classes"][0] = "incorrect"
        stream = events(data["raw"][0])
        if cli == "claude":
            next(e for e in stream if e.get("type") == "result")["result"] = replacement
        else:
            matches = [e["item"] for e in stream if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
            assert len(matches) == 1
            matches[0]["text"] = replacement
        data["raw"][0] = stream
    (base / "recorded" / name).write_text(json.dumps(data), encoding="utf-8")
    args = ["--replay", "--via", cli] + (["--pivot"] if pivot else [])
    output = success(script(base, "strawberry.py", args, env, cwd=base if start == "demo" else root))
    assert f"model {data['meta']['model']} · recorded {data['meta']['date']}" in output.splitlines()
    if pivot:
        compact_pivot(output, data["truth"])
        assert marker in output
    else:
        assert_ask_output(output, data["answers"], data["tools_used"], data["truth"])


def literal_shell_blocks(base, name, env):
    command_blocks = blocks(section(name, "Fallback", base))
    assert command_blocks, f"{name}: fenced offline commands required"
    output = []
    for command in command_blocks:
        output.append(success(run(["bash", "--noprofile", "--norc", "-c", command], base, env)))
    return command_blocks, output


def test_d4_all_strawberry_fallback_commands_run_literally_offline(tmp_path):
    _, base, env = sandbox(tmp_path)
    assert shutil.which("uv"), "Engine prerequisite: real uv"
    command_blocks, output = literal_shell_blocks(base, "strawberry.md", env)
    commands = []
    for block in command_blocks:
        for line in block.replace("\\\n", " ").splitlines():
            if line.strip().startswith("uv "):
                commands.append(shlex.split(line))
    for cli in CLIS:
        for pivot in (False, True):
            prefix = ["uv", "run", "--offline", "strawberry.py", "--replay"]
            flags = (["--via", "codex"] if cli == "codex" else []) + (["--pivot"] if pivot else [])
            assert any(c[:len(prefix)] == prefix and Counter(c[len(prefix):]) == Counter(flags) for c in commands)
        count_command = ["uv", "run", "--no-project", "--offline", "python", f"recorded/{cli}_count_r.py"]
        assert count_command in commands
        # Also run the mandated literal count command alone so a nearby replay
        # printing truth cannot conceal a broken saved program.
        assert success(run(count_command, base, env)).strip() == str(word(base).count("r"))
    assert output and any("wrong:" in value for value in output)
    assert any("true count:" in value for value in output)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_d4_sampling_record_then_offline_replay_and_literal_fallback(tmp_path, provider):
    root, base, env = sandbox(tmp_path)
    with api_server(provider, marker=tmp_path.name) as (port, calls):
        live_env = api_env(env, provider, port)
        success(script(base, "sampling.py", ["--provider", provider, "--record"], live_env))
    data = recording("sampling.json", base)
    assert_sampling_record(data, base, calls, provider, live_env)
    for cwd in (base, root):
        output = success(script(base, "sampling.py", ["--replay"], env, cwd=cwd))
        assert_sampling_output(output, data["runs"])
        assert data["meta"]["model"] in output and data["meta"]["date"] in output
    commands, outputs = literal_shell_blocks(base, "sampling.md", env)
    assert any(re.search(r"\buv\s+run\s+--offline\s+sampling\.py\s+--replay\b", command) for command in commands)
    assert_sampling_output("\n".join(outputs), data["runs"])


def test_d4_missing_sampling_replay_explains_owner_recording(tmp_path):
    _, base, env = sandbox(tmp_path)
    (base / "recorded/sampling.json").unlink(missing_ok=True)
    result = script(base, "sampling.py", ["--replay"], env)
    assert result.returncode == 1
    lines = (result.stdout + result.stderr).strip().splitlines()
    assert len(lines) == 1
    assert re.search(r"missing|no recording|not found", lines[0], re.I)
    assert "--record" in lines[0] and re.search(r"key|API_KEY", lines[0], re.I)
    assert "Traceback" not in result.stdout + result.stderr

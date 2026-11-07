"""The CLI-only model demos (cursus/demos/model): strawberry.py and sampling.py.

Fake claude and codex CLIs check what the scripts send them (tools off for the asks, write permissions for the
pivot), the CLI selection and its diagnostics, and that --record keeps the CLI's own output and reported model. The
committed recordings are checked as real evidence of the miscount, the pivot and the spread, and --replay is shown
to open no socket, start no process and write nothing. No real agent is invoked. The run-of-show's own fallback
commands are run by test_examiner_49_runbook.py.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
DEMO = SESSION / "cursus/demos/model"
CLIS = ("claude", "codex")


def read_record(step, cli, folder=DEMO):
    path = folder / "recorded" / f"{step}-{cli}.json"
    assert path.is_file(), f"Missing real recording: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("meta"), dict), path
    return data


def nodes(value):
    """Walk kept CLI structures, including JSON strings/JSONL stdout."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            for line in value.splitlines():
                if line.lstrip().startswith("{"):
                    try:
                        yield from nodes(json.loads(line))
                    except ValueError:
                        pass
        else:
            if isinstance(decoded, (dict, list)):
                yield from nodes(decoded)
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def kept(data):
    # raw/events are the existing strawberry formats. The aliases permit a
    # wrapper around plain-mode stdout, stderr and the -o last-message file.
    for key in ("raw", "events", "cli_output", "responses", "runs"):
        if key in data:
            if not data[key] and "transcript" in data:
                continue
            return data[key]
    if "transcript" in data:
        return {key: data[key] for key in ("transcript", "last_message", "output_last_message", "final_message") if key in data}
    pytest.fail("Recording must keep CLI events or a plain-mode last-message/transcript")


def final_answer(cli, raw):
    events = list(nodes(raw))
    if cli == "claude":
        results = [e for e in events if e.get("type") == "result"]
        assert results and not results[-1].get("is_error"), "Missing successful Claude result"
        answer = results[-1].get("result")
    else:
        messages = [e["item"].get("text") for e in events
                    if e.get("type") == "item.completed" and isinstance(e.get("item"), dict)
                    and e["item"].get("type") == "agent_message"]
        answer = messages[-1] if messages else None
        if answer is None:
            # This is kept output from Codex's -o file, not the derived answers
            # list. A transcript can also preserve the final `codex` section.
            for e in reversed(events):
                for key in ("last_message", "output_last_message", "final_message"):
                    if isinstance(e.get(key), str):
                        answer = e[key]
                        break
                if answer is not None:
                    break
        if answer is None:
            for text in strings(raw):
                match = re.search(r"(?:^|\n)codex\s*\n(.*?)(?=\n(?:tokens used|usage)\b|\Z)", text, re.DOTALL)
                if match:
                    answer = match[1].strip()
        # A plain-mode raw entry may itself be the -o file's verbatim contents.
        if answer is None and isinstance(raw, str) and not events and not re.search(r"(?:^|\n)exec\s*\n", raw):
            answer = raw
    assert isinstance(answer, str) and answer.strip(), "No answer in kept CLI output"
    return answer.strip()


def recorded_answers(data, cli):
    raw = kept(data)
    assert isinstance(raw, list) and len(raw) == 5, "Keep output for each of five independent runs"
    answers = [final_answer(cli, run) for run in raw]
    saved = data.get("answers", data.get("outputs"))
    if saved is not None:
        assert saved == answers, "Derived answers disagree with kept CLI output"
    return answers, raw


def integer_answer(text):
    values = {int(v) for v in re.findall(r"(?<![\w.])-?\d+(?![\w.])", text)}
    return next(iter(values)) if len(values) == 1 else None


def has_tool(cli, raw):
    for e in nodes(raw):
        if cli == "claude":
            if e.get("type") in {"tool_use", "tool_result"}:
                return True
            if e.get("type") == "result" and e.get("num_turns", 1) != 1:
                return True
        elif isinstance(e.get("item"), dict):
            if e["item"].get("type") not in {"agent_message", "reasoning"}:
                return True
    return cli == "codex" and any(re.search(r"(?:^|\n)exec\s*\n", s) for s in strings(raw))


def runs_code(command):
    return bool(re.search(r"(?:python(?:3)?|uv\s+run)\b[^\n]*count_r\.py", command))


def printed_truth(text, truth):
    return bool(re.search(rf"(?m)^\s*{truth}\s*$", text))


def normalized_source(text):
    """Ignore transcript shell quoting and formatting, but keep code content."""
    return re.sub(r"[\\\"'\s]", "", text)


def writes_counter(command):
    return bool(re.search(r">\s*[\"']?(?:\./)?work/count_r\.py\b", command)
                or ("apply_patch" in command and
                    re.search(r"\*\*\* (?:Add|Update) File: (?:\./)?work/count_r\.py\b", command)))


def write_contents(text):
    """Keep verbatim writes and recover source lines from a patch/diff.

    Diff markers describe the edit, so they are not part of the written file.
    Shell quoting and whitespace are still normalized only at comparison time.
    """
    yield text
    lines = text.splitlines()
    if any(line.startswith(("*** Add File:", "*** Update File:", "@@", "+++")) for line in lines):
        yield "\n".join(line[1:] for line in lines
                        if line.startswith(("+", " ")) and not line.startswith("+++"))


def successful_pivot(data, cli):
    """Return write content that precedes a proven successful counter run.

    Only tool events/exec blocks count: the echoed prompt or final claim is not
    evidence that the agent wrote or ran the file.
    """
    raw, truth = kept(data), data["word"].count("r")
    events = list(nodes(raw))
    prior_writes, proven_writes = [], []
    if cli == "claude":
        runs = {}
        for e in events:
            if e.get("type") == "tool_use":
                inputs = e.get("input") or {}
                command = str(inputs.get("command", ""))
                if (e.get("name") in {"Write", "Edit"} and
                        str(inputs.get("file_path", "")).endswith("count_r.py")):
                    prior_writes.extend(strings(inputs.get("content", inputs.get("new_string", ""))))
                elif e.get("name") == "Bash" and writes_counter(command):
                    prior_writes.extend(write_contents(command))
                elif e.get("name") == "Bash" and runs_code(command):
                    runs[e.get("id")] = list(prior_writes)
            elif (e.get("type") == "tool_result" and e.get("tool_use_id") in runs
                  and not e.get("is_error", False)
                  and any(printed_truth(s, truth) for s in strings(e.get("content")))):
                proven_writes.extend(runs[e["tool_use_id"]])
    else:
        for e in events:
            if e.get("type") != "item.completed" or not isinstance(e.get("item"), dict):
                continue
            item = e["item"]
            if item.get("type") == "file_change" and item.get("status") == "completed":
                for change in nodes(item.get("changes", [])):
                    if str(change.get("path", "")).endswith("work/count_r.py"):
                        for text in strings(change.get("diff", change.get("content", ""))):
                            prior_writes.extend(write_contents(text))
            if item.get("type") != "command_execution" or item.get("exit_code") != 0:
                continue
            command = item.get("command", "")
            if writes_counter(command):
                prior_writes.extend(write_contents(command))
            elif runs_code(command) and printed_truth(item.get("aggregated_output", ""), truth):
                proven_writes.extend(prior_writes)
        for text in strings(raw):
            prior_writes = []
            for block in re.split(r"(?:^|\n)exec\s*\n", text)[1:]:
                block = re.split(r"\n(?:exec|thinking|codex|tokens used)\s*\n", block)[0]
                result = re.search(r"(?m)^\s*succeeded\b[^\n]*:\s*\n?", block)
                if not result:
                    continue
                command, output = block[:result.start()], block[result.end():]
                if writes_counter(command):
                    prior_writes.extend(write_contents(command))
                elif runs_code(command) and printed_truth(output, truth):
                    proven_writes.extend(prior_writes)
    assert proven_writes, "Pivot must show the agent writing count_r.py before running it successfully and printing the truth"
    assert truth in {int(n) for n in re.findall(r"\b\d+\b", final_answer(cli, raw))}, "Final message must state the count"
    return proven_writes


def reported_models(data):
    value = data["meta"].get("model_reported")
    models = [value] if isinstance(value, str) else value
    assert isinstance(models, list) and models and all(isinstance(m, str) and m.strip() for m in models)
    return models


def model_evidence(data, cli):
    meta = data["meta"]
    assert meta.get("cli") == cli
    assert meta.get("model") and meta.get("prompt") and meta.get("command")
    assert isinstance(meta.get("cli_version"), str) and re.search(r"\d+\.\d+", meta["cli_version"])
    assert "model_reported_note" not in meta, "A requested model is not a CLI-reported model"
    recorded_date = date.fromisoformat(meta["date"])
    assert meta["date"] == recorded_date.isoformat() and recorded_date <= date.today()
    if cli == "claude":
        evidence = set()
        for e in nodes(kept(data)):
            if e.get("type") == "result":
                evidence.update((e.get("modelUsage") or {}).keys())
            if e.get("type") == "assistant":
                model = (e.get("message") or {}).get("model")
                if isinstance(model, str):
                    evidence.add(model)
    else:
        assert meta.get("model_evidence"), "Keep verbatim Codex model banner lines from stderr"
        banner_lines = {line.strip() for text in strings(kept(data)) for line in text.splitlines()
                        if re.fullmatch(r"\s*model:\s*\S+\s*", line)}
        saved_lines = set(strings(meta["model_evidence"]))
        assert saved_lines <= banner_lines, "Codex model_evidence must come from its kept transcript, not metadata alone"
        evidence = {line.split(":", 1)[1].strip() for line in banner_lines}
    assert set(reported_models(data)) <= evidence, "Reported IDs lack evidence from this CLI's kept output"


def section(text, title):
    pieces = []
    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*#*\s*$", text))
    for i, h in enumerate(headings):
        if h[2].strip().casefold() == title.casefold():
            end = next((other.start() for other in headings[i + 1:] if len(other[1]) <= len(h[1])), len(text))
            pieces.append(text[h.end():end])
    assert pieces, f"Missing {title} section"
    return "\n".join(pieces)


def code_blocks(text):
    return re.findall(r"(?ms)^```[^\n]*\n(.*?)^```\s*$", text)


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", UV_OFFLINE="1", UV_NO_PROGRESS="1", UV_PYTHON_DOWNLOADS="never")
    return env


def process(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=40, check=False)


def okay(result):
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.stdout


FAKE_CLI = r'''
import json, os, pathlib, re, sys
cli = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ["DEMO_FAKE_ROOT"])
config = json.loads((root / "config.json").read_text())
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"cli": cli, "args": args}) + "\n")
if args == ["--version"]:
    print("2.1.296 (Claude Code)" if cli == "claude" else "codex-cli 0.162.1")
    sys.exit(0)
if args in (["auth", "status"], ["login", "status"]):
    if cli == "claude" and not config.get("auth_status_supported", True):
        print("error: unknown subcommand status", file=sys.stderr)
        sys.exit(2)
    logged = config[cli]
    print(json.dumps({"loggedIn": logged}) if cli == "claude" else
          ("Logged in using ChatGPT" if logged else "Not logged in"))
    sys.exit(0 if logged else 1)
if "--help" in args:
    print(("auth status" if config.get("auth_status_supported", True) else "No auth status subcommand") if cli == "claude" else "login status")
    sys.exit(0)
if not config[cli]:
    print("Not logged in. Run claude then /login or codex login.", file=sys.stderr)
    sys.exit(1)
assert not any(k.endswith("_API_KEY") for k in os.environ)
if cli == "claude":
    prompt = args[args.index("-p") + 1]
else:
    assert args[0] == "exec"
    with_value = {"-o", "--output-last-message", "--sandbox", "-s", "-m", "--model", "-c", "--config", "--disable", "--enable", "--cd", "-C"}
    positional, skip = [], False
    for arg in args[1:]:
        if skip:
            skip = False
        elif arg in with_value:
            skip = True
        elif not arg.startswith("-"):
            positional.append(arg)
    prompt = positional[-1]
counter = root / (cli + "-counter")
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
word = max(re.findall(r"[a-zA-Z]+", prompt), key=len)
pivot = "work/count_r.py" in prompt
is_ask = len(word) > 100
truth = word.count("r")
answer = str(truth) if pivot else (str(truth + n + 7) if is_ask else config["answers"][n % 5])
model = "fake-reported-" + cli + "-" + str(config["variant"])
command = "uv run --no-project python work/count_r.py"
source = "WORD = " + repr(word) + "\nprint(WORD.count('r'))\n"
write_command = "/bin/bash -lc \"cat > work/count_r.py <<'PY'\n" + source + "PY\""
if pivot:
    path = pathlib.Path("work/count_r.py")
    path.parent.mkdir(exist_ok=True)
    path.write_text(source)
if cli == "claude":
    result = {"type": "result", "subtype": "success", "is_error": False,
              "num_turns": 3 if pivot else 1, "result": answer, "modelUsage": {model: {}}}
    events = []
    if pivot:
        events = [
          {"type": "assistant", "message": {"role": "assistant", "model": model, "content": [
           {"type": "tool_use", "id": "write", "name": "Write", "input": {"file_path": "work/count_r.py", "content": source}}]}},
          {"type": "user", "message": {"role": "user", "content": [
           {"type": "tool_result", "tool_use_id": "write", "content": "File created successfully"}]}},
          {"type": "assistant", "message": {"role": "assistant", "model": model, "content": [
           {"type": "tool_use", "id": "run", "name": "Bash", "input": {"command": command}}]}},
          {"type": "user", "message": {"role": "user", "content": [
           {"type": "tool_result", "tool_use_id": "run", "content": answer, "is_error": False}]}}]
    events.append(result)
    fmt = args[args.index("--output-format") + 1] if "--output-format" in args else "text"
    if fmt == "json":
        print(json.dumps(result))
    elif fmt == "stream-json":
        for e in events: print(json.dumps(e))
    else:
        print(answer)
else:
    print("OpenAI Codex\n--------\nmodel: " + model + "\n--------", file=sys.stderr)
    if "--json" in args:
        events = []
        if pivot:
            events.append({"type": "item.completed", "item": {"id": "write", "type": "command_execution",
                           "command": write_command, "aggregated_output": "", "exit_code": 0, "status": "completed"}})
            events.append({"type": "item.completed", "item": {"id": "run", "type": "command_execution",
                           "command": command, "aggregated_output": answer + "\n", "exit_code": 0, "status": "completed"}})
        events += [{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": answer}},
                   {"type": "turn.completed", "usage": {}}]
        for e in events: print(json.dumps(e))
    else:
        if pivot:
            print("exec\n" + write_command + " in .\n succeeded in 1ms:\n", file=sys.stderr)
            print("exec\n" + command + " in .\n succeeded in 3ms:\n" + answer, file=sys.stderr)
        print("codex\n" + answer + "\ntokens used\n12", file=sys.stderr)
        print(answer)
    for opt in ("-o", "--output-last-message"):
        if opt in args: pathlib.Path(args[args.index(opt) + 1]).write_text(answer)
'''


class Harness:
    def __init__(self, root, installed=(), logged=(), variant=1):
        root.mkdir(parents=True)
        self.root = root
        self.folder = root / "model"
        assert DEMO.is_dir(), "Missing cursus/demos/model"
        shutil.copytree(DEMO, self.folder, ignore=shutil.ignore_patterns("work", "__pycache__"))
        bindir = root / "bin"
        bindir.mkdir()
        uv = shutil.which("uv")
        assert uv, "Install uv using the checked-in setup instructions"
        (bindir / "uv").symlink_to(Path(uv).resolve())
        for name in {"python", "python3", Path(sys.executable).name}:
            (bindir / name).symlink_to(sys.executable)
        self.answers = (["Copper Finch", "Copper Finch", "Indigo Loom", "Copper Finch", "Indigo Loom"] if variant == 1
                        else ["Orbit Quill", "Moss Arc", "Quiet Delta", "Cobalt Nest", "Velvet Axis"])
        self.config = {**{cli: cli in logged for cli in CLIS}, "answers": self.answers, "variant": variant}
        (root / "config.json").write_text(json.dumps(self.config), encoding="utf-8")
        for cli in installed:
            path = bindir / cli
            path.write_text(f"#!{sys.executable}\n" + FAKE_CLI, encoding="utf-8")
            path.chmod(0o755)
        self.env = clean_env()
        self.env.update(PATH=str(bindir), DEMO_FAKE_ROOT=str(root))
        for cli in CLIS:
            assert shutil.which(cli, path=self.env["PATH"]) == (str(bindir / cli) if cli in installed else None)

    def run(self, script, *args):
        return process(["uv", "run", "--offline", script, *args], self.folder, self.env)

    def calls(self, main_only=True):
        path = self.root / "calls.jsonl"
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [c for c in calls if "-p" in c["args"] or c["args"][:1] == ["exec"]] if main_only else calls


# os.exec/fork events are process creation; Python's 'exec' audit event also
# occurs during ordinary stdlib imports, so it must remain permitted.
AUDIT_RUNNER = r'''
import os, pathlib, shutil, sys
filename = pathlib.Path(sys.argv[1]).resolve()
code = compile(filename.read_text(encoding="utf-8"), str(filename), "exec")
sys.argv = sys.argv[1:]
sys.dont_write_bytecode = True
violations = []
def deny(message):
    violations.append(message)
    raise RuntimeError(message)
def audit(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.fork", "os.posix_spawn")) or event == "os.system":
        deny("Replay forbidden event: " + event)
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            deny("Replay attempted a file write")
    if event in {"os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.link", "os.symlink", "os.chmod", "os.truncate", "os.utime", "shutil.copyfile"}:
        deny("Replay mutated the filesystem: " + event)
def no_which(*args, **kwargs):
    deny("Replay attempted CLI discovery")
shutil.which = no_which
sys.addaudithook(audit)
try:
    exec(code, {"__name__": "__main__", "__file__": str(filename), "__package__": None})
finally:
    if violations:
        raise RuntimeError("; ".join(violations))
'''


def replay(harness, script, cli=None, pivot=False):
    args = [script, "--replay"]
    if cli:
        args += ["--via", cli]
    if pivot:
        args += ["--pivot"]
    return okay(process([sys.executable, "-c", AUDIT_RUNNER, *args], harness.folder, harness.env))


def run_rows(text):
    rows = re.findall(r"(?m)^run\s+(\d+):\s*(.*)$", text)
    assert [int(i) for i, _ in rows] == list(range(1, 6)), text
    return [value for _, value in rows]


def check_sampling_output(text, answers):
    assert run_rows(text) == answers
    assert re.search(rf"distinct answers:\s*{len(set(answers))}\s+of\s+5\b", text), text
    for answer, count in Counter(answers).items():
        tally = [line for line in text.splitlines() if answer in line and not re.match(r"run\s+\d+:", line)]
        assert any(re.search(rf"\b{count}\b", line) for line in tally), f"Missing tally for {answer!r}"


def no_tool_flags(cli, args):
    assert not any("temperature" in arg.casefold() for arg in args)
    assert not any(re.match(r"--(?:top[-_]?[pk]|seed|sampling)(?:=|$)", arg) for arg in args)
    if cli == "claude":
        assert "-p" in args and option_values(args, "--tools") == [""]
    else:
        assert args[0] == "exec"
        assert option_values(args, "--sandbox", "-s") == ["read-only"]
        assert "shell_tool" in option_values(args, "--disable")


def option_values(args, *names):
    found = []
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            found.append(args[i + 1])
        elif any(arg.startswith(name + "=") for name in names):
            found.append(arg.split("=", 1)[1])
    return found


def call_prompt(call):
    args = call["args"]
    if call["cli"] == "claude":
        return args[args.index("-p") + 1]
    with_value = {"-o", "--output-last-message", "--sandbox", "-s", "-m", "--model", "-c", "--config", "--disable", "--enable", "--cd", "-C"}
    positional, skip = [], False
    for arg in args[1:]:
        if skip:
            skip = False
        elif arg in with_value:
            skip = True
        elif not arg.startswith("-"):
            positional.append(arg)
    assert positional, "CLI invocation must include the demo prompt"
    return positional[-1]


@pytest.mark.parametrize("cli", CLIS)
def test_recordings_prove_miscount_and_pivot(cli, tmp_path):
    ask = read_record("strawberry", cli)
    word = ask["word"]
    assert isinstance(word, str) and len(word) >= 100 and word.isalpha(), "The demo needs a long invented word of letters"
    truth = word.count("r")
    assert ask["truth"] == truth and word in ask["meta"]["prompt"]
    answers, raw = recorded_answers(ask, cli)
    assert all(not has_tool(cli, run) for run in raw), "Ask runs must use no tool"
    assert any(integer_answer(a) is not None and integer_answer(a) != truth for a in answers), "Each CLI needs a parsed, genuinely wrong integer"
    pivot = read_record("pivot", cli)
    assert pivot["word"] == word and pivot["truth"] == truth and word in pivot["meta"]["prompt"]
    writes = successful_pivot(pivot, cli)
    path = DEMO / "recorded" / f"{cli}_count_r.py"
    source = path.read_text(encoding="utf-8")
    assert any(normalized_source(source) in normalized_source(write) for write in writes), "Committed counter must match what the agent wrote before the successful run"
    tree = ast.parse(source)
    assignments = [n for n in ast.walk(tree)
                   if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WORD" for t in n.targets))
                   or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "WORD")]
    assert len(assignments) == 1
    value = assignments[0].value
    assert value is not None and ast.literal_eval(value) == word
    assert okay(process([sys.executable, str(path)], DEMO, clean_env())).strip() == str(truth)
    # Replace the input, not the expected output: rejects a hard-coded 146.
    for i, probe in enumerate(("rRrr-river" * 9, "strawberry" * 3, "No lowercase letters here")):
        assignments[0].value = ast.Constant(value=probe)
        ast.fix_missing_locations(tree)
        copy = tmp_path / f"probe-{i}.py"
        copy.write_text(ast.unparse(tree), encoding="utf-8")
        assert okay(process([sys.executable, str(copy)], tmp_path, clean_env())).strip() == str(probe.count("r"))



@pytest.mark.parametrize("cli", CLIS)
def test_live_ask_and_pivot_permissions_and_recordings(cli, tmp_path):
    h = Harness(tmp_path / cli, installed=CLIS, logged=CLIS)
    ask_output = okay(h.run("strawberry.py", "--via", cli, "--record"))
    ask_calls = h.calls()
    assert len(ask_calls) == 5 and {c["cli"] for c in ask_calls} == {cli}
    assert len({call_prompt(c) for c in ask_calls}) == 1
    word = max(re.findall(r"[a-zA-Z]+", call_prompt(ask_calls[0])), key=len)
    truth = word.count("r")
    rows = run_rows(ask_output)
    assert [integer_answer(row) for row in rows] == [truth + i + 7 for i in range(5)]
    assert re.search(rf"true count:\s*{truth}\b", ask_output)
    for c in ask_calls:
        no_tool_flags(cli, c["args"])
    ask = read_record("strawberry", cli, h.folder)
    model_evidence(ask, cli)
    assert reported_models(ask) == [f"fake-reported-{cli}-1"], "Use the CLI's report, not the requested ID"
    assert recorded_answers(ask, cli)[0] == [str(truth + i + 7) for i in range(5)]
    pivot_output = okay(h.run("strawberry.py", "--via", cli, "--pivot", "--record"))
    pivot_calls = h.calls()[5:]
    assert len(pivot_calls) == 1 and pivot_calls[0]["cli"] == cli
    args = pivot_calls[0]["args"]
    assert "work/count_r.py" in call_prompt(pivot_calls[0]) and word in call_prompt(pivot_calls[0])
    if cli == "claude":
        assert "--permission-mode" in args and args[args.index("--permission-mode") + 1] == "acceptEdits"
        assert "--allowedTools" in args and "Bash" in args[args.index("--allowedTools") + 1]
        assert "--tools" not in args or args[args.index("--tools") + 1] != ""
    else:
        assert any(args[i] in {"--sandbox", "-s"} and args[i + 1] == "workspace-write" for i in range(len(args) - 1))
        assert not any(args[i] == "--disable" and args[i + 1] in {"shell_tool", "unified_exec"} for i in range(len(args) - 1))
    assert "count_r.py" in pivot_output and re.search(rf"true count:\s*{truth}\b", pivot_output)
    pivot = read_record("pivot", cli, h.folder)
    model_evidence(pivot, cli)
    assert pivot["meta"]["date"] == date.today().isoformat()
    assert reported_models(pivot) == [f"fake-reported-{cli}-1"]
    successful_pivot(pivot, cli)


@pytest.mark.parametrize("cli", CLIS)
def test_live_sampling_sends_five_identical_prompts_and_records(cli, tmp_path):
    h = Harness(tmp_path / cli, installed=CLIS, logged=CLIS)
    output = okay(h.run("sampling.py", "--via", cli, "--record"))
    calls = h.calls()
    assert len(calls) == 5 and {c["cli"] for c in calls} == {cli}
    prompts = {call_prompt(c) for c in calls}
    assert len(prompts) == 1 and next(iter(prompts)).strip()
    data = read_record("sampling", cli, h.folder)
    for c in calls:
        no_tool_flags(cli, c["args"])
        assert all(model == data["meta"]["model"] for model in option_values(c["args"], "--model", "-m")), "Requested model must agree with the recording"
    check_sampling_output(output, h.answers)
    assert recorded_answers(data, cli)[0] == h.answers
    meta = data["meta"]
    assert meta["demo"] == "sampling" and meta["prompt"] == next(iter(prompts))
    assert meta.get("model") and meta.get("command")
    model_evidence(data, cli)
    assert reported_models(data) == [f"fake-reported-{cli}-1"], "Use the CLI's report, not the requested ID"


@pytest.mark.parametrize("script,pivot,step", (("strawberry.py", False, "strawberry"),
                                            ("strawberry.py", True, "pivot"), ("sampling.py", False, "sampling")))
@pytest.mark.parametrize("cli", CLIS)
def test_replay_shows_the_recording_with_no_network_process_or_writes(script, pivot, step, cli, tmp_path):
    h = Harness(tmp_path / "offline")
    before = {p.relative_to(h.folder): p.read_bytes() for p in h.folder.rglob("*") if p.is_file()}
    data = read_record(step, cli)
    model_evidence(data, cli)
    recorded_date = date.fromisoformat(data["meta"]["date"])
    assert recorded_date <= date.today() and data["meta"]["date"] == recorded_date.isoformat()
    output = replay(h, script, cli, pivot)
    header = output.splitlines()[0]
    assert f"recorded {recorded_date.isoformat()}" in header
    assert all(model in header for model in reported_models(data))
    if pivot:
        assert "count_r.py" in output and re.search(rf"\b{data['word'].count('r')}\b", output)
    else:
        answers, raw = recorded_answers(data, cli)
        if step == "sampling":
            assert len(set(answers)) >= 2, "Real committed sampling must demonstrate spread"
            assert not any(has_tool(cli, run) for run in raw)
            check_sampling_output(output, answers)
        else:
            for answer, row in zip(answers, run_rows(output)):
                value = integer_answer(answer)
                assert (integer_answer(row) == value) if value is not None else answer in row
    after = {p.relative_to(h.folder): p.read_bytes() for p in h.folder.rglob("*") if p.is_file()}
    assert before == after


# CLI selection lives in agent_cli.py, which both scripts share: sampling.py stands for both.
def failure(result, script, clis):
    assert result.returncode != 0
    text = result.stderr.casefold()
    assert "traceback" not in text
    for cli in clis:
        assert cli in text
    assert re.search(rf"uv run (?:--offline )?{re.escape(script)} --replay", text), text
    return text



def test_missing_and_logged_out_diagnostics(tmp_path):
    script = "sampling.py"
    missing = Harness(tmp_path / "missing")
    text = failure(missing.run(script), script, CLIS)
    assert re.search(r"missing|not found|not installed|not on path", text)
    assert "codex login" in text and "/login" in text
    out = Harness(tmp_path / "logged-out", installed=CLIS)
    text = failure(out.run(script), script, CLIS)
    assert "not logged in" in text or "log in" in text or "login" in text
    assert "codex login" in text and "/login" in text
    assert {c["cli"] for c in out.calls(main_only=False)} == set(CLIS), "Auto-detection must try each installed CLI"


def test_login_fallback_when_claude_has_no_status_subcommand(tmp_path):
    h = Harness(tmp_path / "old-auth", installed=CLIS, logged=("codex",))
    h.config["auth_status_supported"] = False
    (h.root / "config.json").write_text(json.dumps(h.config), encoding="utf-8")
    output = okay(h.run("sampling.py"))
    assert "codex" in output.casefold()
    calls = h.calls()
    assert len([c for c in calls if c["cli"] == "codex"]) == 5
    assert len([c for c in calls if c["cli"] == "claude"]) <= 1


@pytest.mark.parametrize("installed,logged,via,expected", (
    (CLIS, CLIS, None, "claude"),
    (CLIS, ("codex",), None, "codex"),
    (("codex",), ("codex",), None, "codex"),
    (CLIS, CLIS, "codex", "codex"),
))
def test_auto_detection_and_forced_selection(installed, logged, via, expected, tmp_path):
    h = Harness(tmp_path / "selection", installed=installed, logged=logged)
    output = okay(h.run("sampling.py", *(["--via", via] if via else [])))
    calls = h.calls()
    assert len(calls) == 5 and {c["cli"] for c in calls} == {expected}
    assert expected in output.casefold(), "Print which CLI was selected"
    if via:
        assert {c["cli"] for c in h.calls(main_only=False)} == {via}, "Forced selection must not contact the other CLI"


@pytest.mark.parametrize("via,state", (("claude", "missing"), ("codex", "logged-out")))
def test_forced_unavailable_cli_never_falls_back(via, state, tmp_path):
    other = next(c for c in CLIS if c != via)
    h = Harness(tmp_path / "forced", installed=CLIS if state == "logged-out" else (other,), logged=(other,))
    text = failure(h.run("sampling.py", "--via", via), "sampling.py", (via,))
    assert re.search(r"missing|not found|not installed|not on path", text) if state == "missing" else re.search(r"not logged in|log in|login", text)
    assert not any(c["cli"] == other for c in h.calls(main_only=False))


def test_documented_reset_restores_dirty_scratch_repository(tmp_path):
    # strawberry.md and sampling.md give the same Reset command.
    # Only the scratch repository has a baseline commit, needed to test HEAD.
    # No git operation here changes the course repository or its branches.
    root = tmp_path / "scratch"
    folder = root / "model"
    shutil.copytree(DEMO, folder, ignore=shutil.ignore_patterns("work", "__pycache__"))
    env = clean_env()
    okay(process(["git", "init", "--initial-branch=acceptance-scratch", str(root)], tmp_path, env))
    okay(process(["git", "add", "model"], root, env))
    okay(process(["git", "-c", "user.name=Acceptance check", "-c", "user.email=acceptance@example.invalid",
                  "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-m", "Scratch baseline"], root, env))
    before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    (folder / "work").mkdir(exist_ok=True)
    (folder / "work/count_r.py").write_text("print('dirty')\n", encoding="utf-8")
    recording = folder / "recorded/strawberry-claude.json"
    recording.write_text("dirty recording\n", encoding="utf-8")
    okay(process(["git", "add", str(recording)], root, env))
    blocks = code_blocks(section((DEMO / "strawberry.md").read_text(encoding="utf-8"), "Reset"))
    assert blocks, "Reset must provide the command to execute"
    command = "\n".join(blocks)
    assert "git restore" in command and "git clean" in command
    dirty = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    dirty_status = okay(process(["git", "status", "--porcelain", "--untracked-files=all"], root, env))
    refused = process(["/bin/bash", "-e", "-c", command], root, env)
    assert refused.returncode != 0, "Reset must refuse to run from the parent folder"
    assert {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == dirty, "Refused reset must leave dirty files untouched"
    assert okay(process(["git", "status", "--porcelain", "--untracked-files=all"], root, env)) == dirty_status, "Refused reset must preserve staged changes"
    okay(process(["/bin/bash", "-e", "-c", command], folder, env))
    after = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert after == before and not (folder / "work").exists()
    assert okay(process(["git", "status", "--porcelain", "--untracked-files=all"], root, env)) == ""


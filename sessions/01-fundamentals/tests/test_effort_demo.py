"""Issue 33 acceptance checks, authored before the implementation.

Run each ledger filter through the session's locked uv project. Tests never call
real model CLIs: live tests use disposable executable stubs; recorded evidence is
independently decoded. Authenticity of recordings, pricing-page verification and
teaching prose still require review. Consistent JSON is not proof of provenance.

Every collected test has a ledger prefix so the engine's five filtered commands
cover the entire file. The extra greedy-puzzle and default-replay design checks
belong to D2 and D3 respectively; their assertions are unchanged.

Only the agreed filenames, CLI interface, event formats and evidence fields are
contracts. Helpers accept flat or nested token counters and common price layouts;
no implementation function or constant name is required. Puzzle data are read
from literal Python constants, and solved by exhaustive enumeration here.
All git writes below are confined to a disposable reset-test clone.
"""

import ast
import copy
from datetime import date, datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlparse

import pytest


SESSION = Path(__file__).resolve().parents[1]
REPO = SESSION.parents[1]
RELATIVE = Path("sessions/01-fundamentals/cursus/demos/effort")
DEMO = REPO / RELATIVE
RUNS = set(itertools.product(("claude", "codex"), ("low", "high")))
DEFAULTS = {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"}
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
ALIASES = {
    "input": ("input", "input_tokens", "inputTokens"),
    "output": ("output", "output_tokens", "outputTokens"),
    "cache_read": ("cache_read", "cache_read_tokens", "cache_read_input_tokens", "cacheReadInputTokens"),
    "cache_write": ("cache_write", "cache_write_tokens", "cache_creation_input_tokens", "cacheCreationInputTokens"),
    "cached_input": ("cached_input", "cached_input_tokens"),
    "reasoning_output": ("reasoning_output", "reasoning_output_tokens"),
}
RATE_ALIASES = {
    "input": ("input", "input_usd_per_million", "input_per_million", "input_per_million_usd"),
    "output": ("output", "output_usd_per_million", "output_per_million", "output_per_million_usd"),
    "cache_read": ("cache_read", "cache_read_usd_per_million", "cache_read_per_million"),
    "cache_write_5m": ("cache_write_5m", "cache_write_5m_usd_per_million", "cache_write_5m_per_million"),
    "cached_input": ("cached_input", "cached_input_usd_per_million", "cached_input_per_million"),
}


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"Empty artifact: {path}"
    return text


def load(path):
    return json.loads(read(path))


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def field(mapping, aliases, default=None, required=True):
    wanted = {normalized(alias) for alias in aliases}
    found = [value for key, value in mapping.items() if normalized(key) in wanted]
    if not found:
        assert not required, f"Missing one of {aliases}: {mapping}"
        return default
    assert all(value == found[0] for value in found), f"Conflicting aliases: {aliases}"
    return found[0]


def finite(value, positive=False):
    assert type(value) in (int, float) and math.isfinite(value)
    assert value > 0 if positive else value >= 0
    return value


def integer(value):
    assert type(value) is int and value >= 0, f"Expected nonnegative integer counter: {value!r}"
    return value


def counters(row, cli):
    mapping = dict(row)
    for container in ("tokens", "usage", "token_counts", "token_counters"):
        if isinstance(row.get(container), dict):
            mapping.update(row[container])
    required = {"input", "output"} | ({"cache_read", "cache_write"} if cli == "claude"
                                     else {"cached_input", "reasoning_output"})
    return {name: integer(field(mapping, aliases, 0, name in required))
            for name, aliases in ALIASES.items()}


def child_env(**changes):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_") or key in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}:
            env.pop(key)
    env.update(UV_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    env.update(changes)
    return env


def run(args, cwd, env=None):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env or child_env(),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def success(args, cwd, env=None):
    result = run(args, cwd, env)
    assert result.returncode == 0, f"{args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.stdout


def rows(document):
    items = field(document, ("runs", "results", "rows"))
    assert isinstance(items, list)
    result = {}
    for row in items:
        identity = (row["cli"], row["effort"])
        assert identity not in result, f"Duplicate run: {identity}"
        result[identity] = row
    assert set(result) == RUNS, "Need exactly Claude/Codex × low/high"
    return result


def sections():
    source = read(DEMO / "README.md")
    headings = list(re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", source, re.M))
    result = {}
    for keyword in ("timing", "predict", "expected", "reset"):
        matches = [(i, match) for i, match in enumerate(headings) if keyword in match[1].lower()]
        assert matches, f"Runbook needs a {keyword} heading"
        i, match = matches[0]
        # Include nested subsections, stop at the next same/higher-level heading.
        level = len(match[0]) - len(match[0].lstrip("#"))
        end = next((m.start() for m in headings[i + 1:]
                    if len(m[0]) - len(m[0].lstrip("#")) <= level), len(source))
        result[keyword] = source[match.end():end]
    return result


def table_lines(output, expected):
    result = {}
    for identity in expected:
        cli, effort = identity
        matches = [line for line in output.splitlines()
                   if re.search(rf"\b{cli}\b", line, re.I) and re.search(rf"\b{effort}\b", line, re.I)]
        assert len(matches) == 1, f"Need one printed row for {identity}:\n{output}"
        result[identity] = matches[0]
    return result


def has_number(line, value, *, fractional=False):
    numbers = [float(match[0].replace(",", "")) for match in
               re.finditer(r"(?<![\w.])[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.])", line)]
    if fractional:
        # Fixed-width printed cost/time may be rounded; at least six cost decimals
        # aren't mandated, so allow a half-unit in the displayed last place.
        for match in re.finditer(NUMBER, line.replace(",", "")):
            text = match[0]
            decimals = len(text.split(".")[1]) if "." in text and "e" not in text.lower() else 0
            if decimals and abs(float(text) - value) <= 0.5 * 10 ** -decimals + 1e-12:
                return True
        return any(math.isclose(number, value, rel_tol=1e-5, abs_tol=1e-9) for number in numbers)
    return value in numbers


def assert_table(output, expected):
    lines = table_lines(output, expected)
    assert re.search(r"token|input|output", output, re.I)
    assert re.search(r"seconds|wall|time|\bsec\b", output, re.I)
    assert re.search(r"cost|usd|\$", output, re.I)
    assert re.search(r"correct|verdict|answer", output, re.I)
    for identity, row in expected.items():
        line = lines[identity]
        for name in ("input", "output"):
            assert has_number(line, counters(row, identity[0])[name]), f"Missing {name} counter: {line}"
        for name in ("wall_seconds", "cost_usd"):
            assert has_number(line, row[name], fractional=True), f"Missing {name}: {line}"
        verdict = r"true|yes|correct|pass|✓" if row["correct"] else r"false|no|incorrect|wrong|fail|✗|✘"
        assert re.search(rf"(?<!\w)(?:{verdict})(?!\w)", line, re.I), f"Missing verdict: {line}"
        if not row["pure_reasoning"]:
            assert "(used tools)" in line, f"Tool-contaminated run must be marked: {line}"
    return lines


def iso_date(value):
    assert isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    return date.fromisoformat(value)


def timestamp(value):
    assert isinstance(value, str) and "T" in value
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert result.tzinfo is not None and result.utcoffset().total_seconds() == 0, "Use UTC ISO timestamps"
    return result


def option(argv, name):
    assert isinstance(argv, list) and all(isinstance(arg, str) for arg in argv)
    for index, arg in enumerate(argv):
        if arg == name:
            assert index + 1 < len(argv), f"Missing value for {name}"
            return argv[index + 1]
        if arg.startswith(name + "="):
            return arg[len(name) + 1:]
    pytest.fail(f"Missing {name} in argv {argv}")


def config(argv, name):
    values = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg in ("-c", "--config")]
    for value in values:
        if value.startswith(name + "="):
            return value.split("=", 1)[1].strip("\"'")
    pytest.fail(f"Missing config {name}: {argv}")


def assert_invocation(argv, cli, effort, model):
    if cli == "claude":
        assert option(argv, "--effort") == effort
        assert option(argv, "--model") == model
        assert option(argv, "--output-format") == "stream-json"
        assert option(argv, "--tools") == ""
        assert option(argv, "--permission-mode") == "dontAsk"
        assert {"-p", "--verbose", "--no-session-persistence", "--strict-mcp-config"} <= set(argv)
    else:
        assert "exec" in argv and argv[-1] == "-"
        assert config(argv, "model_reasoning_effort") == effort
        assert config(argv, "approval_policy") == "never"
        assert option(argv, "-m") == model
        assert option(argv, "--sandbox") == "read-only"
        assert option(argv, "-C")
        assert {"--json", "--ephemeral", "--skip-git-repo-check"} <= set(argv)


def price_nodes(block):
    """Find model-keyed dictionaries without dictating vendor nesting."""
    found = {}
    def visit(value):
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if isinstance(child, dict):
                names = {normalized(name) for name in child}
                if names & {normalized(alias) for alias in RATE_ALIASES["input"]} and names & {
                        normalized(alias) for alias in RATE_ALIASES["output"]}:
                    assert key not in found, f"Duplicate price for model {key}"
                    found[key] = (value, child)
                else:
                    visit(child)
    visit(block)
    assert found, "Prices must contain per-model input/output rates in USD per million tokens"
    return found


def rates(block, model, cli):
    nodes = price_nodes(block)
    assert model in nodes, f"No rate for usage model {model}"
    node = nodes[model][1]
    required = ("input", "output", "cache_read", "cache_write_5m") if cli == "claude" else (
        "input", "output", "cached_input")
    return {name: finite(field(node, RATE_ALIASES[name]), positive=True) for name in required}


def sources(block):
    found = {}
    def visit(value, trail=()):
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, trail + (key.lower(),))
        elif isinstance(value, str) and value.startswith("https://"):
            label = " ".join(trail)
            host = urlparse(value).hostname or ""
            if "anthropic" in label or "claude" in label or "anthropic" in host or "claude" in host:
                found["claude"] = value
            if "openai" in label or "codex" in label or "openai" in host:
                found["codex"] = value
    visit(block)
    assert set(found) == {"claude", "codex"}, "Need HTTPS pricing source per vendor"
    return found


def puzzle():
    """Locate the literal parcel table structurally; never import the oracle."""
    prompt = read(DEMO / "prompt.txt")
    match = re.search(r"\bcapacity\b[^\n\d]{0,80}(\d+)\b", prompt, re.I)
    assert match, "Prompt must state its integer capacity"
    capacity = int(match[1])
    tree = ast.parse(read(DEMO / "effort.py"))
    constants = []
    tables = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue
        constants.append(value)
        entries = list(value.values()) if isinstance(value, dict) else value
        if not isinstance(entries, (list, tuple)) or len(entries) not in (7, 8):
            continue
        parcels = []
        for entry in entries:
            if isinstance(entry, dict):
                weight = field(entry, ("weight", "w", "mass"), None, False)
                value_ = field(entry, ("value", "v", "profit", "benefit"), None, False)
                pair = (weight, value_)
            elif isinstance(entry, (list, tuple)) and len(entry) in (2, 3):
                pair = tuple(entry[-2:])
            else:
                break
            if any(type(number) is not int for number in pair) or pair[0] <= 0 or pair[1] < 0:
                break
            parcels.append(pair)
        if len(parcels) == len(entries):
            tables.append(parcels)
    assert capacity > 0 and capacity in [x for x in constants if type(x) is int], "Capacity must be a script constant"
    # Numbers may be in Markdown, CSV, or labelled parcel lines. Each line must
    # contain the ordered weight/value pair (a numeric parcel ID is allowed).
    prompt_lines = prompt.splitlines()
    header = next((line.lower() for line in prompt_lines if "weight" in line.lower()
                   and "value" in line.lower() and not re.search(r"\d", line)
                   and any(delimiter in line for delimiter in ("|", ",", "\t"))), "weight value")
    reversed_columns = header.index("value") < header.index("weight")
    numeric_lines = []
    for line in prompt_lines:
        numbers = tuple(map(int, re.findall(r"(?<![\w.])\d+(?![\w.])", line)))
        lower = line.lower()
        reversed_line = (lower.index("value") < lower.index("weight")) if (
            "weight" in lower and "value" in lower) else reversed_columns
        if len(numbers) >= 2 and reversed_line:
            numbers = numbers[:-2] + (numbers[-1], numbers[-2])
        numeric_lines.append(numbers)
    candidates = [table for table in tables if all(any(tuple(line[-2:]) == pair for line in numeric_lines)
                                                  for pair in table)]
    assert len(candidates) == 1, "Shipped prompt must describe the script's one literal parcel table"
    parcels = candidates[0]
    optimum = max(sum(value for take, (_, value) in zip(bits, parcels) if take)
                  for bits in itertools.product((0, 1), repeat=len(parcels))
                  if sum(weight for take, (weight, _) in zip(bits, parcels) if take) <= capacity)
    assert "ANSWER:" in prompt and re.search(r"without tools|no tools|not use tools|do not use.*tools", prompt, re.I)
    return prompt, parcels, capacity, optimum


def answer(text):
    matches = re.findall(r"^\s*ANSWER\s*:\s*(.*?)\s*$", text, re.M)
    if not matches or not re.fullmatch(r"[+-]?\d+", matches[-1]):
        return None
    return int(matches[-1])


def decode(events, cli):
    counts = dict.fromkeys(ALIASES, 0)
    if cli == "claude":
        results = [event for event in events if event.get("type") == "result"]
        assert len(results) == 1, "Need one terminal Claude result"
        result = results[0]
        usage = result["modelUsage"]
        assert isinstance(usage, dict) and usage
        for model_usage in usage.values():
            for name in ("input", "output", "cache_read", "cache_write"):
                counts[name] += integer(field(model_usage, ALIASES[name]))
        init = [event for event in events if event.get("type") == "system" and event.get("subtype") == "init"]
        assert len(init) == 1 and isinstance(init[0].get("tools"), list), "Record Claude init tools"
        tool_calls = sum(block.get("type") == "tool_use" for event in events
                         if event.get("type") == "assistant"
                         for block in event.get("message", {}).get("content", []))
        text = result.get("result")
        if not isinstance(text, str):
            text = "\n".join(block.get("text", "") for event in events if event.get("type") == "assistant"
                             for block in event.get("message", {}).get("content", []) if block.get("type") == "text")
        return counts, text, tool_calls, not tool_calls and not init[0]["tools"], usage, result["total_cost_usd"]
    turns = [event["usage"] for event in events if event.get("type") == "turn.completed"]
    assert turns, "Need Codex turn.completed usage"
    for usage in turns:
        for name in ("input", "output", "cached_input", "reasoning_output"):
            counts[name] += integer(field(usage, ALIASES[name], 0, name != "reasoning_output"))
        assert usage["cached_input_tokens"] <= usage["input_tokens"]
        assert usage.get("reasoning_output_tokens", 0) <= usage["output_tokens"]
    items = [event["item"] for event in events if event.get("type") == "item.completed"]
    text = "\n".join(item.get("text", "") for item in items if item.get("type") == "agent_message")
    tools = set()
    for index, event in enumerate(events):
        item = event.get("item", {})
        kind = item.get("type", "")
        if kind in {"command_execution", "web_search", "file_change"} or "tool" in kind:
            tools.add(item.get("id", f"event-{index}"))
    return counts, text, len(tools), not tools, None, None


def events_at(path):
    events = [json.loads(line) for line in read(path).splitlines() if line.strip()]
    assert all(isinstance(event, dict) for event in events)
    return events


def cost_from_raw(block, cli, model, counts, usage):
    if cli == "claude":
        total = 0
        for name, counters_ in usage.items():
            rate = rates(block, name, cli)
            total += (counters_["inputTokens"] * rate["input"]
                      + counters_["cacheCreationInputTokens"] * rate["cache_write_5m"]
                      + counters_["cacheReadInputTokens"] * rate["cache_read"]
                      + counters_["outputTokens"] * rate["output"])
    else:
        rate = rates(block, model, cli)
        total = ((counts["input"] - counts["cached_input"]) * rate["input"]
                 + counts["cached_input"] * rate["cached_input"] + counts["output"] * rate["output"])
    return total / 1_000_000


@pytest.fixture(scope="module")
def recorded():
    document = load(DEMO / "recorded/results.json")
    return document, rows(document)


@pytest.fixture(scope="module")
def replay(recorded):
    output = success(["uv", "run", "--offline", "effort.py", "replay"], DEMO)
    assert_table(output, recorded[1])
    return output


def test_d1_artifacts_and_documented_commands(recorded, replay):
    for name in ("README.md", "prompt.txt", "effort.py", "prices.json"):
        read(DEMO / name)
    readme = read(DEMO / "README.md").replace("\\\n", " ")
    assert "uv run --offline effort.py replay" in readme
    for cli in ("claude", "codex"):
        assert re.search(rf"uv run effort\.py live[^\n`]*--cli\s+{cli}\b", readme), f"Document standalone {cli} live command"
    assert_table(replay, recorded[1])


@pytest.mark.parametrize("cli,effort", sorted(RUNS))
def test_d2_recorded_rows_rederive_from_raw_and_meta(recorded, cli, effort):
    document, recorded_rows = recorded
    row = recorded_rows[cli, effort]
    prompt, _, _, optimum = puzzle()
    raw = events_at(DEMO / f"recorded/raw/{cli}-{effort}.jsonl")
    meta = load(DEMO / f"recorded/raw/{cli}-{effort}.meta.json")
    counts, text, tools, pure, usage, reported = decode(raw, cli)
    assert counters(row, cli) == counts
    assert row["answer"] == answer(text)
    assert type(row["correct"]) is bool and row["correct"] == (answer(text) == optimum)
    assert integer(row["tool_calls"]) == tools
    assert type(row["pure_reasoning"]) is bool and row["pure_reasoning"] == pure
    assert row["wall_seconds"] == meta["wall_seconds"]
    finite(row["wall_seconds"], positive=True)
    assert row["cli_version"] == meta["cli_version"] and re.search(r"\d+\.\d+", row["cli_version"])
    assert_invocation(meta["argv"], cli, effort, row["model"])
    assert meta["cwd_kind"] == "tempdir-outside-repo"
    assert meta["prompt_sha256"] == hashlib.sha256((DEMO / "prompt.txt").read_bytes()).hexdigest()
    assert type(meta["exit_code"]) is int and meta["exit_code"] == 0
    duration = (timestamp(meta["ended_at"]) - timestamp(meta["started_at"])).total_seconds()
    assert duration >= 0 and abs(duration - row["wall_seconds"]) <= 1
    expected_cost = cost_from_raw(document["prices"], cli, row["model"], counts, usage)
    assert finite(row["cost_usd"]) == pytest.approx(expected_cost, rel=1e-8, abs=1e-10)
    if cli == "claude":
        assert row["reported_cost_usd"] == reported
        delta = field(row, ("cost_delta_usd", "delta_cost_usd", "cost_difference_usd", "cost_delta", "delta_usd"))
        assert type(delta) in (int, float) and math.isfinite(delta)
        # Either sign convention is acceptable when the README explains it.
        assert abs(delta) == pytest.approx(abs(expected_cost - reported), abs=1e-10)


def test_d3_socket_denied_uv_replay(recorded, tmp_path):
    wrapper = tmp_path / "offline_replay.py"
    wrapper.write_text('''import runpy, sys
def deny(event, args):
    if event.startswith("socket.") or event in {
        "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork"
    }:
        raise RuntimeError("Replay tried network/process access: " + event)
sys.addaudithook(deny)
sys.argv = ["effort.py", "replay"]
runpy.run_path("effort.py", run_name="__main__")
''', encoding="utf-8")
    output = success(["uv", "run", "--offline", "python", wrapper], DEMO)
    assert_table(output, recorded[1])


def test_d3_recording_dates_and_files(recorded):
    document, recorded_rows = recorded
    run_date = iso_date(document["run_date"])
    assert run_date <= datetime.now(timezone.utc).date()
    starts = []
    for cli, effort in RUNS:
        read(DEMO / f"recorded/raw/{cli}-{effort}.jsonl")
        meta = load(DEMO / f"recorded/raw/{cli}-{effort}.meta.json")
        start, end = timestamp(meta["started_at"]), timestamp(meta["ended_at"])
        assert run_date <= start.date() <= end.date() <= datetime.now(timezone.utc).date()
        starts.append(start)
        assert re.search(r"\d+\.\d+", recorded_rows[cli, effort]["cli_version"])
    assert min(starts).date() == run_date, "run_date is the first run's UTC date"
    assert document["run_date"] in read(DEMO / "README.md")


def test_a1_runbook_sections_and_exact_expected_table(replay, recorded):
    parts = sections()
    assert re.search(r"\b\d{1,2}:\d{2}\b", parts["timing"])
    assert re.search(r"[^\n?]+\?", parts["predict"])
    for line in table_lines(replay, recorded[1]).values():
        assert line in parts["expected"], f"Paste this replay row verbatim: {line}"


@pytest.mark.parametrize("cwd_kind", ("demo", "session", "repo"))
def test_a1_reset_in_disposable_clone(tmp_path, cwd_kind):
    parts = sections()
    blocks = re.findall(r"```(?:sh|bash|shell|console)?\s*\n(.*?)```", parts["reset"], re.S)
    assert blocks, "Reset needs a fenced command block"
    command = "\n".join(blocks)
    assert str(REPO) not in command, "Reset must be checkout-relative"
    assert re.search(r"discard|delete|destroy|lose|loss|remov", parts["reset"], re.I), "Warn about discarded work"
    clone = tmp_path / "disposable repo with spaces"
    success(["git", "clone", "--local", "--no-hardlinks", REPO, clone], tmp_path)
    success(["git", "checkout", "-b", "test/effort-reset"], clone)
    destination = clone / RELATIVE
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(DEMO, destination, ignore=shutil.ignore_patterns("work", "__pycache__", ".pytest_cache"))
    # Implementations may still be uncommitted when the engine checks them.
    # Snapshot ONLY this demo in the disposable clone, never the worktree.
    success(["git", "config", "user.email", "acceptance@example.invalid"], clone)
    success(["git", "config", "user.name", "Disposable acceptance fixture"], clone)
    success(["git", "add", "-f", "--", RELATIVE], clone)
    success(["git", "commit", "--allow-empty", "-m", "Reset test fixture"], clone)
    outside = [clone / "sessions/01-fundamentals/.venv/sentinel",
               clone / "setup/node_modules/sentinel",
               destination.parent / "effort-reset-sibling/untracked.txt"]
    for path in outside:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserve me", encoding="utf-8")
    dirty = destination / "work/nested/cache.bin"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("dirty run", encoding="utf-8")
    original = (destination / "prompt.txt").read_bytes()
    (destination / "prompt.txt").write_text("uncommitted change", encoding="utf-8")
    cwd = {"demo": destination, "session": clone / "sessions/01-fundamentals", "repo": clone}[cwd_kind]
    success(["bash", "-eu", "-c", command], cwd)
    assert success(["git", "status", "--short", "--ignored", "--untracked-files=all", "--", RELATIVE], clone) == ""
    assert (destination / "prompt.txt").read_bytes() == original
    assert not (destination / "work").exists()
    for path in outside:
        assert path.read_text(encoding="utf-8") == "preserve me", f"Reset damaged {path}"


def test_a2_models_prices_dates_and_documentation(recorded):
    document, recorded_rows = recorded
    price_block = document["prices"]
    assert price_block == load(DEMO / "prices.json"), "Ship the actual pricing snapshot used for the recording"
    as_of = iso_date(price_block["as_of"])
    last_date = max(timestamp(load(DEMO / f"recorded/raw/{cli}-{effort}.meta.json")["ended_at"]).date()
                    for cli, effort in RUNS)
    assert as_of <= last_date
    sources(price_block)
    readme = read(DEMO / "README.md")
    assert price_block["as_of"] in readme and document["run_date"] in readme
    assert re.search(r"million|1\s*M\b|MTok", readme, re.I), "Label price units"
    for cli, effort in RUNS:
        row = recorded_rows[cli, effort]
        model = row["model"]
        assert isinstance(model, str) and model.strip() and normalized(model) not in {"default", "unknown", "na"}
        raw = events_at(DEMO / f"recorded/raw/{cli}-{effort}.jsonl")
        meta = load(DEMO / f"recorded/raw/{cli}-{effort}.meta.json")
        if cli == "claude":
            usage = decode(raw, cli)[4]
            assert any(name == model or name.startswith(model + "-") for name in usage), "Requested Claude model must match usage"
            models = list(usage)
        else:
            assert option(meta["argv"], "-m") == model
            models = [model]
        for used_model in models:
            assert used_model in readme, f"Runbook must name usage model {used_model}"
            # Price evidence must be local to the named model's paragraph/table
            # row/block, rather than matching an unrelated number elsewhere.
            blocks = re.split(r"\n\s*\n", readme)
            relevant = "\n".join(block for block in blocks if used_model in block)
            for rate in rates(price_block, used_model, cli).values():
                assert has_number(relevant, rate), f"Runbook missing {used_model} price {rate}"
    urls = re.findall(r"https://[^\s<>\])`]+", readme)
    assert any("effort" in url and ("claude" in url or "anthropic" in url) for url in urls)
    assert any("config" in url and ("openai" in url or "codex" in url) for url in urls)
    assert "model_reasoning_effort" in readme


STUB = '''#!{python}
import json, os, sys, time
from pathlib import Path
cli = Path(sys.argv[0]).name
args = sys.argv[1:]
if args == ["--version"]:
    print(cli + " 9.8.7-test")
    raise SystemExit(0)
def option(flag):
    return args[args.index(flag) + 1]
if cli == "claude":
    effort = option("--effort")
else:
    setting = next(value for value in args if value.startswith("model_reasoning_effort="))
    effort = setting.split("=", 1)[1].strip(chr(34) + chr(39))
entry = dict(cli=cli, effort=effort, argv=[cli] + args, cwd=os.getcwd(),
             entries=os.listdir(), prompt=sys.stdin.read())
with open(os.environ["EFFORT_STUB_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry) + "\\n")
time.sleep(0.02)
payloads = json.loads(Path(os.environ["EFFORT_STUB_PAYLOADS"]).read_text())
for event in payloads[cli + "-" + effort]:
    print(json.dumps(event), flush=True)
'''


def fixture_prices(destination, models):
    """Preserve the implementer's price layout while substituting test rates."""
    block = copy.deepcopy(load(DEMO / "prices.json"))
    nodes = price_nodes(block)
    claude_key = next((key for key in nodes if key.startswith(DEFAULTS["claude"])), None)
    assert claude_key, "Prices must cover the requested Claude model (possibly dated)"
    assert DEFAULTS["codex"] in nodes
    templates = {"claude": nodes[claude_key], "codex": nodes[DEFAULTS["codex"]]}
    specs = [("claude", models["claude"], {"input": 4, "output": 18, "cache_write_5m": 5, "cache_read": .4}),
             ("claude", "fixture-auxiliary", {"input": 2, "output": 8, "cache_write_5m": 2.5, "cache_read": .2}),
             ("codex", models["codex"], {"input": 3, "output": 15, "cached_input": .3})]
    for cli, model, values in specs:
        parent, template = templates[cli]
        replacement = copy.deepcopy(template)
        for name, value in values.items():
            names = {normalized(alias) for alias in RATE_ALIASES[name]}
            keys = [key for key in replacement if normalized(key) in names]
            assert keys, f"Pricing snapshot needs {name} for {cli}"
            for key in keys:
                replacement[key] = value
        parent[model] = replacement
    (destination / "prices.json").write_text(json.dumps(block), encoding="utf-8")
    return block


def live_payloads(profile, models, optimum):
    payloads, expected = {}, {}
    for cli, effort in sorted(RUNS):
        factor = (profile + 1) * (1 if effort == "low" else 3)
        if profile == 0:
            text = {("claude", "low"): f"ANSWER: {optimum + 11}\nANSWER: {optimum}",
                    ("claude", "high"): f"ANSWER: {optimum}\nANSWER: {optimum + 7}",
                    ("codex", "low"): "I do not have a final answer.",
                    ("codex", "high"): f"ANSWER: {optimum}"}[cli, effort]
        else:
            text = {("claude", "low"): f"ANSWER: {optimum}\nANSWER: not-an-integer",
                    ("claude", "high"): f"ANSWER: {optimum}",
                    ("codex", "low"): f"ANSWER: {optimum - 1}",
                    ("codex", "high"): f"ANSWER: {optimum}"}[cli, effort]
        if cli == "claude":
            usage = {
                models[cli]: {"inputTokens": 100 * factor, "outputTokens": 50 * factor,
                              "cacheCreationInputTokens": 20 * factor, "cacheReadInputTokens": 30 * factor},
                "fixture-auxiliary": {"inputTokens": 40 * factor, "outputTokens": 10 * factor,
                                      "cacheCreationInputTokens": 8 * factor, "cacheReadInputTokens": 12 * factor},
            }
            # Hand arithmetic, independent of cost_from_raw and implementation.
            cost = factor * (100 * 4 + 20 * 5 + 30 * .4 + 50 * 18
                             + 40 * 2 + 8 * 2.5 + 12 * .2 + 10 * 8) / 1_000_000
            reported = cost + .000007
            init_tools = ["Bash"] if profile == 1 and effort == "low" else []
            tool_calls = int(profile == 1 and effort == "high")
            content = [{"type": "text", "text": text}]
            if tool_calls:
                content.insert(0, {"type": "tool_use", "id": "fixture-tool", "name": "Bash", "input": {"command": "true"}})
            events = [
                {"type": "system", "subtype": "init", "tools": init_tools, "model": models[cli]},
                {"type": "assistant", "message": {"role": "assistant", "content": content}},
                {"type": "result", "subtype": "success", "is_error": False, "result": text,
                 "modelUsage": usage, "total_cost_usd": reported,
                 # Aggregated usage included to catch parsers that price it twice.
                 "usage": {"input_tokens": 140 * factor, "output_tokens": 60 * factor,
                           "cache_creation_input_tokens": 28 * factor, "cache_read_input_tokens": 42 * factor}},
            ]
            token_counts = {"input": 140 * factor, "output": 60 * factor,
                            "cache_read": 42 * factor, "cache_write": 28 * factor,
                            "cached_input": 0, "reasoning_output": 0}
            pure = not tool_calls and not init_tools
        else:
            cost = factor * ((200 - 30) * 3 + 30 * .3 + 70 * 15) / 1_000_000
            reported = None
            tool_calls = int((profile == 0 and effort == "high") or (profile == 1 and effort == "low"))
            events = [{"type": "thread.started", "thread_id": "fixture-thread"},
                      {"type": "turn.started"},
                      {"type": "item.completed", "item": {"id": "reason", "type": "reasoning", "text": "brief reasoning"}},
                      {"type": "turn.completed", "usage": {
                          "input_tokens": 120 * factor, "cached_input_tokens": 20 * factor,
                          "output_tokens": 40 * factor, "reasoning_output_tokens": 15 * factor}},
                      {"type": "turn.started"}]
            if tool_calls:
                # The same command has started/completed events; count one call.
                for event_type, status in (("item.started", "in_progress"), ("item.completed", "completed")):
                    events.append({"type": event_type, "item": {"id": "command", "type": "command_execution",
                                   "command": "true", "status": status, "exit_code": 0, "aggregated_output": ""}})
            events += [{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": text}},
                       {"type": "turn.completed", "usage": {
                           "input_tokens": 80 * factor, "cached_input_tokens": 10 * factor,
                           "output_tokens": 30 * factor, "reasoning_output_tokens": 8 * factor}}]
            token_counts = {"input": 200 * factor, "output": 70 * factor, "cache_read": 0,
                            "cache_write": 0, "cached_input": 30 * factor, "reasoning_output": 23 * factor}
            pure = not tool_calls
        payloads[f"{cli}-{effort}"] = events
        expected[cli, effort] = dict(model=models[cli], tokens=token_counts, cost_usd=cost,
                                    reported_cost_usd=reported, answer=answer(text), correct=answer(text) == optimum,
                                    tool_calls=tool_calls, pure_reasoning=pure)
    return payloads, expected


def sandbox_live(tmp_path, profile=0, overrides=False):
    read(DEMO / "effort.py")
    destination = tmp_path / "standalone session/cursus/demos/effort"
    shutil.copytree(DEMO, destination, ignore=shutil.ignore_patterns("work", "__pycache__", ".pytest_cache"))
    caller = tmp_path / "unrelated caller"
    caller.mkdir()
    models = {"claude": "fixture-claude", "codex": "fixture-codex"} if overrides else DEFAULTS.copy()
    price_block = fixture_prices(destination, models)
    payloads, expected = live_payloads(profile, models, puzzle()[3])
    payload_path = tmp_path / "payloads.json"
    payload_path.write_text(json.dumps(payloads), encoding="utf-8")
    bin_dir = tmp_path / "stub bin"
    bin_dir.mkdir()
    for cli in ("claude", "codex"):
        stub = bin_dir / cli
        stub.write_text(STUB.format(python=sys.executable), encoding="utf-8")
        stub.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = child_env(PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                    EFFORT_STUB_LOG=str(log), EFFORT_STUB_PAYLOADS=str(payload_path))
    flags = ["--claude-model", models["claude"], "--codex-model", models["codex"]] if overrides else []
    return destination, caller, env, log, payload_path, payloads, expected, price_block, flags


@pytest.mark.parametrize("profile", (0, 1))
def test_d2_stub_live_accounting_scoring_isolation_and_overrides(tmp_path, profile):
    destination, caller, env, log, _, payloads, expected, prices, flags = sandbox_live(
        tmp_path, profile, overrides=bool(profile))
    out = tmp_path / "captured output"
    output = success([sys.executable, destination / "effort.py", "live", "--cli", "both", "--out", out, *flags], caller, env)
    document = load(out / "results.json")
    observed = rows(document)
    assert document["prices"] == prices
    calls = events_at(log)
    assert len(calls) == 4 and {(call["cli"], call["effort"]) for call in calls} == RUNS
    assert len({call["cwd"] for call in calls}) == 4, "Fresh directory for every effort run"
    prompt = read(DEMO / "prompt.txt")
    for call in calls:
        identity = (call["cli"], call["effort"])
        row, wanted = observed[identity], expected[identity]
        assert_invocation(call["argv"], identity[0], identity[1], wanted["model"])
        cwd = Path(call["cwd"])
        assert not cwd.is_relative_to(REPO) and not cwd.is_relative_to(destination)
        assert call["entries"] == [], "Models must see a completely empty directory"
        assert not cwd.exists(), "Delete temporary reasoning directory in finally"
        if identity[0] == "codex":
            assert Path(option(call["argv"], "-C")) == cwd
        assert call["prompt"] == prompt, "Render the same parcel prompt for every CLI and effort"
        assert counters(row, identity[0]) == wanted["tokens"]
        assert row["model"] == wanted["model"]
        assert row["answer"] == wanted["answer"] and type(row["correct"]) is bool
        assert row["correct"] == wanted["correct"]
        assert row["tool_calls"] == wanted["tool_calls"] and type(row["pure_reasoning"]) is bool
        assert row["pure_reasoning"] == wanted["pure_reasoning"]
        finite(row["wall_seconds"], positive=True)
        assert finite(row["cost_usd"]) == pytest.approx(wanted["cost_usd"], rel=1e-9, abs=1e-12)
        if identity[0] == "claude":
            assert row["reported_cost_usd"] == wanted["reported_cost_usd"]
            delta = field(row, ("cost_delta_usd", "delta_cost_usd", "cost_difference_usd", "cost_delta", "delta_usd"))
            assert abs(delta) == pytest.approx(.000007, abs=1e-12)
        raw_path = out / f"raw/{identity[0]}-{identity[1]}.jsonl"
        assert events_at(raw_path) == payloads[f"{identity[0]}-{identity[1]}"]
        expected_raw = "".join(json.dumps(event) + "\n" for event in payloads[f"{identity[0]}-{identity[1]}"])
        assert raw_path.read_text() == expected_raw, "Keep raw stdout verbatim"
        meta = load(out / f"raw/{identity[0]}-{identity[1]}.meta.json")
        assert meta["prompt_sha256"] == hashlib.sha256((DEMO / "prompt.txt").read_bytes()).hexdigest()
        assert meta["cwd_kind"] == "tempdir-outside-repo" and meta["exit_code"] == 0
        assert row["cli_version"] == meta["cli_version"] == identity[0] + " 9.8.7-test"
        assert meta["wall_seconds"] == row["wall_seconds"]
        duration = (timestamp(meta["ended_at"]) - timestamp(meta["started_at"])).total_seconds()
        assert abs(duration - meta["wall_seconds"]) <= 1
        assert_invocation(meta["argv"], *identity, wanted["model"])
    assert_table(output, observed)
    assert not (caller / "work").exists()


@pytest.mark.parametrize("cli", ("claude", "codex"))
def test_d2_cli_selection_and_script_relative_default_output(tmp_path, cli):
    destination, caller, env, log, *_ = sandbox_live(tmp_path)
    success([sys.executable, destination / "effort.py", "live", "--cli", cli], caller, env)
    calls = events_at(log)
    assert len(calls) == 2 and {(call["cli"], call["effort"]) for call in calls} == {(cli, "low"), (cli, "high")}
    document = load(destination / "work/results.json")
    run_list = field(document, ("runs", "results", "rows"))
    assert {(row["cli"], row["effort"]) for row in run_list} == {(cli, "low"), (cli, "high")}
    assert not (caller / "work").exists()


def test_d2_oracle_recomputes_when_capacity_changes(tmp_path):
    destination, caller, env, log, payload_path, _, _, _, _ = sandbox_live(tmp_path)
    prompt, parcels, capacity, optimum = puzzle()
    feasible = []
    for bits in itertools.product((0, 1), repeat=len(parcels)):
        feasible.append((sum(weight for take, (weight, _) in zip(bits, parcels) if take),
                         sum(value for take, (_, value) in zip(bits, parcels) if take)))
    alternatives = [(limit, max(value for weight, value in feasible if weight <= limit))
                    for limit in range(1, sum(weight for weight, _ in parcels) + 1)]
    alternatives = [(limit, value) for limit, value in alternatives if value != optimum]
    assert alternatives, "The puzzle must have an optimum that depends on capacity"
    changed_capacity, changed_optimum = next(((limit, value) for limit, value in alternatives
                                             if len(str(limit)) == len(str(capacity))), alternatives[0])
    # Edit literal assignments structurally, without relying on the oracle's
    # function name or the name of the capacity constant. Only disposable files.
    script = destination / "effort.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    changed = 0
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant):
            if type(node.value.value) is int and node.value.value == capacity:
                node.value = ast.copy_location(ast.Constant(changed_capacity), node.value)
                changed += 1
    assert changed, "Capacity must be literal puzzle data"
    script.write_text(ast.unparse(tree) + "\n", encoding="utf-8")
    match = re.search(r"\bcapacity\b[^\n\d]{0,80}(\d+)\b", prompt, re.I)
    changed_prompt = prompt[:match.start(1)] + str(changed_capacity) + prompt[match.end(1):]
    (destination / "prompt.txt").write_text(changed_prompt, encoding="utf-8")
    payloads, expected = live_payloads(0, DEFAULTS, changed_optimum)
    payload_path.write_text(json.dumps(payloads), encoding="utf-8")
    out = destination / "work"
    success([sys.executable, script, "live", "--cli", "both"], caller, env)
    observed = rows(load(out / "results.json"))
    for identity, row in observed.items():
        assert row["answer"] == expected[identity]["answer"]
        assert row["correct"] == expected[identity]["correct"], "Oracle must solve the changed instance"
    calls = events_at(log)
    assert len(calls) == 4 and all(call["prompt"] == changed_prompt for call in calls)


@pytest.mark.parametrize("bad_counter", ("cached_input_tokens", "reasoning_output_tokens"))
def test_d2_rejects_noninclusive_codex_usage(tmp_path, bad_counter):
    destination, caller, env, log, payload_path, payloads, *_ = sandbox_live(tmp_path)
    events = payloads["codex-low"]
    usage = next(event["usage"] for event in events if event["type"] == "turn.completed")
    inclusive = "input_tokens" if bad_counter == "cached_input_tokens" else "output_tokens"
    usage[bad_counter] = usage[inclusive] + 1
    payload_path.write_text(json.dumps(payloads), encoding="utf-8")
    result = run([sys.executable, destination / "effort.py", "live", "--cli", "codex"], caller, env)
    assert result.returncode != 0, "Invalid inclusive counters must reject the capture"
    calls = events_at(log)
    assert calls, "The parser must actually consume the invalid event"
    assert all(not Path(call["cwd"]).exists() for call in calls), "Clean temp directories on failure too"
    assert re.search(r"cache|reason|usage|token", result.stderr + result.stdout, re.I)


def test_d2_rejects_unpriced_auxiliary_claude_model(tmp_path):
    destination, caller, env, log, payload_path, payloads, *_ = sandbox_live(tmp_path)
    result_event = next(event for event in payloads["claude-low"] if event["type"] == "result")
    result_event["modelUsage"]["no-price-for-this-model"] = result_event["modelUsage"].pop("fixture-auxiliary")
    payload_path.write_text(json.dumps(payloads), encoding="utf-8")
    result = run([sys.executable, destination / "effort.py", "live", "--cli", "claude"], caller, env)
    assert result.returncode != 0, "Never silently omit an auxiliary model's cost"
    calls = events_at(log)
    assert calls and all(not Path(call["cwd"]).exists() for call in calls)
    assert re.search(r"price|rate|model", result.stderr + result.stdout, re.I)


def test_d2_greedy_density_misses_exhaustive_optimum():
    _, parcels, capacity, optimum = puzzle()
    remaining, greedy = capacity, 0
    for weight, value in sorted(parcels, key=lambda item: item[1] / item[0], reverse=True):
        if weight <= remaining:
            greedy += value
            remaining -= weight
    assert greedy < optimum, "Choose a parcel instance that rewards combinatorial thinking"


def test_d3_default_invocation_is_offline_replay(recorded, replay):
    output = success(["uv", "run", "--offline", "effort.py"], DEMO)
    assert table_lines(output, recorded[1]) == table_lines(replay, recorded[1])


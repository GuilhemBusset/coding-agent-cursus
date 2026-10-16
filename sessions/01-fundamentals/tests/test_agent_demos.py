"""Issue 41 acceptance checks, written before the implementation.

Run from the session with ``uv run pytest tests/test_agent_demos.py -q -k
test_<ledger>_``. No check invokes a real agent or opens a network connection.
The CLI interface, filenames and native event formats in the agreed design are
contracts; implementation function names are not. Metadata may use the common
field aliases below, with per-arm fields in an ``arms`` mapping (or list of
named arms). Full pre/post states are essential: a claim of green is not proof.

Recording provenance and teaching quality require the independent review.
A2 widget playback is deliberately NOT asserted here: it waits for #42/#47.
Codex JSON has no elapsed-time counter, so comparison seconds are independently
computed from the arm's UTC start/end metadata; usage and calls come from raw
events. This is the only reproducible reading of the design's timing check.
"""

import ast
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

import pytest


SESSION = Path(__file__).resolve().parents[1]
REPO = SESSION.parents[1]
DEMO = SESSION / "cursus/demos/agent"
PACK = SESSION / "exercises/p00-lab"
CLIS = ("claude", "codex")
DEMOS = {"loop": "loop.md", "plan": "plan-first.md", "bomb": "context-bomb.md"}
PROPRIETARY = {"gurobipy", "cplex", "docplex", "xpress", "mosek", "knitro", "baron"}
MISSING = object()
GUARD_BIN = None
NETWORK_GUARD = """import sys
def guard(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('acceptance: socket/network access forbidden')
sys.addaudithook(guard)
"""


@pytest.fixture(scope="module", autouse=True)
def forbid_live_agents():
    """An accidental CLI call fails locally instead of using an account."""
    global GUARD_BIN
    with tempfile.TemporaryDirectory(prefix="issue41-cli-guard-") as tmp:
        GUARD_BIN = Path(tmp)
        (GUARD_BIN / "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
        marker = GUARD_BIN / "called"
        for cli in CLIS:
            path = GUARD_BIN / cli
            path.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n"
                            f"Path({str(marker)!r}).write_text('unexpected agent invocation')\n"
                            "raise SystemExit(97)\n", encoding="utf-8")
            path.chmod(0o755)
        yield
        GUARD_BIN = None
        assert not marker.exists(), "A reset, replay or parser probe attempted to call an agent CLI"


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"Empty artifact: {path}"
    return text


def load(path):
    data = json.loads(read(path))
    assert isinstance(data, dict), f"Expected JSON object: {path}"
    return data


def norm(value):
    text = str(value).casefold().replace("δ", "delta").replace("∆", "delta")
    return re.sub(r"[^a-z0-9]", "", text)


def field(data, *names, default=MISSING):
    assert isinstance(data, dict), f"Expected metadata object, got {type(data).__name__}"
    matches = [v for k, v in data.items() if norm(k) in {norm(n) for n in names}]
    if not matches:
        assert default is not MISSING, f"Missing metadata field {names}; keys: {list(data)}"
        return default
    assert all(v == matches[0] for v in matches), f"Conflicting fields {names}"
    return matches[0]


def nonempty(value):
    assert isinstance(value, str) and value.strip(), f"Expected nonempty text, got {value!r}"
    return value


def number(value):
    assert type(value) in (int, float) and math.isfinite(value) and value >= 0
    return value


def digest(content):
    return hashlib.sha256(content if isinstance(content, bytes) else content.encode()).hexdigest()


def utc(value):
    result = datetime.fromisoformat(nonempty(value).replace("Z", "+00:00"))
    assert result.tzinfo is not None and result.utcoffset().total_seconds() == 0, value
    return result


def start(meta):
    return utc(field(meta, "started_at", "start_utc", "started_utc", "utc_start"))


def end(meta):
    return utc(field(meta, "ended_at", "end_utc", "ended_utc", "utc_end"))


def stem(demo, cli, run):
    return f"{demo}-{cli}-run{run}"


def metadata(demo, cli, run):
    return load(DEMO / "recorded" / f"{stem(demo, cli, run)}.meta.json")


def arms(meta):
    value = field(meta, "arms", default={})
    if isinstance(value, list):
        value = {field(row, "arm", "name"): row for row in value}
    assert isinstance(value, dict)
    return value


def arm(meta, name):
    value = field(arms(meta), name)
    assert isinstance(value, dict)
    return value


def effective(meta, row):
    return {**meta, **row}


def state(meta, phase):
    return field(meta, f"{phase}_state", phase)


def hashes(snapshot):
    value = field(snapshot, "file_hashes", "files_sha256", "sha256", "hashes", "files")
    assert isinstance(value, dict) and value
    assert all(isinstance(k, str) and not Path(k).is_absolute() and ".." not in Path(k).parts
               and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in value.items())
    return value


def model_text(snapshot):
    return nonempty(field(snapshot, "p00_model.py", "p00_model_py", "model_text", "p00_model", "p00_model_text"))


def pytest_code(snapshot):
    value = field(snapshot, "pytest_exit_code", "pytest_returncode")
    assert type(value) is int
    return value


def failures(snapshot):
    result = field(snapshot, "failing_test_ids", "failed_test_ids", "failing_tests")
    assert isinstance(result, list) and all(isinstance(s, str) for s in result)
    return result


def changed(snapshot):
    result = field(snapshot, "diff", "changed_files", "diff_name_only", "git_diff_name_only")
    if isinstance(result, dict):
        result = field(result, "name_only", "changed_files", "files")
    if isinstance(result, str):
        result = result.strip().splitlines()
    assert isinstance(result, list) and all(isinstance(p, str) for p in result)
    return sorted(result)


def env(**overrides):
    result = os.environ.copy()
    for key in list(result):
        if key.startswith("GIT_") or key in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}:
            result.pop(key)
    result.update(UV_OFFLINE="1", UV_NO_SYNC="1", PYTHONDONTWRITEBYTECODE="1",
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", GIT_CONFIG_GLOBAL=os.devnull,
                  GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    if GUARD_BIN is not None:
        result["PATH"] = str(GUARD_BIN) + os.pathsep + result.get("PATH", "")
        result["PYTHONPATH"] = str(GUARD_BIN)
    result.update(overrides)
    return result


def process(argv, cwd=None, environ=None, timeout=60):
    return subprocess.run([str(s) for s in argv], cwd=cwd, env=environ or env(),
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def okay(result):
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    return result.stdout


def exported(folder):
    okay(process([sys.executable, PACK / "export.py", "--bug", "flipped-sense", "--out", folder]))
    return folder


def tracked(folder):
    names = okay(process(["git", "-C", folder, "ls-files", "-z"])).split("\0")
    return {name: digest((folder / name).read_bytes()) for name in names if name}


def contract(folder):
    # The session interpreter already has highspy/pytest. Never install or sync
    # in these independent repair checks, and never run the recorded command.
    suite = "tests/test_p00_contract.py" if (folder / "tests/test_p00_contract.py").exists() else "test_p00_contract.py"
    return process([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", suite], folder)


@pytest.fixture(scope="module")
def baseline():
    # export.py deliberately forbids paths inside the checkout, even if a
    # caller has configured pytest's basetemp there.
    with tempfile.TemporaryDirectory(prefix="issue41-contract-") as tmp:
        folder = exported(Path(tmp) / "p00")
        red = contract(folder)
        assert red.returncode == 1, red.stdout + red.stderr
        assert "test_objective_contract" in red.stdout and "FAILED" in red.stdout
        yield folder, tracked(folder), red


def repair_proof(pre, post, baseline, tmp_path):
    source, original, _ = baseline
    assert hashes(pre) == original, "Recording did not start on the fresh flipped-sense export"
    assert model_text(pre) == (source / "p00_model.py").read_text()
    assert pytest_code(pre) == 1 and any("test_objective_contract" in s for s in failures(pre))
    assert pytest_code(post) == 0 and failures(post) == []
    repaired = model_text(post)
    post_hashes = hashes(post)
    assert set(post_hashes) == set(original), "Files added/removed outside the permitted repair"
    assert sorted(k for k in original if original[k] != post_hashes[k]) == ["p00_model.py"]
    assert changed(post) == ["p00_model.py"]
    assert digest(repaired) == post_hashes["p00_model.py"]
    folder = tmp_path / "verify"
    shutil.copytree(source, folder)
    (folder / "p00_model.py").write_text(repaired, encoding="utf-8")
    assert tracked(folder) == post_hashes
    green = contract(folder)
    assert green.returncode == 0 and re.search(r"\b\d+ passed\b", green.stdout), green.stdout + green.stderr
    assert tracked(folder) == post_hashes, "Repair changed protected contract/data during execution"


def raw(demo, cli, run, suffix=None, root=DEMO):
    filename = stem(demo, cli, run) + (f"-{suffix}" if suffix else "") + ".jsonl"
    events = [json.loads(line) for line in read(root / "recorded" / filename).splitlines() if line.strip()]
    assert events and all(isinstance(e, dict) and isinstance(e.get("type"), str) for e in events)
    return events


def content(event):
    return (event.get("message") or {}).get("content", [])


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_content(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("text", value.get("content", "")))
    return ""


def tools(events, cli):
    """Decode native calls/results, not an implementer's normalized summaries.

    Scrubbers may replace IDs. Match duplicate placeholders FIFO, and preserve
    the index of the actual result for the red/edit/green ordering assertion.
    """
    found = []
    if cli == "claude":
        pending = []
        for index, event in enumerate(events):
            if event.get("type") == "assistant":
                for block in content(event):
                    if block.get("type") == "tool_use":
                        row = {"name": block["name"], "input": block.get("input", {}),
                               "index": index, "result_index": None, "output": "", "error": False,
                               "id": block.get("id")}
                        pending.append(row)
                        found.append(row)
            if event.get("type") == "user":
                for block in content(event):
                    if block.get("type") != "tool_result":
                        continue
                    candidates = [r for r in pending if r["id"] == block.get("tool_use_id")]
                    assert candidates, "Orphan Claude tool result"
                    row = candidates[0]
                    pending.remove(row)
                    row.update(output=text_content(block.get("content", "")),
                               error=bool(block.get("is_error")), result_index=index)
    else:
        for index, event in enumerate(events):
            item = event.get("item", {})
            if event.get("type") != "item.completed" or item.get("type") not in {
                "command_execution", "file_change", "mcp_tool_call", "web_search", "tool_call"
            }:
                continue
            found.append({"name": item["type"], "input": item,
                          "index": index, "result_index": index,
                          "output": item.get("aggregated_output", text_content(item.get("result", ""))),
                          "error": item.get("exit_code", 0) != 0 or item.get("status") == "failed"})
    return found


def pytest_result(call):
    payload = json.dumps(call["input"])
    if not re.search(r"\b(?:uv\s+run\s+)?(?:python\S*\s+-m\s+)?pytest\b", payload):
        return None
    output = call["output"]
    if re.search(r"\b(?:[1-9]\d* failed|FAILED\s+\S*test_|FAILURES)\b", output):
        return "red"
    if not call["error"] and re.search(r"\b[1-9]\d* passed\b", output) and not re.search(r"\b[1-9]\d* failed\b", output):
        return "green"
    return None


def loop_sequence(events, cli):
    calls = tools(events, cli)
    def is_read(call):
        payload = json.dumps(call["input"])
        return "p00_model.py" in payload and (
            norm(call["name"]) in {"read", "readfile"} or
            bool(re.search(r"\b(cat|sed|head|tail|rg|nl|awk|more|less|bat|read|read_text|read_bytes|Get-Content)\b", payload)))
    def is_edit(call):
        payload = json.dumps(call["input"])
        return "p00_model.py" in payload and (
            norm(call["name"]) in {"edit", "write", "multiedit", "applypatch", "filechange"} or
            bool(re.search(r"write_text|write_bytes|\.write\(|sed\s+(?:-i|--in-place)|perl\s+-\w*i|"
                           r"\b(?:cp|mv|install)\s|apply_patch|(?:>|tee)\s+[^ ]*p00_model", payload)))
    reads = [c for c in calls if is_read(c)]
    reds = [c for c in calls if pytest_result(c) == "red"]
    edits = [c for c in calls if is_edit(c)]
    greens = [c for c in calls if pytest_result(c) == "green"]
    assert any(r["index"] < f["index"] and f["result_index"] < e["index"] < g["index"]
               for r in reads for f in reds for e in edits for g in greens), (
        "Raw stream must show read p00_model.py → failing pytest result → edit → passing pytest")


TOKEN_NAMES = {
    "input": ("input_tokens", "inputTokens", "input"),
    "output": ("output_tokens", "outputTokens", "output"),
    "cache_read": ("cache_read_input_tokens", "cacheReadInputTokens", "cache_read", "cache_read_tokens"),
    "cache_write": ("cache_creation_input_tokens", "cacheCreationInputTokens", "cache_write", "cache_write_tokens"),
    "cached_input": ("cached_input_tokens", "cached_input"),
    "reasoning_output": ("reasoning_output_tokens", "reasoning_output"),
}


def usage(events, cli):
    if cli == "claude":
        results = [e for e in events if e.get("type") == "result"]
        assert len(results) == 1 and not results[0].get("is_error"), "Need one successful Claude result"
        result = results[0]
        if isinstance(result.get("usage"), dict):
            rows = [result["usage"]]
        else:
            rows = list(result.get("modelUsage", {}).values())
        assert rows
    else:
        assert not any(e.get("type") in {"turn.failed", "error"} for e in events)
        rows = [e["usage"] for e in events if e.get("type") == "turn.completed"]
        assert rows, "Missing Codex turn.completed usage"
    counts = dict.fromkeys(TOKEN_NAMES, 0)
    for row in rows:
        for name, aliases in TOKEN_NAMES.items():
            value = field(row, *aliases, default=0 if name not in {"input", "output"} else MISSING)
            assert type(value) is int and value >= 0
            counts[name] += value
    counts["total"] = counts["input"] + counts["output"]
    if cli == "claude":
        counts["total"] += counts["cache_read"] + counts["cache_write"]
    else:
        assert counts["cached_input"] <= counts["input"]
    return counts


def final_text(events, cli):
    if cli == "claude":
        return "\n".join(e.get("result", "") for e in events if e.get("type") == "result")
    return "\n".join(e.get("item", {}).get("text", "") for e in events
                     if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message")


def usage_matches(row, counts):
    measured = field(row, "usage", "tokens", "token_counts", "token_counters")
    assert isinstance(measured, dict)
    for name, aliases in TOKEN_NAMES.items():
        expected = counts[name]
        actual = field(measured, name, *aliases, default=0 if expected == 0 else MISSING)
        assert actual == expected, f"{name}: recorded {actual} != raw {expected}"
    total = field(measured, "total", "total_tokens", default=counts["total"])
    assert total == counts["total"]


def command(row):
    value = field(row, "command", "argv", "command_line")
    value = shlex.split(value) if isinstance(value, str) else value
    assert isinstance(value, list) and value and all(isinstance(s, str) for s in value)
    return value


def option(argv, name, default=None):
    if name in argv:
        index = argv.index(name)
        assert index + 1 < len(argv), f"Missing argument after {name}"
        return argv[index + 1]
    return next((s[len(name) + 1:] for s in argv if s.startswith(name + "=")), default)


def basic_meta(meta, demo, cli):
    assert field(meta, "demo") == demo and field(meta, "cli", "via") == cli
    for name in ("cli_version", "model", "effort"):
        nonempty(field(meta, name))
    assert field(meta, "model_source") in {"reported", "requested"}
    assert start(meta) <= end(meta)
    codes = [field(meta, name, default=None) for name in ("exit_code", "exit_codes")]
    assert any(code is not None for code in codes), "Missing process exit codes"
    for code in codes:
        if code is None:
            continue
        if isinstance(code, dict):
            assert code and all(type(v) is int and v == 0 for v in code.values())
        else:
            assert type(code) is int and code == 0


def invocation(row, cli, mode="build"):
    argv = command(row)
    assert Path(argv[0]).name == cli
    assert not any(argv[i:i + 2] == ["mcp", "add"] for i in range(len(argv) - 1))
    assert re.fullmatch(r"[0-9a-f]{64}", field(row, "prompt_sha256", "prompt_hash"))
    if cli == "claude":
        assert "-p" in argv and "--strict-mcp-config" in argv
        assert option(argv, "--output-format") == "stream-json" and "--verbose" in argv
        if mode != "bomb":
            assert "--no-session-persistence" in argv
            assert option(argv, "--permission-mode") == ("plan" if mode == "plan" else "acceptEdits")
        if mode == "build":
            assert "uv run pytest" in (option(argv, "--allowedTools") or "")
    else:
        assert "exec" in argv and "--json" in argv
        if mode != "bomb":
            assert "--ephemeral" in argv
            assert option(argv, "--sandbox", option(argv, "-s")) == ("read-only" if mode == "plan" else "workspace-write")
            assert any("approval_policy" in s and "never" in s for s in argv)


def fences(text):
    return re.findall(r"^```[^\n]*\n(.*?)^```", text, flags=re.M | re.S)


def documented_commands(text):
    found = []
    for block in fences(text):
        block = re.sub(r"\\\n\s*", " ", block)
        for line in block.splitlines():
            line = line.strip().removeprefix("$ ")
            if line.startswith("uv run agent_demo.py "):
                args = shlex.split(line, comments=True)[3:]
                assert not any(s in {"&&", ";", "|", ">"} for s in args), "Keep documented demo commands directly executable"
                found.append(args)
    return found


def section(text, title):
    headings = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*#*\s*$", text, re.M))
    for i, match in enumerate(headings):
        if norm(match[2]) == norm(title):
            stop = next((h.start() for h in headings[i + 1:] if len(h[1]) <= len(match[1])), len(text))
            return text[match.end():stop]
    raise AssertionError(f"Missing {title!r} section")


def links(path):
    text = read(path)
    refs = dict(re.findall(r"^\s*\[([^]]+)\]:\s*(\S+)", text, re.M))
    targets = re.findall(r"!?\[[^]]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", text)
    for match in re.finditer(r"\[([^]]+)\]\[([^]]*)\]", text):
        key = match[2] or match[1]
        assert key in refs, f"Undefined reference link {key} in {path}"
        targets.append(refs[key])
    for target in targets:
        parsed = urlsplit(target.strip("<>"))
        if parsed.scheme or parsed.netloc:
            continue
        resolved = path.parent / unquote(parsed.path) if parsed.path else path
        assert resolved.exists(), f"Broken relative link {target!r} in {path}"
        if parsed.fragment and resolved.suffix == ".md":
            headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", read(resolved), re.M)
            ids = {re.sub(r"[^\w\- ]", "", h.lower().replace("`", "")).replace(" ", "-") for h in headings}
            assert unquote(parsed.fragment) in ids, f"Broken heading link {target!r}"
    return targets


def offline_python(tmp_path):
    guard = tmp_path / "network-guard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
    return env(PYTHONPATH=str(guard))


def replay(demo, cli, run, tmp_path, root=DEMO):
    # No agent executable is discoverable. A replay needing a subprocess agent,
    # network or installed CLI fails, rather than accidentally spending tokens.
    isolated = tmp_path / "empty-path"
    isolated.mkdir(exist_ok=True)
    environ = offline_python(tmp_path)
    environ["PATH"] = str(isolated)
    return okay(process([sys.executable, root / "agent_demo.py", "replay", demo,
                         "--via", cli, "--run", str(run)], root, environ))


def reset(demo, work_root):
    # UV_NO_SYNC must not prevent the reset's explicit offline sync.
    environ = env()
    environ.pop("UV_NO_SYNC", None)
    okay(process([sys.executable, DEMO / "agent_demo.py", "reset", demo,
                  "--work-root", work_root], DEMO, environ))
    assert work_root.exists()
    if demo == "bomb":
        candidates = list(work_root.rglob("mcp.json"))
    else:
        candidates = [p for p in work_root.rglob("p00_model.py") if (p.parent / ".git").exists()]
    assert len(candidates) == 1, f"Expected one workspace for {demo}: {candidates}"
    folder = candidates[0].parent
    assert not folder.is_relative_to(REPO)
    return folder


def clean_workspace(folder, demo, baseline):
    if demo == "bomb":
        assert sorted(p.name for p in folder.iterdir()) == ["mcp.json"]
        config = load(folder / "mcp.json")
        assert str(DEMO / "context_bomb.py") in json.dumps(config)
        return {"mcp.json": digest((folder / "mcp.json").read_bytes())}
    assert tracked(folder) == baseline[1]
    assert (folder / ".venv").is_dir(), "Reset must pre-sync the export, offline"
    red = contract(folder)
    assert red.returncode == 1 and "test_objective_contract" in red.stdout
    assert not okay(process(["git", "-C", folder, "status", "--porcelain", "--untracked-files=all"])).strip()
    return tracked(folder)


def table_rows(text):
    """Return Markdown table rows with normalized column names."""
    lines = text.splitlines()
    result = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|") or index + 1 >= len(lines):
            continue
        if not re.fullmatch(r"[\s|:\-]+", lines[index + 1]):
            continue
        headers = [norm(s.strip(" `")) for s in line.strip().strip("|").split("|")]
        for row in lines[index + 2:]:
            if not row.lstrip().startswith("|"):
                break
            cells = [s.strip().strip("`") for s in row.strip().strip("|").split("|")]
            assert len(cells) == len(headers), f"Malformed table row: {row}"
            result.append((row, dict(zip(headers, cells))))
    return result


def table_number(value):
    value = value.replace(",", "").strip().strip("`*")
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(?:s|seconds?|tokens?)?", value)
    assert match, f"Expected measured numeric table cell, got {value!r}"
    return float(match[1])


def recording_table(demo, cli, run, meta):
    text = section(read(DEMO / DEMOS[demo]), "Recorded runs")
    matching = [line for line, _ in table_rows(text) if stem(demo, cli, run) in line]
    assert matching, f"Recorded runs table omits {stem(demo, cli, run)}"
    version = re.search(r"\d+\.\d+(?:\.\d+)?", field(meta, "cli_version"))
    version = version[0] if version else field(meta, "cli_version")
    assert any(version in line and all(str(field(meta, key)) in line for key in ("model", "effort"))
               and start(meta).date().isoformat() in line and field(meta, "model_source") in line
               for line in matching), f"Runbook disagrees with metadata: {stem(demo, cli, run)}"


def test_d1_layout_and_local_links():
    for filename in ("README.md", *DEMOS.values(), "agent_demo.py", "context_bomb.py"):
        read(DEMO / filename)
    targets = links(DEMO / "README.md")
    assert set(DEMOS.values()) <= {urlsplit(t.strip("<>")).path for t in targets}
    for filename in DEMOS.values():
        links(DEMO / filename)


def test_d1_run_requires_an_explicit_supported_harness():
    read(DEMO / "agent_demo.py")
    for arguments in (("run", "loop"), ("run", "loop", "--via", "not-a-harness")):
        result = process([sys.executable, DEMO / "agent_demo.py", *arguments], DEMO)
        assert result.returncode == 2 and "--via" in result.stderr, "argparse must require --via claude|codex"


@pytest.mark.parametrize("demo", DEMOS)
def test_d1_runbook_commands_parse_and_fallback_executes(demo, tmp_path):
    text = read(DEMO / DEMOS[demo])
    commands = documented_commands(text)
    assert ["reset", demo] in commands, "Runbook needs its one simple reset command"
    fallback = documented_commands(section(text, "Fallback"))
    assert any(args[:2] == ["replay", demo] for args in fallback)
    # Execute the script with its own argparse, stopping immediately after a
    # successful parse. This does not require a parser factory or public name.
    probe = """
import argparse, runpy, sys
class Parsed(BaseException): pass
original = argparse.ArgumentParser.parse_args
def parse(self, *args, **kwargs):
    value = original(self, *args, **kwargs)
    raise Parsed()
argparse.ArgumentParser.parse_args = parse
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except Parsed:
    pass
else:
    raise SystemExit('driver did not parse its arguments')
"""
    for args in commands:
        okay(process([sys.executable, "-c", probe, DEMO / "agent_demo.py", *args], DEMO))
    with tempfile.TemporaryDirectory(prefix="issue41-runbook-") as temp:
        reset(demo, Path(temp) / "work")
    for cli in CLIS:
        output = replay(demo, cli, 1, tmp_path)
        assert output.strip() and cli in output.lower()
        assert re.search(r"token|usage", output, re.I), "Fallback must include its token table"
        if demo != "bomb":
            assert re.search(r"failed|FAILED", output) and re.search(r"\bpassed\b", output)
    for args in fallback:
        if args[:2] != ["replay", demo]:
            continue
        environ = offline_python(tmp_path)
        environ["PATH"] = str(tmp_path / "empty-path")
        output = okay(process([sys.executable, DEMO / "agent_demo.py", *args], DEMO, environ))
        assert output.strip(), "The documented fallback command itself must play"


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("run", (1, 2))
def test_d2_loop_raw_sequence_and_independent_repair(cli, run, baseline, tmp_path):
    meta = metadata("loop", cli, run)
    basic_meta(meta, "loop", cli)
    invocation(meta, cli)
    assert field(meta, "prompt_sha256", "prompt_hash") == field(metadata("loop", "claude", 1), "prompt_sha256", "prompt_hash"), (
        "The loop task prompt must be constant across rehearsals and harnesses")
    events = raw("loop", cli, run)
    usage(events, cli)
    loop_sequence(events, cli)
    repair_proof(state(meta, "pre"), state(meta, "post"), baseline, tmp_path)


def test_d2_decoder_rejects_narration_and_wrong_order():
    # Mutation controls: prose claiming red/green and an edit before red cannot
    # count as the actual agent loop, even with a plausible completion message.
    for cli, events in (
        ("claude", [{"type": "result", "result": "Read p00_model.py; pytest failed; fixed; 40 passed"}]),
        ("codex", [{"type": "item.completed", "item": {"type": "agent_message", "text": "pytest FAILED then passed"}}]),
    ):
        with pytest.raises(AssertionError):
            loop_sequence(events, cli)
    calls = [
        {"type": "command_execution", "command": "cat p00_model.py", "aggregated_output": "source", "exit_code": 0},
        {"type": "file_change", "changes": [{"path": "p00_model.py", "kind": "update"}]},
        {"type": "command_execution", "command": "uv run pytest", "aggregated_output": "1 failed, 39 passed", "exit_code": 1},
        {"type": "command_execution", "command": "uv run pytest", "aggregated_output": "40 passed", "exit_code": 0},
    ]
    with pytest.raises(AssertionError):
        loop_sequence([{"type": "item.completed", "item": c} for c in calls], "codex")
    calls[1], calls[2] = calls[2], calls[1]
    loop_sequence([{"type": "item.completed", "item": c} for c in calls], "codex")


def driver_harness(tmp_path):
    """Copy only session-owned runtime files; provide executable fake agents.

    The fake agent actually runs the exported contract and writes a distinct
    valid repair. It supplies native events and arbitrary usage values so the
    driver must observe its subprocess rather than replay a committed example.
    """
    session = tmp_path / "session"
    folder = session / "cursus/demos/agent"
    shutil.copytree(DEMO, folder, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PACK, session / "exercises/p00-lab", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "uv.lock", "mise.toml"):
        shutil.copy2(SESSION / name, session / name)
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.jsonl"
    repair = tmp_path / "repair.py.txt"
    nonce = digest(str(tmp_path))[:19]
    repair.write_text(read(PACK / "p00_model.py") + f"\n# rehearsal {nonce}\n")
    fake = r'''
import hashlib, json, os
from pathlib import Path
import subprocess, sys
cli = Path(sys.argv[0]).name
argv = sys.argv[1:]
def flag(name, default=None):
    if name in argv:
        return argv[argv.index(name) + 1]
    return next((s[len(name)+1:] for s in argv if s.startswith(name+'=')), default)
if '--version' in argv:
    print('99.4.17 (Acceptance stub)')
    raise SystemExit(0)
if argv[:2] in (['auth','status'], ['login','status']):
    print(json.dumps({'loggedIn': True, 'authenticated': True}) if cli == 'claude' else 'Logged in using ChatGPT')
    raise SystemExit(0)
if argv[:2] == ['mcp','list']:
    print('[]')
    raise SystemExit(0)
if '-C' in argv:
    os.chdir(flag('-C'))
elif '--cd' in argv:
    os.chdir(flag('--cd'))
assert Path('p00_model.py').is_file(), 'agent cwd must be the exported task'
if cli == 'claude':
    assert '-p' in argv and flag('--output-format') == 'stream-json' and '--verbose' in argv
    position = argv.index('-p') + 1
    prompt = argv[position] if position < len(argv) and not argv[position].startswith('--') else sys.stdin.read()
else:
    assert 'exec' in argv and '--json' in argv
    # Codex permits the prompt after flags, or as stdin with a '-' argument.
    paired = {'-C','--cd','--sandbox','-s','-m','--model','-c','--config','--output-last-message','-o'}
    candidates = []
    skip = False
    for value in argv[1:]:
        if skip:
            skip = False
        elif value in paired:
            skip = True
        elif not value.startswith('-'):
            candidates.append(value)
    prompt = candidates[-1] if candidates else sys.stdin.read()
    if prompt == '-':
        prompt = sys.stdin.read()
planning = flag('--permission-mode') == 'plan' or flag('--sandbox', flag('-s')) == 'read-only'
model = flag('--model', flag('-m', 'requested-model'))
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
entry = {'cli': cli, 'argv': argv, 'prompt': prompt, 'planning': planning,
         'pre_model': Path('p00_model.py').read_text(), 'cwd': str(Path.cwd()),
         'offline': os.environ.get('UV_OFFLINE'), 'no_sync': os.environ.get('UV_NO_SYNC')}
with open(os.environ['ISSUE41_CALL_LOG'], 'a') as handle:
    handle.write(json.dumps(entry)+'\n')
def emit(value):
    print(json.dumps(value), flush=True)
if cli == 'claude':
    emit({'type':'system','subtype':'init','model':model,'tools':['Read','Bash','Edit'],
          'mcp_servers':[], 'claude_code_version':'99.4.17'})
else:
    emit({'type':'thread.started','thread_id':'acceptance-thread'})
    emit({'type':'turn.started'})
sequence = 0
def tool(name, arguments, output, code=0):
    global sequence
    sequence += 1
    ident = 'call-'+str(sequence)
    if cli == 'claude':
        emit({'type':'assistant','message':{'content':[{'type':'tool_use','id':ident,'name':name,'input':arguments}]}})
        emit({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':ident,'content':output,'is_error':code!=0}]}})
    else:
        item = {'id':ident,'type':'command_execution','command':arguments.get('command','cat p00_model.py'),
                'aggregated_output':output,'exit_code':code,'status':'completed'}
        if name == 'Edit':
            item = {'id':ident,'type':'file_change','status':'completed','changes':[{'path':'p00_model.py','kind':'update'}]}
        emit({'type':'item.completed','item':item})
tool('Read', {'file_path':'p00_model.py'}, Path('p00_model.py').read_text())
plan = 'Inspect the objective contract, repair its objective sense, and run the unchanged suite. '+os.environ['ISSUE41_NONCE']
if not planning:
    suite = 'tests/test_p00_contract.py' if Path('tests/test_p00_contract.py').exists() else 'test_p00_contract.py'
    def check():
        return subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider',suite],capture_output=True,text=True)
    red = check()
    assert red.returncode == 1 and 'test_objective_contract' in red.stdout
    tool('Bash', {'command':'uv run pytest'}, red.stdout, red.returncode)
    Path('p00_model.py').write_text(Path(os.environ['ISSUE41_REPAIR']).read_text())
    tool('Edit', {'file_path':'p00_model.py'}, 'updated')
    green = check()
    assert green.returncode == 0, green.stdout+green.stderr
    tool('Bash', {'command':'uv run pytest'}, green.stdout)
answer = plan if planning else 'The unchanged objective contract now passes.'
if cli == 'claude':
    emit({'type':'result','subtype':'success','is_error':False,'result':answer,'duration_ms':1437,
          'usage':{'input_tokens':137,'output_tokens':29,'cache_read_input_tokens':41,'cache_creation_input_tokens':53},
          'modelUsage':{model:{'inputTokens':137,'outputTokens':29,'cacheReadInputTokens':41,'cacheCreationInputTokens':53}}})
else:
    emit({'type':'item.completed','item':{'id':'answer','type':'agent_message','text':answer}})
    emit({'type':'turn.completed','usage':{'input_tokens':173,'output_tokens':31,'cached_input_tokens':43,'reasoning_output_tokens':11}})
'''
    for cli in CLIS:
        path = binary / cli
        path.write_text(f"#!{sys.executable}\n" + fake)
        path.chmod(0o755)
    environ = env(PATH=str(binary) + os.pathsep + os.environ.get("PATH", ""),
                  ISSUE41_CALL_LOG=str(log), ISSUE41_REPAIR=str(repair), ISSUE41_NONCE=nonce)
    return folder, log, repair, environ


def exercise_driver(demo, cli, tmp_path, baseline):
    folder, log, repair, environ = driver_harness(tmp_path)
    work = tmp_path / "work"
    okay(process([sys.executable, folder / "agent_demo.py", "reset", demo,
                  "--work-root", work], folder, environ))
    candidates = [p for p in work.rglob("p00_model.py") if (p.parent / ".git").exists()]
    assert len(candidates) == 1
    candidates[0].write_text("raise RuntimeError('run must reset before invoking the agent')\n")
    junk = candidates[0].parent / "unexpected-file.txt"
    junk.write_text("dirty rehearsal\n")
    okay(process([sys.executable, folder / "agent_demo.py", "run", demo, "--via", cli,
                  "--record", "--run", "17", "--work-root", work], folder, environ))
    assert not junk.exists(), "run must use the same reset as the documented reset command"
    calls = [json.loads(line) for line in read(log).splitlines()]
    assert {c["cli"] for c in calls} == {cli}
    assert len(calls) == (1 if demo == "loop" else 3)
    assert all(c["offline"] == c["no_sync"] == "1" for c in calls)
    assert all(c["pre_model"] == (baseline[0] / "p00_model.py").read_text() for c in calls)
    meta = load(folder / "recorded" / f"{stem(demo, cli, 17)}.meta.json")
    basic_meta(meta, demo, cli)
    assert "99.4.17" in field(meta, "cli_version")
    names = (None,) if demo == "loop" else ("direct", "plan", "build")
    for suffix, call in zip(names, calls):
        row = meta if suffix is None else arm(meta, suffix)
        assert field(row, "prompt_sha256", "prompt_hash") == digest(call["prompt"])
        events = raw(demo, cli, 17, suffix, folder)
        assert usage(events, cli)["input"] == (137 if cli == "claude" else 173)
        if suffix == "plan":
            assert call["planning"]
            assert hashes(state(row, "pre")) == hashes(state(row, "post"))
            continue
        assert not call["planning"]
        invocation(effective(meta, row), cli)
        assert model_text(state(row, "post")) == repair.read_text()
        loop_sequence(events, cli)
    if demo == "plan":
        assert calls[0]["prompt"] in calls[1]["prompt"], "Plan the same task as the direct arm"
        plan_events = raw(demo, cli, 17, "plan", folder)
        assert final_text(plan_events, cli) in calls[2]["prompt"], "Build must receive the observed plan"
    output = replay(demo, cli, 17, tmp_path, folder)
    assert re.search(r"\b(?:137|260)\b" if cli == "claude" else r"\b(?:173|204)\b", output), (
        "Replay must read the newly observed token counters")


@pytest.mark.parametrize("cli", CLIS)
def test_d2_driver_run_uses_requested_cli_and_records_observed_repair(cli, tmp_path, baseline):
    exercise_driver("loop", cli, tmp_path, baseline)


@pytest.mark.parametrize("cli", CLIS)
def test_d4_driver_plans_and_builds_the_same_task_on_fresh_exports(cli, tmp_path, baseline):
    exercise_driver("plan", cli, tmp_path, baseline)


class RPC:
    def __init__(self):
        read(DEMO / "context_bomb.py")
        self.child = subprocess.Popen([sys.executable, "-u", DEMO / "context_bomb.py"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, env=env(), bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.child.stdout, selectors.EVENT_READ)
        self.buffer = b""

    def send(self, request):
        self.child.stdin.write((json.dumps(request) + "\n").encode())
        self.child.stdin.flush()

    def response(self):
        # A finite timeout also catches servers that mistake JSONL for
        # Content-Length framing. Never block readline on a partial line.
        deadline = time.monotonic() + 10
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            assert remaining > 0 and self.selector.select(remaining), "MCP response timed out"
            part = os.read(self.child.stdout.fileno(), 65536)
            assert part, "MCP exited without a JSON-RPC response"
            self.buffer += part
        line, self.buffer = self.buffer.split(b"\n", 1)
        result = json.loads(line)
        assert result.get("jsonrpc") == "2.0", "stdout must contain only framed JSON-RPC"
        return result

    def call(self, ident, method, params=None):
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        result = self.response()
        assert result.get("id") == ident, "Server must echo each request ID, including non-default IDs"
        return result

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
        tail, _ = self.child.communicate(timeout=5)
        self.selector.close()
        for line in (self.buffer + tail).splitlines():
            if line.strip():
                assert json.loads(line).get("jsonrpc") == "2.0", "MCP stdout contains unframed logging"


def test_d3_context_bomb_stdio_protocol_and_nontrivial_requests():
    rpc = RPC()
    try:
        init = rpc.call("acceptance-init-93", "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "issue41-acceptance", "version": "1"}})
        result = init["result"]
        assert result.get("protocolVersion") and result.get("serverInfo") and "tools" in result.get("capabilities", {})
        instructions = nonempty(result.get("instructions"))
        assert len(instructions) >= 10000, "Initialize must actually carry oversized instructions"
        rpc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = rpc.call(791, "tools/list")["result"]["tools"]
        bomb = next((t for t in listed if t.get("name") == "bomb_status"), None)
        assert bomb and nonempty(bomb.get("description"))
        assert bomb["inputSchema"]["type"] == "object"
        for ident in ("probe-a", 9403):
            response = rpc.call(ident, "tools/call", {"name": "bomb_status", "arguments": {}})["result"]
            payload = response.get("structuredContent")
            if payload is None:
                payload = json.loads(text_content(response.get("content", [])))
            assert isinstance(payload, dict)
            assert {"answer", "context_blocks", "context_characters"} <= payload.keys()
            nonempty(payload["answer"])
            blocks = payload["context_blocks"]
            chars = payload["context_characters"]
            assert type(chars) is int and chars >= 10000
            assert (type(blocks) is int and blocks > 0) or (isinstance(blocks, list) and blocks)
        for ident, method, params in (("unknown-tool", "tools/call", {"name": "not_bomb_status", "arguments": {}}),
                                      ("unknown-method", "not/a/method", {})):
            error = rpc.call(ident, method, params)
            assert "error" in error or error.get("result", {}).get("isError") is True
        rpc.child.stdin.write(b'{"jsonrpc": invalid json}\n')
        rpc.child.stdin.flush()
        error = rpc.response()
        assert error.get("error", {}).get("code") == -32700
        assert rpc.call("still-alive", "tools/list")["result"]["tools"] == listed
    finally:
        rpc.close()


def test_d3_pinned_upstream_and_attribution():
    doc = read(DEMO / "context-bomb.md")
    assert re.search(r"https://github.com/GuilhemBusset/agentic-or-workshop(?:/[^\s)>]+)?", doc)
    assert "workshop/materials/part-01-explorer-paradigm/01-data-explorer/mcp/context-bomb" in doc
    assert re.search(r"\b[0-9a-f]{40}\b", doc), "Pin the source commit, not a mutable branch"
    for filename in ("server.py", "README.md"):
        snapshot = DEMO / "upstream" / f"{filename}.txt"
        read(snapshot)
        assert digest(snapshot.read_bytes()) in doc, f"Missing/checksum-mismatched upstream {filename}"
    upstream = read(DEMO / "upstream/server.py.txt")
    ast.parse(upstream)
    assert "bomb_status" in upstream
    assert all(key in upstream for key in ("answer", "context_blocks", "context_characters"))
    # Whether the attribution/licensing rationale and deviations are accurate
    # is a source-review obligation; structural evidence must still be present.
    assert re.search(r"licen[cs]e|attribution|same.author|authorship", doc, re.I)
    assert re.search(r"deviation|porting|port notes|differences", doc, re.I)


def mcp_evidence(events, cli):
    if cli == "claude":
        init = [e for e in events if e.get("type") == "system" and e.get("subtype") == "init"]
        assert init and isinstance(init[0].get("tools"), list) and isinstance(init[0].get("mcp_servers"), list)
        servers = init[0]["mcp_servers"]
        connected = any("bomb" in json.dumps(s).lower() and
                        (not isinstance(s, dict) or s.get("status") in {"connected", "ready", "running"}) for s in servers)
        discovered = any("bomb_status" in str(t) for t in init[0]["tools"])
        assert connected or discovered, "No raw evidence of the connected bomb server"
    else:
        # Restrict to structured MCP startup/discovery events, never prose
        # from the assistant saying it used a server.
        evidence = [e for e in events if "mcp" in str(e.get("type", "")).lower() or
                    "mcp" in str(e.get("item", {}).get("type", "")).lower() or
                    "mcp" in str(e.get("method", "")).lower()]
        assert any(("bomb_status" in json.dumps(e) or "bomb" in json.dumps(e).lower()) and
                   re.search(r"ready|connect|complete|success|bomb_status", json.dumps(e), re.I)
                   for e in evidence), "No raw Codex MCP startup/discovery evidence"


def token_table(doc, key, arm_name, counts, baseline_counts):
    rows = [row for line, row in table_rows(doc) if key in line and
            any(norm(cell) == norm(arm_name) for cell in row.values())]
    assert rows, f"Missing measured token row for {key}/{arm_name}"
    row = rows[0]
    for name in ("input", "output"):
        cell = field(row, name, *TOKEN_NAMES[name])
        assert table_number(cell) == counts[name]
    for name, aliases in TOKEN_NAMES.items():
        cell = field(row, name, *aliases, default=None)
        if cell is not None:
            assert table_number(cell) == counts[name]
    total = field(row, "total", "total_tokens", default=None)
    if total is not None:
        assert table_number(total) == counts["total"]
    for name, aliases in {**TOKEN_NAMES, "total": ("total_tokens", "tokens")}.items():
        delta_names = [variant for alias in (name, *aliases)
                       for variant in (f"delta_{alias}", f"{alias}_delta")]
        if name == "total":
            delta_names += ["delta", "delta_vs_baseline", "token_delta"]
        cell = field(row, *delta_names, default=None)
        if cell is not None:
            assert table_number(cell) == counts[name] - baseline_counts[name]


def tool_search_disabled(row):
    argv = command(row)
    for index, token in enumerate(argv):
        name = norm(token.split("=", 1)[0])
        if "toolsearch" not in name and "defer" not in name:
            continue
        if "disable" in name:
            return True
        value = token.split("=", 1)[1] if "=" in token else (argv[index + 1] if index + 1 < len(argv) else "")
        if value.lower() in {"0", "false", "off", "no"}:
            return True
    environ = field(row, "env", "environment", default={})
    assert isinstance(environ, dict)
    return any(("toolsearch" in norm(key) or "defer" in norm(key)) and
               (("disable" in norm(key) and str(value).lower() in {"1", "true", "on", "yes"}) or
                ("disable" not in norm(key) and str(value).lower() in {"0", "false", "off", "no"}))
               for key, value in environ.items())


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("run", (1, 2))
def test_d3_bomb_recordings_usage_captures_and_search_findings(cli, run):
    meta = metadata("bomb", cli, run)
    basic_meta(meta, "bomb", cli)
    doc = read(DEMO / "context-bomb.md")
    required = {"without", "with"} | ({"with-tool-search-off"} if cli == "claude" else set())
    assert required <= set(arms(meta))
    baseline_counts = usage(raw("bomb", cli, run, "without"), cli)
    for name in arms(meta):
        row = arm(meta, name)
        invocation(effective(meta, row), cli, "bomb")
        assert field(effective(meta, row), "prompt_sha256", "prompt_hash") == digest("Reply with exactly: OK")
        events = raw("bomb", cli, run, name)
        counts = usage(events, cli)
        assert final_text(events, cli).strip() == "OK"
        usage_matches(row, counts)
        token_table(doc, stem("bomb", cli, run), name, counts, baseline_counts)
        argv = command(effective(meta, row))
        if name != "without":
            mcp_evidence(events, cli)
            if cli == "claude":
                assert option(argv, "--mcp-config")
            else:
                assert any("mcp_servers." in s and "command" in s for s in argv)
        elif cli == "claude":
            assert "--mcp-config" not in argv
        if cli == "codex":
            # Visible global MCP configuration is evidence, not an assertion
            # that the instructor must have no other registered servers.
            servers = field(row, "effective_mcp_servers", "mcp_list", "mcp_servers")
            assert isinstance(servers, (str, list, dict)) and (not isinstance(servers, str) or servers.strip())
    capture = "context" if cli == "claude" else "status"
    method = nonempty(field(meta, "context_method", "capture_method", "status_method"))
    assert re.search(r"print|tmux|tui|pty|context|status", method, re.I)
    for phase in ("before", "after"):
        text = read(DEMO / "recorded" / f"{stem('bomb', cli, run)}-{capture}-{phase}.txt")
        assert re.search(r"token|context|usage|window|remaining|status|model", text, re.I)
        assert not re.search(r"unknown (?:command|skill)|not supported|invalid command", text, re.I)
    version = re.search(r"\d+\.\d+(?:\.\d+)?", field(meta, "cli_version"))
    assert (version[0] if version else field(meta, "cli_version")) in doc and field(meta, "model") in doc
    assert start(meta).date().isoformat() in doc
    # Findings may live in prose; the captured metadata must at least identify
    # the forced-off toggle, including an environment toggle if that CLI uses it.
    if cli == "claude":
        disabled = arm(meta, "with-tool-search-off")
        assert tool_search_disabled(effective(meta, disabled)), "Record the documented toggle actually used"
    assert re.search(r"tool.search|deferr", doc, re.I)
    assert re.search(r"https://(?:code\.claude\.com|docs\.anthropic\.com|claude\.com|platform\.claude\.com|github\.com/anthropics)/", doc)
    assert re.search(r"https://(?:developers\.openai\.com|platform\.openai\.com|github\.com/openai)/", doc)


def plan_from_raw(events, cli, source):
    source = nonempty(source)
    if cli == "claude" and re.search(r"ExitPlanMode", source, re.I):
        candidates = [field(c["input"], "plan", default="") for c in tools(events, cli)
                      if norm(c["name"]) == "exitplanmode"]
        return nonempty(next((s for s in candidates if isinstance(s, str) and s.strip()), ""))
    assert re.search(r"result|agent.message|assistant|final", source, re.I), f"Unrecognized plan source {source!r}"
    return nonempty(final_text(events, cli))


def plan_metrics(meta, cli, planned):
    names = ("plan", "build") if planned else ("direct",)
    counts = dict.fromkeys(TOKEN_NAMES, 0)
    counts["total"] = 0
    calls = 0
    seconds = 0
    for name in names:
        row = arm(meta, name)
        events = raw("plan", cli, field(meta, "run", "run_number"), name)
        usage_ = usage(events, cli)
        for key in counts:
            counts[key] += usage_[key]
        calls += len(tools(events, cli))
        assert start(row) <= end(row)
        seconds += (end(row) - start(row)).total_seconds()
    post = state(arm(meta, "build" if planned else "direct"), "post")
    return {"tokens": counts["total"], "tool_calls": calls, "seconds": seconds,
            "files_changed": len(changed(post)), "pytest_exit_code": pytest_code(post)}


def comparison_row_matches(row, expected):
    for name, aliases in {
        "tokens": ("total_tokens",), "tool_calls": ("tools",),
        "seconds": ("wall_seconds", "elapsed_seconds"),
        "files_changed": ("changed_files", "files"),
        "pytest_exit_code": ("pytest", "final_pytest", "pytest_result"),
    }.items():
        actual = field(row, name, *aliases)
        if name == "files_changed" and isinstance(actual, list):
            actual = len(actual)
        if isinstance(actual, str):
            if name == "pytest_exit_code" and norm(actual) in {"pass", "passed", "green"}:
                actual = 0
            else:
                actual = table_number(actual)
        if name == "seconds":
            assert abs(number(actual) - expected[name]) <= 0.51, "Recorded comparison seconds must agree within rounding"
        else:
            assert actual == expected[name], f"Comparison {name}: {actual} != {expected[name]}"


@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("run", (1, 2))
def test_d4_plan_two_fresh_arms_and_derived_comparison(cli, run, baseline, tmp_path):
    meta = metadata("plan", cli, run)
    basic_meta(meta, "plan", cli)
    assert {"direct", "plan", "build"} <= set(arms(meta))
    direct, planning, build = [arm(meta, n) for n in ("direct", "plan", "build")]
    assert hashes(state(direct, "pre")) == hashes(state(planning, "pre")) == baseline[1]
    assert hashes(state(planning, "pre")) == hashes(state(planning, "post")) == hashes(state(build, "pre"))
    assert model_text(state(planning, "pre")) == model_text(state(planning, "post"))
    assert changed(state(planning, "post")) == [], "Planning call edited the workspace"
    # The task identity hash belongs to the original loop task. Wrapped plan
    # and build prompts have their own invocation hashes, and need not equal it.
    task_hash = field(meta, "task_prompt_sha256", "prompt_sha256")
    assert re.fullmatch(r"[0-9a-f]{64}", task_hash)
    assert task_hash == field(metadata("loop", cli, run), "prompt_sha256", "prompt_hash")
    assert field(direct, "task_prompt_sha256", "prompt_sha256") == task_hash
    for name, row in (("direct", direct), ("plan", planning), ("build", build)):
        invocation(effective(meta, row), cli, "plan" if name == "plan" else "build")
        for key in ("model", "effort"):
            assert field(row, key, default=field(meta, key)) == field(meta, key)
        assert field(row, "task_prompt_sha256", default=task_hash) == task_hash
    source = field(planning, "plan_source", default=field(meta, "plan_source", default=None))
    plan = plan_from_raw(raw("plan", cli, run, "plan"), cli, source)
    saved_plan = field(planning, "plan_text", "plan", default=plan)
    assert saved_plan == plan
    # Exact build-prefix text is agreed in the design. An implementation can
    # retain its full prompt, or prove its construction with the matching hash.
    build_prompt = field(build, "prompt", "prompt_text", default="Implement this plan: " + plan)
    assert plan in build_prompt
    assert digest(build_prompt) == field(build, "prompt_sha256", "prompt_hash")
    for name, row in (("direct", direct), ("build", build)):
        dest = tmp_path / name
        dest.mkdir()
        repair_proof(state(row, "pre"), state(row, "post"), baseline, dest)
    summary = field(meta, "comparison")
    doc = read(DEMO / "plan-first.md")
    for planned, aliases in ((False, ("direct",)), (True, ("planned", "plan_then_build", "plan-build", "plan-first"))):
        name = "planned" if planned else "direct"
        derived = plan_metrics({**meta, "run": run}, cli, planned)
        comparison_row_matches(field(summary, *aliases), derived)
        rows = [row for line, row in table_rows(doc) if stem("plan", cli, run) in line and
                any(norm(cell) in {norm(alias) for alias in aliases} for cell in row.values())]
        assert rows, f"Missing plan comparison table row {cli}/run{run}/{name}"
        comparison_row_matches(rows[0], derived)


@pytest.mark.parametrize("demo", DEMOS)
def test_d5_dirty_reset_restores_content_and_stays_in_workspace(demo, baseline):
    commands = documented_commands(section(read(DEMO / DEMOS[demo]), "Reset"))
    assert ["reset", demo] in commands
    with tempfile.TemporaryDirectory(prefix="issue41-dirty-") as temp:
        root = Path(temp) / "scratch with spaces"
        folder = reset(demo, root)
        expected = clean_workspace(folder, demo, baseline)
        # Random name and sibling sentinel catch a reset hard-coded to a known
        # example or an overly broad rmtree of the requested root's parent.
        sibling = Path(temp) / "must-survive.txt"
        sibling.write_text("outside demo workspace\n")
        junk = folder / ("dirty-" + digest(str(root))[:13])
        junk.write_text("not part of the clean state\n")
        target = folder / ("mcp.json" if demo == "bomb" else "p00_model.py")
        target.write_text("deliberately broken\n")
        restored = reset(demo, root)
        assert clean_workspace(restored, demo, baseline) == expected
        assert not junk.exists() and sibling.read_text() == "outside demo workspace\n"


@pytest.mark.parametrize("demo", DEMOS)
@pytest.mark.parametrize("cli", CLIS)
@pytest.mark.parametrize("run", (1, 2))
def test_d5_metadata_and_runbook_version_model_tables(demo, cli, run):
    meta = metadata(demo, cli, run)
    basic_meta(meta, demo, cli)
    recording_table(demo, cli, run, meta)
    suffixes = (None,) if demo == "loop" else tuple(arms(meta))
    assert suffixes
    for suffix in suffixes:
        row = meta if suffix is None else effective(meta, arm(meta, suffix))
        events = raw(demo, cli, run, suffix)
        model = field(row, "model")
        provenance = field(row, "model_source")
        argv = command(row)
        if cli == "claude":
            assert option(argv, "--effort") == field(row, "effort")
        else:
            effort_settings = [s for s in argv if "model_reasoning_effort=" in s.replace(" ", "")]
            assert effort_settings and any(s.split("=", 1)[1].strip(" \"'") == field(row, "effort")
                                           for s in effort_settings)
        if provenance == "requested":
            assert option(argv, "--model", option(argv, "-m")) == model
        else:
            reported = []
            def collect(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "model" and isinstance(child, str):
                            reported.append(child)
                        elif key == "modelUsage" and isinstance(child, dict):
                            reported.extend(child)
                        collect(child)
                elif isinstance(value, list):
                    for child in value:
                        collect(child)
            collect(events)
            assert model in reported, "A reported model needs raw CLI evidence; otherwise mark it requested"
    # Scrubbing must include IDs, absolute home/work paths, not only prose.
    paths = list((DEMO / "recorded").glob(stem(demo, cli, run) + "*"))
    assert paths
    for path in paths:
        text = read(path)
        assert not re.search(r"/(?:home|Users)/[^/\s\"]+/", text), f"Unscrubbed home path in {path.name}"
        assert str(REPO) not in text
        assert "/tmp/cursus-s1-agent/" not in text
        if path.suffix in {".json", ".jsonl"}:
            values = json.loads(text) if path.name.endswith(".meta.json") else [json.loads(s) for s in text.splitlines() if s.strip()]
            def walk(value, parent=None):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if (key in {"session_id", "thread_id", "uuid", "message_id"} or
                                (key == "id" and parent == "message")) and item is not None:
                            assert isinstance(item, str) and re.fullmatch(r"<[^>]+>", item), f"Unscrubbed {key}"
                        walk(item, key)
                elif isinstance(value, list):
                    for item in value:
                        walk(item, parent)
            walk(values)


@pytest.mark.parametrize("demo", DEMOS)
def test_a1_two_consecutive_resets_are_identical(demo, baseline):
    with tempfile.TemporaryDirectory(prefix="issue41-repeat-") as temp:
        root = Path(temp) / "work"
        first = clean_workspace(reset(demo, root), demo, baseline)
        second = clean_workspace(reset(demo, root), demo, baseline)
        assert first == second, "Compare content identity, never time-dependent git commit IDs"


@pytest.mark.parametrize("demo", DEMOS)
@pytest.mark.parametrize("cli", CLIS)
def test_a1_two_real_rehearsals_clean_start_and_outcome(demo, cli, baseline, tmp_path):
    first, second = [metadata(demo, cli, run) for run in (1, 2)]
    assert end(first) <= start(second), "run2 must follow run1, rather than overlap or reuse it"
    for key in ("cli_version", "model", "effort"):
        assert field(first, key) == field(second, key)
    for run, meta in ((1, first), (2, second)):
        basic_meta(meta, demo, cli)
        if demo == "bomb":
            pre = hashes(state(meta, "pre"))
            assert set(pre) == {"mcp.json"}
            assert pre == hashes(state(first, "pre"))
            required = {"without", "with"} | ({"with-tool-search-off"} if cli == "claude" else set())
            assert required <= set(arms(meta))
            for name in arms(meta):
                events = raw(demo, cli, run, name)
                assert final_text(events, cli).strip() == "OK"
                usage(events, cli)
                row = arm(meta, name)
                assert field(row, "exit_code") == 0
        else:
            rows = [("loop", meta)] if demo == "loop" else [(name, arm(meta, name)) for name in ("direct", "build")]
            for name, row in rows:
                dest = tmp_path / f"run{run}-{name}"
                dest.mkdir()
                repair_proof(state(row, "pre"), state(row, "post"), baseline, dest)


def python_imports(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module.split(".")[0]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            function = node.func
            if ((isinstance(function, ast.Name) and function.id == "__import__") or
                    (isinstance(function, ast.Attribute) and function.attr == "import_module")):
                value = node.args[0].value
                if isinstance(value, str):
                    yield value.split(".")[0]


def recorded_models(meta):
    candidates = [meta, *arms(meta).values()]
    for row in candidates:
        for phase in ("pre", "post"):
            snapshot = field(row, f"{phase}_state", phase, default=None)
            if isinstance(snapshot, dict):
                source = field(snapshot, "p00_model.py", "p00_model_py", "model_text", "p00_model", "p00_model_text", default=None)
                if source:
                    yield source


def test_a3_stdlib_demo_and_no_proprietary_solver_in_export_or_repairs(baseline):
    scripts = list(DEMO.rglob("*.py"))
    assert scripts and DEMO / "agent_demo.py" in scripts and DEMO / "context_bomb.py" in scripts
    local = {p.stem for p in scripts} | {p.parent.name for p in scripts if p.name == "__init__.py"}
    allowed = sys.stdlib_module_names | local
    for script in scripts:
        imports = set(python_imports(read(script)))
        assert not imports & PROPRIETARY
        assert imports <= allowed, f"Non-stdlib dependency in {script}: {imports - allowed}"
    for filename in ("pyproject.toml", "uv.lock"):
        text = read(baseline[0] / filename)
        names = set(re.findall(r'(?m)^\s*name\s*=\s*[\"\']([^\"\']+)', text))
        names |= set(re.findall(r'[\"\']([a-zA-Z][\w-]*)(?:[<>=!~\[]|[\"\'])', text))
        assert not {name.lower() for name in names} & PROPRIETARY
    count = 0
    for demo in DEMOS:
        for cli in CLIS:
            for run in (1, 2):
                meta = metadata(demo, cli, run)
                sources = list(recorded_models(meta))
                if demo != "bomb":
                    assert sources, "Missing recorded repair text for independent import scan"
                for source in sources:
                    assert not set(python_imports(source)) & PROPRIETARY
                    count += 1
    assert count >= 12

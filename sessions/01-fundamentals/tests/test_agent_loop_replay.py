"""Issue 41: acceptance of schema-1 recordings and the offline replay delivery.

Run in the session's locked uv environment. This decoder deliberately does not
import the producer. Temporary session copies exercise new inputs, drift and
invalid stream/rehearsal mappings without changing the committed evidence.

The design leaves tool-call display text unspecified: its input is checked
structurally instead. Codex inputs may retain the complete native item or just
its command/changes/arguments; neither may lose the actual tool arguments.
"""

import ast
from collections import defaultdict
from datetime import datetime
from email.parser import Parser
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit

import highspy
import pytest


SESSION = Path(__file__).resolve().parents[1]
DEMO = SESSION / "cursus/demos/agent"
RECORDED = DEMO / "recorded"
RUNS = SESSION / "cursus/fixtures/runs"
PAGE = SESSION / "cursus/labs/agent-loop.html"
RUNBOOKS = {"loop": "loop.md", "plan": "plan-first.md", "bomb": "context-bomb.md"}
CLIS = ("claude", "codex")
PROPRIETARY = {"gurobipy", "cplex", "docplex", "xpress", "mosek", "knitro",
               "localsolver", "hexaly", "coptpy"}
INLINE = re.compile(rb'<script\b(?=[^>]*\bid=[\'"]agent-runs[\'"])[^>]*>(.*?)</script\s*>', re.S | re.I)


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    return path.read_text(encoding="utf-8")


def load(path):
    return json.loads(read(path))


def events(path):
    rows = [json.loads(line) for line in read(path).splitlines() if line.strip()]
    assert rows and all(isinstance(row, dict) and "type" in row for row in rows), path
    return rows


def recordings(root=RECORDED):
    streams = sorted(root.glob("*.jsonl"))
    assert streams, f"No raw streams in {root}"
    return streams


def parent(stream, root=RECORDED):
    matches = [(p.name.removesuffix(".meta.json"), load(p)) for p in root.glob("*.meta.json")
               if stream.stem == p.name.removesuffix(".meta.json") or
               stream.stem.startswith(p.name.removesuffix(".meta.json") + "-")]
    assert len(matches) == 1, f"Stream needs exactly one parent rehearsal: {stream.name}"
    rehearsal, meta = matches[0]
    arm = stream.stem[len(rehearsal):].removeprefix("-") or None
    assert arm is None or arm in meta.get("arms", {}), f"Unmapped arm: {stream.name}"
    return rehearsal, meta, arm


def catalog(path=RUNS / "agent-demos.json"):
    data = load(path)
    assert data.get("schema") == 1
    rows = data.get("runs")
    assert isinstance(rows, list) and rows
    ids = [row["id"] for row in rows]
    assert ids == sorted(set(ids)), "Catalog runs must be unique and sorted"
    return {row["id"]: row for row in rows}


def text_blocks(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_blocks(block) for block in value)
    if isinstance(value, dict):
        return text_blocks(value.get("text", value.get("content", "")))
    return ""


def decode(rows, cli):
    """Independent ordered raw decoder. No derived totals or system/init steps."""
    steps, pending, usage = [], defaultdict(list), None
    for event in rows:
        kind = event["type"]
        if cli == "claude":
            if kind == "result":
                usage = event.get("usage")
            if kind not in {"assistant", "user"}:
                continue
            for block in event.get("message", {}).get("content", []):
                typ = block.get("type")
                if kind == "assistant" and typ in {"thinking", "text"}:
                    steps.append({"type": "thought" if typ == "thinking" else "message",
                                  "text": block.get("thinking" if typ == "thinking" else "text", "")})
                elif kind == "assistant" and typ == "tool_use":
                    pending[block.get("id")].append(block)
                    steps.append({"type": "tool_call", "tool": block["name"],
                                  "input": block.get("input", {}), "text": None})
                elif kind == "user" and typ == "tool_result":
                    queue = pending[block.get("tool_use_id")]
                    assert queue, "Orphan Claude tool result"
                    call = queue.pop(0)
                    step = {"type": "tool_result", "tool": call["name"],
                            "text": text_blocks(block.get("content", "")),
                            "is_error": bool(block.get("is_error", False))}
                    if "exit_code" in block:
                        step["exit_code"] = block["exit_code"]
                    elif "exit_code" in event.get("tool_use_result", {}):
                        step["exit_code"] = event["tool_use_result"]["exit_code"]
                    steps.append(step)
        else:
            if kind == "turn.completed":
                usage = event.get("usage")
            item = event.get("item", {})
            typ = item.get("type")
            if kind == "item.completed" and typ in {"reasoning", "agent_message"}:
                steps.append({"type": "thought" if typ == "reasoning" else "message", "text": item.get("text", "")})
            elif kind == "item.started" and typ in {"command_execution", "file_change", "mcp_tool_call"}:
                pending[item["id"]].append(item)
                steps.append({"type": "tool_call", "tool": typ, "input": item, "text": None})
            elif kind == "item.completed" and typ in {"command_execution", "file_change", "mcp_tool_call"}:
                assert pending[item["id"]], "Orphan Codex tool result"
                pending[item["id"]].pop(0)
                steps.append({"type": "tool_result", "tool": typ,
                              "text": item.get("aggregated_output", text_blocks(item.get("result", ""))),
                              "exit_code": item.get("exit_code"),
                              "is_error": item.get("status") == "failed" or item.get("exit_code") not in (0, None)})
    assert not any(pending.values()), "Raw stream has incomplete tool calls"
    return steps, usage


def assert_steps(actual, expected, cli):
    assert len(actual) == len(expected), "Every raw step must survive, in order (including empty thoughts)"
    for index, (got, want) in enumerate(zip(actual, expected)):
        label = f"step {index}: {want['type']}"
        assert got["type"] == want["type"], label
        assert isinstance(got["text"], str), label
        assert type(got["chars"]) is int and got["chars"] >= 0, label
        assert type(got["truncated"]) is bool, label
        assert len(got["text"]) == min(got["chars"], 1200), label
        assert got["truncated"] == (got["chars"] > 1200), label
        if want["text"] is not None:
            assert got["text"] == want["text"][:1200], label
            assert got["chars"] == len(want["text"]), label
        if "tool" in want:
            allowed_names = {want["tool"]}
            if want["tool"] == "mcp_tool_call" and "input" in want:
                allowed_names.add(want["input"].get("tool"))
            assert got.get("tool") in allowed_names, label
        if want["type"] == "tool_call":
            inp = got.get("input")
            native = want["input"]
            if cli == "claude":
                assert inp == native, label
            elif want["tool"] == "command_execution":
                assert (inp.get("command") if isinstance(inp, dict) else inp) == native["command"], label
            elif want["tool"] == "file_change":
                assert (inp.get("changes") if isinstance(inp, dict) else inp) == native["changes"], label
            else:
                assert isinstance(inp, dict), label
                assert inp.get("arguments", inp) == native.get("arguments", {}), label
        for key in ("exit_code", "is_error"):
            if key in want:
                # Optional null and false fields may be omitted in schema 1.
                assert got.get(key, False if key == "is_error" else None) == want[key], (label, key)
        for key in ("timestamp", "timestamp_utc", "usage", "context_occupancy"):
            if key in got:
                assert got[key] is None, f"Unrecorded per-step {key} must not be invented"


def captures(rehearsal, meta, root=RECORDED):
    if meta["demo"] != "bomb":
        return None
    method = "context" if meta["cli"] == "claude" else "status"
    return {phase: (root / f"{rehearsal}-{method}-{phase}.txt").read_bytes().decode("utf-8")
            for phase in ("before", "after")}


def own_time(row, phase, final):
    for source in (row, final):
        for key in (f"{phase}_utc", f"{phase}_at"):
            if key in source:
                return source[key]
    return None


def assert_meta(run, stream, root=RECORDED):
    rehearsal, meta, arm = parent(stream, root)
    assert run["rehearsal"] == rehearsal and run["arm"] == arm
    assert run["demo"] == meta["demo"] and run["cli"] == meta["cli"] and run["run"] == meta["run"]
    for key in ("cli", "cli_version", "model", "model_source", "effort"):
        assert run["meta"][key] == meta[key], (stream.name, key)
    own = meta if arm is None else meta["arms"][arm]
    finals = [e for e in events(stream) if e["type"] in {"result", "turn.completed"}]
    final = finals[-1] if finals else {}
    for phase in ("started", "ended"):
        assert run["meta"][f"{phase}_utc"] == own_time(own, phase, final), (stream.name, phase)
    assert run["meta"]["exit_code"] == own.get("exit_code", final.get("exit_code"))
    assert run["usage"] == decode(events(stream), meta["cli"])[1], "Use raw final usage, never aggregate or double-count cached input"


class ScriptAttributes(HTMLParser):
    attrs = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.attrs = dict(attrs)


def inline(page):
    matches = list(INLINE.finditer(page))
    assert len(matches) == 1, "One inline agent-runs catalog is required"
    match = matches[0]
    parser = ScriptAttributes()
    parser.feed(match.group(0).split(b">", 1)[0].decode() + ">")
    assert parser.attrs.get("type") == "application/json"
    return match, parser.attrs


def test_d1_fallback_links_resolve():
    runs = catalog()
    for demo, name in RUNBOOKS.items():
        book = read(DEMO / name)
        section = re.search(r"^##\s+Fallback\b[^\n]*\n(.*?)(?=^##\s|\Z)", book, re.M | re.S)
        assert section, f"{name} needs a Fallback section"
        links = re.findall(r"\]\(([^\s)]+)\)", section[1])
        selected = []
        for target in links:
            url = urlsplit(target)
            if unquote(url.path) == "../../labs/agent-loop.html":
                assert (DEMO / unquote(url.path)).resolve() == PAGE.resolve()
                assert url.fragment.startswith("run=")
                run_id = unquote(url.fragment[4:])
                assert run_id in runs and runs[run_id]["demo"] == demo
                selected.append(run_id)
        assert selected, f"{name}: link to a recorded run in the widget"
        for cli in CLIS:
            assert re.search(rf"agent_demo\.py\s+replay\s+{demo}\s+--via\s+{cli}", section[1])
    index = read(DEMO / "README.md")
    assert "labs/agent-loop.html" in index and "normalize_runs.py" in index


def test_d2_normalized_loop_order():
    runs = [row for row in catalog().values() if row["demo"] == "loop"]
    assert {row["cli"] for row in runs} == set(CLIS)
    for run in runs:
        steps = run["steps"]
        calls = [(i, s, json.dumps(s.get("input", ""))) for i, s in enumerate(steps) if s["type"] == "tool_call"]
        reads = [i for i, s, arg in calls if "p00_model.py" in arg and
                 (s["tool"].lower() == "read" or re.search(r"\b(cat|sed|head|rg|read_text)\b", arg))]
        edits = [i for i, s, arg in calls if "p00_model.py" in arg and
                 (re.search(r"edit|write|file_change|patch", s["tool"], re.I) or "apply_patch" in arg)]
        red, green = [], []
        for i, call, arg in calls:
            if "pytest" not in arg:
                continue
            result = next(((j, s) for j, s in enumerate(steps[i + 1:], i + 1)
                           if s["type"] == "tool_result" and s.get("tool") == call["tool"]), None)
            assert result, "Pytest call needs a result"
            j, output = result
            if output.get("exit_code") not in (None, 0) or re.search(r"FAILURES|\b[1-9]\d* failed\b|AssertionError", output["text"]):
                red.append((i, j))
            elif re.search(r"\b[1-9]\d* passed\b", output["text"]) and not output.get("is_error"):
                green.append(i)
        assert any(r < f and fr < e < g for r in reads for f, fr in red for e in edits for g in green), run["id"]


def test_d3_upstream_license():
    license_file = DEMO / "upstream/LICENSE.txt"
    data = license_file.read_bytes()
    text = data.decode("utf-8")
    book = read(DEMO / "context-bomb.md")
    row = next((line for line in book.splitlines() if "upstream/LICENSE.txt" in line and "|" in line), None)
    assert row, "Add the license to the pinned snapshot table"
    assert hashlib.sha256(data).hexdigest() in row
    assert "MIT License" in text
    for notice in ("Permission is hereby granted, free of charge", "to deal in the Software without restriction",
                   "The above copyright notice and this permission notice shall be included",
                   'THE SOFTWARE IS PROVIDED "AS IS"', "IN NO EVENT SHALL THE"):
        assert notice in " ".join(text.split()), "Full MIT license, including conditions and disclaimer"
    copyright_line = re.search(r"Copyright\s+\(c\)\s+\d{4}[^\n]+", text)
    assert copyright_line and copyright_line[0] in " ".join(book.split())
    assert len(data) > 1000, "The full upstream license is required"


def test_d3_bomb_captures_in_catalog():
    runs = catalog()
    for stream in recordings():
        rehearsal, meta, _ = parent(stream)
        if meta["demo"] == "bomb":
            assert runs[stream.stem]["captures"] == captures(rehearsal, meta)
            assert_meta(runs[stream.stem], stream)


def test_d4_plan_arms_in_catalog():
    runs = catalog()
    metas = sorted(RECORDED.glob("plan-*.meta.json"))
    assert metas
    for path in metas:
        meta = load(path)
        rehearsal = path.name.removesuffix(".meta.json")
        arm_runs = [r for r in runs.values() if r["rehearsal"] == rehearsal]
        assert {r["arm"] for r in arm_runs} == set(meta["arms"])
        for row in arm_runs:
            assert_meta(row, RECORDED / (row["id"] + ".jsonl"))


def test_d5_catalog_meta_matches():
    runs = catalog()
    for stream in recordings():
        row = runs[stream.stem]
        assert_meta(row, stream)
        book = read(DEMO / RUNBOOKS[row["demo"]])
        table = [line for line in book.splitlines() if "|" in line and f"recorded/{row['rehearsal']}.meta.json" in line]
        assert len(table) == 1, f"One recorded-runs row for {row['rehearsal']}"
        for key in ("model", "model_source", "effort"):
            assert row["meta"][key] in table[0]
        version = re.search(r"\d+\.\d+\.\d+", row["meta"]["cli_version"])
        assert version and version[0] in table[0]


def test_a1_catalog_includes_both_rehearsals_per_harness():
    runs = catalog()
    for demo in RUNBOOKS:
        for cli in CLIS:
            rows = [r for r in runs.values() if r["demo"] == demo and r["cli"] == cli]
            assert {r["run"] for r in rows} >= {1, 2}
            for row in rows:
                assert row["meta"]["exit_code"] == 0
                begin, end = (datetime.fromisoformat(row["meta"][key].replace("Z", "+00:00"))
                              for key in ("started_utc", "ended_utc"))
                assert begin.tzinfo is not None and begin <= end


def test_a2_all_streams_raw_fidelity_and_mapping():
    runs = catalog()
    streams = recordings()
    assert set(runs) == {p.stem for p in streams}, "Exactly one playable run per raw stream"
    used = set()
    for stream in streams:
        rehearsal, meta, _ = parent(stream)
        used.add(rehearsal)
        run = runs[stream.stem]
        expected, usage = decode(events(stream), meta["cli"])
        assert expected, f"No replay steps: {stream.name}"
        assert_steps(run["steps"], expected, meta["cli"])
        assert run["usage"] == usage
        assert run["captures"] == captures(rehearsal, meta)
        assert_meta(run, stream)
    assert used == {p.name.removesuffix(".meta.json") for p in RECORDED.glob("*.meta.json")}


def test_a2_inline_catalog_privacy_and_review():
    data = (RUNS / "agent-demos.json").read_bytes()
    page = PAGE.read_bytes()
    match, attrs = inline(page)
    assert match[1] == data, "Inline catalog must equal fixture bytes, including final newline"
    assert attrs.get("data-sha256") == hashlib.sha256(data).hexdigest()
    assert data.endswith(b"\n")
    def sorted_object(pairs):
        assert [k for k, _ in pairs] == sorted(k for k, _ in pairs), "Sort JSON object keys"
        return dict(pairs)
    json.loads(data, object_pairs_hook=sorted_object)
    for content in (data.decode(), page.decode()):
        for pattern in (r"/(?:home|Users)/[^/\s\"<>]+/", r"[A-Za-z]:\\Users\\[^\\\s]+\\",
                        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}",
                        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"):
            assert not re.search(pattern, content), f"Private identity or key pattern: {pattern}"
    review = read(PAGE.with_suffix("") / "review.md")
    assert hashlib.sha256(page).hexdigest() in review, "Review must identify current HTML"
    assert re.search(rf"\b{len(page):,}\s+bytes\b|\b{len(page)}\s+bytes\b", review)
    assert re.search(r"screenshot", review, re.I), "Record the screenshot review"
    assert read(RUNS / "README.md").strip()


def imports(source):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "Delivered scripts must not import repository parents"
            if node.module:
                yield node.module.split(".")[0]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "__import__" or
                    isinstance(func, ast.Attribute) and func.attr == "import_module"):
                if isinstance(node.args[0].value, str):
                    yield node.args[0].value.split(".")[0]


def test_a2_normalizer_stdlib():
    names = set(imports(read(RUNS / "normalize_runs.py")))
    assert names <= sys.stdlib_module_names, f"Normalizer dependencies outside stdlib: {names - sys.stdlib_module_names}"


@pytest.fixture
def isolated(tmp_path):
    """Minimal session moved to a new location; tests may mutate only this copy."""
    session = tmp_path / "copy/sessions/01-fundamentals"
    for relative in ("cursus/fixtures/runs", "cursus/demos/agent/recorded"):
        shutil.copytree(SESSION / relative, session / relative)
    page = session / "cursus/labs/agent-loop.html"
    page.parent.mkdir(parents=True)
    shutil.copyfile(PAGE, page)
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import sys\ndef audit(event, args):\n"
        "    if event.startswith('socket.'):\n"
        "        raise RuntimeError('acceptance: normalizer must be offline')\n"
        "sys.addaudithook(audit)\n", encoding="utf-8")
    return session, tmp_path, guard


def normalize(copy, *args):
    session, cwd, guard = copy
    env = dict(os.environ, PYTHONPATH=str(guard), PYTHONDONTWRITEBYTECODE="1", UV_OFFLINE="1")
    return subprocess.run([sys.executable, session / "cursus/fixtures/runs/normalize_runs.py", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr


def tree_bytes(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_a2_deterministic_location_independent_and_check_drift(isolated):
    session = isolated[0]
    page = session / "cursus/labs/agent-loop.html"
    fixture = session / "cursus/fixtures/runs/agent-demos.json"
    authored = INLINE.sub(b"<CATALOG>", page.read_bytes())
    original = fixture.read_bytes()
    fixture.unlink()
    success(normalize(isolated))
    assert fixture.read_bytes() == original, "Regenerate the committed catalog from raw streams"
    assert INLINE.sub(b"<CATALOG>", page.read_bytes()) == authored, "Do not rewrite authored markup"
    first = fixture.read_bytes(), page.read_bytes()
    success(normalize(isolated))
    assert (fixture.read_bytes(), page.read_bytes()) == first
    before = tree_bytes(session)
    success(normalize(isolated, "--check"))
    assert tree_bytes(session) == before, "--check must not write, even identical bytes"
    for target in (fixture, page):
        if target == fixture:
            stale = load(fixture)
            stale["schema"] = 999
            fixture.write_text(json.dumps(stale) + "\n", encoding="utf-8")
        else:
            # Alter the inline catalog, rather than harmless authored prose.
            match, _ = inline(page.read_bytes())
            page.write_bytes(page.read_bytes()[:match.start(1)] + b"{}\n" + page.read_bytes()[match.end(1):])
        before = tree_bytes(session)
        result = normalize(isolated, "--check")
        assert result.returncode == 1, result.stdout + result.stderr
        assert tree_bytes(session) == before, "--check must leave stale artifacts untouched"
        success(normalize(isolated))


@pytest.mark.parametrize("invalid", ["missing-meta", "unknown-arm", "unused-meta"])
def test_a2_unmapped_evidence_fails_loudly(isolated, invalid):
    root = isolated[0] / "cursus/demos/agent/recorded"
    if invalid == "missing-meta":
        shutil.copyfile(root / "loop-codex-run1.jsonl", root / "loop-codex-run987.jsonl")
    elif invalid == "unknown-arm":
        shutil.copyfile(root / "plan-codex-run1-direct.jsonl", root / "plan-codex-run1-unmapped.jsonl")
    else:
        meta = load(root / "loop-codex-run1.meta.json")
        meta["run"] = 987
        (root / "loop-codex-run987.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    result = normalize(isolated)
    assert result.returncode != 0, f"Accepted invalid recording map: {invalid}"
    assert (result.stdout + result.stderr).strip(), "Invalid input needs a diagnostic"


@pytest.mark.parametrize("cli", CLIS)
def test_a2_alternate_raw_events_and_missing_arm_metadata(isolated, cli):
    root = isolated[0] / "cursus/demos/agent/recorded"
    stem = f"plan-{cli}-run2"
    stream = root / f"{stem}-direct.jsonl"
    # Unequal lengths and Unicode exercise truncation by characters, not bytes.
    thought, message = "a new thought Ω\n", "alternate message\n" + "é" * 1220
    output = "tool failed at a new boundary\n" + "界" * 1207
    usage = {"input_tokens": 173, "cached_input_tokens": 101, "output_tokens": 19,
             "acceptance_extra": {"preserve": "verbatim"}}
    if cli == "claude":
        rows = [
            {"type": "system", "subtype": "init", "model": "ignored-init"},
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": thought}, {"type": "text", "text": message},
                {"type": "text", "text": "b" * 1200},
                {"type": "tool_use", "id": "alternate", "name": "UnseenTool", "input": {"path": "other.py", "n": 17}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "alternate", "content": output, "is_error": True}]}},
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "done"}]}},
            {"type": "result", "usage": usage},
        ]
    else:
        call = {"id": "other-call", "type": "command_execution", "command": "python -c 'print(173)'", "status": "in_progress"}
        change = {"id": "other-change", "type": "file_change", "changes": [{"path": "other.py", "kind": "update"}], "status": "in_progress"}
        rows = [
            {"type": "thread.started", "thread_id": "ignored"},
            {"type": "item.completed", "item": {"type": "reasoning", "text": thought}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "b" * 1200}},
            {"type": "item.started", "item": call},
            {"type": "item.completed", "item": {**call, "aggregated_output": output, "exit_code": 17, "status": "failed"}},
            {"type": "item.started", "item": change},
            {"type": "item.completed", "item": {**change, "status": "completed"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
            {"type": "turn.completed", "usage": usage},
        ]
    stream.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    path = root / f"{stem}.meta.json"
    meta = load(path)
    for key in ("started_at", "ended_at", "exit_code", "usage"):
        meta["arms"]["direct"].pop(key, None)
    # The rehearsal aggregate remains present: copying it into this arm is wrong.
    meta.update(started_at="2000-01-01T00:00:00Z", ended_at="2000-01-02T00:00:00Z", exit_code=91, usage={"input_tokens": 999999})
    path.write_text(json.dumps(meta), encoding="utf-8")
    success(normalize(isolated))
    row = catalog(isolated[0] / "cursus/fixtures/runs/agent-demos.json")[stream.stem]
    expected, raw_usage = decode(rows, cli)
    assert_steps(row["steps"], expected, cli)
    assert row["usage"] == raw_usage
    assert_meta(row, stream, root)
    assert row["meta"]["started_utc"] is None and row["meta"]["ended_utc"] is None
    assert row["meta"]["exit_code"] is None
    success(normalize(isolated, "--check"))


def test_a3_no_proprietary_solver():
    for path in (DEMO / "agent_demo.py", DEMO / "context_bomb.py", RUNS / "normalize_runs.py",
                 SESSION / "exercises/p00-lab/p00_model.py"):
        assert not set(imports(read(path))) & PROPRIETARY, path
    repairs = []
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"p00_model_py", "p00_model.py", "model_text"} and isinstance(child, str):
                    repairs.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for path in RECORDED.glob("*.meta.json"):
        visit(load(path))
    assert repairs, "Recorded repair sources must be independently scannable"
    for source in repairs:
        assert not set(imports(source)) & PROPRIETARY
    lock = tomllib.loads(read(SESSION / "uv.lock"))
    packages = {row["name"].lower() for row in lock["package"]}
    assert "highspy" in packages and not packages & PROPRIETARY
    assert "highspy" in set(imports(read(SESSION / "exercises/p00-lab/p00_model.py")))
    # Read the locked distribution's metadata beside the imported package.
    # The session's self-containment guard forbids importlib, including its
    # metadata module; inspecting this data file needs no dynamic imports.
    highs_package = next(row for row in lock["package"] if row["name"].lower() == "highspy")
    metadata_file = (Path(highspy.__file__).resolve().parent.parent /
                     f"highspy-{highs_package['version']}.dist-info" / "METADATA")
    license_meta = Parser().parsestr(read(metadata_file))
    assert "MIT" in (license_meta.get("License-Expression", "") + license_meta.get("License", ""))

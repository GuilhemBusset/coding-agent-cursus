"""Normalize the recorded Act III agent runs for replay. Two outputs, one script:

    python normalize_runs.py [--raw DIR] [--out DIR] [--check]

1. Agent-run recordings, schema agent-run/1. Reads every `<run>.jsonl` in --raw (default:
   raw/ beside this script) with its `<run>.meta.json` sidecar, and writes `<run>.json` into
   --out (default: this script's folder).
2. The demo catalog, schema 1. Reads every raw stream in `cursus/demos/agent/recorded/*.jsonl`
   (`claude -p --output-format stream-json --verbose` or `codex exec --json`), resolves each
   one to its rehearsal's `*.meta.json`, and writes `agent-demos.json` next to this script.
   The same bytes are copied into the inline `<script type="application/json" id="agent-runs">`
   block of `cursus/labs/agent-loop.html`.
3. The page's copy of the agent-run recordings from (1), schema agent-run-recordings/1, in its
   inline `<script type="application/json" id="agent-run-recordings">` block: every step with
   its text clipped for display. The rest of that page is authored and left alone.

With no --raw or --out both outputs are built; with either, only the agent runs in those folders.
--check writes nothing and exits 1 if any output differs byte for byte, is missing, or is extra
(an extra file is any `*-claude.json` or `*-codex.json` without a recording). Standard library
only, no network, no clock, no randomness, independent of the working directory; files are read
in sorted name order.

One normalized run:

    {"schema": "agent-run/1",
     "meta": {run, task, vendor, cli_version, model, effort, date, argv, exit_code, prompt_sha256},
     "steps": [{i, line, type, t_ms, source_ts, text, tool, call_id, input, is_error, parent, tokens}],
     "totals": {input, output, cached_input, reasoning},
     "diagnostics": {"ignored": {<event>: count}, "unknown": [{line, type}]}}

`type` is thought, tool_call, tool_result or message. `line` is the 1-based source line.
`t_ms` is the line's receipt offset from the meta's line_offsets_ms (one clock per run);
a native event timestamp, if any, is copied to `source_ts` and never used for ordering.
`input` counts include cached input. Step `tokens` come once per Claude message id, on
its first step; totals come from Claude's `result.usage` or from the sum of Codex
`turn.completed` usage. A counter the vendor did not report is null, never 0.

The demo catalog's schema is in README.md. Any demo stream without exactly one parent
rehearsal, any arm the meta does not declare, and any meta or declared arm that no stream
uses stops the run with a message.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
SCHEMA = "agent-run/1"
VENDORS = ("claude", "codex")
META_FIELDS = ("task", "vendor", "cli_version", "model", "effort", "date", "argv", "exit_code", "prompt_sha256")
CODEX_TOOLS = ("command_execution", "file_change", "mcp_tool_call", "web_search")
# Codex item fields that describe the outcome rather than the call.
CODEX_RESULT_FIELDS = {"id", "type", "status", "aggregated_output", "exit_code", "result", "error"}

# The demo catalog played by the agent-loop replay widget.
SESSION = HERE.parents[2]
RECORDED = SESSION / "cursus/demos/agent/recorded"
CATALOG = HERE / "agent-demos.json"
PAGE = SESSION / "cursus/labs/agent-loop.html"
CATALOG_SCHEMA = 1
MAX_CHARS = 1200
CATALOG_CODEX_TOOLS = ("command_execution", "file_change", "mcp_tool_call")
CAPTURE_METHOD = {"claude": "context", "codex": "status"}
RECORDINGS_SCHEMA = "agent-run-recordings/1"
RECORDING_STEP_FIELDS = ("i", "t_ms", "tool", "input", "is_error", "tokens")


def inline_block(block_id):
    return re.compile(rb'(<script\b(?=[^>]*\bid=[\'"]' + block_id + rb'[\'"])[^>]*>)(.*?)(</script\s*>)', re.S | re.I)


INLINE = inline_block(b"agent-runs")
RECORDINGS_INLINE = inline_block(b"agent-run-recordings")
SHA_ATTR = re.compile(rb'\bdata-sha256=(["\'])[^"\']*\1')
ESCAPED_AT = re.compile(r"(?<!\\)((?:\\\\)*\\[bfnrt])@")


class InputError(Exception):
    pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def read_events(path):
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError as error:
            raise InputError(f"{path.name}:{number}: invalid JSON ({error.msg})") from None
        if not isinstance(event, dict):
            raise InputError(f"{path.name}:{number}: expected a JSON object")
        events.append((number, event))
    return events


def counter(value):
    return value if type(value) is int and value >= 0 else None


class Builder:
    def __init__(self, offsets):
        self.offsets = offsets
        self.steps = []
        self.ignored = {}
        self.unknown = []

    def step(self, number, event, kind, text=None, tool=None, call_id=None, input=None,
             is_error=None, parent=None, tokens=None):
        t_ms = None
        if isinstance(self.offsets, list) and number - 1 < len(self.offsets):
            t_ms = self.offsets[number - 1]
        source_ts = event.get("timestamp")
        self.steps.append(dict(i=len(self.steps), line=number, type=kind, t_ms=t_ms,
                               source_ts=source_ts if isinstance(source_ts, str) else None,
                               text=text, tool=tool, call_id=call_id, input=input,
                               is_error=is_error, parent=parent, tokens=tokens))
        return self.steps[-1]

    def ignore(self, key):
        self.ignored[key] = self.ignored.get(key, 0) + 1

    def unknown_event(self, number, kind):
        self.unknown.append({"line": number, "type": kind})


def text_of(content):
    """Flatten a Claude tool_result content (a string or a list of blocks) to text."""
    if content is None:
        return None
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else [content]:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif isinstance(block, dict):
            parts.append(f"[{block.get('type', 'block')}]")
        else:
            parts.append(str(block))
    return "\n".join(parts)


def claude_tokens(usage):
    if not isinstance(usage, dict):
        return None
    base = counter(usage.get("input_tokens"))
    total = None
    if base is not None:
        total = base + sum(counter(usage.get(key)) or 0
                           for key in ("cache_read_input_tokens", "cache_creation_input_tokens"))
    return {"input": total, "output": counter(usage.get("output_tokens")),
            "cached_input": counter(usage.get("cache_read_input_tokens"))}


def claude(events, offsets):
    build = Builder(offsets)
    totals = dict.fromkeys(("input", "output", "cached_input", "reasoning"))
    tokens_done = set()
    tool_names = {}
    for number, event in events:
        kind = event.get("type")
        parent = event.get("parent_tool_use_id")
        parent = parent if isinstance(parent, str) else None
        if kind == "system":
            build.ignore(f"system/{event.get('subtype')}")
        elif kind in {"stream_event", "rate_limit_event"}:
            build.ignore(kind)
        elif kind == "result":
            build.ignore(kind)
            usage = event.get("usage")
            if isinstance(usage, dict):
                tokens = claude_tokens(usage)
                totals.update(tokens)
                thinking = [model.get("thinkingTokens") for model in (event.get("modelUsage") or {}).values()
                            if isinstance(model, dict)]
                if thinking and all(counter(count) is not None for count in thinking):
                    totals["reasoning"] = sum(thinking)
        elif kind == "assistant":
            message = event.get("message") or {}
            message_id = message.get("id")
            usage = claude_tokens(message.get("usage"))
            for block in message.get("content") or []:
                block_type = block.get("type") if isinstance(block, dict) else None
                if block_type in {"thinking", "redacted_thinking"}:
                    step = build.step(number, event, "thought", text=block.get("thinking"), parent=parent)
                elif block_type == "text":
                    step = build.step(number, event, "message", text=block.get("text"), parent=parent)
                elif isinstance(block_type, str) and block_type.endswith("tool_use"):
                    tool_names[block.get("id")] = block.get("name")
                    step = build.step(number, event, "tool_call", tool=block.get("name"), call_id=block.get("id"),
                                      input=block.get("input"), parent=parent)
                elif isinstance(block_type, str) and block_type.endswith("tool_result"):
                    step = build.step(number, event, "tool_result", text=text_of(block.get("content")),
                                      tool=tool_names.get(block.get("tool_use_id")), call_id=block.get("tool_use_id"),
                                      is_error=bool(block.get("is_error", False)), parent=parent)
                else:
                    build.unknown_event(number, f"assistant/{block_type}")
                    continue
                if message_id not in tokens_done:
                    tokens_done.add(message_id)
                    step["tokens"] = usage
        elif kind == "user":
            content = (event.get("message") or {}).get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
            for block in blocks:
                block_type = block.get("type") if isinstance(block, dict) else None
                if block_type == "tool_result":
                    build.step(number, event, "tool_result", text=text_of(block.get("content")),
                               tool=tool_names.get(block.get("tool_use_id")), call_id=block.get("tool_use_id"),
                               is_error=bool(block.get("is_error", False)), parent=parent)
                else:
                    # Prompts and harness reminders echoed back, not agent steps.
                    build.ignore(f"user/{block_type}")
        else:
            build.unknown_event(number, str(kind))
    return build, totals


def codex_input(item):
    return {key: value for key, value in item.items() if key not in CODEX_RESULT_FIELDS}


def codex_result_text(item):
    kind = item.get("type")
    if kind == "command_execution":
        return item.get("aggregated_output")
    if kind == "file_change":
        changes = item.get("changes") or []
        return "\n".join(f"{change.get('kind')} {change.get('path')}" for change in changes if isinstance(change, dict))
    if kind == "mcp_tool_call":
        if item.get("error") is not None:
            error = item["error"]
            return error.get("message") if isinstance(error, dict) else str(error)
        result = item.get("result")
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            return text_of(result["content"])
        return None if result is None else json.dumps(result, sort_keys=True, ensure_ascii=False)
    return None


def codex(events, offsets):
    build = Builder(offsets)
    usages = []
    called = set()
    for number, event in events:
        kind = event.get("type")
        if kind in {"thread.started", "turn.started", "turn.failed", "error"}:
            build.ignore(kind)
        elif kind == "turn.completed":
            build.ignore(kind)
            usages.append(event.get("usage") if isinstance(event.get("usage"), dict) else {})
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item") or {}
            item_type = item.get("type")
            if kind == "item.updated":
                build.ignore(kind)
            elif item_type in CODEX_TOOLS:
                if item.get("id") not in called:
                    called.add(item.get("id"))
                    build.step(number, event, "tool_call", tool=item_type, call_id=item.get("id"), input=codex_input(item))
                if kind == "item.completed":
                    exit_code = item.get("exit_code")
                    failed = (type(exit_code) is int and exit_code != 0) or item.get("status") == "failed"
                    build.step(number, event, "tool_result", text=codex_result_text(item), tool=item_type,
                               call_id=item.get("id"), is_error=failed)
            elif kind == "item.started" and item_type in {"reasoning", "agent_message", "todo_list", "error"}:
                build.ignore(f"{kind}/{item_type}")
            elif item_type == "reasoning":
                build.step(number, event, "thought", text=item.get("text"))
            elif item_type == "agent_message":
                build.step(number, event, "message", text=item.get("text"))
            elif item_type in {"todo_list", "error"}:
                build.ignore(f"{kind}/{item_type}")
            else:
                build.unknown_event(number, f"{kind}/{item_type}")
        else:
            build.unknown_event(number, str(kind))
    totals = {}
    for target, source in (("input", "input_tokens"), ("output", "output_tokens"),
                           ("cached_input", "cached_input_tokens"), ("reasoning", "reasoning_output_tokens")):
        counts = [counter(usage.get(source)) for usage in usages]
        totals[target] = sum(counts) if counts and None not in counts else None
    return build, totals


def normalize(name, events, meta):
    vendor = meta.get("vendor") or name.rsplit("-", 1)[-1]
    if vendor not in VENDORS:
        raise InputError(f"{name}: unknown vendor {vendor!r}")
    offsets = meta.get("line_offsets_ms")
    build, totals = (claude if vendor == "claude" else codex)(events, offsets)
    return {
        "schema": SCHEMA,
        "meta": {"run": name, **{field: meta.get(field) for field in META_FIELDS}, "vendor": vendor},
        "steps": build.steps,
        "totals": totals,
        "diagnostics": {"ignored": build.ignored, "unknown": build.unknown},
    }


def render(raw):
    outputs = {}
    for path in sorted(raw.glob("*.jsonl")):
        name = path.name[:-len(".jsonl")]
        meta_path = raw / f"{name}.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        outputs[f"{name}.json"] = canonical(normalize(name, read_events(path), meta))
    return outputs


def check(outputs, out):
    problems = []
    existing = {path.name for vendor in VENDORS for path in out.glob(f"*-{vendor}.json")}
    for filename, content in sorted(outputs.items()):
        path = out / filename
        if not path.is_file():
            problems.append(f"missing: {path}")
        elif path.read_bytes() != content:
            problems.append(f"differs: {path}")
    problems.extend(f"extra: {out / name}" for name in sorted(existing - set(outputs)))
    return problems


# The demo catalog (schema 1) for the agent-loop replay widget.
class RecordingError(Exception):
    pass


def block_text(value):
    """Plain text of a tool result's content: a string, a list of blocks, or one block."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(block_text(block) for block in value)
    if isinstance(value, dict):
        return block_text(value.get("text", value.get("content", "")))
    return ""


def step(kind, text, **fields):
    text = text if isinstance(text, str) else ""
    out = {"type": kind, "text": text[:MAX_CHARS], "chars": len(text), "truncated": len(text) > MAX_CHARS}
    out.update(fields)
    return out


def claude_call_text(tool_input):
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    return json.dumps(tool_input, ensure_ascii=False, indent=2, sort_keys=True)


def codex_call(item):
    kind = item["type"]
    if kind == "command_execution":
        tool_input = {"command": item.get("command")}
        text = item.get("command") if isinstance(item.get("command"), str) else ""
    elif kind == "file_change":
        tool_input = {"changes": item.get("changes")}
        text = "\n".join(f"{c.get('kind', '?')} {c.get('path', '?')}" for c in item.get("changes") or [])
    else:
        tool_input = {"server": item.get("server"), "tool": item.get("tool"), "arguments": item.get("arguments", {})}
        text = f"{item.get('server')}.{item.get('tool')} " + json.dumps(
            item.get("arguments", {}), ensure_ascii=False, sort_keys=True)
    return tool_input, text


def decode_stream(rows, cli, name):
    """Ordered steps and the final reported usage of one raw stream."""
    steps, pending, usage = [], defaultdict(list), None
    for number, event in enumerate(rows, 1):
        kind = event.get("type")
        where = f"{name}:{number}"
        if cli == "claude":
            if kind == "result":
                usage = event.get("usage")
            if kind not in ("assistant", "user"):
                continue  # system/init, rate limits and the result carry no replay step
            content = event.get("message", {}).get("content", [])
            if not isinstance(content, list):
                raise RecordingError(f"{where}: message content is not a list of blocks")
            for block in content:
                typ = block.get("type")
                if kind == "assistant" and typ == "thinking":
                    steps.append(step("thought", block.get("thinking", "")))
                elif kind == "assistant" and typ == "text":
                    steps.append(step("message", block.get("text", "")))
                elif kind == "assistant" and typ == "tool_use":
                    pending[block.get("id")].append(block)
                    tool_input = block.get("input", {})
                    steps.append(step("tool_call", claude_call_text(tool_input), tool=block["name"], input=tool_input))
                elif kind == "user" and typ == "tool_result":
                    queue = pending[block.get("tool_use_id")]
                    if not queue:
                        raise RecordingError(f"{where}: tool result without a matching tool call")
                    call = queue.pop(0)
                    fields = {"tool": call["name"], "is_error": bool(block.get("is_error", False))}
                    native = event.get("tool_use_result")
                    if "exit_code" in block:
                        fields["exit_code"] = block["exit_code"]
                    elif isinstance(native, dict) and "exit_code" in native:
                        fields["exit_code"] = native["exit_code"]
                    steps.append(step("tool_result", block_text(block.get("content", "")), **fields))
        else:
            if kind == "turn.completed":
                usage = event.get("usage")
            item = event.get("item", {})
            typ = item.get("type")
            if kind == "item.completed" and typ in ("reasoning", "agent_message"):
                steps.append(step("thought" if typ == "reasoning" else "message", item.get("text", "")))
            elif kind == "item.started" and typ in CATALOG_CODEX_TOOLS:
                pending[item["id"]].append(item)
                tool_input, text = codex_call(item)
                steps.append(step("tool_call", text, tool=typ, input=tool_input))
            elif kind == "item.completed" and typ in CATALOG_CODEX_TOOLS:
                if not pending[item["id"]]:
                    raise RecordingError(f"{where}: {typ} completed without being started")
                pending[item["id"]].pop(0)
                exit_code = item.get("exit_code")
                fields = {"tool": typ, "is_error": item.get("status") == "failed" or exit_code not in (0, None)}
                if exit_code is not None:
                    fields["exit_code"] = exit_code
                text = item.get("aggregated_output", block_text(item.get("result", "")))
                steps.append(step("tool_result", text, **fields))
    open_calls = [key for key, queue in pending.items() if queue]
    if open_calls:
        raise RecordingError(f"{name}: tool calls without a result: {open_calls}")
    return steps, usage


def read_rows(path):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or "type" not in row:
            raise RecordingError(f"{path.name}:{number}: not a typed JSON event")
        rows.append(row)
    if not rows:
        raise RecordingError(f"{path.name}: empty stream")
    return rows


def own_time(own, final, phase):
    for source in (own, final):
        for key in (f"{phase}_utc", f"{phase}_at"):
            if key in source:
                return source[key]
    return None


def build_catalog(recorded):
    streams = sorted(recorded.glob("*.jsonl"))
    if not streams:
        raise RecordingError(f"no raw streams in {recorded}")
    metas = {p.name.removesuffix(".meta.json"): json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(recorded.glob("*.meta.json"))}
    used = defaultdict(set)
    runs = []
    for stream in streams:
        stem = stream.stem
        parents = [r for r in metas if stem == r or stem.startswith(r + "-")]
        if len(parents) != 1:
            raise RecordingError(f"{stream.name}: needs exactly one parent rehearsal meta, found {parents or 'none'}")
        rehearsal = parents[0]
        meta = metas[rehearsal]
        arm = stem[len(rehearsal):].removeprefix("-") or None
        arms = meta.get("arms")
        if arm is None and arms:
            raise RecordingError(f"{stream.name}: rehearsal {rehearsal} has arms {sorted(arms)}; name the arm")
        if arm is not None and arm not in (arms or {}):
            raise RecordingError(f"{stream.name}: arm {arm!r} is not declared in {rehearsal}.meta.json")
        used[rehearsal].add(arm)
        cli = meta["cli"]
        if cli not in CAPTURE_METHOD:
            raise RecordingError(f"{rehearsal}.meta.json: unknown cli {cli!r}")
        rows = read_rows(stream)
        steps, usage = decode_stream(rows, cli, stream.name)
        if not steps:
            raise RecordingError(f"{stream.name}: no replay steps")
        finals = [e for e in rows if e["type"] in ("result", "turn.completed")]
        final = finals[-1] if finals else {}
        own = meta if arm is None else arms[arm]
        captures = None
        if meta["demo"] == "bomb":
            method = CAPTURE_METHOD[cli]
            captures = {}
            for phase in ("before", "after"):
                capture = recorded / f"{rehearsal}-{method}-{phase}.txt"
                if not capture.is_file():
                    raise RecordingError(f"{stream.name}: missing capture {capture.name}")
                captures[phase] = capture.read_bytes().decode("utf-8")
        runs.append({
            "id": stem,
            "demo": meta["demo"],
            "cli": cli,
            "rehearsal": rehearsal,
            "run": meta["run"],
            "arm": arm,
            "meta": {
                "cli": cli,
                "cli_version": meta["cli_version"],
                "model": meta["model"],
                "model_source": meta["model_source"],
                "effort": meta["effort"],
                "started_utc": own_time(own, final, "started"),
                "ended_utc": own_time(own, final, "ended"),
                "exit_code": own.get("exit_code", final.get("exit_code")),
            },
            "usage": usage,
            "captures": captures,
            "per_step": {"context_occupancy": None, "timestamp": None, "usage": None},
            "steps": steps,
        })
    unused = sorted(set(metas) - set(used))
    if unused:
        raise RecordingError(f"meta without any raw stream: {', '.join(r + '.meta.json' for r in unused)}")
    for rehearsal, arms_used in used.items():
        missing = sorted(set(metas[rehearsal].get("arms") or {}) - arms_used)
        if missing:
            raise RecordingError(f"{rehearsal}.meta.json declares arms with no raw stream: {missing}")
    return {"schema": CATALOG_SCHEMA, "runs": sorted(runs, key=lambda run: run["id"])}


def serialize(catalog):
    text = json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    # "<" only occurs inside JSON strings; escaping it keeps "</script>" out of the inline copy.
    text = text.replace("<", "\\u003c")
    # An "@" right after a control escape (a "@pytest" decorator after "\n") would join the "n"
    # and the dotted name after it into an e-mail address for a privacy scan. Escape that "@"
    # only; real addresses still show.
    return ESCAPED_AT.sub(r"\1\\u0040", text).encode("utf-8")


def inline_page(page, data, pattern=INLINE, block_id="agent-runs"):
    matches = list(pattern.finditer(page))
    if len(matches) != 1:
        raise RecordingError(f"{PAGE.name}: expected one inline {block_id} script block, found {len(matches)}")
    match = matches[0]
    opening = match.group(1)
    if not SHA_ATTR.search(opening):
        raise RecordingError(f"{PAGE.name}: the {block_id} block needs a data-sha256 attribute")
    digest = hashlib.sha256(data).hexdigest().encode()
    opening = SHA_ATTR.sub(lambda m: b"data-sha256=" + m.group(1) + digest + m.group(1), opening, count=1)
    return page[:match.start()] + opening + data + match.group(3) + page[match.end():]


def recording_call_text(vendor, tool_input):
    """What the page shows for a recorded tool call: the command, the changed files, or the input as JSON."""
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if vendor == "codex" and isinstance(tool_input, dict) and isinstance(tool_input.get("changes"), list):
        return "\n".join(f"{c.get('kind', '?')} {c.get('path', '?')}" for c in tool_input["changes"] if isinstance(c, dict))
    return json.dumps(tool_input, ensure_ascii=False, indent=2, sort_keys=True)


def build_recordings(outputs):
    """The page's copy of every normalized agent run: meta and totals as they are, step texts clipped."""
    runs = []
    for filename, content in sorted(outputs.items()):
        run = json.loads(content)
        steps = []
        for source in run["steps"]:
            text = source["text"]
            if source["type"] == "tool_call" and text is None:
                text = recording_call_text(run["meta"]["vendor"], source["input"])
            steps.append(step(source["type"], text, **{field: source[field] for field in RECORDING_STEP_FIELDS}))
        runs.append({"meta": run["meta"], "totals": run["totals"], "steps": steps})
    return {"schema": RECORDINGS_SCHEMA, "runs": runs}


def catalog_outputs(outputs):
    """The demo catalog's bytes, keyed by every file that must hold them, plus the page's recordings block."""
    data = serialize(build_catalog(RECORDED))
    if not PAGE.is_file():
        raise RecordingError(f"missing replay page {PAGE}")
    page = inline_page(PAGE.read_bytes(), data)
    page = inline_page(page, serialize(build_recordings(outputs)), RECORDINGS_INLINE, "agent-run-recordings")
    return data, {CATALOG: data, PAGE: page}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, help="folder of <run>.jsonl and <run>.meta.json (default: raw/ here)")
    parser.add_argument("--out", type=Path, help="folder for <run>.json (default: this folder)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if an output would change")
    args = parser.parse_args(argv)
    # Explicit folders normalize just those agent runs; the demo catalog has fixed paths.
    with_catalog = args.raw is None and args.out is None
    raw = HERE / "raw" if args.raw is None else args.raw
    out = HERE if args.out is None else args.out
    try:
        outputs = render(raw)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    data, catalog = b"", {}
    if with_catalog:
        try:
            data, catalog = catalog_outputs(outputs)
        except (RecordingError, KeyError, ValueError) as error:
            print(f"normalize_runs: {type(error).__name__}: {error}", file=sys.stderr)
            return 2
    stale = [path for path, content in catalog.items() if not path.is_file() or path.read_bytes() != content]
    if args.check:
        problems = check(outputs, out)
        for problem in problems:
            print(problem, file=sys.stderr)
        for path in stale:
            print(f"normalize_runs: out of date: {path.relative_to(SESSION)}", file=sys.stderr)
        if stale:
            print("normalize_runs: rebuild with: uv run cursus/fixtures/runs/normalize_runs.py", file=sys.stderr)
        if problems or stale:
            return 1
        if with_catalog:
            print(f"normalize_runs: up to date ({len(json.loads(data)['runs'])} catalog runs)")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        (out / filename).write_bytes(content)
    for path in stale:
        path.write_bytes(catalog[path])
        print(f"normalize_runs: wrote {path.relative_to(SESSION)}")
    if with_catalog and not stale:
        print("normalize_runs: catalog already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

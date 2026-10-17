"""Normalize recorded Claude Code and Codex runs into one replay schema, agent-run/1.

    python normalize_runs.py [--raw DIR] [--out DIR] [--check]

Reads every `<run>.jsonl` in --raw (default: raw/ beside this script) with its
`<run>.meta.json` sidecar, and writes `<run>.json` into --out (default: this script's
folder). --check regenerates in memory and exits 1 if any output differs byte for byte,
is missing, or is extra (an extra file is any `*-claude.json` or `*-codex.json` without a
recording). The output is canonical JSON and depends on the input bytes only: no clock,
no randomness, no working directory, files in sorted name order.

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
"""

import argparse
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
SCHEMA = "agent-run/1"
VENDORS = ("claude", "codex")
META_FIELDS = ("task", "vendor", "cli_version", "model", "effort", "date", "argv", "exit_code", "prompt_sha256")
CODEX_TOOLS = ("command_execution", "file_change", "mcp_tool_call", "web_search")
# Codex item fields that describe the outcome rather than the call.
CODEX_RESULT_FIELDS = {"id", "type", "status", "aggregated_output", "exit_code", "result", "error"}


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=HERE / "raw", help="folder of <run>.jsonl and <run>.meta.json")
    parser.add_argument("--out", type=Path, default=HERE, help="folder for <run>.json")
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed output is stale")
    args = parser.parse_args(argv)
    try:
        outputs = render(args.raw)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.check:
        problems = check(outputs, args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        (args.out / filename).write_bytes(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())

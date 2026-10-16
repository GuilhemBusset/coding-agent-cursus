"""Normalize the Act III agent-demo recordings into the replay widget's catalog (schema 1).

Reads every raw stream in ``cursus/demos/agent/recorded/*.jsonl`` (``claude -p
--output-format stream-json --verbose`` or ``codex exec --json``), resolves each one to its
rehearsal's ``*.meta.json``, and writes ``agent-demos.json`` next to this script. The same
bytes are copied into the inline ``<script type="application/json" id="agent-runs">`` block
of ``cursus/labs/agent-loop.html``; the rest of that page is authored and left alone.

Standard library only, no network, and independent of the working directory:

    uv run cursus/fixtures/runs/normalize_runs.py           # rebuild after any --record
    uv run cursus/fixtures/runs/normalize_runs.py --check   # write nothing, exit 1 on drift

Any stream without exactly one parent rehearsal, any arm the meta does not declare, and any
meta or declared arm that no stream uses stops the run with a message.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SESSION = HERE.parents[2]
RECORDED = SESSION / "cursus/demos/agent/recorded"
CATALOG = HERE / "agent-demos.json"
PAGE = SESSION / "cursus/labs/agent-loop.html"

SCHEMA = 1
MAX_CHARS = 1200
CODEX_TOOLS = ("command_execution", "file_change", "mcp_tool_call")
CAPTURE_METHOD = {"claude": "context", "codex": "status"}
INLINE = re.compile(rb'(<script\b(?=[^>]*\bid=[\'"]agent-runs[\'"])[^>]*>)(.*?)(</script\s*>)', re.S | re.I)
SHA_ATTR = re.compile(rb'\bdata-sha256=(["\'])[^"\']*\1')
ESCAPED_AT = re.compile(r"(?<!\\)((?:\\\\)*\\[bfnrt])@")


class RecordingError(Exception):
    pass


def text_of(value):
    """Plain text of a tool result's content: a string, a list of blocks, or one block."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_of(block) for block in value)
    if isinstance(value, dict):
        return text_of(value.get("text", value.get("content", "")))
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


def decode(rows, cli, name):
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
                    steps.append(step("tool_result", text_of(block.get("content", "")), **fields))
        else:
            if kind == "turn.completed":
                usage = event.get("usage")
            item = event.get("item", {})
            typ = item.get("type")
            if kind == "item.completed" and typ in ("reasoning", "agent_message"):
                steps.append(step("thought" if typ == "reasoning" else "message", item.get("text", "")))
            elif kind == "item.started" and typ in CODEX_TOOLS:
                pending[item["id"]].append(item)
                tool_input, text = codex_call(item)
                steps.append(step("tool_call", text, tool=typ, input=tool_input))
            elif kind == "item.completed" and typ in CODEX_TOOLS:
                if not pending[item["id"]]:
                    raise RecordingError(f"{where}: {typ} completed without being started")
                pending[item["id"]].pop(0)
                exit_code = item.get("exit_code")
                fields = {"tool": typ, "is_error": item.get("status") == "failed" or exit_code not in (0, None)}
                if exit_code is not None:
                    fields["exit_code"] = exit_code
                text = item.get("aggregated_output", text_of(item.get("result", "")))
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


def build(recorded):
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
        steps, usage = decode(rows, cli, stream.name)
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
    return {"schema": SCHEMA, "runs": sorted(runs, key=lambda run: run["id"])}


def serialize(catalog):
    text = json.dumps(catalog, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    # "<" only occurs inside JSON strings; escaping it keeps "</script>" out of the inline copy.
    text = text.replace("<", "\\u003c")
    # An "@" right after a control escape ("\n@pytest.fixture") would read as "n@pytest.fixture",
    # an e-mail address to a privacy scan. Escape that "@" only; real addresses still show.
    return ESCAPED_AT.sub(r"\1\\u0040", text).encode("utf-8")


def inline_page(page, data):
    matches = list(INLINE.finditer(page))
    if len(matches) != 1:
        raise RecordingError(f"{PAGE.name}: expected one inline agent-runs script block, found {len(matches)}")
    match = matches[0]
    opening = match.group(1)
    if not SHA_ATTR.search(opening):
        raise RecordingError(f"{PAGE.name}: the agent-runs block needs a data-sha256 attribute")
    digest = hashlib.sha256(data).hexdigest().encode()
    opening = SHA_ATTR.sub(lambda m: b"data-sha256=" + m.group(1) + digest + m.group(1), opening, count=1)
    return page[:match.start()] + opening + data + match.group(3) + page[match.end():]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if an output would change")
    args = parser.parse_args(argv)
    try:
        data = serialize(build(RECORDED))
        if not PAGE.is_file():
            raise RecordingError(f"missing replay page {PAGE}")
        page = PAGE.read_bytes()
        outputs = {CATALOG: data, PAGE: inline_page(page, data)}
    except (RecordingError, KeyError, ValueError) as error:
        print(f"normalize_runs: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    stale = [path for path, content in outputs.items() if not path.is_file() or path.read_bytes() != content]
    if args.check:
        for path in stale:
            print(f"normalize_runs: out of date: {path.relative_to(SESSION)}", file=sys.stderr)
        if stale:
            print("normalize_runs: rebuild with: uv run cursus/fixtures/runs/normalize_runs.py", file=sys.stderr)
            return 1
        print(f"normalize_runs: up to date ({len(json.loads(data)['runs'])} runs)")
        return 0
    for path in stale:
        path.write_bytes(outputs[path])
        print(f"normalize_runs: wrote {path.relative_to(SESSION)}")
    if not stale:
        print("normalize_runs: already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

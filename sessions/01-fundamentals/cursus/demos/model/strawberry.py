# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Strawberry pivot: an agent miscounts letters, then writes code and gets it right.

The ask step sends the same question five times, headless, through Claude Code or
Codex with tools disabled, and checks each answer against the true count. The pivot
step asks the agent to write and run work/count_r.py instead. --record saves either
step under recorded/; --replay prints a recording with no network and no process.
The CLIs use their own logins: this script reads no API key.
"""

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RECORDED = HERE / "recorded"
WORK = HERE / "work"

# Invented: 300 letters, 146 of them r. Fixed so that recordings stay comparable.
WORD = "strawberrtorrrabbvarrstrarvarrnorturrorrberrkrerkrernorferrrorrsarrstrarerrprirstrarrorrmarrvarrerrkrernorwirrtorrrorrkrerstrarprirbrurrriorrurrbrurquirrriorrnortorrquirvarrlirrrabbferrrabbrabborrerrrorrferrprirzarrdorrquirstrarurrglererrrabbmarrerrnormarrlirrnordorrerrsarrrridorrerrdorrrorrstrarnor"

ASK = ("How many times does the letter r appear in {WORD}? Answer from memory, by reading "
       "the word: do not write code and do not use any tools. Reply with the number only.")

PIVOT = ("Write a Python file work/count_r.py that keeps this word in a variable named WORD "
         "and prints only the number of times the letter r appears in it: {WORD}. Once the "
         "file is written, run it as a separate step with exactly this command: "
         "uv run --no-project python work/count_r.py and reply with what it printed.")

# Small, fast models at low effort: the point is the failure mode, not the best score.
MODELS = {"claude": "claude-haiku-5-5", "codex": "gpt-6-luna"}
EFFORT = {"claude": "low", "codex": "low"}
RUNS = 5
TIMEOUT_S = 300
PRIVATE_KEYS = {"session_id", "thread_id", "uuid"}
CLAUDE_RESULT_KEYS = ("type", "subtype", "is_error", "num_turns", "result", "stop_reason",
                      "duration_ms", "modelUsage")
SYMBOL = {"correct": "✓", "incorrect": "✗", "unparseable": "?"}


class Failure(Exception):
    """A one-line, user-facing error."""


def prompt(template):
    return template.replace("{WORD}", WORD)


def ask_argv(cli):
    if cli == "claude":
        return ["claude", "-p", prompt(ASK), "--model", MODELS[cli], "--effort", EFFORT[cli],
                "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                "--output-format", "json"]
    return ["codex", "exec", "--json", "--sandbox", "read-only", "-m", MODELS[cli],
            "-c", f'model_reasoning_effort="{EFFORT[cli]}"', "--disable", "shell_tool",
            "--disable", "unified_exec", "--skip-git-repo-check", "--ephemeral", prompt(ASK)]


def pivot_argv(cli):
    if cli == "claude":
        return ["claude", "-p", prompt(PIVOT), "--model", MODELS[cli], "--effort", EFFORT[cli],
                "--permission-mode", "acceptEdits", "--allowedTools", "Bash(uv run:*)",
                "--strict-mcp-config", "--no-session-persistence",
                "--output-format", "stream-json", "--verbose"]
    return ["codex", "exec", "--json", "--sandbox", "workspace-write", "-m", MODELS[cli],
            "-c", f'model_reasoning_effort="{EFFORT[cli]}"', "--ephemeral", prompt(PIVOT)]


def parse_events(text):
    """CLI stdout as a list of JSON objects (one document or JSON lines)."""
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else [value]
    except ValueError:
        pass
    found = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    return [event for event in found if isinstance(event, dict)]


def scrub(value):
    """Drop private ids and make paths relative to this folder or the home folder."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if key not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        value = value.replace(str(HERE) + "/", "").replace(str(HERE), ".")
        return value.replace(str(Path.home()), "~")
    return value


def answer_text(cli, events):
    if cli == "claude":
        results = [e for e in events if e.get("type") == "result"]
        return results[-1].get("result", "") if results else ""
    return "\n".join(e["item"].get("text", "") for e in events
                     if e.get("type") == "item.completed"
                     and isinstance(e.get("item"), dict) and e["item"].get("type") == "agent_message")


def tool_assisted(cli, events):
    if cli == "claude":
        results = [e for e in events if e.get("type") == "result"]
        return bool(results) and results[-1].get("num_turns") != 1
    return any(e["item"].get("type") not in {"agent_message", "reasoning"}
               for e in events if isinstance(e.get("item"), dict))


def classify(text, truth=None):
    """One distinct integer is the answer; none or several make it unparseable."""
    truth = WORD.count("r") if truth is None else truth
    numbers = {int(n) for n in re.findall(r"\b\d+\b", text)}
    if len(numbers) != 1:
        return None, "unparseable"
    number = numbers.pop()
    return number, "correct" if number == truth else "incorrect"


def run_line(i, text, tool, truth):
    number, kind = classify(text, truth)
    shown = number if number is not None else f"{' '.join(text.split())[:40]!r}"
    return f"run {i}: {shown}  {SYMBOL[kind]}" + (" [tool used]" if tool else "")


def summary(answers, tools, truth):
    counts = Counter(classify(answer, truth)[1] for answer in answers)
    return (f"wrong: {counts['incorrect']} of {len(answers)} (unparseable: {counts['unparseable']}, "
            f"tool-assisted: {sum(tools)}; true count: {truth})")


def require(cli):
    if shutil.which(cli) is None:
        raise Failure(f"{cli} CLI not found on PATH; install and log in, or use "
                      f"`uv run strawberry.py --replay --via {cli}`")


def cli_failed(cli, code, stderr):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    detail = f" ({lines[-1][:120]})" if lines else ""
    return Failure(f"{cli} exited with status {code}{detail}; "
                   f"use `uv run strawberry.py --replay --via {cli}` instead")


def call(cli, argv, env=None):
    try:
        done = subprocess.run(argv, cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env,
                              timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure(f"{cli} could not run ({type(error).__name__}); "
                      f"use `uv run strawberry.py --replay --via {cli}` instead") from None
    if done.returncode != 0:
        raise cli_failed(cli, done.returncode, done.stderr)
    return done.stdout


def cli_version(cli):
    try:
        done = subprocess.run([cli, "--version"], cwd=HERE, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return done.stdout.strip() or "unknown"


def meta(cli, step, argv, template, events):
    data = {"demo": "strawberry", "step": step, "cli": cli, "cli_version": cli_version(cli),
            "model": MODELS[cli], "effort": EFFORT[cli], "date": date.today().isoformat(),
            "command": ["<prompt>" if arg == prompt(template) else arg for arg in argv],
            "prompt": prompt(template)}
    if cli == "claude":
        reported = sorted({name for e in events for name in (e.get("modelUsage") or {})})
        data["model_reported"] = reported
    else:
        reported = sorted({e["model"] for e in events if isinstance(e.get("model"), str)})
        data["model_reported"] = reported or [MODELS[cli]]
        if not reported:
            data["model_reported_note"] = "codex exec --json did not report a model; this is the requested ID"
    return data


def write_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ask(cli, record):
    require(cli)
    truth = WORD.count("r")
    print(f"model {MODELS[cli]} · live via {cli} · {RUNS} headless runs, tools off", flush=True)
    answers, tools, raws, everything = [], [], [], []
    for i in range(1, RUNS + 1):
        events = parse_events(call(cli, ask_argv(cli)))
        if cli == "claude":
            events = [{key: e[key] for key in CLAUDE_RESULT_KEYS if key in e}
                      for e in events if e.get("type") == "result"]
        else:
            events = [e for e in events if e.get("type") != "thread.started"]
        events = scrub(events)
        text, tool = answer_text(cli, events), tool_assisted(cli, events)
        print(run_line(i, text, tool, truth), flush=True)
        answers.append(text)
        tools.append(tool)
        raws.append(events)
        everything.extend(events)
    print(summary(answers, tools, truth))
    if record:
        write_json(RECORDED / f"strawberry-{cli}.json", {
            "meta": meta(cli, "ask", ask_argv(cli), ASK, everything), "word": WORD, "truth": truth,
            "answers": answers, "classes": [classify(a, truth)[1] for a in answers],
            "tools_used": tools, "raw": raws})


def keep_pivot_event(cli, event):
    """Whitelist what a public recording needs: tool calls, their results, the outcome."""
    kind = event.get("type")
    if cli == "claude":
        if kind == "result":
            return {key: event[key] for key in CLAUDE_RESULT_KEYS if key in event}
        if kind not in {"assistant", "user"}:
            return None
        message = event.get("message") or {}
        wanted = "tool_use" if kind == "assistant" else "tool_result"
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict) and b.get("type") == wanted]
        if not blocks:
            return None
        kept = {"role": message.get("role", kind), "content": blocks}
        if isinstance(message.get("model"), str):
            kept["model"] = message["model"]
        return {"type": kind, "message": kept}
    if kind == "turn.completed":
        return {"type": kind, "usage": event.get("usage", {})}
    item = event.get("item")
    if (isinstance(kind, str) and kind.startswith("item.") and isinstance(item, dict)
            and item.get("type") in {"command_execution", "file_change", "agent_message"}):
        return {"type": kind, "item": item}
    return None


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(result_text(item.get("text", "") if isinstance(item, dict) else item)
                         for item in content)
    return str(content)


def show_result(text, limit=12):
    lines = text.rstrip("\n").splitlines()
    for line in lines[:limit]:
        prefix = "    | " if line.lstrip().startswith(("{", "[")) else "    "
        print(prefix + line[:160])
    if len(lines) > limit:
        print(f"    … {len(lines) - limit} more lines")


def squeeze(text, width=150):
    """One line for the projector; keep both ends of a long command."""
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width // 2 - 2] + " … " + text[-(width // 2 - 2):]


def short_path(path):
    path = str(path)
    marker = "work/"
    return path[path.index(marker):] if marker in path else path


def project(cli, event):
    """Print one whitelisted event in the compact projector view."""
    if cli == "claude":
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                data = block.get("input") or {}
                detail = data.get("command") or short_path(data.get("file_path", ""))
                print(f"tool: {block.get('name')} {squeeze(detail)}")
            elif block.get("type") == "tool_result":
                show_result(result_text(block.get("content", "")))
        if event.get("type") == "result":
            print(f"agent: {squeeze(event.get('result', ''))}")
        return
    item = event.get("item") or {}
    if event.get("type") != "item.completed":
        return
    if item.get("type") == "file_change":
        for change in item.get("changes") or []:
            print(f"tool: file_change {change.get('kind')} {short_path(change.get('path', ''))}")
    elif item.get("type") == "command_execution":
        print(f"tool: command {squeeze(item.get('command', ''))}")
        show_result(str(item.get("aggregated_output", "")))
    elif item.get("type") == "agent_message":
        print(f"agent: {squeeze(item.get('text', ''))}")


def pivot(cli, record):
    require(cli)
    truth = WORD.count("r")
    print(f"model {MODELS[cli]} · live via {cli} · the agent writes and runs work/count_r.py", flush=True)
    WORK.mkdir(exist_ok=True)
    (WORK / "count_r.py").unlink(missing_ok=True)
    env = None
    if cli == "codex":
        env = dict(os.environ, UV_CACHE_DIR=str(WORK / ".uv-cache"))
    argv = pivot_argv(cli)
    with tempfile.TemporaryFile("w+", encoding="utf-8") as errors:
        try:
            process = subprocess.Popen(argv, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=errors, text=True, encoding="utf-8", errors="replace", env=env)
        except OSError as error:
            raise Failure(f"{cli} could not start ({type(error).__name__}); "
                          f"use `uv run strawberry.py --replay --pivot --via {cli}` instead") from None
        kept = []
        for line in process.stdout:
            for event in parse_events(line):
                event = keep_pivot_event(cli, event)
                if event is not None:
                    event = scrub(event)
                    kept.append(event)
                    project(cli, event)
        code = process.wait()
        errors.seek(0)
        stderr = errors.read()
    if code != 0:
        raise cli_failed(cli, code, stderr)
    print(f"true count: {truth}")
    if record:
        write_json(RECORDED / f"pivot-{cli}.json", {
            "meta": meta(cli, "pivot", argv, PIVOT, kept), "word": WORD, "truth": truth,
            "exit_code": code, "events": kept})
        written = WORK / "count_r.py"
        if not written.is_file():
            raise Failure(f"{cli} did not write work/count_r.py; nothing to record")
        (RECORDED / f"{cli}_count_r.py").write_bytes(written.read_bytes())


def load(name):
    path = RECORDED / name
    if not path.is_file():
        raise Failure(f"no recording at recorded/{name}; make one with `uv run strawberry.py --record`")
    return json.loads(path.read_text(encoding="utf-8"))


def replay(cli, step_pivot):
    data = load(f"{'pivot' if step_pivot else 'strawberry'}-{cli}.json")
    info = data["meta"]
    print(f"model {info['model']} · recorded {info['date']}")
    print(f"replaying {cli} {info.get('cli_version', '')}".rstrip())
    truth = data["truth"]
    if step_pivot:
        for event in data["events"]:
            project(cli, event)
        print(f"true count: {truth}")
        return
    for i, (text, tool) in enumerate(zip(data["answers"], data["tools_used"]), 1):
        print(run_line(i, text, tool, truth))
    print(summary(data["answers"], data["tools_used"], truth))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--via", choices=sorted(MODELS), default="claude", help="agent CLI (default: claude)")
    parser.add_argument("--pivot", action="store_true", help="ask the agent to write and run code instead")
    parser.add_argument("--record", action="store_true", help="save the run under recorded/")
    parser.add_argument("--replay", action="store_true", help="print the recording; no network, no CLI")
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record and --replay are exclusive")
    try:
        if args.replay:
            replay(args.via, args.pivot)
        elif args.pivot:
            pivot(args.via, args.record)
        else:
            ask(args.via, args.record)
    except Failure as error:
        print(f"strawberry.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

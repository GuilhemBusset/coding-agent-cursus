# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Strawberry pivot: an agent miscounts letters, then writes code and gets it right.

The ask step sends the same question five times, headless, through Claude Code or
Codex with tools disabled, and checks each answer against the true count. The pivot
step asks the agent to write and run work/count_r.py instead. With no --via, the first
installed and logged-in CLI is used (claude, then codex). --record saves either step
under recorded/; --replay prints a recording with no network and no process. The CLIs
use their own logins: this script reads no API key.
"""

import argparse
from collections import Counter
from datetime import date
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import agent_cli
from agent_cli import EFFORT, MODELS, RECORDED, WORK, Failure

SCRIPT = "strawberry.py"

# Invented: 300 letters, 146 of them r. Fixed so that recordings stay comparable.
WORD = "strawberrtorrrabbvarrstrarvarrnorturrorrberrkrerkrernorferrrorrsarrstrarerrprirstrarrorrmarrvarrerrkrernorwirrtorrrorrkrerstrarprirbrurrriorrurrbrurquirrriorrnortorrquirvarrlirrrabbferrrabbrabborrerrrorrferrprirzarrdorrquirstrarurrglererrrabbmarrerrnormarrlirrnordorrerrsarrrridorrerrdorrrorrstrarnor"

ASK = ("How many times does the letter r appear in {WORD}? Answer from memory, by reading "
       "the word: do not write code and do not use any tools. Reply with the number only.")

PIVOT = ("Write a Python file work/count_r.py that keeps this word in a variable named WORD "
         "and prints only the number of times the letter r appears in it: {WORD}. Once the "
         "file is written, run it as a separate step with exactly this command: "
         "uv run --no-project python work/count_r.py and reply with what it printed.")

RUNS = 5
SYMBOL = {"correct": "✓", "incorrect": "✗", "unparseable": "?"}
# Codex plain-mode transcript: a section starts with one of these words on its own line.
SECTIONS = {"user", "codex", "exec", "thinking", "tokens used", "file update", "apply_patch"}


def prompt(template):
    return template.replace("{WORD}", WORD)


def pivot_argv(cli, last_message=None):
    if cli == "claude":
        return ["claude", "-p", prompt(PIVOT), "--model", MODELS[cli], "--effort", EFFORT[cli],
                "--permission-mode", "acceptEdits", "--allowedTools", "Bash(uv run:*)",
                "--strict-mcp-config", "--no-session-persistence",
                "--output-format", "stream-json", "--verbose"]
    return ["codex", "exec", "--sandbox", "workspace-write", "-m", MODELS[cli],
            "-c", f'model_reasoning_effort="{EFFORT[cli]}"', "--skip-git-repo-check", "--ephemeral",
            "-o", last_message or "<last-message-file>", prompt(PIVOT)]


def tool_assisted(cli, kept):
    if cli == "claude":
        results = [e for e in kept if e.get("type") == "result"]
        return bool(results) and results[-1].get("num_turns") != 1
    return bool(re.search(r"(?:^|\n)exec\s*\n", kept.get("transcript", "")))


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
    shown = number if number is not None else " ".join(text.split())
    return f"run {i}: {shown}  {SYMBOL[kind]}" + (" [tool used]" if tool else "")


def summary(answers, tools, truth):
    counts = Counter(classify(answer, truth)[1] for answer in answers)
    return (f"wrong: {counts['incorrect']} of {len(answers)} (unparseable: {counts['unparseable']}, "
            f"tool-assisted: {sum(tools)}; true count: {truth})")


def meta(cli, step, argv, template, reported, evidence=None):
    data = {"demo": "strawberry", "step": step, "cli": cli, "cli_version": agent_cli.cli_version(cli),
            "model": MODELS[cli], "effort": EFFORT[cli], "date": date.today().isoformat(),
            "command": agent_cli.shown_command(argv, prompt(template)), "prompt": prompt(template),
            "model_reported": reported}
    if evidence is not None:
        data["model_evidence"] = evidence
    return data


def model_report(cli, kept):
    """(model_reported, model_evidence) from the kept CLI output only."""
    if cli == "claude":
        return agent_cli.reported_models(cli, kept), None
    evidence = agent_cli.banner_lines([run["transcript"] for run in kept])
    return agent_cli.reported_models(cli, evidence), evidence


def ask(via, record):
    cli = agent_cli.pick(via, SCRIPT)
    truth = WORD.count("r")
    print(f"model {MODELS[cli]} · live via {cli} · {RUNS} headless runs, tools off", flush=True)
    answers, tools, raws = [], [], []
    for i in range(1, RUNS + 1):
        text, kept = agent_cli.ask_once(cli, prompt(ASK), SCRIPT)
        tool = tool_assisted(cli, kept)
        print(run_line(i, text, tool, truth), flush=True)
        answers.append(text)
        tools.append(tool)
        raws.append(kept)
    print(summary(answers, tools, truth))
    if record:
        reported, evidence = model_report(cli, raws)
        agent_cli.write_json(RECORDED / f"strawberry-{cli}.json", {
            "meta": meta(cli, "ask", agent_cli.headless_argv(cli, prompt(ASK)), ASK, reported, evidence),
            "word": WORD, "truth": truth, "answers": answers,
            "classes": [classify(a, truth)[1] for a in answers], "tools_used": tools, "raw": raws})
        print(f"recorded to recorded/strawberry-{cli}.json")


def keep_pivot_event(event):
    """Whitelist what a public Claude Code recording needs: tool calls, their results, the outcome."""
    kind = event.get("type")
    if kind == "result":
        return {key: event[key] for key in agent_cli.CLAUDE_RESULT_KEYS if key in event}
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


def project(event):
    """Print one whitelisted Claude Code event in the compact projector view."""
    for block in (event.get("message") or {}).get("content") or []:
        if block.get("type") == "tool_use":
            data = block.get("input") or {}
            detail = data.get("command") or short_path(data.get("file_path", ""))
            print(f"tool: {block.get('name')} {squeeze(detail)}")
        elif block.get("type") == "tool_result":
            show_result(result_text(block.get("content", "")))
    if event.get("type") == "result":
        print(f"agent: {squeeze(event.get('result', ''))}")


def runs_counter(command):
    command = str(command)
    return (bool(re.search(r"(?:python3?|uv\s+run)\b[^\n]*count_r\.py\b", command))
            and not re.search(r">\s*[\"']?(?:\./)?work/count_r\.py\b", command))


def printed(text):
    """The integers the counter printed, one per line on its own."""
    return {int(n) for n in re.findall(r"(?m)^\s*(\d+)\s*$", text)}


def counter_outputs(cli, kept):
    """Output of every successful run of work/count_r.py in the kept CLI output."""
    if cli == "claude":
        runs, outputs = set(), []
        for event in kept:
            for block in (event.get("message") or {}).get("content") or []:
                if (block.get("type") == "tool_use" and block.get("name") == "Bash"
                        and runs_counter((block.get("input") or {}).get("command", ""))):
                    runs.add(block.get("id"))
                elif (block.get("type") == "tool_result" and block.get("tool_use_id") in runs
                        and not block.get("is_error", False)):
                    outputs.append(result_text(block.get("content", "")))
        return outputs
    outputs = []
    for block in re.split(r"(?:^|\n)exec\s*\n", kept)[1:]:
        block = re.split(r"\n(?:exec|thinking|codex|tokens used|file update|apply_patch)\s*\n", block)[0]
        status = re.search(r"(?m)^\s*(succeeded|exited \d+|failed)\b[^\n]*:\s*$", block)
        if status and status.group(1) == "succeeded" and runs_counter(block[:status.start()]):
            outputs.append(block[status.end():])
    return outputs


def check_counted(cli, kept, truth):
    """Fail unless the agent ran the counter successfully and it printed the true count."""
    seen = set().union(*(printed(text) for text in counter_outputs(cli, kept)))
    if truth in seen:
        return
    problem = (f"it printed {', '.join(map(str, sorted(seen)))}, not {truth}" if seen else
               "no successful run of work/count_r.py in its output")
    raise Failure(f"{cli} did not run the counter successfully: {problem}; nothing recorded\n"
                  f"Or replay the recording: {agent_cli.replay_command(SCRIPT, cli, True)}")


class Transcript:
    """Print a Codex plain-mode transcript, minus its config banner and the echoed prompt."""

    def __init__(self):
        self.rules, self.section = 0, None

    def feed(self, line):
        line = line.rstrip("\n")
        if self.rules < 2 and line.strip() not in SECTIONS:
            self.rules += line.strip() == "--------"
            return
        self.rules = 2
        if line.strip() in SECTIONS:
            self.section = line.strip()
            if self.section != "user":
                print(self.section, flush=True)
        elif self.section != "user":
            print("    " + squeeze(line, 156), flush=True)


def pivot_claude(record):
    argv = pivot_argv("claude")
    with tempfile.TemporaryFile("w+", encoding="utf-8") as errors:
        try:
            process = subprocess.Popen(argv, cwd=agent_cli.HERE, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=errors, text=True,
                                       encoding="utf-8", errors="replace")
        except OSError as error:
            raise Failure(f"claude could not start ({type(error).__name__})\nOr replay the "
                          f"recording: {agent_cli.replay_command(SCRIPT, 'claude', True)}") from None
        kept = []
        for line in process.stdout:
            for event in agent_cli.parse_events(line):
                event = keep_pivot_event(event)
                if event is not None:
                    event = agent_cli.scrub(event)
                    kept.append(event)
                    project(event)
        code = process.wait()
        errors.seek(0)
        stderr = errors.read()
    if code != 0:
        raise agent_cli.cli_failed("claude", code, stderr, SCRIPT, pivot=True)
    check_counted("claude", kept, WORD.count("r"))
    if record:
        return {"meta": meta("claude", "pivot", argv, PIVOT, agent_cli.reported_models("claude", kept)),
                "exit_code": code, "events": kept}
    return None


def pivot_codex(record):
    with tempfile.TemporaryDirectory() as scratch, \
            tempfile.TemporaryFile("w+", encoding="utf-8") as out:
        last = Path(scratch) / "last-message.txt"
        argv = pivot_argv("codex", str(last))
        try:
            process = subprocess.Popen(argv, cwd=agent_cli.HERE, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace", env=agent_cli.codex_env())
        except OSError as error:
            raise Failure(f"codex could not start ({type(error).__name__})\nOr replay the "
                          f"recording: {agent_cli.replay_command(SCRIPT, 'codex', True)}") from None
        lines, view = [], Transcript()
        for line in process.stderr:
            lines.append(line)
            view.feed(agent_cli.scrub_transcript(line))
        code = process.wait()
        out.seek(0)
        stdout = out.read()
        message = last.read_text(encoding="utf-8") if last.is_file() else ""
    transcript = agent_cli.scrub_transcript("".join(lines))
    if code != 0:
        raise agent_cli.cli_failed("codex", code, transcript + stdout, SCRIPT, pivot=True)
    check_counted("codex", transcript, WORD.count("r"))
    if record:
        evidence = agent_cli.banner_lines([transcript])
        shown = pivot_argv("codex")
        return {"meta": meta("codex", "pivot", shown, PIVOT, agent_cli.reported_models("codex", evidence),
                             evidence),
                "exit_code": code, "transcript": transcript, "last_message": message}
    return None


def pivot(via, record):
    cli = agent_cli.pick(via, SCRIPT, pivot=True)
    truth = WORD.count("r")
    print(f"model {MODELS[cli]} · live via {cli} · the agent writes and runs work/count_r.py", flush=True)
    WORK.mkdir(exist_ok=True)
    (WORK / "count_r.py").unlink(missing_ok=True)
    data = pivot_claude(record) if cli == "claude" else pivot_codex(record)
    print(f"true count: {truth}")
    if record:
        written = WORK / "count_r.py"
        if not written.is_file():
            raise Failure(f"{cli} did not write work/count_r.py; nothing recorded")
        meta_block = data.pop("meta")
        agent_cli.write_json(RECORDED / f"pivot-{cli}.json",
                             {"meta": meta_block, "word": WORD, "truth": truth, **data})
        (RECORDED / f"{cli}_count_r.py").write_bytes(written.read_bytes())
        print(f"recorded to recorded/pivot-{cli}.json and recorded/{cli}_count_r.py")


def replay(cli, step_pivot):
    data = agent_cli.load(f"{'pivot' if step_pivot else 'strawberry'}-{cli}.json", SCRIPT)
    info = data["meta"]
    print(f"model {', '.join(info['model_reported'])} · recorded {info['date']}")
    print(f"replaying {cli} {info.get('cli_version', '')}".rstrip())
    truth = data["truth"]
    if step_pivot:
        if "events" in data:
            for event in data["events"]:
                project(event)
        else:
            view = Transcript()
            for line in data["transcript"].splitlines():
                view.feed(line)
        print(f"true count: {truth}")
        return
    for i, (text, tool) in enumerate(zip(data["answers"], data["tools_used"]), 1):
        print(run_line(i, text, tool, truth))
    print(summary(data["answers"], data["tools_used"], truth))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--via", choices=agent_cli.CLIS,
                        help="agent CLI to use (default: the first installed and logged-in, "
                             "claude then codex; for --replay, claude)")
    parser.add_argument("--pivot", action="store_true", help="ask the agent to write and run code instead")
    parser.add_argument("--record", action="store_true", help="save the run under recorded/")
    parser.add_argument("--replay", action="store_true", help="print the recording; no network, no CLI")
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record and --replay are exclusive")
    try:
        if args.replay:
            replay(args.via or "claude", args.pivot)
        elif args.pivot:
            pivot(args.via, args.record)
        else:
            ask(args.via, args.record)
    except Failure as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

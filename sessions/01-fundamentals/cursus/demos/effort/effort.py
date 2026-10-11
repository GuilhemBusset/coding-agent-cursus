"""Effort dial demo: one small knapsack puzzle at low and at high effort.

    uv run effort.py                 # same as `replay`
    uv run effort.py replay          # print the recorded, dated results (no network)
    uv run effort.py live --cli claude|codex|both [--out work] [--claude-model ID] [--codex-model ID]
    uv run effort.py prompt          # print the prompt rendered from PARCELS and CAPACITY

`live` sends prompt.txt on stdin to each CLI, once at `low` and once at `high` effort, each
time from a fresh empty temporary folder outside the repository. It keeps every CLI's raw
stdout verbatim plus a meta sidecar, and writes results.json and a table. Costs are list-price
equivalents computed from prices.json (USD per million tokens). See README.md.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent

# The puzzle: (parcel, weight in kg, value in EUR). Greedy by value per kg reaches 181;
# the optimum is 229 (B, D, E, G at 62 kg), and filling the van exactly (A, B, D, G) gives 228.
PARCELS = (
    ("A", 28, 67),
    ("B", 9, 52),
    ("C", 6, 20),
    ("D", 10, 64),
    ("E", 27, 68),
    ("F", 27, 29),
    ("G", 16, 45),
    ("H", 30, 61),
)
CAPACITY = 63

EFFORTS = ("low", "high")
CLIS = ("claude", "codex")
DEFAULT_MODELS = {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"}
TIMEOUT_SECONDS = 900
DOCS = {
    "claude_effort": "https://platform.claude.com/docs/en/build-with-claude/effort",
    "codex_config": "https://developers.openai.com/codex/config-reference",
}
# thinking (Claude) and reasoning_output (Codex) are already inside output; cache_write_1h is
# the part of Claude's cache_write written to the 1-hour cache. cached_input and
# cache_write_input (Codex) are both already inside input.
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "cache_write_1h", "cached_input",
                "reasoning_output", "thinking", "cache_write_input")


class DemoError(Exception):
    pass


def render_prompt(parcels=PARCELS, capacity=CAPACITY):
    rows = "\n".join(f"| {name} | {weight} | {value} |" for name, weight, value in parcels)
    return f"""A courier van has a weight capacity of {capacity} kg. Choose which parcels to load so
that the total value of the load is as large as possible without going over the limit.
Each parcel is either loaded whole or left behind, and there is only one of each.

| Parcel | Weight (kg) | Value (EUR) |
| --- | --- | --- |
{rows}

Rules:
- Do not use tools: no code, no shell commands, no files, no search. Reason in text only.
- End your reply with one final line of the form ANSWER: <total value>, where <total value>
  is the best total value as a plain integer, with no units and no formatting.
"""


def optimum(parcels=PARCELS, capacity=CAPACITY):
    """Brute force over all 2^n subsets."""
    best = 0
    for bits in itertools.product((0, 1), repeat=len(parcels)):
        load = [parcel for take, parcel in zip(bits, parcels) if take]
        if sum(weight for _, weight, _ in load) <= capacity:
            best = max(best, sum(value for _, _, value in load))
    return best


def final_answer(text):
    """The integer on the last `ANSWER:` line, or None when it is missing or not an integer."""
    matches = re.findall(r"^\s*ANSWER\s*:\s*(.*?)\s*$", text or "", re.M)
    if not matches or not re.fullmatch(r"[+-]?\d+", matches[-1]):
        return None
    return int(matches[-1])


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_prices():
    return json.loads((HERE / "prices.json").read_text(encoding="utf-8"))


def rate_card(prices, vendor, model):
    models = prices[vendor]["models"]
    if model not in models:
        raise DemoError(f"No price for model {model!r} in prices.json ({vendor}); add its rates first")
    return models[model]


def command(cli, effort, model, workdir):
    if cli == "claude":
        return ["claude", "-p", "--output-format", "stream-json", "--verbose",
                "--effort", effort, "--model", model,
                "--no-session-persistence", "--strict-mcp-config",
                "--tools", "", "--permission-mode", "dontAsk"]
    return ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check",
            "-C", str(workdir), "--sandbox", "read-only",
            "-c", 'approval_policy="never"', "-c", f'model_reasoning_effort="{effort}"',
            "-m", model, "-"]


def parse_events(raw):
    events = []
    for line in raw.splitlines():
        if line.strip():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def one_hour_writes(result):
    """Tokens each model wrote to the 1-hour cache; the rest of its cache writes are 5-minute.

    modelUsage has no duration, so it comes from the result's usage.cache_creation split
    (ephemeral_1h / ephemeral_5m). Without a split, every write is priced at the 5-minute rate.
    """
    writes = {model: int(usage.get("cacheCreationInputTokens", 0))
              for model, usage in result["modelUsage"].items()}
    split = (result.get("usage") or {}).get("cache_creation")
    if not isinstance(split, dict):
        return {}
    hour, five = int(split.get("ephemeral_1h_input_tokens", 0)), int(split.get("ephemeral_5m_input_tokens", 0))
    if not hour:
        return {}
    if not five and hour == sum(writes.values()):
        return writes
    owners = [model for model, count in writes.items() if count and count == hour + five]
    if len(owners) == 1:
        if sum(writes.values()) != hour + five:
            print("warning: Claude reported no cache duration for some models; their cache writes "
                  "are priced at the 5-minute rate", file=sys.stderr)
        return {owners[0]: hour}
    raise DemoError(f"cannot attribute the cache-write durations {split} to the models in modelUsage")


def claude_row(events, prices):
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1 or not isinstance(results[0].get("modelUsage"), dict):
        raise DemoError("Claude output has no single result event with modelUsage")
    result = results[0]
    tokens = dict.fromkeys(TOKEN_FIELDS, 0)
    cost = 0.0
    hours = one_hour_writes(result)
    # Claude Code's counters are exclusive: input excludes cache reads and writes, and
    # output includes thinking. Every model that ran (auxiliary ones too) is priced, and
    # cache writes at the rate of the duration they were written for.
    for model, usage in result["modelUsage"].items():
        rate = rate_card(prices, "anthropic", model)
        counts = {name: int(usage.get(key, 0)) for name, key in (
            ("input", "inputTokens"), ("output", "outputTokens"),
            ("cache_read", "cacheReadInputTokens"), ("cache_write", "cacheCreationInputTokens"))}
        counts["cache_write_1h"] = hours.get(model, 0)
        for name, count in counts.items():
            tokens[name] += count
        tokens["thinking"] += int(usage.get("thinkingTokens", 0))
        cost += (counts["input"] * rate["input"]
                 + (counts["cache_write"] - counts["cache_write_1h"]) * rate["cache_write_5m"]
                 + counts["cache_write_1h"] * rate["cache_write_1h"]
                 + counts["cache_read"] * rate["cache_read"] + counts["output"] * rate["output"])
    init = [event for event in events if event.get("type") == "system" and event.get("subtype") == "init"]
    init_tools = init[0].get("tools") if init else None
    tool_calls = sum(block.get("type") == "tool_use" for event in events if event.get("type") == "assistant"
                     for block in event.get("message", {}).get("content", []))
    text = result.get("result")
    if not isinstance(text, str):
        text = "\n".join(block.get("text", "") for event in events if event.get("type") == "assistant"
                         for block in event.get("message", {}).get("content", []) if block.get("type") == "text")
    cost /= 1_000_000
    reported = result.get("total_cost_usd")
    return dict(tokens=tokens, tool_calls=tool_calls, init_tools=init_tools,
                pure_reasoning=tool_calls == 0 and init_tools == [],
                cost_usd=cost, reported_cost_usd=reported,
                cost_delta_usd=None if reported is None else cost - reported, text=text)


def codex_row(events, prices, model):
    turns = [event.get("usage") for event in events if event.get("type") == "turn.completed"]
    if not turns or not all(isinstance(usage, dict) for usage in turns):
        raise DemoError("Codex output has no turn.completed usage")
    tokens = dict.fromkeys(TOKEN_FIELDS, 0)
    # Codex's counters are inclusive: input_tokens includes cached_input_tokens and
    # cache_write_input_tokens, and output_tokens includes reasoning_output_tokens. Refuse
    # usage that breaks this.
    for usage in turns:
        counts = {name: int(usage.get(key, 0)) for name, key in (
            ("input", "input_tokens"), ("output", "output_tokens"),
            ("cached_input", "cached_input_tokens"), ("reasoning_output", "reasoning_output_tokens"),
            ("cache_write_input", "cache_write_input_tokens"))}
        if counts["cached_input"] > counts["input"]:
            raise DemoError(f"Codex usage has more cached tokens than input tokens: {usage}")
        if counts["cached_input"] + counts["cache_write_input"] > counts["input"]:
            raise DemoError(f"Codex usage has more cached and cache-write tokens than input tokens: {usage}")
        if counts["reasoning_output"] > counts["output"]:
            raise DemoError(f"Codex usage has more reasoning tokens than output tokens: {usage}")
        for name, count in counts.items():
            tokens[name] += count
    rate = rate_card(prices, "openai", model)
    if tokens["cache_write_input"] and "cache_write" not in rate:
        raise DemoError(f"Codex reported {tokens['cache_write_input']} cache-write tokens but prices.json "
                        f"has no cache_write rate for {model!r}; add it first")
    uncached = tokens["input"] - tokens["cached_input"] - tokens["cache_write_input"]
    cost = (uncached * rate["input"] + tokens["cached_input"] * rate["cached_input"]
            + tokens["cache_write_input"] * rate.get("cache_write", 0)
            + tokens["output"] * rate["output"]) / 1_000_000
    tools = set()
    for index, event in enumerate(events):
        item = event.get("item") or {}
        kind = item.get("type", "")
        if kind in {"command_execution", "web_search", "file_change"} or "tool" in kind:
            tools.add(item.get("id", f"event-{index}"))
    text = "\n".join(event["item"].get("text", "") for event in events
                     if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message")
    return dict(tokens=tokens, tool_calls=len(tools), pure_reasoning=not tools,
                cost_usd=cost, reported_cost_usd=None, text=text)


def cli_version(cli):
    result = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise DemoError(f"`{cli} --version` failed: {result.stderr.strip()}")
    return result.stdout.strip()


def run_one(cli, effort, model, version, prompt, prices, out):
    workdir = Path(tempfile.mkdtemp(prefix=f"effort-{cli}-{effort}-"))
    try:
        argv = command(cli, effort, model, workdir)
        print(f"[{utc_now()}] {cli} at {effort} effort ({model}) ...", file=sys.stderr, flush=True)
        started_at = utc_now()
        start = time.monotonic()
        result = subprocess.run(argv, cwd=workdir, input=prompt.encode("utf-8"),
                                capture_output=True, timeout=TIMEOUT_SECONDS)
        wall = round(time.monotonic() - start, 3)
        ended_at = utc_now()
        raw_dir = out / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{cli}-{effort}.jsonl").write_bytes(result.stdout)
        meta = dict(argv=[arg.replace(str(workdir), "<tmp>") for arg in argv],
                    cwd_kind="tempdir-outside-repo",
                    prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    cli_version=version, started_at=started_at, ended_at=ended_at,
                    wall_seconds=wall, exit_code=result.returncode)
        (raw_dir / f"{cli}-{effort}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if result.returncode != 0:
            tail = result.stderr.decode("utf-8", "replace").strip()[-2000:]
            raise DemoError(f"{cli} at {effort} effort exited {result.returncode}:\n{tail}")
        events = parse_events(result.stdout.decode("utf-8", "replace"))
        parsed = claude_row(events, prices) if cli == "claude" else codex_row(events, prices, model)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    text = parsed.pop("text")
    parsed.pop("init_tools", None)
    answer = final_answer(text)
    row = dict(cli=cli, cli_version=version, model=model, effort=effort, **parsed,
               wall_seconds=wall, answer=answer, correct=answer == optimum(),
               raw=f"raw/{cli}-{effort}.jsonl", meta=f"raw/{cli}-{effort}.meta.json",
               started_at=started_at)
    if cli == "codex":
        row.pop("reported_cost_usd")
    return row


def live(args):
    prompt = (HERE / "prompt.txt").read_text(encoding="utf-8")
    if prompt != render_prompt():
        raise DemoError("prompt.txt does not match PARCELS and CAPACITY; "
                        "regenerate it with `uv run effort.py prompt > prompt.txt`")
    prices = load_prices()
    out = Path(args.out)
    out = out if out.is_absolute() else HERE / out
    models = {"claude": args.claude_model, "codex": args.codex_model}
    clis = CLIS if args.cli == "both" else (args.cli,)
    runs = []
    for cli in clis:
        version = cli_version(cli)
        for effort in EFFORTS:
            runs.append(run_one(cli, effort, models[cli], version, prompt, prices, out))
    document = dict(
        run_date=min(row["started_at"] for row in runs)[:10],
        note="Costs are list-price equivalents from prices.json, in USD; subscription logins are not billed per token.",
        puzzle=dict(capacity=CAPACITY, optimum=optimum(),
                    prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest()),
        docs=DOCS, prices=prices, runs=runs)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print_table(document)
    print(f"\nWrote {out / 'results.json'}", file=sys.stderr)


def number(value):
    return "-" if value is None else f"{value:,}"


def print_table(document):
    runs = document["runs"]
    columns = ("CLI", "effort", "model", "input tok", "output tok", "cache read", "cache write",
               "reasoning", "seconds", "cost USD", "answer", "correct")
    lines = []
    for row in runs:
        tokens = row["tokens"]
        claude = row["cli"] == "claude"
        verdict = "yes" if row["correct"] else "no"
        if not row["pure_reasoning"]:
            verdict += " (used tools)"
        lines.append((row["cli"], row["effort"], row["model"], number(tokens["input"]), number(tokens["output"]),
                      number(tokens["cache_read"] if claude else tokens["cached_input"]),
                      number(tokens["cache_write"]) if claude else "-",
                      number(tokens["thinking"] if claude else tokens["reasoning_output"]),
                      f"{row['wall_seconds']:.1f}", f"{row['cost_usd']:.4f}", number(row["answer"]), verdict))
    widths = [max(len(str(line[i])) for line in (columns, *lines)) for i in range(len(columns))]
    left = {0, 1, 2, 11}
    def fmt(cells):
        return "  ".join(str(cell).ljust(width) if i in left else str(cell).rjust(width)
                         for i, (cell, width) in enumerate(zip(cells, widths))).rstrip()
    print(f"Effort dial - knapsack, capacity {document['puzzle']['capacity']} kg - "
          f"optimum by brute force over all subsets: {document['puzzle']['optimum']}")
    print(f"Run date {document['run_date']} (UTC) - prices as of {document['prices']['as_of']}, "
          "USD list-price equivalent")
    print()
    print(fmt(columns))
    print(fmt(["-" * width for width in widths]))
    for line in lines:
        print(fmt(line))
    print()
    print("Claude counts input without cache reads/writes; Codex counts cached tokens inside input.")
    print("reasoning = Claude thinking tokens or Codex reasoning tokens, already counted in output.")
    by_key = {(row["cli"], row["effort"]): row for row in runs}
    ratios = []
    for cli in CLIS:
        low, high = by_key.get((cli, "low")), by_key.get((cli, "high"))
        if low and high and low["tokens"]["output"] and low["wall_seconds"] and low["cost_usd"]:
            reasoning = "thinking" if cli == "claude" else "reasoning_output"
            extra = (f"   reasoning x{high['tokens'][reasoning] / low['tokens'][reasoning]:.1f}"
                     if low["tokens"][reasoning] else "")
            ratios.append(f"  {cli:<6}  output tokens x{high['tokens']['output'] / low['tokens']['output']:.1f}{extra}"
                          f"   seconds x{high['wall_seconds'] / low['wall_seconds']:.1f}"
                          f"   cost x{high['cost_usd'] / low['cost_usd']:.1f}")
    if ratios:
        print("High effort divided by low effort, per CLI:")
        print("\n".join(ratios))


def replay(args):
    folder = Path(args.dir)
    folder = folder if folder.is_absolute() else HERE / folder
    document = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    print_table(document)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command")
    replay_parser = commands.add_parser("replay", help="print recorded results; no network, no CLI")
    replay_parser.add_argument("--dir", default="recorded",
                               help="folder holding results.json, relative to this script (default: recorded)")
    live_parser = commands.add_parser("live", help="run the CLIs at low and high effort")
    live_parser.add_argument("--cli", choices=("claude", "codex", "both"), required=True)
    live_parser.add_argument("--out", default="work", help="output folder, relative to this script (default: work)")
    live_parser.add_argument("--claude-model", default=DEFAULT_MODELS["claude"])
    live_parser.add_argument("--codex-model", default=DEFAULT_MODELS["codex"])
    commands.add_parser("prompt", help="print the prompt rendered from PARCELS and CAPACITY")
    args = parser.parse_args(argv)
    try:
        if args.command == "live":
            live(args)
        elif args.command == "prompt":
            sys.stdout.write(render_prompt())
        else:
            replay(args if args.command == "replay" else parser.parse_args(["replay"]))
    except DemoError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

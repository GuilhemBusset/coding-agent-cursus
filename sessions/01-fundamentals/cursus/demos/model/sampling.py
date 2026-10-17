# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Sampling divergence: the same prompt five times through an agent CLI, at its default sampling.

Sends one fixed prompt five times, headless and with tools off, through Claude Code
(`claude -p`) or Codex (`codex exec`), then counts the distinct answers. Neither CLI has
a temperature option, so this shows the spread at the default sampling. With no --via,
the first installed and logged-in CLI is used (claude, then codex). --record saves the
run to recorded/sampling-<cli>.json; --replay prints it with no network and no process.
The CLIs use their own logins: this script reads no API key.
"""

import argparse
from collections import Counter
from datetime import date
import sys

import agent_cli
from agent_cli import EFFORT, MODELS, RECORDED, Failure

SCRIPT = "sampling.py"
PROMPT = "Invent a name for a new optimization solver. Reply with the name only."
RUNS = 5


def show(answers):
    for i, answer in enumerate(answers, 1):
        print(f"run {i}: {' '.join(answer.split())}")
    counts = Counter(" ".join(answer.split()) for answer in answers)
    for answer, count in counts.most_common():
        print(f"  {count} × {answer}")
    print(f"distinct answers: {len(counts)} of {len(answers)}")


def live(via, record):
    cli = agent_cli.pick(via, SCRIPT)
    print(f"model {MODELS[cli]} · live via {cli} · {RUNS} headless runs, same prompt, "
          f"default sampling", flush=True)
    print(f"prompt: {PROMPT}", flush=True)
    answers, raws = [], []
    for _ in range(RUNS):
        text, kept = agent_cli.ask_once(cli, PROMPT, SCRIPT)
        answers.append(text)
        raws.append(kept)
    show(answers)
    if record:
        info = {"demo": "sampling", "cli": cli, "cli_version": agent_cli.cli_version(cli),
                "model": MODELS[cli], "effort": EFFORT[cli], "date": date.today().isoformat(),
                "prompt": PROMPT,
                "command": agent_cli.shown_command(agent_cli.headless_argv(cli, PROMPT), PROMPT)}
        if cli == "claude":
            info["model_reported"] = agent_cli.reported_models(cli, raws)
        else:
            evidence = agent_cli.banner_lines([run["transcript"] for run in raws])
            info["model_reported"] = agent_cli.reported_models(cli, evidence)
            info["model_evidence"] = evidence
        agent_cli.write_json(RECORDED / f"sampling-{cli}.json",
                             {"meta": info, "answers": answers, "raw": raws})
        print(f"recorded to recorded/sampling-{cli}.json")


def replay(cli):
    data = agent_cli.load(f"sampling-{cli}.json", SCRIPT)
    info = data["meta"]
    print(f"model {', '.join(info['model_reported'])} · recorded {info['date']}")
    print(f"replaying {cli} {info.get('cli_version', '')}".rstrip())
    print(f"prompt: {info['prompt']}")
    show(data["answers"])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--via", choices=agent_cli.CLIS,
                        help="agent CLI to use (default: the first installed and logged-in, "
                             "claude then codex; for --replay, claude)")
    parser.add_argument("--record", action="store_true", help="save the run to recorded/sampling-<cli>.json")
    parser.add_argument("--replay", action="store_true", help="print the recording; no network, no CLI")
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record and --replay are exclusive")
    try:
        if args.replay:
            replay(args.via or "claude")
        else:
            live(args.via, args.record)
    except Failure as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

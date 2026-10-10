"""Strawberry pivot: ask an agent to count the r's in a long invented word, five times.

Live, the question goes to an agent CLI run headless with every tool withheld (Claude Code
by default, or Codex), or straight to a vendor API. The answers are compared with the true
count. --replay prints a committed recording instead, with no network and no CLI.
The second half of the demo, the pivot to code, is run by hand: see strawberry.md.
"""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

# Keep the demo folder clean: no __pycache__ beside the runbooks.
sys.dont_write_bytecode = True
import llm_api  # noqa: E402

HERE = Path(__file__).resolve().parent
# Invented and long on purpose. In rehearsal (strawberry.md) the CLIs' default models, which
# think before answering, counted 29- to 401-letter words right almost every time.
WORD = ("strawberrbrarorrfurrrrieturrparrrrinderrderrorrfurrbrarrrinrroarderrquarrberrwer"
        "rverrrasorrbrarverwerrderrwerrtorrtorrrrierrumrrievererrriederrturrorrrrrrraberr"
        "berrtorrwerrquarrorrrrumrrieverbrarrrumsorrparrrrawerrtorrderrbrarersorrarerfurr"
        "rrrparrmirrbrarorrrrumerverbrarwerrfurrquarrbrarverrrarrierrierrierrofurrorrsorr"
        "verlerrparrtorrsorrerrrinrrrararrrumderrarorrerkirrturrrrinrraorrquarrbrarverpar"
        "r")
RUNS = 5
CLI_TIMEOUT_S = 300
MAX_TOKENS = 1024
# Claude Code: -p is headless, --tools "" removes every built-in tool and
# --strict-mcp-config (with no --mcp-config) loads no MCP server, so no tool is left.
CLAUDE_FLAGS = ["--tools", "", "--strict-mcp-config", "--output-format", "json"]
# Codex: a read-only sandbox, run in an empty scratch folder, with no session saved.
CODEX_FLAGS = ["--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--color", "never"]
# The naive step is one fast pass: each CLI's small model at low effort.
CLI_MODELS = {"claude": "haiku", "codex": "gpt-6-luna"}
EFFORT = "low"
FALLBACK = "uv run --no-project --offline python strawberry.py --replay"


def prompt(name, word):
    return (HERE / name).read_text(encoding="utf-8").replace("{WORD}", word).strip()


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else HERE / path


def fail(message, code=1):
    print("error: " + message, file=sys.stderr)
    sys.exit(code)


def verdict(raw, truth):
    try:
        return "right" if int(raw.strip()) == truth else "wrong"
    except ValueError:
        return "wrong (not a number)"


def show(index, raw, truth):
    print(f"  {index}. {raw}    [{verdict(raw, truth)}]", flush=True)


def ask_cli(cli, text, model):
    """One headless CLI run. Returns (answer, reported model, extra fields)."""
    executable = shutil.which(cli)
    hint = f"Replay the recording instead: {FALLBACK} --via {cli}"
    if executable is None:
        fail(f"the {cli} CLI is not on PATH. Install it and log in, or replay the recording: "
             f"{FALLBACK} --via {cli}")
    argv = cli_argv(cli, model, text)
    argv[0] = executable
    with tempfile.TemporaryDirectory(prefix="strawberry-") as scratch:
        try:
            result = subprocess.run(argv, cwd=scratch, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, encoding="utf-8",
                                    timeout=CLI_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            fail(f"{cli} did not answer within {CLI_TIMEOUT_S} s. {hint}")
        except OSError as error:
            fail(f"could not start {cli} ({error.strerror}). {hint}")
    if result.returncode != 0:
        last = (result.stderr.strip() or result.stdout.strip()).splitlines()[-1:] or [""]
        fail(f"{cli} exited with code {result.returncode} ({last[0][:200]}). "
             f"Check that you are logged in and have quota. {hint}")
    if cli == "claude":
        try:
            data = json.loads(result.stdout)
        except ValueError:
            fail(f"claude printed something that is not JSON. {hint}")
        if data.get("is_error"):
            fail(f"claude reported an error: {data.get('result')}. {hint}")
        usage = data.get("modelUsage") or {}
        reported = (max(usage, key=lambda name: usage[name].get("outputTokens", 0))
                    if usage else data.get("model"))
        return str(data.get("result", "")).strip(), reported, {}
    found = re.search(r"^model:\s*(\S+)", result.stderr, re.M)
    # Codex logs every command it runs as an "exec" block; a read-only sandbox still
    # allows reading commands, so keep the evidence of whether it used one.
    ran = bool(re.search(r"^exec$", result.stderr, re.M))
    return result.stdout.strip(), found[1] if found else None, {"ran_command": ran}


def cli_argv(cli, model, text):
    if cli == "claude":
        return [cli, "-p", text, "--model", model, "--effort", EFFORT, *CLAUDE_FLAGS]
    return [cli, "exec", "--model", model, "-c", f'model_reasoning_effort="{EFFORT}"',
            *CODEX_FLAGS, text]


def cli_version(cli):
    result = subprocess.run([shutil.which(cli), "--version"], capture_output=True, text=True,
                            encoding="utf-8", timeout=60, check=False,
                            stdin=subprocess.DEVNULL)
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"


def live(args, word):
    truth = word.count("r")
    text = prompt("ask.txt", word)
    keyed = args.via in llm_api.KEY_VARS
    if keyed:
        llm_api.require_key(args.via)
    print(f"Asking {args.via} {RUNS} times: how many r's in {word}?", flush=True)
    meta = {"via": args.via, "date": date.today().isoformat(), "prompt": text,
            "script": "strawberry.py", "requested_model": args.model}
    answers, models = [], []
    for index in range(1, RUNS + 1):
        if keyed:
            model = args.model or llm_api.DEFAULT_MODELS[args.via]
            try:
                raw, reported = llm_api.complete(args.via, model, text, MAX_TOKENS)
            except llm_api.ApiError as error:
                fail(f"{llm_api.VENDORS[args.via]} API: {error.message}")
            extra = {}
        else:
            raw, reported, extra = ask_cli(args.via, text, args.model or CLI_MODELS[args.via])
        models.append(reported)
        answers.append({"raw": raw, "verdict": verdict(raw, truth), "model": reported, **extra})
        show(index, raw, truth)
    wrong = sum(answer["verdict"] != "right" for answer in answers)
    print(f"True count: {truth}. Wrong answers: {wrong} of {RUNS}.")
    if keyed:
        meta.update(provider=args.via, endpoint=llm_api.endpoint(args.via),
                    requested_model=args.model or llm_api.DEFAULT_MODELS[args.via],
                    params={"temperature": "vendor default", "tools": "none sent",
                            "max_tokens": MAX_TOKENS})
    else:
        model = args.model or CLI_MODELS[args.via]
        meta.update(cli=args.via, cli_version=cli_version(args.via), requested_model=model,
                    params={"command": cli_argv(args.via, model, "<prompt>"), "effort": EFFORT,
                            "tools": ('withheld: --tools "" --strict-mcp-config'
                                      if args.via == "claude" else "withheld: --sandbox read-only"),
                            "temperature": "vendor default", "cwd": "empty scratch folder"})
    meta["model"] = models[0] if len(set(models)) == 1 else ", ".join(dict.fromkeys(map(str, models)))
    if args.record:
        record(resolve(args.record), {"meta": meta, "word": word, "truth": truth, "answers": answers})


def record(path, data):
    meta = data["meta"]
    same = ("via", "cli", "provider", "requested_model", "prompt")
    try:
        old = json.loads(path.read_text(encoding="utf-8"))["meta"]
        repeat = all(old.get(key) == meta.get(key) for key in same)
        meta["attempt"] = old.get("attempt", 0) + 1 if repeat else 1
    except (OSError, ValueError, KeyError, TypeError):
        meta["attempt"] = 1
    data["meta"] = dict(sorted(meta.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded to {path.name} (attempt {meta['attempt']}).")


def replay(args):
    path = resolve(args.replay or f"recorded/strawberry-{args.via}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        fail(f"cannot read the recording {path.name}: {error}")
    meta = data["meta"]
    tool = meta.get("cli") or meta.get("provider")
    version = f" {meta['cli_version']}" if meta.get("cli_version") else ""
    print(f"Recorded run, replayed offline from recorded/{path.name}")
    print(f"{tool}{version} · model {meta['model']} · recorded {meta['date']} · "
          f"attempt {meta.get('attempt', 1)}")
    print(f"How many r's in {data['word']}? True count: {data['truth']}.")
    for index, answer in enumerate(data["answers"], 1):
        raw = answer["raw"] if isinstance(answer, dict) else str(answer)
        show(index, raw, data["truth"])
    wrong = sum(verdict(a["raw"] if isinstance(a, dict) else str(a), data["truth"]) != "right"
                for a in data["answers"])
    print(f"Wrong answers: {wrong} of {len(data['answers'])}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--via", choices=["claude", "codex", "anthropic", "openai"],
                        default="claude", help="who answers (default: claude)")
    parser.add_argument("--word", default=WORD, help=f"the word to count in (default: the {len(WORD)}-letter WORD "
                        "constant in this file)")
    parser.add_argument("--model", help="model to request (default: haiku for claude, gpt-6-luna for codex, "
                        "llm_api.DEFAULT_MODELS for the API modes)")
    parser.add_argument("--record", metavar="PATH",
                        help="save the run as JSON (relative paths are beside this script)")
    parser.add_argument("--replay", nargs="?", const="", metavar="PATH",
                        help="print a recording offline (default: recorded/strawberry-<via>.json)")
    parser.add_argument("--print-prompts", action="store_true",
                        help="print the two prompts with the word filled in, then exit")
    args = parser.parse_args()
    if not args.word.isalpha():
        parser.error("--word must contain letters only")
    if args.print_prompts:
        print("Ask (ask.txt):\n" + prompt("ask.txt", args.word))
        print("\nPivot (pivot.txt):\n" + prompt("pivot.txt", args.word))
    elif args.replay is not None:
        replay(args)
    else:
        live(args, args.word)


if __name__ == "__main__":
    main()

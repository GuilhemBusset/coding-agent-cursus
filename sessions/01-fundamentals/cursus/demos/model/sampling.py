"""Sampling divergence: one prompt, five times at a low and five times at a high temperature.

Calls the vendor API directly, because only the API lets you set the temperature. Sends
`temperature` alone: no top_p, no thinking or reasoning options. Prints the answers side by
side and how many distinct answers each temperature gave.

  --probe   asks each --model once with a temperature and records which models accept it
  --replay  prints the committed recording, with no key and no network
"""

import argparse
from datetime import date
import json
from pathlib import Path
import sys

# Keep the demo folder clean: no __pycache__ beside the runbooks.
sys.dont_write_bytecode = True
import llm_api  # noqa: E402

HERE = Path(__file__).resolve().parent
PROMPT = "Invent a name for a new optimization solver. Reply with the name only."
PROBE_PROMPT = "Reply with the word ok."
RUNS = 5
MAX_TOKENS = 256
FALLBACK = "uv run --no-project --offline python sampling.py --replay"


def resolve(path):
    path = Path(path)
    return path if path.is_absolute() else HERE / path


def fail(message, code=1):
    print("error: " + message, file=sys.stderr)
    sys.exit(code)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def table(runs):
    """Two columns, one row per draw, then the spread."""
    low, high = sorted(runs, key=lambda run: run["temperature"])
    left = [f"T={low['temperature']}", *low["outputs"]]
    right = [f"T={high['temperature']}", *high["outputs"]]
    width = max(len(line) for line in left)
    labels = ["", *(str(index) for index in range(1, len(left)))]
    for label, a, b in zip(labels, left, right):
        print(f"{label:>2}  {a.ljust(width)}  |  {b}")
    counts = [len(set(run["outputs"])) for run in (low, high)]
    print(f"distinct outputs: {counts[0]} of {len(low['outputs'])} at T={low['temperature']}, "
          f"{counts[1]} of {len(high['outputs'])} at T={high['temperature']}")
    if any("\n" in text for run in runs for text in run["outputs"]):
        for run in (low, high):
            print(f"\nFull outputs at T={run['temperature']}:")
            for text in run["outputs"]:
                print(text)


def live(args, model):
    llm_api.require_key(args.provider)
    runs, served = [], set()
    for temperature in (args.low, args.high):
        outputs = []
        for _ in range(RUNS):
            try:
                text, echoed = llm_api.complete(args.provider, model, PROMPT, MAX_TOKENS,
                                                temperature=temperature)
            except llm_api.ApiError as error:
                fail(f"{llm_api.VENDORS[args.provider]} API rejected model {model} at "
                     f"temperature {temperature}: {error.message}")
            outputs.append(text)
            served.add(echoed)
        runs.append({"temperature": temperature, "outputs": outputs})
    print(f"{args.provider} · {model} · prompt: {PROMPT}")
    table(runs)
    if args.record:
        meta = {"provider": args.provider, "endpoint": llm_api.endpoint(args.provider),
                "model": model, "requested_model": model,
                "served_model": sorted(served)[0] if len(served) == 1 else sorted(served),
                "date": date.today().isoformat(), "prompt": PROMPT, "script": "sampling.py",
                "params": {"temperatures": [args.low, args.high], "runs_per_temperature": RUNS,
                           "max_tokens": MAX_TOKENS, "top_p": "not sent",
                           "thinking or reasoning": "not sent"}}
        path = resolve(args.record)
        old = (load(path) or {}).get("meta", {})
        same = all(old.get(key) == meta[key] for key in ("provider", "model", "prompt", "params"))
        meta["attempt"] = old.get("attempt", 0) + 1 if same else 1
        write(path, {"meta": dict(sorted(meta.items())), "runs": runs})
        print(f"Recorded to {path.name} (attempt {meta['attempt']}).")


def probe(args, models):
    llm_api.require_key(args.provider)
    today = date.today().isoformat()
    entries = []
    for model in models:
        entry = {"provider": args.provider, "model": model,
                 "endpoint": llm_api.endpoint(args.provider), "temperature": args.low,
                 "date": today}
        try:
            llm_api.complete(args.provider, model, PROBE_PROMPT, 16, temperature=args.low)
        except llm_api.ApiError as error:
            if error.status in (None, 401, 403):  # Unreachable or unauthorised: not a verdict.
                fail(f"{llm_api.VENDORS[args.provider]} API: {error.message}")
            entry.update(accepted=False, http_status=error.status, error=error.message)
        else:
            entry.update(accepted=True, http_status=200, error=None)
        entries.append(entry)
        print(f"{model}: temperature={args.low} "
              f"{'accepted' if entry['accepted'] else 'rejected: ' + entry['error']}")
    path = resolve(args.record or "recorded/temperature_probe.json")
    old = load(path) or {}
    kept = [entry for entry in old.get("models", []) if entry.get("provider") != args.provider]
    meta = {"date": today, "attempt": old.get("meta", {}).get("attempt", 0) + 1,
            "prompt": PROBE_PROMPT, "script": "sampling.py",
            "note": "One request per model with only temperature set; HTTP 4xx = rejected."}
    write(path, {"meta": meta, "models": kept + entries})
    print(f"Recorded to {path.name}.")


def replay(args):
    path = resolve(args.replay or "recorded/sampling.json")
    data = load(path)
    if data is None:
        fail(f"cannot read the recording {path.name}")
    meta = data["meta"]
    print(f"Recorded run, replayed offline from recorded/{path.name}")
    print(f"{meta['provider']} · model {meta['model']} · recorded {meta['date']} · "
          f"attempt {meta.get('attempt', 1)}")
    print(f"prompt: {meta['prompt']}")
    table(data["runs"])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=sorted(llm_api.KEY_VARS), default="anthropic",
                        help="which vendor API to call (default: anthropic)")
    parser.add_argument("--model", action="append",
                        help="model ID (default: llm_api.DEFAULT_MODELS); repeat with --probe")
    parser.add_argument("--low", type=float, default=0.0, help="low temperature (default 0.0)")
    parser.add_argument("--high", type=float, default=1.0, help="high temperature (default 1.0)")
    parser.add_argument("--probe", action="store_true",
                        help="record which --model values accept a temperature")
    parser.add_argument("--record", metavar="PATH",
                        help="save the run as JSON (relative paths are beside this script)")
    parser.add_argument("--replay", nargs="?", const="", metavar="PATH",
                        help="print a recording offline (default: recorded/sampling.json)")
    args = parser.parse_args()
    models = args.model or [llm_api.DEFAULT_MODELS[args.provider]]
    if args.replay is not None:
        replay(args)
    elif args.probe:
        probe(args, models)
    elif len(models) > 1:
        parser.error("give one --model, or use --probe to try several")
    else:
        live(args, models[0])


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Sampling divergence: one prompt, five times at a low and five at a high temperature.

Calls the Anthropic Messages API or the OpenAI Chat Completions API with the standard
library only. The key comes from ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment
and goes into the auth header only. --record saves the run to recorded/sampling.json;
--replay prints that recording with no key and no network. --fixture is a labelled offline
stand-in, not the API: it draws GPT-2's next token from the committed logits in
cursus/fixtures/next_token.json.
"""

import argparse
from datetime import date
import json
import math
import os
from pathlib import Path
import random
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
RECORDING = HERE / "recorded" / "sampling.json"
FIXTURE = HERE.parents[1] / "fixtures" / "next_token.json"
FIXTURE_PROMPT = "open-ended"
FIXTURE_MODEL = "openai-community/gpt2"
SEED = 2026
STAND_IN = "uv run --offline sampling.py --fixture"

PROMPT = "Invent a name for a new optimization solver. Reply with the name only."
RUNS = 5
MAX_TOKENS = 20
TIMEOUT_S = 60
# Both accept `temperature`; see "Temperature support" in sampling.md before changing one.
DEFAULT_MODELS = {"anthropic": "claude-opus-4-6", "openai": "gpt-4.1-mini"}
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
BASES = {"anthropic": ("ANTHROPIC_BASE_URL", "https://api.anthropic.com", "/v1/messages"),
         "openai": ("OPENAI_BASE_URL", "https://api.openai.com/v1", "/chat/completions")}


class Failure(Exception):
    """A one-line, user-facing error, with the exit code to use."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def endpoint(provider):
    variable, default, path = BASES[provider]
    return (os.environ.get(variable) or default).rstrip("/") + path


def request(provider, model, temperature, key):
    body = {"model": model, "temperature": temperature,
            "messages": [{"role": "user", "content": PROMPT}]}
    headers = {"content-type": "application/json"}
    if provider == "anthropic":
        body["max_tokens"] = MAX_TOKENS
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        body["max_completion_tokens"] = MAX_TOKENS
        headers["authorization"] = "Bearer " + key
    call = Request(endpoint(provider), data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(call, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            message = json.loads(error.read().decode("utf-8"))["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = error.reason
        raise Failure(f"{provider} API error {error.code}: {message}") from None
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise Failure(f"{provider} API unreachable ({reason}); use `uv run sampling.py --replay`") from None
    if provider == "anthropic":
        text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
        reason = ("stop_reason", data.get("stop_reason"))
    else:
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        reason = ("finish_reason", choice.get("finish_reason"))
    response = {"id": data.get("id"), "model_reported": data.get("model"), reason[0]: reason[1],
                "usage": data.get("usage")}
    return " ".join(text.split()), response


def show(runs):
    low, high = runs
    width = max(len(text) for text in low["outputs"] + [f"T = {low['temperature']}"])
    print(f"   {'T = ' + str(low['temperature']):<{width}} | T = {high['temperature']}")
    for i, (left, right) in enumerate(zip(low["outputs"], high["outputs"]), 1):
        print(f"{i}  {left:<{width}} | {right}")
    for item in runs:
        print(f"distinct answers at temperature {item['temperature']}: {len(set(item['outputs']))} of {RUNS}")


def live(args):
    key = os.environ.get(KEYS[args.provider], "")
    if not key.strip():
        raise Failure(f"{KEYS[args.provider]} is not set; export it to call the API, "
                      f"or run `uv run sampling.py --replay` for the recording", code=2)
    model = args.model or DEFAULT_MODELS[args.provider]
    print(f"model {model} · live via the {args.provider} API · {RUNS} runs per temperature", flush=True)
    runs = []
    for temperature in (args.low, args.high):
        outputs, responses = [], []
        for _ in range(RUNS):
            text, response = request(args.provider, model, temperature, key.strip())
            outputs.append(text)
            responses.append(response)
        runs.append({"temperature": temperature, "outputs": outputs, "responses": responses})
    show(runs)
    if args.record:
        RECORDING.parent.mkdir(exist_ok=True)
        data = {"meta": {"demo": "sampling", "provider": args.provider, "model": model,
                         "endpoint": endpoint(args.provider), "date": date.today().isoformat(),
                         "prompt": PROMPT, "max_tokens": MAX_TOKENS},
                "runs": runs}
        RECORDING.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded to recorded/{RECORDING.name}")


def replay():
    if not RECORDING.is_file():
        raise Failure("no recording: recorded/sampling.json is missing; make it with "
                      "`uv run sampling.py --record` and ANTHROPIC_API_KEY or OPENAI_API_KEY set, "
                      f"or run `{STAND_IN}` for the GPT-2 stand-in (not the API)")
    data = json.loads(RECORDING.read_text(encoding="utf-8"))
    info = data["meta"]
    print(f"model {info['model']} · recorded {info['date']}")
    print(f"prompt: {info['prompt']}")
    show(data["runs"])


def draw(top, temperature, rng):
    """One next token from softmax(z / T) over the top 20 only, renormalised; T = 0 is argmax."""
    best = max(top, key=lambda item: item["logit"])
    if temperature == 0:
        return best["text"]
    weights = [math.exp((item["logit"] - best["logit"]) / temperature) for item in top]
    return rng.choices([item["text"] for item in top], weights=weights)[0]


def fixture(args):
    if not FIXTURE.is_file():
        raise Failure("no fixture: cursus/fixtures/next_token.json is missing from this session")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entry = next(item for item in data["prompts"] if item["id"] == FIXTURE_PROMPT)
    model = next(item for item in data["meta"]["models"] if item["id"] == FIXTURE_MODEL)
    print(f"GPT-2 stand-in, not the API · {model['id']} @ {model['revision'][:12]} · "
          f"logits of {data['meta']['date']} · top-20 renormalised · seed {args.seed}")
    print(f"prompt: {entry['prompt']!r} → next token")
    rng = random.Random(args.seed)
    runs = [{"temperature": temperature,
             "outputs": [repr(draw(entry["top"], temperature, rng)) for _ in range(RUNS)]}
            for temperature in (args.low, args.high)]
    show(runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=sorted(DEFAULT_MODELS), default="anthropic",
                        help="API to call (default: anthropic)")
    parser.add_argument("--model", help="model ID (default: %s)" % ", ".join(
        f"{p}: {m}" for p, m in DEFAULT_MODELS.items()))
    parser.add_argument("--low", type=float, default=0.0, help="low temperature (default: 0.0)")
    parser.add_argument("--high", type=float, default=1.0, help="high temperature (default: 1.0)")
    parser.add_argument("--record", action="store_true", help="save the run to recorded/sampling.json")
    parser.add_argument("--replay", action="store_true", help="print the recording; no key, no network")
    parser.add_argument("--fixture", action="store_true",
                        help="offline GPT-2 stand-in from cursus/fixtures/next_token.json; not the API")
    parser.add_argument("--seed", type=int, default=SEED, help=f"--fixture sampling seed (default: {SEED})")
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record and --replay are exclusive")
    for other in ("record", "replay"):
        if args.fixture and getattr(args, other):
            parser.error(f"--fixture and --{other} are exclusive: the stand-in never reads or writes recordings")
    if args.fixture and args.low < 0:
        parser.error(f"--low temperature ({args.low}) must be 0 or more")
    if args.low >= args.high:
        parser.error(f"--low temperature ({args.low}) must be below --high ({args.high})")
    try:
        if args.fixture:
            fixture(args)
        else:
            replay() if args.replay else live(args)
    except Failure as error:
        print(f"sampling.py: {error}", file=sys.stderr)
        return error.code
    return 0


if __name__ == "__main__":
    sys.exit(main())

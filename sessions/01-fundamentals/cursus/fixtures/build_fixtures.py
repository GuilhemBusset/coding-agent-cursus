"""Export real model traces for the Act I widgets as committed JSON.

Run from sessions/01-fundamentals (instructors only; Linux, CPU, a few minutes):

    uv run --locked --group fixtures python cursus/fixtures/build_fixtures.py

Writes next_token.json, attention.json and base_vs_instruct.json next to this
script (or into --out DIR). The output is byte-identical across runs: pinned
model revisions, CPU float32, one thread, greedy decoding, logits rounded to
3 decimals, attention quantized to 0..255 and canonical JSON. To move to newer
models, bump REVISIONS and EXPORT_DATE together, rerun and commit the result.
"""

import argparse
import gc
import json
from pathlib import Path

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer


GPT2 = "openai-community/gpt2"
BASE = "HuggingFaceTB/SmolLM2-135M"
INSTRUCT = "HuggingFaceTB/SmolLM2-135M-Instruct"

# Commit SHAs from https://huggingface.co/api/models/<id> (field "sha").
REVISIONS = {
    GPT2: "607a30d783dfa663caf39e06633721c8d4cfcd7e",
    BASE: "93efa2f097d58c2a74874c7e644dbc9b0cee75a2",
    INSTRUCT: "12fd25f77366fa6b3b4b768ec3050bf629380bac",
}
# The day the revisions above were pinned and first exported, not the wall clock.
EXPORT_DATE = "2026-10-10"

DEVICE = "cpu"
TOP_K = 20
LOGIT_DECIMALS = 3
ATTENTION_SCALE = 255
MAX_NEW_TOKENS = 48

# (id, category, prompt, expected token text in GPT-2's real top 20 or None)
NEXT_TOKEN_PROMPTS = [
    ("or-minimize-total", "or", "The transport problem: choose shipments to minimize total", " cost"),
    ("or-subject-to", "or", "minimize 3x + 2y subject to", None),
    ("or-objective", "or", "In linear programming, the function we optimize is called the objective", " function"),
    ("or-vertex", "or", "The simplex method moves from one vertex of the feasible region to", None),
    ("or-constraints", "or", "x + y <= 10, x >= 0, y >=", " 0"),
    ("strawberry", "tokenization", " strawberry", None),
    ("strawberry-count", "tokenization", "The number of times the letter r appears in the word strawberry is", None),
    ("factual-capital", "factual", "The capital of France is", " Paris"),
    ("factual-landmark", "factual", "The Eiffel Tower is located in the city of", " Paris"),
    ("factual-analogy", "factual", "Paris is to France as Berlin is to", " Germany"),
    ("numeric-sequence", "numeric", "2, 4, 6, 8,", " 10"),
    ("numeric-arithmetic", "numeric", "12 + 7 =", None),
    ("numeric-year", "numeric", "Columbus sailed across the Atlantic in the year", " 14"),
    ("story-opening", "story", "Once upon a time", ","),
    ("idiom-thanks", "idiom", "Thank you very", " much"),
    ("idiom-shakespeare", "idiom", "To be or not to", " be"),
    ("code-import", "code", "import numpy as", " np"),
    ("code-return", "code", "def add(a, b):\n    return a", " +"),
    ("multilingual-french", "multilingual", "Le chat est sur la", None),
    ("open-ended", "open", "The best thing about learning is", None),
]

ATTENTION_SENTENCE = "The animal didn't cross the street because it was too tired."
ATTENTION_FOCUS = "it"
ATTENTION_REFERENT = "animal"

COMPARISON_PROMPTS = [
    ("factual", "What is the capital of Australia?"),
    ("lp-word-problem",
     "A bakery makes bread and cakes. Each loaf of bread earns $3 and each cake earns $5. "
     "Both need 1 hour of oven time and the oven is free for 40 hours. At most 15 cakes can "
     "be sold. How many of each should the bakery make to maximize profit?"),
    ("strawberry", "How many r's are in strawberry?"),
    ("dual-variable", "Explain in one sentence what a dual variable is in linear programming."),
    ("haiku", "Write a haiku about optimization."),
]


def configure():
    torch.manual_seed(0)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    transformers.logging.set_verbosity_error()


def load(model_id, attention=False):
    revision = REVISIONS[model_id]
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
    options = {"attn_implementation": "eager"} if attention else {}
    model = AutoModelForCausalLM.from_pretrained(
        model_id, revision=revision, dtype=torch.float32, use_safetensors=True, **options
    ).to(DEVICE)
    model.eval()
    return tokenizer, model


def meta(model_ids, **notes):
    return {
        "generator": "cursus/fixtures/build_fixtures.py",
        "models": [{"id": model_id, "revision": REVISIONS[model_id]} for model_id in model_ids],
        "libraries": {"torch": torch.__version__, "transformers": transformers.__version__},
        "date": EXPORT_DATE,
        "device": DEVICE,
        "dtype": "float32",
        **notes,
    }


def token_records(tokenizer, ids):
    return [{"id": token_id, "text": tokenizer.decode([token_id])} for token_id in ids]


def rounded(value):
    return round(float(value), LOGIT_DECIMALS)


def next_token(tokenizer, model):
    prompts = []
    for prompt_id, category, prompt, expect in NEXT_TOKEN_PROMPTS:
        encoded = tokenizer(prompt, return_tensors="pt")
        logits = model(**encoded).logits[0, -1].float()
        values = [rounded(value) for value in logits.tolist()]
        # Rank on the rounded values with ties by id, so the order never depends on topk.
        top_ids = sorted(range(len(values)), key=lambda token_id: (-values[token_id], token_id))[:TOP_K]
        top = [{"id": token_id, "text": tokenizer.decode([token_id]), "logit": values[token_id]}
               for token_id in top_ids]
        item = {
            "id": prompt_id,
            "category": category,
            "prompt": prompt,
            "prompt_tokens": token_records(tokenizer, encoded["input_ids"][0].tolist()),
            "logsumexp": rounded(torch.logsumexp(logits, dim=-1)),
            "top": top,
        }
        if expect is not None:
            if expect not in [record["text"] for record in top]:
                raise SystemExit(f"{prompt_id}: expected {expect!r} is not in the top {TOP_K}")
            item["expect"] = expect
        prompts.append(item)
    return {
        "meta": meta([GPT2], logits={
            "decimals": LOGIT_DECIMALS,
            "position": "last prompt token",
            "top": TOP_K,
            "order": "descending rounded logit, ties by ascending token id",
            "logsumexp": "over the full vocabulary, before rounding the logits",
        }),
        "prompts": prompts,
    }


def attention(tokenizer, model):
    encoded = tokenizer(ATTENTION_SENTENCE, return_tensors="pt")
    tokens = token_records(tokenizer, encoded["input_ids"][0].tolist())
    texts = [token["text"].strip() for token in tokens]
    focus = texts.index(ATTENTION_FOCUS)
    referent = texts.index(ATTENTION_REFERENT)
    attentions = model(**encoded, output_attentions=True).attentions
    weights = [[[[round(float(weight) * ATTENTION_SCALE) for weight in row]
                 for row in head.tolist()]
                for head in layer[0]]
               for layer in attentions]
    return {
        "meta": meta([GPT2], quantization={
            "scale": ATTENTION_SCALE,
            "rule": "round(weight * scale), Python ties-to-even; divide by scale to recover",
            "layout": "weights[layer][head][query][key], zeros above the causal diagonal",
        }),
        "sentence": ATTENTION_SENTENCE,
        "tokens": tokens,
        "focus": focus,
        "referent": referent,
        "scale": ATTENTION_SCALE,
        "layers": len(weights),
        "heads": len(weights[0]),
        "weights": weights,
    }


def complete(tokenizer, model, prompt, chat):
    if chat:
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], add_generation_prompt=True, tokenize=False
        )
        encoded = tokenizer(text, return_tensors="pt", add_special_tokens=False)
    else:
        text = prompt
        encoded = tokenizer(prompt, return_tensors="pt")
    eos = model.generation_config.eos_token_id
    if eos is None:
        eos = tokenizer.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    pad = tokenizer.pad_token_id
    if pad is None:
        pad = eos_ids[0]
    # Explicit greedy settings override any sampling defaults in generation_config.
    generated = model.generate(
        **encoded, do_sample=False, num_beams=1, max_new_tokens=MAX_NEW_TOKENS,
        pad_token_id=pad, eos_token_id=eos,
    )
    new_ids = generated[0, encoded["input_ids"].shape[1]:].tolist()
    return {
        "input": text,
        "text": tokenizer.decode(new_ids, skip_special_tokens=True),
        "token_ids": new_ids,
        "stop": "eos" if new_ids[-1] in eos_ids else "length",
    }


def base_vs_instruct():
    items = [{"id": item_id, "prompt": prompt} for item_id, prompt in COMPARISON_PROMPTS]
    for variant, model_id in (("base", BASE), ("instruct", INSTRUCT)):
        tokenizer, model = load(model_id)
        for item in items:
            item[variant] = complete(tokenizer, model, item["prompt"], chat=variant == "instruct")
        del tokenizer, model
        gc.collect()
    return {
        "meta": meta([BASE, INSTRUCT], decoding={
            "strategy": "greedy",
            "do_sample": False,
            "num_beams": 1,
            "max_new_tokens": MAX_NEW_TOKENS,
            "base_input": "the raw prompt",
            "instruct_input": "the tokenizer's chat template with one user turn and the generation prompt",
            "kept": "new tokens only, text decoded with special tokens skipped",
        }),
        "max_new_tokens": MAX_NEW_TOKENS,
        "items": items,
    }


def write(path, data):
    text = json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"wrote {path} ({len(text.encode('utf-8'))} bytes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent,
                        help="output directory (default: next to this script)")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    configure()
    with torch.inference_mode():
        tokenizer, model = load(GPT2, attention=True)
        write(out / "next_token.json", next_token(tokenizer, model))
        write(out / "attention.json", attention(tokenizer, model))
        del tokenizer, model
        gc.collect()
        write(out / "base_vs_instruct.json", base_vs_instruct())


if __name__ == "__main__":
    main()

"""Independent model replay for issue 27 (explicit selection only).

Run from the session directory:
  uv run --locked --group fixtures pytest -q -p no:cacheprovider tests/fixture_replay_checks.py

The builder's initial online export must populate the Hugging Face cache first.
These checks use local_files_only=True, so replay itself is offline. A missing
library, cache entry or revision is a failure, never a skip. No builder code is
imported or executed; every expected value comes from the pinned model weights.
"""

import ast
import gc
import json
import math
from pathlib import Path
import re

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer


FIXTURES = Path(__file__).resolve().parents[1] / "cursus" / "fixtures"
GPT2 = "openai-community/gpt2"
BASE = "HuggingFaceTB/SmolLM2-135M"
INSTRUCT = BASE + "-Instruct"


def read_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def provenance(data, expected_ids):
    meta = data["meta"]
    assert meta["device"] == "cpu" and meta["dtype"] == "float32"
    assert meta["libraries"] == {
        "torch": torch.__version__, "transformers": transformers.__version__
    }, "Replay must use exactly the recorded library versions"
    tree = ast.parse((FIXTURES / "build_fixtures.py").read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    models = meta["models"]
    assert len(models) == len(expected_ids)
    assert {model["id"] for model in models} == set(expected_ids)
    revisions = {}
    for model in models:
        revision = model["revision"]
        assert re.fullmatch(r"[0-9a-fA-F]{40}", revision)
        assert revision in literals, "Model revision must be literal in builder"
        revisions[model["id"]] = revision
    return revisions


def load_model(model_id, revision, attention=False):
    tokenizer = AutoTokenizer.from_pretrained(
        model_id, revision=revision, local_files_only=True
    )
    options = {"attn_implementation": "eager"} if attention else {}
    model = AutoModelForCausalLM.from_pretrained(
        model_id, revision=revision, dtype=torch.float32,
        use_safetensors=True, local_files_only=True, **options
    ).to("cpu")
    model.eval()
    assert all(parameter.device.type == "cpu" for parameter in model.parameters())
    assert all(parameter.dtype == torch.float32 for parameter in model.parameters()
               if parameter.is_floating_point())
    return tokenizer, model


def token_records(tokenizer, ids):
    return [{"id": token_id, "text": tokenizer.decode([token_id])} for token_id in ids]


def close_number(stored, actual, context):
    assert type(stored) in (int, float) and math.isfinite(stored), context
    assert abs(stored - actual) <= 0.002 + 1e-12, (context, stored, actual)


def replay_next_token(data, tokenizer, model):
    assert len(data["prompts"]) == 20
    for item in data["prompts"]:
        encoded = tokenizer(item["prompt"], return_tensors="pt")
        assert item["prompt_tokens"] == token_records(tokenizer, encoded["input_ids"][0].tolist()), item["id"]
        logits = model(**encoded).logits[0, -1].float()
        assert logits.numel() == 50257
        rounded = [round(float(value), 3) for value in logits.tolist()]
        top_ids = sorted(range(len(rounded)), key=lambda token_id: (-rounded[token_id], token_id))[:20]
        assert [token["id"] for token in item["top"]] == top_ids, item["id"]
        for record, token_id in zip(item["top"], top_ids):
            assert record["text"] == tokenizer.decode([token_id]), (item["id"], token_id)
            close_number(record["logit"], rounded[token_id], (item["id"], token_id))
        logsumexp = round(float(torch.logsumexp(logits, dim=-1)), 3)
        close_number(item["logsumexp"], logsumexp, (item["id"], "full-vocabulary logsumexp"))
        if "expect" in item:
            assert item["expect"] in [tokenizer.decode([token_id]) for token_id in top_ids]


def replay_attention(data, tokenizer, model):
    assert data["sentence"] == "The animal didn't cross the street because it was too tired."
    encoded = tokenizer(data["sentence"], return_tensors="pt")
    ids = encoded["input_ids"][0].tolist()
    assert data["tokens"] == token_records(tokenizer, ids)
    assert data["scale"] == 255
    assert data["layers"] == data["heads"] == 12
    attentions = model(**encoded, output_attentions=True).attentions
    assert attentions is not None and len(attentions) == 12
    stored = torch.tensor(data["weights"])
    assert tuple(stored.shape) == (12, 12, len(ids), len(ids))
    assert stored.dtype in (torch.int32, torch.int64)
    assert bool(((stored >= 0) & (stored <= 255)).all())
    actual = torch.stack([layer[0] for layer in attentions])
    assert tuple(actual.shape) == tuple(stored.shape)
    # Python round uses ties-to-even, matching the agreed exporter contract.
    quantized = torch.tensor([round(float(weight) * 255) for weight in actual.flatten().tolist()])
    quantized = quantized.reshape(stored.shape)
    difference = (stored - quantized).abs()
    assert int(difference.max()) <= 1, f"Attention differs by {int(difference.max())} quanta"
    assert int(torch.triu(stored, diagonal=1).count_nonzero()) == 0


def replay_completions(data, variant, tokenizer, model):
    assert len(data["items"]) == 5 and data["max_new_tokens"] == 48
    eos = model.generation_config.eos_token_id
    if eos is None:
        eos = tokenizer.eos_token_id
    assert eos is not None, "Pinned model must define EOS"
    eos_ids = eos if isinstance(eos, list) else [eos]
    pad = tokenizer.pad_token_id
    if pad is None:
        pad = eos_ids[0]
    for item in data["items"]:
        record = item[variant]
        if variant == "instruct":
            rendered = tokenizer.apply_chat_template(
                [{"role": "user", "content": item["prompt"]}],
                add_generation_prompt=True, tokenize=False
            )
            assert record["input"] == rendered, item["id"]
            encoded = tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
        else:
            assert record["input"] == item["prompt"], item["id"]
            encoded = tokenizer(item["prompt"], return_tensors="pt")
        generated = model.generate(
            **encoded, do_sample=False, num_beams=1, max_new_tokens=48,
            pad_token_id=pad, eos_token_id=eos
        )
        new_ids = generated[0, encoded["input_ids"].shape[1]:].tolist()
        assert record["token_ids"] == new_ids, (variant, item["id"])
        assert record["text"] == tokenizer.decode(new_ids, skip_special_tokens=True), (variant, item["id"])
        assert 1 <= len(new_ids) <= 48
        expected_stop = "eos" if new_ids[-1] in eos_ids else "length"
        assert record["stop"] == expected_stop, (variant, item["id"])
        if expected_stop == "length":
            assert len(new_ids) == 48


def test_d1_all_traces_replay_from_pinned_models():
    """Full corpus replay prevents satisfying provenance with one canned example."""
    torch.manual_seed(0)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    next_token = read_fixture("next_token.json")
    attention = read_fixture("attention.json")
    comparison = read_fixture("base_vs_instruct.json")
    gpt_revisions = provenance(next_token, [GPT2])
    assert provenance(attention, [GPT2]) == gpt_revisions
    smol_revisions = provenance(comparison, [BASE, INSTRUCT])
    with torch.inference_mode():
        tokenizer, model = load_model(GPT2, gpt_revisions[GPT2], attention=True)
        replay_next_token(next_token, tokenizer, model)
        replay_attention(attention, tokenizer, model)
        del model, tokenizer
        gc.collect()
        for variant, model_id in (("base", BASE), ("instruct", INSTRUCT)):
            tokenizer, model = load_model(model_id, smol_revisions[model_id])
            replay_completions(comparison, variant, tokenizer, model)
            del model, tokenizer
            gc.collect()

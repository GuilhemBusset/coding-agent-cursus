"""The model fixtures the Act I labs and decks show, checked offline (no model libraries).

These check the content the pages rely on: twenty prompts with their sorted top
tokens, causal and normalized attention for the coreference sentence, five greedy
base/instruct completions. The explicitly selected fixture_replay_checks.py proves
provenance by replaying the pinned models.
"""

import json
import math
import re
import tomllib
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
FIXTURES = SESSION / "cursus" / "fixtures"
SENTENCE = "The animal didn't cross the street because it was too tired."
LIMIT = 500_000


def reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        assert key not in obj, f"Duplicate JSON key: {key}"
        obj[key] = value
    return obj


def decode_payload(raw):
    assert len(raw) <= LIMIT, f"Fixture exceeds {LIMIT} bytes"
    value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant,
                       object_pairs_hook=unique_keys)
    assert isinstance(value, dict) and isinstance(value.get("meta"), dict), "Missing meta"
    return value


def read_fixture(name):
    path = FIXTURES / name
    assert path.is_file(), f"Missing fixture: {path}"
    return decode_payload(path.read_bytes())


def nonempty(value):
    assert isinstance(value, str) and value.strip(), f"Expected nonempty text: {value!r}"


def integer(value, low, high):
    assert type(value) is int and low <= value <= high, f"Invalid integer: {value!r}"


def rounded_number(value):
    assert type(value) in (float, int) and math.isfinite(value), f"Invalid number: {value!r}"
    assert round(value, 3) == value, f"More than three decimals: {value!r}"


def tokens(value, vocab=50257):
    assert isinstance(value, list) and value, "Expected token records"
    for token in value:
        assert isinstance(token, dict)
        integer(token["id"], 0, vocab - 1)
        assert isinstance(token["text"], str)


def validate_prompt(item):
    nonempty(item["id"])
    nonempty(item["category"])
    nonempty(item["prompt"])
    tokens(item["prompt_tokens"])
    tokens(item["top"])
    assert len(item["top"]) == 20
    ids = [token["id"] for token in item["top"]]
    assert len(set(ids)) == 20
    for token in item["top"]:
        rounded_number(token["logit"])
    order = [(-token["logit"], token["id"]) for token in item["top"]]
    assert order == sorted(order), "Top tokens must use rounded-logit/id order"
    rounded_number(item["logsumexp"])
    assert item["logsumexp"] >= item["top"][0]["logit"]
    if "expect" in item:
        assert isinstance(item["expect"], str)
        assert item["expect"] in [token["text"] for token in item["top"]]


def validate_next_token(data):
    prompts = data["prompts"]
    # The design resolves "about 20" to exactly 20, without fixing prompt wording.
    assert isinstance(prompts, list) and len(prompts) == 20
    for item in prompts:
        validate_prompt(item)
    assert len({item["id"] for item in prompts}) == 20
    assert len({item["prompt"] for item in prompts}) == 20
    assert any("minimize total" in item["prompt"].lower() for item in prompts)
    assert any("subject to" in item["prompt"].lower() for item in prompts)
    strawberry = [item for item in prompts if item["prompt"] == " strawberry"]
    assert len(strawberry) == 1
    assert "".join(token["text"] for token in strawberry[0]["prompt_tokens"]) == " strawberry"
    # Category spelling and factual question wording are intentionally free.
    # Content review establishes factual recall; replay establishes that the
    # expected answers really occur in the model's top twenty.
    expected = [item for item in prompts if "expect" in item]
    assert len(expected) >= 2, "Recall and numeric prompts both need expect"
    assert any(re.search(r"\d", item["prompt"]) for item in expected), "Missing numeric prompt with expect"


def validate_attention(data):
    assert data["sentence"] == SENTENCE
    tokens(data["tokens"])
    assert "".join(token["text"] for token in data["tokens"]) == SENTENCE
    n = len(data["tokens"])
    integer(data["focus"], 0, n - 1)
    integer(data["referent"], 0, data["focus"] - 1)
    assert data["tokens"][data["focus"]]["text"].strip() == "it"
    assert data["tokens"][data["referent"]]["text"].strip() == "animal"
    assert data["scale"] == 255
    assert data["layers"] == data["heads"] == 12
    assert len(data["weights"]) == 12
    for layer in data["weights"]:
        assert len(layer) == 12
        for head in layer:
            assert len(head) == n
            for query, row in enumerate(head):
                assert len(row) == n
                for key, weight in enumerate(row):
                    integer(weight, 0, 255)
                    if key > query:
                        assert weight == 0, "Noncausal attention"
                assert abs(sum(row) - 255) <= n, "Attention row not normalized"


def validate_comparisons(data):
    assert data["max_new_tokens"] == 48
    items = data["items"]
    assert isinstance(items, list) and len(items) == 5
    assert len({item["id"] for item in items}) == 5
    assert len({item["prompt"] for item in items}) == 5
    for item in items:
        nonempty(item["id"])
        nonempty(item["prompt"])
        assert item["base"]["input"] == item["prompt"]
        for variant in ("base", "instruct"):
            record = item[variant]
            nonempty(record["input"])
            nonempty(record["text"])
            assert isinstance(record["token_ids"], list) and 1 <= len(record["token_ids"]) <= 48
            for token_id in record["token_ids"]:
                integer(token_id, 0, 2**31 - 1)  # Replay checks actual model vocabulary.
            assert record["stop"] in {"eos", "length"}
            if record["stop"] == "length":
                assert len(record["token_ids"]) == 48


def test_d2_next_token_schema():
    validate_next_token(read_fixture("next_token.json"))


def test_d3_attention_schema():
    validate_attention(read_fixture("attention.json"))


def test_d4_base_vs_instruct_schema():
    validate_comparisons(read_fixture("base_vs_instruct.json"))


def test_a2_torch_is_only_in_nondefault_fixtures_group():
    config = tomllib.loads((SESSION / "pyproject.toml").read_text(encoding="utf-8"))

    def is_torch(requirement):
        if not isinstance(requirement, str):
            return False
        match = re.match(r"\s*([\w.-]+)", requirement)
        return bool(match and match[1].lower() == "torch")

    assert not any(is_torch(dep) for dep in config["project"]["dependencies"])
    for dependencies in config["project"].get("optional-dependencies", {}).values():
        assert not any(is_torch(dep) for dep in dependencies)
    groups = config.get("dependency-groups", {})
    assert any(is_torch(dep) for dep in groups["fixtures"])
    for name, dependencies in groups.items():
        if name != "fixtures":
            assert not any(is_torch(dep) for dep in dependencies)
    default = config.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    assert default != "all", "Default sync must not select fixtures"
    assert isinstance(default, list)

    def included(name, seen):
        assert name not in seen, "Dependency group cycle"
        result = {name}
        for dep in groups.get(name, []):
            if isinstance(dep, dict) and "include-group" in dep:
                result.update(included(dep["include-group"], seen | {name}))
        return result

    active = set().union(*(included(name, set()) for name in default))
    assert "fixtures" not in active

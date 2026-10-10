"""Offline acceptance checks for issue 27; no model libraries in the student suite.

The explicitly selected fixture_replay_checks.py proves provenance. The engine's
A1 command proves regeneration in isolated processes; A2 proves a real clean sync.
Synthetic objects below exercise validators, never stand in for model evidence.
"""

import ast
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path
import re
import sys
import tomllib
from unittest import TestCase


SESSION = Path(__file__).resolve().parents[1]
FIXTURES = SESSION / "cursus" / "fixtures"
BUILDER = FIXTURES / "build_fixtures.py"
FILES = ("next_token.json", "attention.json", "base_vs_instruct.json")
GPT2 = "openai-community/gpt2"
BASE = "HuggingFaceTB/SmolLM2-135M"
INSTRUCT = BASE + "-Instruct"
SENTENCE = "The animal didn't cross the street because it was too tired."
LIMIT = 500_000


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


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


def literal_strings(tree):
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def validate_meta(meta, models, literals=None):
    assert meta["generator"] == "cursus/fixtures/build_fixtures.py"
    assert meta["device"] == "cpu" and meta["dtype"] == "float32"
    assert isinstance(meta["models"], list) and len(meta["models"]) == len(models)
    assert {model["id"] for model in meta["models"]} == set(models)
    for model in meta["models"]:
        assert re.fullmatch(r"[0-9a-fA-F]{40}", model["revision"]), "Unpinned revision"
        if literals is not None:
            assert model["revision"] in literals, "Revision must be literal in builder"
    for library in ("torch", "transformers"):
        nonempty(meta["libraries"][library])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["date"])
    assert date.fromisoformat(meta["date"]).isoformat() == meta["date"]
    if literals is not None:
        assert meta["date"] in literals, "Export date must be constant in builder"


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
    validate_meta(data["meta"], [GPT2])
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
    validate_meta(data["meta"], [GPT2])
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


def metadata_values(value, key):
    """Notes can be nested; their container's spelling is not part of the schema."""
    found = []
    if isinstance(value, dict):
        if key in value:
            found.append(value[key])
        for child in value.values():
            found.extend(metadata_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(metadata_values(child, key))
    return found


def validate_comparisons(data):
    validate_meta(data["meta"], [BASE, INSTRUCT])
    assert data["max_new_tokens"] == 48
    for key, expected in (("do_sample", False), ("num_beams", 1), ("max_new_tokens", 48)):
        values = metadata_values(data["meta"], key)
        assert values and all(type(value) is type(expected) and value == expected for value in values)
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


def test_d1_builder_pins_models_and_cpu():
    assert BUILDER.is_file(), f"Missing builder: {BUILDER}"
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    literals = literal_strings(tree)
    assert {GPT2, BASE, INSTRUCT} <= literals
    assert len({value for value in literals if re.fullmatch(r"[0-9a-fA-F]{40}", value)}) >= 3
    assert "cpu" in literals, "Builder must force CPU"
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "from_pretrained"]
    assert calls, "No pretrained model/tokenizer loading"
    for call in calls:
        revision = next((kw.value for kw in call.keywords if kw.arg == "revision"), None)
        assert revision is not None, "Every model/tokenizer load must pass revision="
        if isinstance(revision, ast.Constant):
            assert isinstance(revision.value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", revision.value)
    readme = (SESSION / "README.md").read_text(encoding="utf-8")
    assert any("uv run" in line and "--group fixtures" in line for line in readme.splitlines())


def test_d2_next_token_schema():
    validate_next_token(read_fixture("next_token.json"))


def test_d3_attention_schema():
    validate_attention(read_fixture("attention.json"))


def test_d4_base_vs_instruct_schema():
    validate_comparisons(read_fixture("base_vs_instruct.json"))


def test_d5_metadata_and_consistent_provenance():
    literals = literal_strings(ast.parse(BUILDER.read_text(encoding="utf-8")))
    metas = [read_fixture(name)["meta"] for name in FILES]
    for meta, model_ids in zip(metas, ([GPT2], [GPT2], [BASE, INSTRUCT])):
        validate_meta(meta, model_ids, literals)
    assert len({meta["date"] for meta in metas}) == 1
    assert all(meta["libraries"] == metas[0]["libraries"] for meta in metas)
    assert metas[0]["models"] == metas[1]["models"]


def test_d6_files_fit_limit_and_checks_are_stdlib_only():
    for name in FILES:
        read_fixture(name)
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module.split(".")[0] in sys.stdlib_module_names


def example_prompt():
    return {"id": "validator-only", "category": "synthetic", "prompt": "Test",
            "prompt_tokens": [{"id": 1, "text": "Test"}], "logsumexp": 25.125,
            "top": [{"id": 100 + i, "text": f" token{i}", "logit": round(20 - i / 2, 3)}
                    for i in range(20)]}


def test_d6_negative_payload_cases():
    case = TestCase()
    assert decode_payload(b'{"meta":{}}') == {"meta": {}}
    with case.assertRaisesRegex(AssertionError, "exceeds"):
        decode_payload(b'{"meta":{},"padding":"' + b'x' * LIMIT + b'"}')
    with case.assertRaisesRegex(AssertionError, "Missing meta"):
        decode_payload(b'{"prompts":[]}')
    with case.assertRaises(ValueError):
        decode_payload(b'{"meta":{},"logit":NaN}')
    with case.assertRaisesRegex(AssertionError, "Duplicate"):
        decode_payload(b'{"meta":{},"meta":{}}')


def test_d6_negative_top_tokens_and_rounding():
    case = TestCase()
    valid = example_prompt()
    validate_prompt(valid)  # Positive control: rejection is not unconditional.
    for bad_value in (float("nan"), float("inf"), True, 20.0001):
        broken = deepcopy(valid)
        broken["top"][0]["logit"] = bad_value
        with case.assertRaises(AssertionError):
            validate_prompt(broken)
    tied = deepcopy(valid)
    tied["top"][1]["logit"] = tied["top"][0]["logit"]
    validate_prompt(tied)
    tied["top"][0], tied["top"][1] = tied["top"][1], tied["top"][0]
    with case.assertRaises(AssertionError):
        validate_prompt(tied)
    duplicate = deepcopy(valid)
    duplicate["top"][1]["id"] = duplicate["top"][0]["id"]
    with case.assertRaises(AssertionError):
        validate_prompt(duplicate)
    bad_expect = deepcopy(valid)
    bad_expect["expect"] = "not a predicted token"
    with case.assertRaises(AssertionError):
        validate_prompt(bad_expect)


def example_meta(model_ids):
    """Synthetic schema control, not provenance evidence or exported fixture data."""
    return {"generator": "cursus/fixtures/build_fixtures.py", "device": "cpu",
            "dtype": "float32", "date": "2026-10-10",
            "models": [{"id": name, "revision": "a" * 40} for name in model_ids],
            "libraries": {"torch": "schema-control", "transformers": "schema-control"}}


def test_d6_negative_attention_checks_every_head_and_row():
    parts = ["The", " animal", " didn't", " cross", " the", " street",
             " because", " it", " was", " too", " tired", "."]
    n = len(parts)
    valid = {"meta": example_meta([GPT2]), "sentence": SENTENCE,
             "tokens": [{"id": i, "text": text} for i, text in enumerate(parts)],
             "focus": 7, "referent": 1, "scale": 255, "layers": 12, "heads": 12,
             "weights": [[[[255 if q == k else 0 for k in range(n)]
                            for q in range(n)] for _ in range(12)] for _ in range(12)]}
    validate_attention(valid)
    case = TestCase()
    for mutation in ("noncausal", "missing-row", "boolean", "unnormalized"):
        broken = deepcopy(valid)
        head = broken["weights"][-1][-1]
        if mutation == "noncausal":
            head[-2][-2], head[-2][-1] = 0, 255
        elif mutation == "missing-row":
            head.pop()
        elif mutation == "boolean":
            head[-1][0] = False
        else:
            head[-1] = [0] * n
        with case.assertRaises(AssertionError, msg=mutation):
            validate_attention(broken)


def test_d6_negative_completion_records():
    meta = example_meta([BASE, INSTRUCT])
    meta["decoding"] = {"do_sample": False, "num_beams": 1, "max_new_tokens": 48}
    valid = {"meta": meta, "max_new_tokens": 48, "items": []}
    for index in range(5):
        prompt = f"Synthetic validator prompt {index}"
        record = {"input": prompt, "text": "Synthetic text", "token_ids": list(range(48)), "stop": "length"}
        valid["items"].append({"id": str(index), "prompt": prompt,
                               "base": deepcopy(record), "instruct": deepcopy(record)})
    validate_comparisons(valid)
    case = TestCase()
    for key, bad_value in (("token_ids", list(range(49))), ("token_ids", [1]),
                           ("text", ""), ("stop", "sampled"), ("input", "wrong input")):
        broken = deepcopy(valid)
        broken["items"][-1]["base"][key] = bad_value
        with case.assertRaises(AssertionError, msg=key):
            validate_comparisons(broken)


def walk_numbers(value):
    if isinstance(value, float):
        rounded_number(value)
    elif isinstance(value, dict):
        for child in value.values():
            walk_numbers(child)
    elif isinstance(value, list):
        for child in value:
            walk_numbers(child)


def test_a1_canonical_bytes_and_fixed_rounding():
    for name in FILES:
        data = read_fixture(name)
        assert (FIXTURES / name).read_bytes() == canonical(data), name
        walk_numbers(data)


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


def test_a3_readme_regeneration_command():
    readme = (SESSION / "README.md").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^(?=#+\s)", readme)
    matching = [section for section in sections if section.splitlines()
                and re.search(r"regenerat", section.splitlines()[0], re.I)
                and re.search(r"fixture", section.splitlines()[0], re.I)]
    assert matching, "README needs a fixture regeneration heading"
    assert any(all(part in line for part in (
        "uv run", "--locked", "--group fixtures", "python cursus/fixtures/build_fixtures.py"
    )) for section in matching for line in section.splitlines())

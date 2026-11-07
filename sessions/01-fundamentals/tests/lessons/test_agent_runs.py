"""Agent-run recordings: the committed captures, normalize_runs.py and sanitize.py.

Offline, stdlib plus pytest, no vendor CLI. Synthetic streams here are unit-test
inputs, never recording evidence. Only the documented command-line interfaces are
exercised.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
RUNS = SESSION / "cursus/fixtures/runs"
TASKS = ("flipped-sense", "impossible", "context-bomb")
VENDORS = ("claude", "codex")
NAMES = tuple(f"{task}-{vendor}" for task in TASKS for vendor in VENDORS)
LIMIT = 4_000_000
STEP_KEYS = {"i", "line", "type", "t_ms", "source_ts", "text", "tool",
             "call_id", "input", "is_error", "parent", "tokens"}
TOKEN_KEYS = {"input", "output", "cached_input"}
META_KEYS = {"run", "task", "vendor", "cli_version", "model", "effort", "date",
             "argv", "exit_code", "prompt_sha256"}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def decode(text):
    return json.loads(text, object_pairs_hook=unique_keys,
                      parse_constant=reject_constant)


def load(path):
    assert path.is_file(), f"Missing artifact: {path}"
    return decode(path.read_text(encoding="utf-8"))


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def nonempty(value):
    assert isinstance(value, str) and value.strip(), "Expected nonempty string"


def invoke(script, *args, cwd=None, env=None, success=True):
    path = RUNS / script
    assert path.is_file(), f"Missing script: {path}"
    child_env = dict(os.environ if env is None else env, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, str(path), *map(str, args)],
                            cwd=cwd or SESSION, env=child_env, capture_output=True,
                            text=True, encoding="utf-8", timeout=90, check=False)
    if success:
        # Do not echo subprocess output: a failed privacy control could contain
        # its input. The implementation's CLI can be run separately to diagnose.
        assert result.returncode == 0, f"{script} exited {result.returncode}"
    return result


def raw_meta(name):
    return load(RUNS / "raw" / f"{name}.meta.json")


def events(name):
    path = RUNS / "raw" / f"{name}.jsonl"
    assert path.is_file(), f"Missing capture: {path}"
    payload = path.read_bytes()
    assert 0 < len(payload) <= LIMIT
    lines = payload.decode("utf-8").splitlines()
    assert lines and all(line.strip() for line in lines), "Blank JSONL line"
    result = [decode(line) for line in lines]
    assert all(isinstance(event, dict) for event in result)
    return result


def normalized(name):
    path = RUNS / f"{name}.json"
    assert path.is_file(), f"Missing normalized capture: {path}"
    assert 0 < path.stat().st_size <= LIMIT
    return load(path)


def option(argv, name):
    assert name in argv, f"Missing option {name}"
    index = argv.index(name)
    assert index + 1 < len(argv)
    return argv[index + 1]


def test_recordings_show_what_the_lesson_claims():
    """The page replays these runs; each one must show the behaviour the lesson describes."""
    for name in NAMES:
        task, vendor = name.rsplit("-", 1)
        stream, meta, replay = events(name), raw_meta(name), normalized(name)
        assert meta["task"] == task and meta["vendor"] == vendor
        # The model the page names is the model that ran.
        if vendor == "claude":
            init = next(e for e in stream if e.get("type") == "system" and e.get("subtype") == "init")
            assert init["model"].startswith(meta["model"])
        else:
            assert option(meta["argv"], "-m") == meta["model"]
        results = "\n".join(step["text"] or "" for step in replay["steps"] if step["type"] == "tool_result")
        if task == "flipped-sense":
            raw = json.dumps(stream)
            assert "kMaximize" in raw and "kMinimize" in raw
            assert meta["verification"]["pre"]["exit_code"] != 0
            assert meta["verification"]["post"]["exit_code"] == 0
        elif task == "impossible":
            assert meta["verification"]["pre"]["exit_code"] != 0
            assert "485" in results and "400" in results
        else:
            sentinels = [noise["sentinel"] for noise in meta["scenario"]["noise"]["files"]]
            assert len(sentinels) == 24
            assert sum(s in results for s in sentinels) >= 12, "Context bomb did not exercise half the logs"


def write_stream(directory, vendor, stream, *, offsets=True, extra=None):
    directory.mkdir(parents=True, exist_ok=True)
    name = f"unit-{vendor}"
    raw = directory / f"{name}.jsonl"
    raw.write_bytes(b"".join(canonical(event) for event in stream))
    meta = {
        "vendor": vendor, "task": "unit", "cli_version": "unit CLI",
        "model": "unit-model", "effort": "medium", "started_at": "2026-01-02T03:04:05Z",
        "ended_at": "2026-01-02T03:04:06Z", "date": "2026-01-02",
        "argv": [vendor], "exit_code": 0, "prompt": "unit prompt",
        "prompt_sha256": sha("unit prompt"),
    }
    if offsets:
        meta["line_offsets_ms"] = [11 + 17 * i for i in range(len(stream))]
    if extra:
        meta.update(extra)
    (directory / f"{name}.meta.json").write_bytes(canonical(meta))
    return name, meta


def normalize_unit(tmp_path, vendor, stream, **kwargs):
    raw, out = tmp_path / "raw", tmp_path / "out"
    name, meta = write_stream(raw, vendor, stream, **kwargs)
    invoke("normalize_runs.py", "--raw", raw, "--out", out, cwd=tmp_path)
    value = load(out / f"{name}.json")
    validate_schema(value, len(stream))
    return value, meta


def validate_counter(value):
    assert value is None or (type(value) is int and value >= 0)


def validate_schema(value, line_count):
    assert set(value) == {"schema", "meta", "steps", "totals", "diagnostics"}
    assert value["schema"] == "agent-run/1"
    assert set(value["meta"]) == META_KEYS
    assert set(value["totals"]) == TOKEN_KEYS | {"reasoning"}
    for count in value["totals"].values():
        validate_counter(count)
    assert set(value["diagnostics"]) == {"ignored", "unknown"}
    assert isinstance(value["diagnostics"]["ignored"], dict)
    assert isinstance(value["diagnostics"]["unknown"], list)
    for count in value["diagnostics"]["ignored"].values():
        assert type(count) is int and count > 0
    assert isinstance(value["steps"], list)
    previous_line = 0
    for index, step in enumerate(value["steps"]):
        assert set(step) == STEP_KEYS
        assert step["i"] == index
        assert type(step["line"]) is int and previous_line <= step["line"] <= line_count
        assert step["line"] >= 1
        previous_line = step["line"]
        assert step["type"] in {"thought", "tool_call", "tool_result", "message"}
        assert step["t_ms"] is None or (type(step["t_ms"]) in (int, float) and math.isfinite(step["t_ms"]) and step["t_ms"] >= 0)
        assert step["source_ts"] is None or isinstance(step["source_ts"], str)
        for field in ("text", "tool", "call_id", "parent"):
            assert step[field] is None or isinstance(step[field], str)
        assert step["is_error"] is None or type(step["is_error"]) is bool
        if step["type"] == "tool_call":
            nonempty(step["call_id"])
            nonempty(step["tool"])
        if step["type"] in {"thought", "message"}:
            assert step["tool"] is None and step["call_id"] is None and step["input"] is None
        if step["tokens"] is not None:
            assert set(step["tokens"]) == TOKEN_KEYS
            for count in step["tokens"].values():
                validate_counter(count)


def test_d2_claude_mapping_tokens_and_provenance(tmp_path):
    base = 7
    usage = {"input_tokens": base, "output_tokens": 4,
             "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2}
    message_id = f"message-{base}"
    call_id = f"tool-{base}"
    stream = [
        {"type": "system", "subtype": "init", "model": "unit-model"},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial must disappear"}}},
        {"type": "assistant", "timestamp": "2026-01-02T03:04:07Z", "parent_tool_use_id": "parent-1", "message": {
            "id": message_id, "usage": usage, "content": [
                {"type": "thinking", "thinking": f"plan {base}"},
                {"type": "text", "text": "Inspect café"},
                {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": f"printf {base}"}},
            ]}},
        {"type": "user", "timestamp": "2026-01-02T03:04:01Z", "parent_tool_use_id": "parent-1", "message": {"content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": "command failed", "is_error": True}]}},
        {"type": "assistant", "message": {"id": message_id, "usage": usage, "content": [{"type": "text", "text": "Repeated id, new block"}]}},
        {"type": "system", "subtype": "api_retry", "attempt": 1},
        {"type": "rate_limit_event", "rate_limit_info": {}},
        {"type": "result", "result": "terminal duplicate must disappear", "usage": {
            "input_tokens": base * 10, "output_tokens": 17,
            "cache_read_input_tokens": 20, "cache_creation_input_tokens": 10}},
    ]
    value, meta = normalize_unit(tmp_path, "claude", stream)
    steps = value["steps"]
    assert [s["type"] for s in steps] == ["thought", "message", "tool_call", "tool_result", "message"]
    assert steps[0]["text"] == f"plan {base}" and steps[1]["text"] == "Inspect café"
    assert steps[2]["input"] == {"command": f"printf {base}"}
    assert steps[2]["tool"] == "Bash" and steps[2]["call_id"] == call_id
    assert steps[3]["call_id"] == call_id and steps[3]["is_error"] is True
    assert steps[3]["text"] == "command failed"
    assert all(s["parent"] == "parent-1" for s in steps[:4])
    assert steps[0]["tokens"] == {"input": base + 5, "output": 4, "cached_input": 3}
    assert all(s["tokens"] is None for s in steps[1:])
    assert value["totals"] == {"input": base * 10 + 30, "output": 17, "cached_input": 20, "reasoning": None}
    assert [s["line"] for s in steps] == [3, 3, 3, 4, 5]
    assert steps[0]["source_ts"] == stream[2]["timestamp"]
    assert steps[3]["source_ts"] == stream[3]["timestamp"]
    for step in steps:
        assert step["t_ms"] == meta["line_offsets_ms"][step["line"] - 1]
    for key in ("system/init", "system/api_retry", "stream_event", "rate_limit_event", "result"):
        assert value["diagnostics"]["ignored"][key] == 1
    assert value["diagnostics"]["unknown"] == []


@pytest.mark.parametrize("exit_code", [0, 13])
def test_d2_codex_mapping_dedup_and_turn_totals(tmp_path, exit_code):
    call_id = f"cmd-{exit_code}"
    stream = [
        {"type": "thread.started", "thread_id": "thread-unit"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "r1", "type": "reasoning", "text": "Need a command"}},
        {"type": "item.started", "timestamp": "2026-01-02T03:04:07Z", "item": {"id": call_id, "type": "command_execution", "command": "printf replay", "status": "in_progress"}},
        {"type": "item.updated", "item": {"id": call_id, "type": "command_execution", "command": "printf replay", "aggregated_output": "partial", "status": "in_progress"}},
        {"type": "item.completed", "timestamp": "2026-01-02T03:04:01Z", "item": {"id": call_id, "type": "command_execution", "command": "printf replay", "aggregated_output": "replay", "exit_code": exit_code, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "a1", "type": "agent_message", "text": "Finished"}},
        {"type": "turn.completed", "usage": {"input_tokens": 31, "cached_input_tokens": 11, "output_tokens": 7}},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "a2", "type": "agent_message", "text": "One more turn"}},
        {"type": "turn.completed", "usage": {"input_tokens": 43, "cached_input_tokens": 13, "output_tokens": 9}},
    ]
    value, meta = normalize_unit(tmp_path, "codex", stream)
    steps = value["steps"]
    assert [s["type"] for s in steps] == ["thought", "tool_call", "tool_result", "message", "message"]
    assert steps[0]["text"] == "Need a command"
    assert steps[1]["call_id"] == steps[2]["call_id"] == call_id
    assert "printf replay" in json.dumps(steps[1]["input"])
    assert steps[2]["text"] == "replay" and steps[2]["is_error"] is (exit_code != 0)
    assert steps[3]["text"] == "Finished"
    assert [s["line"] for s in steps] == [3, 4, 6, 7, 10]
    assert steps[1]["source_ts"] == stream[3]["timestamp"]
    assert steps[2]["source_ts"] == stream[5]["timestamp"]
    assert all(s["tokens"] is None for s in steps)
    assert value["totals"] == {"input": 74, "output": 16, "cached_input": 24, "reasoning": None}
    assert value["diagnostics"]["unknown"] == []
    for step in steps:
        assert step["t_ms"] == meta["line_offsets_ms"][step["line"] - 1]


def test_d2_codex_completed_without_started_and_failed_status(tmp_path):
    item = {"id": "only-completed", "type": "mcp_tool_call", "status": "failed", "server": "unit",
            "tool": "lookup", "arguments": {"n": 19}, "result": {"content": [{"type": "text", "text": "found"}]}}
    value, _ = normalize_unit(tmp_path, "codex", [{"type": "item.completed", "item": item}])
    assert [s["type"] for s in value["steps"]] == ["tool_call", "tool_result"]
    assert all(s["call_id"] == item["id"] for s in value["steps"])
    assert value["steps"][1]["is_error"] is True
    assert all(v is None for v in value["totals"].values())


def test_d2_unknown_diagnostics_and_missing_usage(tmp_path):
    stream = [
        {"type": "item.completed", "item": {"id": "todo", "type": "todo_list", "items": []}},
        {"type": "item.completed", "item": {"id": "err", "type": "error", "message": "unit error"}},
        {"type": "turn.failed", "error": {"message": "unit failure"}},
        {"type": "future.event", "value": "unit unknown"},
    ]
    value, _ = normalize_unit(tmp_path, "codex", stream)
    assert value["steps"] == []
    diagnostic_text = json.dumps(value["diagnostics"])
    assert all(word in diagnostic_text for word in ("todo_list", "error", "future.event"))
    assert value["diagnostics"]["unknown"]
    assert all(v is None for v in value["totals"].values())


def test_d2_claude_multiple_messages_and_structured_result(tmp_path):
    stream = [
        {"type": "assistant", "message": {"id": "one", "usage": {"input_tokens": 5, "output_tokens": 2}, "content": [
            {"type": "tool_use", "id": "read-1", "name": "Read", "input": {"file_path": "model.py"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "read-1", "content": [
            {"type": "text", "text": "first line"}, {"type": "text", "text": "second line"}]}]}},
        {"type": "assistant", "message": {"id": "two", "usage": {"input_tokens": 8, "output_tokens": 3}, "content": [
            {"type": "text", "text": "New message"}, {"type": "text", "text": "Another block"}]}},
    ]
    value, _ = normalize_unit(tmp_path, "claude", stream, offsets=False)
    steps = value["steps"]
    assert [s["type"] for s in steps] == ["tool_call", "tool_result", "message", "message"]
    assert steps[1]["call_id"] == "read-1"
    assert "first line" in steps[1]["text"] and "second line" in steps[1]["text"]
    assert steps[1]["is_error"] is False
    assert steps[0]["tokens"]["input"] == 5 and steps[2]["tokens"]["input"] == 8
    assert steps[1]["tokens"] is steps[3]["tokens"] is None
    assert all(s["t_ms"] is None and s["source_ts"] is None for s in steps)
    assert all(v is None for v in value["totals"].values()), "No authoritative result usage is available"


def test_d2_malformed_json_reports_file_and_line(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    name, _ = write_stream(raw, "codex", [{"type": "thread.started"}])
    with (raw / f"{name}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"type": broken}\n')
    result = invoke("normalize_runs.py", "--raw", raw, "--out", out, success=False)
    assert result.returncode != 0
    assert re.search(re.escape(f"{name}.jsonl") + r":2\b", result.stdout + result.stderr)


def secret_controls():
    filler = "Q7n8r9T0u1V2w3X4y5Z6"
    return {
        "home": "/" + "home/" + "alice/project/model.py",
        "mac_home": "/" + "Users/" + "alice/project/model.py",
        "windows_home": "C:" + "\\Users\\" + "alice\\project\\model.py",
        "encoded_home": "-" + "home-" + "alice-proj",
        "email": "bob" + "@" + "corp.example",
        "anthropic_key": "sk-" + "ant-" + filler,
        "openai_key": "sk-" + filler,
        "project_key": "sk-" + "proj-" + filler,
        "github_key": "gh" + "p_" + filler,
        "github_pat": "github_" + "pat_" + filler,
        "aws_key": "AK" + "IA" + "A1B2C3D4E5F6G7H8",
        "slack_key": "xox" + "b-" + filler,
        "bearer": "Bear" + "er " + filler,
        "assignment": "api_" + "key=" + filler,
        "private_key": "-----BEGIN " + "PRIVATE KEY-----\n" + filler + "\n-----END " + "PRIVATE KEY-----",
    }


def test_d3_sanitizes_nested_json_meta_text_without_clipping(tmp_path):
    values = secret_controls()
    values.update({"login": "alice", "prose": "Ask alice to review this.",
                   "display": "Alice Example", "display_prose": "Ask Alice Example to review.",
                   "identity_email": "alice" + "@" + "example.com"})
    # Large non-sensitive text (84,000 characters, past any display clip or 64 KiB buffer)
    # proves that sanitizing is not clipping.
    long_text = "Complete evidence Δ. " * 4_000
    nested = {"z_tool": {"id": "call-preserve-937", "input": values},
              "a_result": [{"output": values.copy(), "long": long_text,
                            "signature": "opaque" * 100,
                            "encrypted_content": "opaque" * 70}],
              "innocent": "malice"}
    jsonl, meta, plain = (tmp_path / name for name in ("stream.jsonl", "stream.meta.json", "notes.txt"))
    jsonl.write_text(json.dumps(nested, ensure_ascii=False) + "\n" + json.dumps({"second": "alice"}) + "\n", encoding="utf-8")
    meta.write_text(json.dumps(nested, ensure_ascii=False), encoding="utf-8")
    plain.write_text("\n".join(values.values()) + "\nmalice\n" + long_text, encoding="utf-8")
    args = ["--identity", "alice", "--identity", "Alice Example", "--identity", "alice" + "@" + "example.com"]
    invoke("sanitize.py", *args, jsonl, meta, plain, cwd=tmp_path)
    sanitized = decode(jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert list(sanitized) == list(nested), "Sanitizer changed JSON key order"
    assert sanitized["z_tool"]["id"] == "call-preserve-937"
    result = sanitized["a_result"][0]
    assert result["long"] == long_text
    assert result["signature"] == result["encrypted_content"] == "<redacted>"
    assert sanitized["innocent"] == "malice"
    assert decode(jsonl.read_text(encoding="utf-8").splitlines()[1]) == {"second": "<user>"}
    assert load(meta)["a_result"][0]["long"] == long_text
    for rewritten in (sanitized["z_tool"]["input"], result["output"]):
        for name in ("home", "mac_home", "windows_home"):
            assert rewritten[name].startswith("~"), f"Home prefix not scrubbed: {name}"
        assert "-<work>" in rewritten["encoded_home"]
        assert rewritten["login"] == "<user>"
        assert rewritten["prose"] == "Ask <user> to review this."
        assert rewritten["display"] == "<user>"
        assert rewritten["display_prose"] == "Ask <user> to review."
        assert rewritten["email"] == "<email>"
        assert rewritten["identity_email"] in {"<email>", "<user>"}
        for name in values.keys() - {"home", "mac_home", "windows_home", "encoded_home", "login", "prose", "display", "display_prose", "email", "identity_email"}:
            assert "<key>" in rewritten[name], f"Missing key replacement for {name}"
    for path in (jsonl, meta, plain):
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in secret_controls().values()), "A control survived sanitization"
        assert not re.search(r"\balice\b", text, re.IGNORECASE)
    assert long_text in plain.read_text(encoding="utf-8")
    before = {path: path.read_bytes() for path in (jsonl, meta, plain)}
    invoke("sanitize.py", *args, jsonl, meta, plain, cwd=tmp_path)
    assert before == {path: path.read_bytes() for path in before}, "Sanitizer is not idempotent"
    invoke("sanitize.py", "--scan", tmp_path)


def scan_report(*paths):
    """Run the scanner once; return its exit code, report text and the files it flagged."""
    result = invoke("sanitize.py", "--scan", *paths, success=False)
    report = result.stdout + result.stderr
    flagged = {Path(line.rsplit(":", 2)[0]).name for line in report.splitlines() if line.count(":") >= 2}
    return result.returncode, report, flagged


def test_d3_scan_positive_controls_and_no_secret_in_report(tmp_path):
    """One scan over every control: each is reported as file:line:category, none is echoed."""
    controls = secret_controls()
    # An address spelled with JSON escapes is still found, in a key or in a value.
    escaped = "".join(f"\\u{ord(char):04x}" for char in "reviewer" + "@" + "corp.example")
    seeded = {f"{name}.txt": "safe line\n" + value + "\n" for name, value in controls.items()}
    seeded.update({"escaped-value.json": '{"contact":"' + escaped + '"}',
                   "escaped-key.json": '{"' + escaped + '":"safe"}'})
    # Negative control: a decorator after an escaped newline is not an address.
    code = "\n@pytest.fixture\ndef fixture():\n    pass\n"
    clean = {"decorators.json": json.dumps({"tool_result": [{"text": code}]}),
             "decorators.jsonl": json.dumps({"text": code}) + "\n" + json.dumps({"other": "\r@sample.decorator"}) + "\n"}
    for name, text in {**seeded, **clean}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    status, report, flagged = scan_report(tmp_path)
    assert status == 1
    assert before == {path: path.read_bytes() for path in tmp_path.iterdir()}, "--scan changed a file"
    assert flagged == set(seeded), f"Missed {set(seeded) - flagged}, false alarm {flagged - set(seeded)}"
    assert not [name for name, value in controls.items() if value in report], "Scanner echoed a secret"
    invoke("sanitize.py", *(tmp_path / name for name in seeded))
    status, report, _ = scan_report(tmp_path)
    assert status == 0, report


def test_d3_scan_identities_and_exact_placeholder_exemptions(tmp_path):
    path = tmp_path / "identities.txt"
    path.write_text("alice\nAsk Alice Example to review.\n", encoding="utf-8")
    result = invoke("sanitize.py", "--scan", "--identity", "alice", "--identity", "Alice Example", path, success=False)
    assert result.returncode == 1
    assert "alice" not in result.stdout.casefold() + result.stderr.casefold()
    invoke("sanitize.py", "--identity", "alice", "--identity", "Alice Example", path)
    invoke("sanitize.py", "--scan", path)
    path.write_text("~ <work> -<work> <user> <email> <key> <redacted>\nBearer <key>\napi_key=<key>\n", encoding="utf-8")
    invoke("sanitize.py", "--scan", path)
    # A placeholder embedded into another value cannot whitelist that value.
    path.write_text("Bearer " + "<key>suffix" + "\n", encoding="utf-8")
    assert invoke("sanitize.py", "--scan", path, success=False).returncode == 1


def test_committed_recordings_pass_the_privacy_scan():
    """No secret, home path, recorded or local identity in any committed recording."""
    invoke("sanitize.py", "--scan", RUNS)


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def deterministic_environments():
    for seed, zone in (("1", "UTC"), ("987654", "Pacific/Honolulu")):
        yield dict(os.environ, PYTHONHASHSEED=seed, TZ=zone)


def test_a2_committed_regeneration_is_byte_deterministic(tmp_path):
    assert (RUNS / "raw").is_dir(), "Missing raw recordings"
    original = snapshot(RUNS / "raw")
    outputs = []
    for index, env in enumerate(deterministic_environments()):
        raw, out, cwd = (tmp_path / f"{prefix}-{index}" for prefix in ("raw", "out", "cwd"))
        raw.mkdir()
        cwd.mkdir()
        for name, content in sorted(original.items(), reverse=bool(index)):
            path = raw / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        invoke("normalize_runs.py", "--raw", raw, "--out", out, cwd=cwd, env=env)
        assert snapshot(raw) == original, "Normalizer changed raw evidence"
        output = snapshot(out)
        assert set(output) == {f"{name}.json" for name in NAMES}
        for filename, content in output.items():
            assert content == canonical(decode(content.decode("utf-8")))
            assert content == (RUNS / filename).read_bytes(), f"Stale normalized file: {filename}"
        outputs.append(output)
    assert outputs[0] == outputs[1]
    assert snapshot(RUNS / "raw") == original
    invoke("normalize_runs.py", "--check", cwd=tmp_path)


def test_a2_no_timestamp_clock_and_check_detects_differences(tmp_path):
    raw = tmp_path / "raw"
    stream = [{"type": "item.completed", "item": {"id": "text-unit", "type": "agent_message", "text": "No native timestamp Ω"}}]
    name, _ = write_stream(raw, "codex", stream, offsets=False)
    out = tmp_path / "out"
    invoke("normalize_runs.py", "--raw", raw, "--out", out, cwd=tmp_path)
    target = out / f"{name}.json"
    value = load(target)
    validate_schema(value, 1)
    assert len(value["steps"]) == 1
    assert value["steps"][0]["t_ms"] is None
    assert value["steps"][0]["source_ts"] is None
    result = target.read_bytes()
    check_args = ("--raw", raw, "--out", out, "--check")
    invoke("normalize_runs.py", *check_args)
    target.write_bytes(result + b" ")
    assert invoke("normalize_runs.py", *check_args, success=False).returncode == 1
    assert target.read_bytes() == result + b" ", "--check must not rewrite output"
    target.unlink()
    assert invoke("normalize_runs.py", *check_args, success=False).returncode == 1
    target.write_bytes(result)
    extra = out / "unexpected-codex.json"
    extra.write_bytes(result)
    assert invoke("normalize_runs.py", *check_args, success=False).returncode == 1
    extra.unlink()
    invoke("normalize_runs.py", *check_args)

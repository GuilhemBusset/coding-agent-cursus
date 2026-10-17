"""Independent examination of the six actual captures, without vendor access."""
import json
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def test_d1_actual_recordings_cover_both_vendors_and_three_tasks():
    for task in ("flipped-sense", "impossible", "context-bomb"):
        for vendor in ("claude", "codex"):
            name = f"{task}-{vendor}"
            meta = json.loads((RUNS / "raw" / f"{name}.meta.json").read_text())
            events = [json.loads(line) for line in (RUNS / "raw" / f"{name}.jsonl").read_text().splitlines()]
            expected = ["claude", "-p", "--output-format", "stream-json", "--verbose"] if vendor == "claude" else ["codex", "exec", "--json"]
            assert meta["argv"][:len(expected)] == expected
            assert meta["task"] == task and meta["vendor"] == vendor
            assert len(events) == len(meta["line_offsets_ms"])
            if vendor == "claude":
                assert any(e.get("type") == "assistant" for e in events)
                assert any(e.get("type") == "user" for e in events)
                assert any(e.get("type") == "result" for e in events)
            else:
                assert any(e.get("type") == "item.completed" and e["item"]["type"] == "command_execution" for e in events)
                assert any(e.get("type") == "turn.completed" for e in events)
            replay = json.loads((RUNS / f"{name}.json").read_text())
            tool_text = "\n".join(s["text"] or "" for s in replay["steps"] if s["type"] == "tool_result")
            if task == "flipped-sense":
                assert "kMaximize" in json.dumps(events) and "kMinimize" in json.dumps(events)
                assert meta["verification"]["pre"]["exit_code"] != 0
                assert meta["verification"]["post"]["exit_code"] == 0
            elif task == "impossible":
                assert "400" in meta["scenario"]["added"][0]["text"]
                assert "485" in tool_text and "400" in tool_text
                assert meta["verification"]["pre"]["exit_code"] != 0
            else:
                assert "-- checked" in meta["prompt"]
                files = meta["scenario"]["noise"]["files"]
                assert len(files) == 24
                assert all(f["sentinel"] in tool_text for f in files)

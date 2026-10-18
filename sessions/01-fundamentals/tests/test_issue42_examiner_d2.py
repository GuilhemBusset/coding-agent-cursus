"""Independent vendor mapping checks through the delivered normalizer CLI."""
import json
import subprocess
import sys
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def test_d2_vendor_steps_usage_and_timestamps(tmp_path):
    streams = {
        "claude": [
            {"type": "assistant", "timestamp": "2026-10-16T12:00:00Z", "message": {
                "id": "examiner-message", "usage": {"input_tokens": 19, "output_tokens": 7, "cache_read_input_tokens": 5},
                "content": [{"type": "thinking", "thinking": "Inspect the failure"},
                            {"type": "tool_use", "id": "examiner-call", "name": "Bash", "input": {"command": "check"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "examiner-call", "content": "failed check", "is_error": True}]}},
            {"type": "assistant", "message": {"id": "examiner-final", "content": [{"type": "text", "text": "The contract conflicts"}]}},
            {"type": "result", "usage": {"input_tokens": 19, "output_tokens": 7, "cache_read_input_tokens": 5}},
        ],
        "codex": [
            {"type": "item.completed", "timestamp": "2026-10-16T12:00:00Z", "item": {"id": "examiner-thought", "type": "reasoning", "text": "Inspect the failure"}},
            {"type": "item.started", "item": {"id": "examiner-call", "type": "command_execution", "command": "check"}},
            {"type": "item.completed", "item": {"id": "examiner-call", "type": "command_execution", "command": "check", "aggregated_output": "failed check", "exit_code": 3}},
            {"type": "item.completed", "item": {"id": "examiner-final", "type": "agent_message", "text": "The contract conflicts"}},
            {"type": "turn.completed", "usage": {"input_tokens": 24, "output_tokens": 7, "cached_input_tokens": 5}},
        ],
    }
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    for vendor, events in streams.items():
        (raw / f"examiner-{vendor}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (raw / f"examiner-{vendor}.meta.json").write_text(json.dumps({"vendor": vendor, "line_offsets_ms": [31 * (i + 1) for i in range(len(events))]}))
    subprocess.run([sys.executable, str(RUNS / "normalize_runs.py"), "--raw", str(raw), "--out", str(out)], check=True)
    for vendor in streams:
        result = json.loads((out / f"examiner-{vendor}.json").read_text())
        steps = result["steps"]
        assert result["schema"] == "agent-run/1"
        assert [s["type"] for s in steps] == ["thought", "tool_call", "tool_result", "message"]
        assert steps[0]["text"] == "Inspect the failure"
        assert steps[0]["source_ts"] == "2026-10-16T12:00:00Z"
        assert steps[1]["input"]["command"] == "check"
        assert steps[1]["call_id"] == steps[2]["call_id"] == "examiner-call"
        assert steps[2]["text"] == "failed check" and steps[2]["is_error"] is True
        assert steps[3]["text"] == "The contract conflicts"
        assert all(s["t_ms"] == s["line"] * 31 for s in steps)
        assert result["totals"]["input"] == 24
        assert result["totals"]["cached_input"] == 5
        assert result["totals"]["output"] == 7
        assert result["diagnostics"]["unknown"] == []

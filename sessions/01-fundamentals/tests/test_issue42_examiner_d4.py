"""Independent completeness and consistency of every run's metadata."""
from datetime import date
import json
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def test_d4_metadata_for_all_six_runs():
    captures = list((RUNS / "raw").glob("*.jsonl"))
    assert len(captures) == 6
    for capture in captures:
        meta = json.loads(capture.with_suffix(".meta.json").read_text())
        normalized = json.loads((RUNS / f"{capture.stem}.json").read_text())["meta"]
        for key in ("cli_version", "model", "effort", "date"):
            assert isinstance(meta[key], str) and meta[key].strip()
            assert normalized[key] == meta[key]
        assert date.fromisoformat(meta["date"]).isoformat() == meta["date"]
        assert meta["started_at"].startswith(meta["date"])
        argv = meta["argv"]
        if meta["vendor"] == "claude":
            assert argv[argv.index("--model") + 1] == meta["model"]
            assert argv[argv.index("--effort") + 1] == meta["effort"]
            init = next(json.loads(line) for line in capture.read_text().splitlines() if json.loads(line).get("subtype") == "init")
            assert init["model"] == meta["model"]
            assert init["claude_code_version"] in meta["cli_version"]
        else:
            assert argv[argv.index("-m") + 1] == meta["model"]
            assert f'model_reasoning_effort="{meta["effort"]}"' in argv

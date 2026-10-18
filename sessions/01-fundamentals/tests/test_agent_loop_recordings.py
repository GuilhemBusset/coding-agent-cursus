"""Issue 47: the replay page embeds every committed agent-run/1 recording.

Independent of the producer: the expected block is derived here from the committed
`<task>-<vendor>.json` files and the README's display rules (clip at 1,200 characters).
"""

import hashlib
import json
from pathlib import Path
import re


SESSION = Path(__file__).resolve().parents[1]
RUNS = SESSION / "cursus/fixtures/runs"
PAGE = SESSION / "cursus/labs/agent-loop.html"
BLOCK = re.compile(rb'<script type="application/json" id="agent-run-recordings" data-sha256="([0-9a-f]*)">(.*?)</script>', re.S)
CLIP = 1200


def call_text(vendor, tool_input):
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if vendor == "codex" and isinstance(tool_input, dict) and isinstance(tool_input.get("changes"), list):
        return "\n".join(f"{c['kind']} {c['path']}" for c in tool_input["changes"])
    return json.dumps(tool_input, ensure_ascii=False, indent=2, sort_keys=True)


def embedded():
    matches = BLOCK.findall(PAGE.read_bytes())
    assert len(matches) == 1, "one inline agent-run-recordings block"
    digest, data = matches[0]
    assert digest.decode() == hashlib.sha256(data).hexdigest()
    assert b"</" not in data, "nothing in the block can close the script element"
    block = json.loads(data)
    assert block["schema"] == "agent-run-recordings/1"
    return {run["meta"]["run"]: run for run in block["runs"]}


def test_d1_every_committed_recording_is_embedded_with_clipped_text():
    files = sorted(p for vendor in ("claude", "codex") for p in RUNS.glob(f"*-{vendor}.json"))
    assert {p.stem.rsplit("-", 1)[0] for p in files} == {"flipped-sense", "impossible", "context-bomb"}
    runs = embedded()
    assert set(runs) == {p.stem for p in files}
    for path in files:
        source = json.loads(path.read_text(encoding="utf-8"))
        run = runs[path.stem]
        assert run["meta"] == source["meta"] and run["totals"] == source["totals"]
        assert len(run["steps"]) == len(source["steps"])
        for got, want in zip(run["steps"], source["steps"]):
            for field in ("i", "type", "t_ms", "tool", "input", "is_error", "tokens"):
                assert got[field] == want[field], (path.stem, want["i"], field)
            text = want["text"]
            if text is None and want["type"] == "tool_call":
                text = call_text(source["meta"]["vendor"], want["input"])
            text = text or ""
            assert got["text"] == text[:CLIP] and got["chars"] == len(text) and got["truncated"] == (len(text) > CLIP)

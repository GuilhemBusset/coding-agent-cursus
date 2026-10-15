"""Offline drift guard: fixture regeneration must refresh the lab's inline copy.

Only stdlib imports; this test also runs in a standalone session checkout.
"""

import hashlib
import json
from pathlib import Path
import re


SESSION = Path(__file__).resolve().parents[1]


def test_attention_inline_fixture_and_digest_match_recorded_bytes():
    fixture = SESSION / "cursus/fixtures/attention.json"
    page = SESSION / "cursus/labs/attention.html"
    assert page.is_file(), "Missing attention lab: cursus/labs/attention.html"
    raw = fixture.read_bytes()
    html = page.read_text(encoding="utf-8")
    blocks = []
    for match in re.finditer(r"<script\b([^>]*)>([\s\S]*?)</script\s*>", html, re.I):
        attrs = {
            key.lower(): value
            for key, _, value in re.findall(
                r'''([\w-]+)\s*=\s*(["'])(.*?)\2''', match[1], re.S
            )
        }
        if attrs.get("id") == "attention-data":
            blocks.append((attrs, match[2]))
    assert len(blocks) == 1, "Exactly one #attention-data script is required"
    attrs, inline = blocks[0]
    assert attrs.get("type") == "application/json"
    assert "src" not in attrs, "The fixture must be inline for file:// viewing"
    assert json.loads(inline) == json.loads(raw), "Inline attention data drifted from the fixture"
    assert attrs.get("data-sha256") == hashlib.sha256(raw).hexdigest(), (
        "Refresh the inline fixture and its data-sha256 after regeneration"
    )
    assert inline.strip() == raw.decode("utf-8").strip(), "Embed the fixture verbatim"

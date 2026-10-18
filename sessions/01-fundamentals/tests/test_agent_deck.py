"""Issue 48: structure of the Act III deck, cursus/03-agent.html.

Prose accuracy is reviewed (cursus/03-agent/review.md), not keyword-matched here.
These tests check the timing plan, that every demo and lab link sits on its slide
and resolves inside the session, and that the landscape slides carry a date and a
source.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


SESSION = Path(__file__).resolve().parents[1]
CURSUS = SESSION / "cursus"
DECK = CURSUS / "03-agent.html"
REPLAY = CURSUS / "labs/agent-loop.html"


class DeckParser(HTMLParser):
    """Collect each slide's notes, links, text and data-landscape flag."""

    def __init__(self):
        super().__init__()
        self.slides, self.slide, self.depth = [], None, 0
        self.notes = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.slide is None:
            if tag == "section" and "data-slide" in attrs:
                self.slide = {"id": attrs.get("id"), "landscape": "data-landscape" in attrs,
                              "notes": [], "hrefs": [], "text": ""}
                self.depth = 1
            return
        if tag == "section":
            self.depth += 1
        if tag == "details" and "notes" in (attrs.get("class") or "").split():
            self.notes = {"minutes": attrs.get("data-minutes"), "summary": "", "in_summary": False}
            self.slide["notes"].append(self.notes)
        if tag == "summary" and self.notes is not None:
            self.notes["in_summary"] = True
        if tag == "a" and attrs.get("href"):
            self.slide["hrefs"].append(attrs["href"])

    def handle_endtag(self, tag):
        if self.slide is None:
            return
        if tag == "summary" and self.notes is not None:
            self.notes["in_summary"] = False
        if tag == "details" and self.notes is not None and not self.notes["in_summary"]:
            self.notes = None
        if tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.slides.append(self.slide)
                self.slide = None

    def handle_data(self, data):
        if self.slide is None:
            return
        if self.notes is not None and self.notes["in_summary"]:
            self.notes["summary"] += data
        elif self.notes is None:
            self.slide["text"] += data


def deck_slides():
    parser = DeckParser()
    parser.feed(DECK.read_text(encoding="utf-8"))
    return {slide["id"]: slide for slide in parser.slides}


def replay_run_ids():
    page = REPLAY.read_text(encoding="utf-8")
    ids = set()
    for block in ("agent-runs", "agent-run-recordings"):
        match = re.search(rf'<script type="application/json" id="{block}"[^>]*>(.*?)</script>', page, re.S)
        assert match, f"{block} is inlined in the replay widget"
        for run in json.loads(match.group(1))["runs"]:
            ids.add(run.get("id") or run["meta"]["run"])
    return ids


def test_every_slide_has_notes_and_the_minutes_fill_40():
    slides = deck_slides()
    assert len(slides) >= 15
    total = 0.0
    for slide_id, slide in slides.items():
        assert len(slide["notes"]) == 1, f"#{slide_id} has one speaker-notes block"
        minutes = slide["notes"][0]["minutes"]
        assert slide["notes"][0]["summary"].strip() == f"Speaker notes · {minutes} min", slide_id
        total += float(minutes)
    assert total == 40, "per-slide minutes fill the 40-minute act"


def test_demo_and_lab_links_sit_on_their_slides_and_resolve():
    slides = deck_slides()
    expected = {
        "loop-demo": ["demos/agent/loop.md", "labs/agent-loop.html#run=loop-claude-run1",
                      "labs/agent-loop.html#run=loop-codex-run1"],
        "bomb-demo": ["demos/agent/context-bomb.md", "labs/agent-loop.html#run=bomb-claude-run1-without",
                      "labs/agent-loop.html#run=bomb-claude-run1-with"],
        "context-window": ["labs/context.html#budget-title"],
        "cost-growth": ["labs/context.html#cost-title"],
        "wrap": ["labs/context.html", "labs/agent-loop.html"],
    }
    for slide_id, hrefs in expected.items():
        for href in hrefs:
            assert href in slides[slide_id]["hrefs"], f"#{slide_id} links {href}"

    runs = replay_run_ids()
    for slide in slides.values():
        for href in slide["hrefs"]:
            url = urlsplit(href)
            if url.scheme:
                assert url.scheme == "https", href
                continue
            target = (CURSUS / unquote(url.path)).resolve()
            assert target.is_relative_to(SESSION) and target.is_file(), href
            if url.fragment.startswith("run="):
                assert target == REPLAY and url.fragment[4:] in runs, href
            elif url.fragment:
                assert f'id="{url.fragment}"' in target.read_text(encoding="utf-8"), href


def test_landscape_slides_carry_an_as_of_date_and_a_source():
    slides = deck_slides()
    landscape = {slide_id for slide_id, slide in slides.items() if slide["landscape"]}
    assert {"ladder", "models", "time-horizons", "benchmarks", "vibe-vs-agentic"} <= landscape
    for slide_id in landscape:
        slide = slides[slide_id]
        assert re.search(r"As of \d{4}-\d{2}-\d{2}", slide["text"]), f"#{slide_id} shows an as-of date"
        assert any(href.startswith("https://") for href in slide["hrefs"]), f"#{slide_id} cites a source"

"""The bibliography (cursus/sources.html) and the fact-check pass behind it (issue #50).

An as-of, checked, read or accessed date on a delivered page must not predate the pass recorded
in sources.html (data-fact-check). An older snapshot date is allowed only beside a "rechecked"
date from the pass, in the same paragraph, list item, cell or table caption.
"""

import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

SESSION = Path(__file__).resolve().parents[1]
CURSUS = SESSION / "cursus"
SOURCES = CURSUS / "sources.html"
LOG = CURSUS / "sources" / "fact-check.md"
PAGES = [p for p in sorted([*CURSUS.rglob("*.html"), *(SESSION / "exercises").rglob("*.html")]) if p != SOURCES]
DECKS = sorted(CURSUS.glob("[0-9][0-9]-*.html"))

ISO = r"(\d{4}-\d{2}-\d{2})"
DATED = re.compile(r"\b(?:as of|checked|read|accessed)\b[^.;]{0,60}?" + ISO, re.I)
RECHECKED = re.compile(r"\brechecked\b[^.;]{0,60}?" + ISO, re.I)
BLOCKS = {"p", "li", "td", "th", "caption", "figcaption", "footer", "summary", "dt", "dd",
          "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "div", "section", "aside",
          "figure", "header", "main", "legend", "label", "body"}


class Page(HTMLParser):
    """Text per innermost block, tables by column, links, sections and entries."""

    def __init__(self, text):
        super().__init__()
        self.blocks, self.tables, self.links = [], [], []
        self.sections, self.entries, self.times = [], [], []
        self.stack, self.skip, self.fact_check = [], 0, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if "data-fact-check" in attrs:
            self.fact_check = attrs["data-fact-check"]
        if tag == "section" and "data-act" in attrs:
            self.sections.append([])
        if tag == "li" and "data-source" in attrs:
            self.entries.append({"text": "", "times": []})
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
            if self.sections:
                self.sections[-1].append(attrs["href"])
        if tag == "time" and self.entries:
            self.entries[-1]["times"].append(attrs.get("datetime", ""))
        if tag == "table":
            self.tables.append({"head": [], "rows": [], "caption": ""})
        if tag == "tr" and self.tables:
            self.tables[-1]["rows"].append([])
        if tag in BLOCKS:
            self.stack.append([tag, ""])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag not in BLOCKS or not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            name, text = self.stack.pop()
            self.blocks.append(text)
            if self.tables and name in ("td", "th"):
                table = self.tables[-1]
                (table["head"] if name == "th" and not table["rows"][1:] else table["rows"][-1]).append(text)
            if self.tables and name == "caption":
                self.tables[-1]["caption"] = text
            if name == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self.stack:
            self.stack[-1][1] += data
        if self.entries:
            self.entries[-1]["text"] += data


def parse(path):
    return Page(path.read_text(encoding="utf-8"))


SOURCE_PAGE = parse(SOURCES)
PASS = date.fromisoformat(SOURCE_PAGE.fact_check)


def stale(text, context=""):
    """Dates in text older than the pass, unless the block carries a fresh recheck."""
    if any(date.fromisoformat(d) >= PASS for d in RECHECKED.findall(text + " " + context)):
        return []
    return [d for d in DATED.findall(text) if date.fromisoformat(d) < PASS]


def test_every_act_deck_has_its_section():
    for deck in DECKS:
        assert any(deck.name in hrefs for hrefs in SOURCE_PAGE.sections), f"no section cites {deck.name}"


def test_every_entry_carries_an_access_date_from_the_pass():
    assert len(SOURCE_PAGE.entries) >= len(DECKS)
    for entry in SOURCE_PAGE.entries:
        assert "Accessed" in entry["text"] and entry["times"], entry["text"]
        assert all(date.fromisoformat(t) >= PASS for t in entry["times"]), entry["text"]


def test_every_external_link_on_a_page_is_in_the_bibliography():
    listed = {h for h in SOURCE_PAGE.links if h.startswith("https://")}
    for page in PAGES:
        missing = {h for h in parse(page).links if h.startswith("https://")} - listed
        assert not missing, f"{page.relative_to(SESSION)}: {sorted(missing)}"


def test_no_dated_claim_predates_the_fact_check():
    problems = []
    for page in PAGES:
        parsed = parse(page)
        for text in parsed.blocks:
            problems += [(page.name, d, text.strip()[:80]) for d in stale(text)]
        for table in parsed.tables:
            columns = [i for i, h in enumerate(table["head"]) if re.fullmatch(r"\s*(as of|accessed|checked)\s*", h, re.I)]
            for row in table["rows"]:
                for i in columns:
                    cell = row[i] if i < len(row) else ""
                    problems += [(page.name, d, "table") for d in stale("as of " + cell, table["caption"])]
    assert not problems, problems


def test_pass_date_is_not_backdated_behind_the_log():
    logged = [date.fromisoformat(d) for d in re.findall(ISO, LOG.read_text(encoding="utf-8"))]
    assert logged and PASS >= max(logged)
    assert PASS.isoformat() in LOG.read_text(encoding="utf-8")

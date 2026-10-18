"""The Session 1 homework sheet: four parts, a good answer for each, the grading rule, both agents."""

import ast
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


SESSION = Path(__file__).resolve().parents[1]
SHEET = SESSION / "exercises" / "home.html"
PARTS = ("part-1", "part-2", "part-3", "part-4")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Sheet(HTMLParser):
    """Text per section id, the text of each good-answer block per section, and every href."""

    def __init__(self):
        super().__init__()
        self.stack, self.text, self.good, self.links = [], {}, {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in VOID:
            return
        section = attrs.get("id") if tag == "section" else None
        good = "good" in (attrs.get("class") or "").split()
        self.stack.append((tag, section, good))
        if section:
            self.text[section] = ""
        if good:
            self.good.setdefault(self.section(), []).append("")

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop()[0] != tag:
            pass

    def section(self):
        return next((s for _, s, _ in reversed(self.stack) if s), None)

    def handle_data(self, data):
        section = self.section()
        if section:
            self.text[section] += data
            if any(g for _, _, g in self.stack):
                self.good[section][-1] += data


def sheet():
    parser = Sheet()
    parser.feed(SHEET.read_text(encoding="utf-8"))
    return parser


def flat(text):
    return " ".join(text.split())


def test_four_parts_each_with_a_good_answer():
    page = sheet()
    for part in PARTS:
        assert part in page.text, f"missing section #{part}"
        blocks = page.good.get(part, [])
        assert len(blocks) == 1, f"#{part} needs one good-answer block"
        assert flat(blocks[0]).startswith("What a good answer looks like"), part


def test_grading_rule_is_stated():
    rule = "feasibility proven by the checker counts more than the objective value"
    assert rule in flat(sheet().text["grading"]).lower()


def test_instructions_for_both_agents():
    page = sheet()
    for part in ("start", "part-1", "part-4"):
        text = flat(page.text[part])
        assert "Claude Code" in text and "Codex" in text, part
    turn_in = flat(page.text["part-4"])
    assert "/turn-in 01" in turn_in and "$turn-in 01" in turn_in and "scripts/turn-in.sh 01" in turn_in


def test_local_links_resolve_inside_the_session():
    for href in sheet().links:
        url = urlsplit(href)
        if url.scheme or not url.path:
            continue
        target = (SHEET.parent / unquote(url.path)).resolve()
        assert target.is_relative_to(SESSION) and target.exists(), href


def script_constants(path, *names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {t.id: node.value for node in tree.body if isinstance(node, ast.Assign) for t in node.targets}
    return [ast.literal_eval(values[name]) for name in names]


def test_demo_prompts_are_the_ones_run_in_class():
    source = unescape(SHEET.read_text(encoding="utf-8"))
    demos = SESSION / "cursus" / "demos" / "model"
    (sampling,) = script_constants(demos / "sampling.py", "PROMPT")
    word, ask = script_constants(demos / "strawberry.py", "WORD", "ASK")
    assert source.count(f'"{sampling}"') == 2  # once per agent
    prompt = re.search(r'aria-label="Strawberry prompt"><code>(.*?)</code>', source, re.S).group(1)
    assert prompt == ask.format(WORD=word)

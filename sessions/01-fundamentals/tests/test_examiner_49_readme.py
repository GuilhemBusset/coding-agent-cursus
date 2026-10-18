"""The README agenda must agree with the student's hub (D4)."""
from html.parser import HTMLParser
from pathlib import Path
import re

SESSION = Path(__file__).resolve().parents[1]


class Hrefs(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.paths = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.paths.append(dict(attrs).get("href", ""))


def test_readme_agenda_contains_the_hub_schedule_and_materials():
    source = (SESSION / "index.html").read_text(encoding="utf-8")
    readme = (SESSION / "README.md").read_text(encoding="utf-8")
    agenda = readme.split("## Agenda", 1)[1].split("\n## ", 1)[0]
    assert not re.search(r"\b(TBD|Placeholder)\b", agenda, re.I)
    assert "(index.html)" in agenda
    for time in re.findall(r'<p class="agenda-time">([^<]+)</p>', source):
        assert time in agenda, f"Missing time block: {time}"
    for href in Hrefs(source).paths:
        if href.endswith(".html") and href.startswith(("cursus/labs/", "exercises/")):
            assert f"({href})" in agenda, f"Missing student material: {href}"
        if re.fullmatch(r"cursus/\d[^/]*\.html", href):
            assert f"({href})" in agenda, f"Missing deck: {href}"
    for path in ("index.html", "cursus/run-of-show.html", "cursus/instructor-notes.html"):
        assert f"| `{path}` |" in readme

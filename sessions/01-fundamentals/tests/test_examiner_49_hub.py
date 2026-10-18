"""Independent checks of the student-facing material sequence (D1)."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

SESSION = Path(__file__).resolve().parents[1]


class Anchors(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.paths = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = urlsplit(dict(attrs).get("href", ""))
            if url.path and not url.scheme and not url.netloc:
                self.paths.append(url.path)


def test_hub_has_all_student_pages_in_act_order():
    paths = Anchors(SESSION / "index.html").paths
    decks = sorted(p for p in (SESSION / "cursus").glob("*.html")
                   if p.name[:2].isdigit())
    positions = [paths.index(p.relative_to(SESSION).as_posix()) for p in decks]
    assert positions == sorted(positions)
    for folder in ("cursus/labs", "exercises"):
        for page in (SESSION / folder).rglob("*.html"):
            assert page.relative_to(SESSION).as_posix() in paths
    assert paths.index("exercises/00-prework.html") < positions[0]
    assert positions[3] < paths.index("exercises/lab-ladder.html") < positions[4]
    assert paths.index("exercises/home.html") > positions[-1]
    for deck, start, end in zip(decks, positions, positions[1:] + [len(paths)]):
        labs = [p for p in Anchors(deck).paths if p.startswith("labs/")]
        listed = list(dict.fromkeys("cursus/" + p for p in labs))
        assert all(start < paths.index(p) < end for p in listed)
    # Run-of-show links reflect classroom order; decks also link preparation notes.
    taught = list(dict.fromkeys("cursus/" + p for p in
                  Anchors(SESSION / "cursus/run-of-show.html").paths
                  if p.startswith("labs/") and p.endswith(".html")))
    assert [paths.index(p) for p in taught] == sorted(paths.index(p) for p in taught)

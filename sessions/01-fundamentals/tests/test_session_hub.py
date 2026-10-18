"""The session hub: index.html links every page in teaching order, and no local link is broken."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SESSION = Path(__file__).resolve().parents[1]
INDEX = SESSION / "index.html"
DECKS = ["00-opening", "01-sampler", "02-thinking", "03-agent", "05-failure", "99-close"]


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path, self.links, self.ids = path, [], set()
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for name in ("href", "src"):
            url = urlsplit((attrs.get(name) or "").strip())
            if url.scheme or url.netloc or not (url.path or url.fragment):
                continue  # Remote, mailto: or data: URLs, and empty attributes.
            target = (self.path.parent / unquote(url.path)).resolve() if url.path else self.path
            self.links.append((target, url.fragment))

    handle_startendtag = handle_starttag


def session_pages():
    return sorted(
        p for p in SESSION.rglob("*.html")
        if not any(part.startswith(".") for part in p.relative_to(SESSION).parts)
    )


def test_every_page_is_reachable_from_index():
    seen, queue = {INDEX}, [INDEX]
    while queue:
        for target, _ in Page(queue.pop()).links:
            if target.suffix == ".html" and target.is_file() and target not in seen:
                seen.add(target)
                queue.append(target)
    missing = [str(p.relative_to(SESSION)) for p in session_pages() if p not in seen]
    assert not missing, f"not reachable from index.html: {missing}"


def test_no_broken_local_links():
    pages = {p: Page(p) for p in session_pages()}
    broken = []
    for page in pages.values():
        for target, fragment in page.links:
            where = f"{page.path.relative_to(SESSION)} -> {target.name}#{fragment}"
            if not target.exists():
                broken.append(where)
            # Fragments holding "=" are hash-routed state (agent-loop.html#run=...), not ids.
            elif fragment and "=" not in fragment and target.suffix == ".html":
                ids = (pages.get(target) or Page(target)).ids
                if unquote(fragment) not in ids:
                    broken.append(where)
    assert not broken, "broken local links:\n" + "\n".join(broken)


def test_index_links_decks_labs_and_exercises_in_teaching_order():
    order = [t.relative_to(SESSION).as_posix() for t, _ in Page(INDEX).links if t.is_relative_to(SESSION)]
    first = {path: order.index(path) for path in set(order)}
    pages = {p.relative_to(SESSION).as_posix() for p in session_pages()}
    wanted = {p for p in pages if p.startswith(("cursus/labs/", "exercises/"))}
    wanted |= {f"cursus/{d}.html" for d in DECKS}
    assert not wanted - first.keys(), f"not linked from index.html: {sorted(wanted - first.keys())}"

    deck_pos = [first[f"cursus/{d}.html"] for d in DECKS]
    assert deck_pos == sorted(deck_pos), "decks are not in act order"
    for i, deck in enumerate(DECKS):
        upper = deck_pos[i + 1] if i + 1 < len(DECKS) else len(order)
        for target, _ in Page(SESSION / f"cursus/{deck}.html").links:
            lab = target.relative_to(SESSION).as_posix() if target.is_relative_to(SESSION) else ""
            if lab.startswith("cursus/labs/") and lab.endswith(".html"):
                assert deck_pos[i] < first[lab] < upper, f"{lab} is not listed under {deck}"
    assert first["exercises/00-prework.html"] < deck_pos[0], "pre-work comes before the opening"
    assert deck_pos[3] < first["exercises/lab-ladder.html"] < deck_pos[4], "the ladder is Act IV"
    assert first["exercises/home.html"] > deck_pos[-1], "homework comes after the close"

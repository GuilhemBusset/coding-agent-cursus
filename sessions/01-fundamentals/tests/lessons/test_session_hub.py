"""The session hub: every page is reachable from index.html, and no local link is broken.

check-page.mjs checks each page's own files and same-page anchors; this checks what it does not
follow: anchors on other pages, and the #run=<id> routes into the agent-loop replay widget.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SESSION = Path(__file__).resolve().parents[2]
INDEX = SESSION / "index.html"


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


def replay_runs(path):
    """The run ids a replay widget's JSON catalogs hold (agent-loop.html)."""
    catalogs = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                          path.read_text(encoding="utf-8"), re.DOTALL)
    return {run.get("id") or run.get("meta", {}).get("run")
            for data in map(json.loads, catalogs) if isinstance(data, dict) for run in data.get("runs", [])}


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
    runs = {}
    broken = []
    for page in pages.values():
        for target, fragment in page.links:
            where = f"{page.path.relative_to(SESSION)} -> {target.name}#{fragment}"
            if not target.exists():
                broken.append(where)
            elif fragment.startswith("run="):
                if target not in runs:
                    runs[target] = replay_runs(target)
                if unquote(fragment[4:]) not in runs[target]:
                    broken.append(where)
            elif fragment and "=" not in fragment and target.suffix == ".html":
                ids = (pages.get(target) or Page(target)).ids
                if unquote(fragment) not in ids:
                    broken.append(where)
    assert not broken, "broken local links:\n" + "\n".join(broken)
